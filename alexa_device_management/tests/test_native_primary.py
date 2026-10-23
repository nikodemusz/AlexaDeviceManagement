"""Native main editor, exact endpoint reconciliation, and lifecycle failure tests."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "rootfs/opt/alexa_device_management/web"))
import native_export
import native_lifecycle
from native_endpoints import endpoints
from native_skill_config import NativeSkillConfigStore, NativeSkillConfigError
from config_store import ConfigStore
from device_overview import build_overview

spec = importlib.util.spec_from_file_location("native_reports", ROOT / "rootfs/opt/alexa_device_management/ha_component/alexa_device_management_sync/native_reports.py")
reporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporter)


def config():
    return {"schema_version": 6, "enabled": True, "locale": "de-DE", "devices": {
        "tank": {"name": "Tank", "enabled": True, "capabilities": [
            {"interface": "Alexa.RangeController", "entity_id": "sensor.liters", "instance": "liters", "unit": "Alexa.Unit.Liters"},
            {"interface": "Alexa.RangeController", "entity_id": "sensor.percent", "instance": "percent", "unit": "Alexa.Unit.Percent"}]},
        "desk": {"name": "Desk", "enabled": True, "capabilities": [{"interface": "Alexa.PowerController", "entity_id": "light.desk"}]}}}


def old_device(serial="old", description="light.desk via Home Assistant"):
    return {"serial": serial, "source": "smart_home", "raw": {"description": description}}


class NativePrimaryTests(unittest.TestCase):
    def test_legacy_flags_are_preserved_but_never_reenable_export(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "config.json", Path(directory) / "old.json", Path(directory) / "alexa.yaml")
            raw = {"legacy_export_enabled": True, "entities": {"light.old": {"enabled": True, "unknown": "retained"}}}
            saved = store.save(raw)
            self.assertFalse(saved["legacy_export_enabled"])
            self.assertEqual(saved["entities"], raw["entities"])

    def test_main_editor_changes_native_device_and_retains_multi_sensor_endpoint(self):
        original = config()
        selected = native_export.entity_settings(original)
        selected["sensor.liters"]["enabled"] = False
        updated = native_export.apply_entities(original, selected, {"devices": []})
        self.assertFalse(updated["devices"]["tank"]["enabled"])
        self.assertEqual(updated["devices"]["tank"]["capabilities"], original["devices"]["tank"]["capabilities"])
        self.assertEqual(set(updated["devices"]), {"desk", "tank"})
        self.assertTrue(original["devices"]["tank"]["enabled"])

    def test_explicit_new_light_uses_real_capabilities_without_importing_legacy(self):
        inventory = {"devices": [{"entities": [{"entity_id": "light.new", "supported_color_modes": ["brightness"]}]}]}
        updated = native_export.apply_entities(config(), {"light.new": {"enabled": True, "name": "New"}}, inventory)
        self.assertEqual([c["interface"] for c in updated["devices"]["ha:light.new"]["capabilities"]],
                         ["Alexa.PowerController", "Alexa.BrightnessController"])
        self.assertEqual(endpoints(updated)[1]["endpointId"], "native:ha:light.new")

    def test_existing_selected_dimmer_gets_missing_brightness_controller(self):
        original = config()
        requested = native_export.entity_settings(original)
        inventory = {"devices": [{"entities": [{"entity_id": "light.desk", "supported_color_modes": ["brightness"]}]}]}
        updated = native_export.apply_entities(original, requested, inventory)
        self.assertEqual([c["interface"] for c in updated["devices"]["desk"]["capabilities"]],
                         ["Alexa.PowerController", "Alexa.BrightnessController"])
        self.assertEqual([c["interface"] for c in original["devices"]["desk"]["capabilities"]],
                         ["Alexa.PowerController"])

    def test_existing_on_off_light_does_not_get_brightness_controller(self):
        original = config()
        requested = native_export.entity_settings(original)
        inventory = {"devices": [{"entities": [{"entity_id": "light.desk", "supported_color_modes": ["onoff"]}]}]}
        updated = native_export.apply_entities(original, requested, inventory)
        self.assertEqual([c["interface"] for c in updated["devices"]["desk"]["capabilities"]],
                         ["Alexa.PowerController"])

    def test_standard_cover_profile_is_position_slider_without_a_switch_or_stop_button(self):
        inventory = {"devices": [{"entities": [{"entity_id": "cover.blind", "supported_features": 4}]}]}
        updated = native_export.apply_entities(config(), {"cover.blind": {"enabled": True}}, inventory)
        capabilities = updated["devices"]["ha:cover.blind"]["capabilities"]
        self.assertEqual([cap["interface"] for cap in capabilities], ["Alexa.RangeController"])
        self.assertEqual(capabilities[0]["instance"], "cover.position")

    def test_custom_cover_can_export_only_stop_without_position_support(self):
        inventory = {"devices": [{"entities": [{"entity_id": "cover.blind", "supported_features": 0}]}]}
        updated = native_export.apply_entities(config(), {"cover.blind": {
            "enabled": True, "capability_mode": "custom", "capabilities": ["Alexa.PlaybackController"]
        }}, inventory)
        active = [cap for cap in updated["devices"]["ha:cover.blind"]["capabilities"]
                  if cap.get("enabled", True)]
        self.assertEqual([cap["interface"] for cap in active], ["Alexa.PlaybackController"])

    def test_standard_relay_category_uses_device_names_without_changing_on_off_semantics(self):
        for entity_id, name, category in (
            ("switch.badlicht", "Badlicht", "LIGHT"),
            ("switch.keller_steckdose", "Keller Steckdose", "SMARTPLUG"),
            ("switch.heizventil", "Heizventil", "SWITCH"),
        ):
            with self.subTest(entity_id=entity_id):
                inventory = {"devices": [{"name": name, "entities": [
                    {"entity_id": entity_id, "domain": "switch", "name": name}
                ]}]}
                updated = native_export.apply_entities(config(), {entity_id: {"enabled": True}}, inventory)
                device = updated["devices"]["ha:" + entity_id]
                self.assertEqual(device["display_category"], category)
                self.assertEqual([cap["interface"] for cap in device["capabilities"]],
                                 ["Alexa.PowerController"])

    def test_unsupported_new_devices_do_not_partially_change_configuration(self):
        original = config()
        with self.assertRaises(ValueError):
            native_export.apply_entities(original, {"camera.new": {"enabled": True}}, {"devices": [{"entities": [{"entity_id": "camera.new"}]}]})
        self.assertEqual(original, config())

    def test_main_thermostat_declares_only_actual_ha_modes(self):
        inventory = {"devices": [{"entities": [{"entity_id": "climate.room", "hvac_modes": ["off", "heat"]}]}]}
        updated = native_export.apply_entities(config(), {"climate.room": {"enabled": True, "name": "Room"}}, inventory)
        thermostat = next(item for item in endpoints(updated) if item["endpointId"] == "native:ha:climate.room")
        capability = next(item for item in thermostat["capabilities"] if item["interface"] == "Alexa.ThermostatController")
        self.assertEqual(capability["configuration"]["supportedModes"], ["HEAT", "OFF"])

    def test_endpoint_summary_counts_tank_once_and_does_not_match_old_copy(self):
        native = config()
        preferences = native_export.configuration(native, {})
        inventory = {"devices": [{"device_id": "tank", "entities": [{"entity_id": "sensor.liters"}, {"entity_id": "sensor.percent"}, {"entity_id": "light.desk"}]}]}
        alexa = [{"serial": "native:tank", "source": "smart_home", "raw": {}}, old_device()]
        result = build_overview(inventory, alexa, [], preferences, native)
        self.assertEqual(result["summary"]["selected"], 2)
        self.assertEqual(result["summary"]["synced"], 1)
        self.assertEqual(result["summary"]["pending"], 1)
        self.assertEqual(result["summary"]["only_alexa"], 1)
        self.assertEqual(result["devices"][0]["entities"][2]["status"], "pending")

    def test_removal_matches_never_selected_and_opaque_ha_devices_but_no_native_or_vendor(self):
        native = {**old_device("wrapped"), "raw": {"endpointId": "amzn1.alexa.endpoint.native:desk", "description": "light.desk via Home Assistant"}}
        nested_native = {**old_device("nested"), "raw": {"description": "light.desk via Home Assistant", "payload": json.dumps({"endpointId": "native:desk"})}}
        opaque = {"serial": "opaque", "source": "graphql", "manufacturer": "Home Assistant", "raw": {}}
        vendor = {"serial": "vendor", "source": "smart_home", "name": "Home Assistant", "raw": {"description": "light.other"}}
        echo = {**old_device("echo"), "source": "echo"}
        selected = native_lifecycle.legacy_targets([old_device("never_selected"), native, nested_native, opaque, vendor, echo])
        self.assertEqual({v["device"]["serial"] for v in selected}, {"never_selected", "opaque"})

    def test_reports_have_stable_native_ids_and_split_before_size_or_count_limit(self):
        eps = [{"endpointId": f"native:{i}", "description": "ä" * 3000} for i in range(162)]
        result = reporter.reports(eps, ["light#old"], "dummy-lwa")
        self.assertEqual(result[0]["event"]["header"]["name"], "DeleteReport")
        additions = [r for r in result if r["event"]["header"]["name"] == "AddOrUpdateReport"]
        self.assertEqual(sum(len(r["event"]["payload"]["endpoints"]) for r in additions), 162)
        for report in result:
            self.assertLessEqual(len(report["event"]["payload"]["endpoints"]), 50)
            self.assertLessEqual(len(json.dumps(report, ensure_ascii=False).encode()), reporter.MAX_BYTES)
            self.assertEqual(report["event"]["payload"]["scope"]["token"], "dummy-lwa")

    def test_reports_reject_v5_additions_and_deletion_of_active_native_ids(self):
        for ids, deletes in (([{"endpointId": "light#old"}], []), ([{"endpointId": "native:desk"}], ["native:desk"])):
            with self.assertRaises(ValueError):
                reporter.reports(ids, deletes, "dummy")

    def test_store_rejects_activation_above_300_but_retains_disabled_drafts(self):
        value = NativeSkillConfigStore.default()
        value["devices"] = {f"d{i}": {"name": "Light", "capabilities": [{"interface": "Alexa.PowerController", "entity_id": f"light.d{i}"}]} for i in range(301)}
        NativeSkillConfigStore.validate(value)
        value["enabled"] = True
        with self.assertRaises(NativeSkillConfigError):
            NativeSkillConfigStore.validate(value)


class NativeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.status_patch = patch.object(native_lifecycle, "STATUS_PATH", Path(self.temp.name) / "status.json")
        self.status_patch.start()

    async def asyncTearDown(self):
        self.status_patch.stop()
        self.temp.cleanup()

    async def test_cleanup_rechecks_amazon_and_never_deletes_overlapping_native(self):
        old = old_device()
        new = {**old_device("native:desk"), "raw": {"endpointId": "native:desk", "description": "light.desk via Home Assistant"}}
        server = Mock()
        server.is_configured.return_value = True
        server._DEVICES_CACHE = {}
        server._fetch_devices_from_alexa = AsyncMock(side_effect=[([old, new], []), ([new], [])])
        server._delete_target = AsyncMock()
        result = await native_lifecycle.cleanup_legacy(server)
        server._delete_target.assert_awaited_once_with(old, server.session_data())
        self.assertTrue(result["legacy_verified"])
        self.assertEqual(result["legacy_remaining"], 0)

    async def test_delete_acknowledgement_without_inventory_removal_is_pending(self):
        server = Mock()
        server.is_configured.return_value = True
        server._DEVICES_CACHE = {}
        server._fetch_devices_from_alexa = AsyncMock(return_value=([old_device()], []))
        server._delete_target = AsyncMock()
        result = await native_lifecycle.cleanup_legacy(server)
        self.assertFalse(result["legacy_verified"])
        self.assertEqual(result["legacy_remaining"], 1)

    async def test_partial_inventory_removes_confirmed_v5_but_does_not_claim_complete_success(self):
        server = Mock()
        server.is_configured.return_value = True
        server._fetch_devices_from_alexa = AsyncMock(return_value=([old_device()], ["HTTP error"]))
        server._delete_target = AsyncMock()
        result = await native_lifecycle.cleanup_legacy(server)
        server._delete_target.assert_awaited_once()
        self.assertFalse(result["legacy_verified"])
        self.assertTrue(result["legacy_error"])

    async def test_native_publication_contains_both_tank_ranges_not_ha_entity_ids(self):
        fake_store = Mock()
        fake_store.load.return_value = config()
        prefs = Mock()
        prefs.load.return_value = {"event_gateway": {"enabled": True}}
        with patch.object(native_lifecycle, "NativeSkillConfigStore", return_value=fake_store), \
             patch.object(native_lifecycle.ha_export, "CONFIG_STORE", prefs), \
             patch.object(native_lifecycle.support, "deploy_component", return_value={"restart_required": False}), \
             patch.object(native_lifecycle.support, "_service_available", AsyncMock(return_value=True)), \
             patch.object(native_lifecycle.support, "_call_sync_service", AsyncMock(return_value=(200, {"service_response": {"ok": True}}))) as call:
            result = await native_lifecycle.publish_native()
            payload = call.call_args.args[0]
            self.assertEqual(payload["add_or_update"], [])
            self.assertEqual({d["endpointId"] for d in payload["native_endpoints"]}, {"native:desk", "native:tank"})
            tank = next(d for d in payload["native_endpoints"] if d["endpointId"] == "native:tank")
            self.assertEqual(sum(c["interface"] == "Alexa.RangeController" for c in tank["capabilities"]), 2)
            self.assertIsNone(result["publish_error"])
            await native_lifecycle.publish_native()
            self.assertEqual(call.await_count, 1)

    async def test_failed_publication_retains_pending_revision_for_retry(self):
        fake_store = Mock()
        fake_store.load.return_value = config()
        prefs = Mock()
        prefs.load.return_value = {"event_gateway": {"enabled": True}}
        with patch.object(native_lifecycle, "NativeSkillConfigStore", return_value=fake_store), \
             patch.object(native_lifecycle.ha_export, "CONFIG_STORE", prefs), \
             patch.object(native_lifecycle.support, "deploy_component", return_value={"restart_required": False}), \
             patch.object(native_lifecycle.support, "_service_available", AsyncMock(return_value=True)), \
             patch.object(native_lifecycle.support, "_call_sync_service", AsyncMock(return_value=(200, {"service_response": {"ok": False, "error": "Rejected"}}))) as call:
            await native_lifecycle.publish_native()
            await native_lifecycle.publish_native()
            self.assertEqual(call.await_count, 2)
            self.assertNotIn("published_revision", native_lifecycle.read_status())

    async def test_missing_native_ids_are_republished_even_after_previous_acceptance(self):
        server = Mock()
        server.is_configured.return_value = True
        server._DEVICES_CACHE = {"devices": [{"serial": "native:tank"}]}
        fake_store = Mock()
        fake_store.load.return_value = config()
        native_lifecycle.write_status(inventory_verified=True, publish_error="retry")
        with patch.object(native_lifecycle, "NativeSkillConfigStore", return_value=fake_store), \
             patch.object(native_lifecycle, "cleanup_legacy", AsyncMock()), \
             patch.object(native_lifecycle, "publish_native", AsyncMock()) as publish:
            await native_lifecycle.reconcile(server)
            publish.assert_awaited_once_with(True)
            self.assertEqual(native_lifecycle.read_status()["native_pending"], 1)


if __name__ == "__main__":
    unittest.main()
