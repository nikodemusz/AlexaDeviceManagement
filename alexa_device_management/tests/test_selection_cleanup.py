"""Unwanted endpoints are removed by ID/provider, never by a device name."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rootfs/opt/alexa_device_management/web"))
import native_lifecycle as lifecycle
from native_skill_config import NativeSkillConfigStore
import server_clean
from server_clean import _normalize_smart_home_device
import server_extended


def selection():
    return {"schema_version": 6, "enabled": True, "locale": "de-DE", "devices": {
        "desk": {"name": "Selected", "capabilities": [{"interface": "Alexa.PowerController", "entity_id": "light.desk"}]},
        "fritz": {"name": "FRITZ!Box deselected", "enabled": False,
                  "capabilities": [{"interface": "Alexa.PowerController", "entity_id": "switch.fritz"}]}}}


def device(serial, **raw):
    return _normalize_smart_home_device({"id": serial, "displayName": "FRITZ!Box test", **raw})


class SelectionTargetTests(unittest.TestCase):
    def test_nested_legacy_provider_from_real_normalizer_identifies_v5(self):
        old = device("old", legacyAppliance={"manufacturerName": "Home Assistant", "applianceId": "legacy-old"})
        self.assertEqual(old["family"], "Home Assistant")
        self.assertEqual([t["device"]["serial"] for t in lifecycle.legacy_targets([old])], ["old"])

    def test_nested_provider_and_case_insensitive_description_identify_v5(self):
        old = device("old", providerData={"providerName": "Home Assistant"})
        described = device("described", description="switch.fritz via home assistant")
        self.assertEqual(len(lifecycle.legacy_targets([old, described])), 2)

    def test_provider_in_json_wrapped_inventory_is_read_as_data(self):
        old = device("old", payload=json.dumps({"providerName": "Home Assistant"}))
        self.assertEqual(len(lifecycle.legacy_targets([old])), 1)

    def test_legacy_wrapper_description_identifies_old_endpoint(self):
        old = device("old", legacyAppliance={"description": "switch.fritz via Home Assistant"})
        self.assertEqual(lifecycle.legacy_targets([old])[0]["endpoint_id"], "switch#fritz")

    def test_explicit_home_assistant_provider_uses_entity_id_for_delete_report(self):
        old = device("switch.fritz", manufacturerName="Home Assistant")
        self.assertEqual(lifecycle.legacy_targets([old])[0]["entity_id"], "switch.fritz")

    def test_untracked_disabled_native_and_all_v5_copies_are_targets(self):
        kept = device("native:desk", manufacturerName="Alexa Device Management")
        disabled = device("native:fritz", manufacturerName="Alexa Device Management")
        old_copy = device("old-desk", description="light.desk via Home Assistant")
        never_selected = device("never-selected", legacyAppliance={"manufacturerName": "Home Assistant"})
        targets = lifecycle.selection_targets([kept, disabled, old_copy, never_selected], selection())
        self.assertEqual({t["device"]["serial"] for t in targets}, {"native:fritz", "old-desk", "never-selected"})
        self.assertEqual(next(t for t in targets if t["kind"] == "unselected_native")["native_ids"], ["native:fritz"])

    def test_removed_native_requires_managed_provider_evidence(self):
        managed = device("native:removed", manufacturerName="Alexa Device Management")
        unrelated = device("native:vendor-device", manufacturerName="Unrelated vendor")
        named_only = device("named-only", manufacturerName="Unrelated vendor", description="FRITZ!Box Home Assistant")
        echo = {**device("native:fritz", manufacturerName="Alexa Device Management"), "source": "echo"}
        targets = lifecycle.selection_targets([managed, unrelated, named_only, echo], selection())
        self.assertEqual([t["device"]["serial"] for t in targets], ["native:removed"])

    def test_known_disabled_id_does_not_depend_on_provider_metadata_or_history(self):
        targets = lifecycle.selection_targets([device("native:fritz")], selection())
        self.assertEqual(targets[0]["endpoint_id"], "native:fritz")

    def test_wrapped_selected_id_and_multivalue_references_are_protected(self):
        wrapped = device("amazon-id", manufacturerName="Home Assistant",
                         payload={"endpointId": "amzn1.alexa.endpoint.native:desk"})
        ambiguous = device("native:fritz", manufacturerName="Alexa Device Management",
                           payload=json.dumps({"endpointId": "native:desk"}))
        self.assertEqual(lifecycle.selection_targets([wrapped, ambiguous], selection()), [])

    def test_disabled_global_selection_has_no_selected_native_endpoints(self):
        native = selection()
        native["enabled"] = False
        targets = lifecycle.selection_targets([device("native:desk"), device("native:fritz")], native)
        self.assertEqual({t["endpoint_id"] for t in targets}, {"native:desk", "native:fritz"})


class SelectionCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.status = patch.object(lifecycle, "STATUS_PATH", Path(self.directory.name) / "status.json")
        self.status.start()
        self.addCleanup(self.status.stop)
        self.native = selection()
        self.config_patch = patch.object(lifecycle, "selection_config", side_effect=lambda: copy.deepcopy(self.native))
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.server = Mock()
        self.server.is_configured.return_value = True
        self.server._DEVICES_CACHE = {}
        self.inventory = [device("native:desk", manufacturerName="Alexa Device Management"),
                          device("native:fritz", manufacturerName="Alexa Device Management"),
                          device("old-desk", description="light.desk via Home Assistant"),
                          device("old-fritz", legacyAppliance={"manufacturerName": "Home Assistant"})]
        async def fetch(_):
            return copy.deepcopy(self.inventory), []
        async def delete(item, _):
            self.inventory = [d for d in self.inventory if d["serial"] != item["serial"]]
        self.server._fetch_devices_from_alexa = AsyncMock(side_effect=fetch)
        self.server._delete_target = AsyncMock(side_effect=delete)

    async def test_fresh_inventory_confirms_exact_selected_remainder(self):
        result = await lifecycle.cleanup_legacy(self.server, self.native)
        removed = {call.args[0]["serial"] for call in self.server._delete_target.await_args_list}
        self.assertEqual(removed, {"native:fritz", "old-desk", "old-fritz"})
        self.assertEqual([d["serial"] for d in self.inventory], ["native:desk"])
        self.assertEqual(result["legacy_deleted"], 2)
        self.assertEqual(result["unselected_native_deleted"], 1)
        self.assertEqual(result["selection_remaining"], 0)
        self.assertTrue(result["selection_verified"])

    async def test_reselected_device_is_checked_again_before_deletion(self):
        self.inventory = [device("native:fritz", manufacturerName="Alexa Device Management")]
        snapshot = copy.deepcopy(self.native)
        self.native["devices"]["fritz"]["enabled"] = True
        result = await lifecycle.cleanup_legacy(self.server, snapshot)
        self.server._delete_target.assert_not_awaited()
        self.assertTrue(result["selection_verified"])

    async def test_acknowledgement_without_removal_is_not_success(self):
        self.server._delete_target = AsyncMock()
        result = await lifecycle.cleanup_legacy(self.server, self.native)
        self.assertFalse(result["selection_verified"])
        self.assertEqual(result["selection_remaining"], 3)
        self.assertEqual(result["unselected_native_remaining"], 1)
        self.assertEqual(result["unselected_native_ids"], ["native:fritz"])

    async def test_confirmed_v5_entity_uses_official_delete_report_and_stays_pending_until_fresh_inventory(self):
        preferences = Mock()
        preferences.load.return_value = {"event_gateway": {"enabled": True}}
        with patch.object(lifecycle.ha_export, "CONFIG_STORE", preferences), \
             patch.object(lifecycle.support, "_service_available", AsyncMock(return_value=True)), \
             patch.object(lifecycle.support, "_call_sync_service", AsyncMock(
                 return_value=(200, {"service_response": {"ok": True}})
             )) as report:
            result = await lifecycle.cleanup_legacy(self.server, self.native)
        self.assertEqual(report.call_args.args[0]["delete"], ["light.desk"])
        self.assertEqual(result["legacy_delete_report_accepted"], ["light.desk"])
        # An accepted DeleteReport is not itself proof Alexa removed the row.
        self.assertEqual(result["legacy_remaining"], 1)
        self.assertFalse(result["selection_verified"])
        self.assertNotIn("old-desk", {call.args[0]["serial"] for call in self.server._delete_target.await_args_list})

    async def test_unavailable_or_disabled_event_gateway_does_not_claim_report(self):
        preferences = Mock()
        preferences.load.return_value = {"event_gateway": {"enabled": False}}
        with patch.object(lifecycle.ha_export, "CONFIG_STORE", preferences), \
             patch.object(lifecycle.support, "_service_available", AsyncMock(return_value=False)), \
             patch.object(lifecycle.support, "_call_sync_service", AsyncMock()) as report:
            result = await lifecycle.cleanup_legacy(self.server, self.native)
        report.assert_not_awaited()
        self.assertEqual(result["legacy_delete_report_accepted"], [])
        self.assertEqual(result["selection_remaining"], 0)


    async def test_failed_deletion_is_retained_for_retry_and_private_error_is_hidden(self):
        self.server._delete_target = AsyncMock(side_effect=RuntimeError("private-session-marker"))
        result = await lifecycle.cleanup_legacy(self.server, self.native)
        self.assertEqual(result["selection_deleted"], 0)
        self.assertEqual(result["selection_remaining"], 3)
        self.assertEqual(len(result["legacy_failures"]), 3)
        self.assertNotIn("private-session-marker", json.dumps(result))

    async def test_partial_inventory_cannot_claim_completed_selection_cleanup(self):
        self.server._fetch_devices_from_alexa = AsyncMock(return_value=(copy.deepcopy(self.inventory), ["Incomplete inventory"]))
        result = await lifecycle.cleanup_legacy(self.server, self.native)
        self.assertFalse(result["selection_verified"])
        self.assertFalse(result["inventory_verified"])
        self.assertTrue(result["legacy_error"])

    async def test_missing_selection_blocks_inventory_deletion_and_publication(self):
        self.config_patch.stop()
        store = NativeSkillConfigStore(Path(self.directory.name) / "missing.yaml")
        with patch.object(lifecycle, "NativeSkillConfigStore", return_value=store), \
             patch.object(lifecycle.support, "_call_sync_service", AsyncMock()) as report:
            result = await lifecycle.reconcile(self.server)
        self.server._fetch_devices_from_alexa.assert_not_awaited()
        self.server._delete_target.assert_not_awaited()
        report.assert_not_awaited()
        self.assertFalse(result["selection_verified"])

    async def test_official_report_removes_untracked_disabled_and_orphan_ids(self):
        lifecycle.write_status(unselected_native_ids=["native:orphan"])
        preferences = Mock()
        preferences.load.return_value = {"event_gateway": {"enabled": True}}
        with patch.object(lifecycle.ha_export, "CONFIG_STORE", preferences), \
             patch.object(lifecycle.support, "deploy_component", return_value={"restart_required": False}), \
             patch.object(lifecycle.support, "_service_available", AsyncMock(return_value=True)), \
             patch.object(lifecycle.support, "_call_sync_service", AsyncMock(return_value=(200, {"service_response": {"ok": True}}))) as report:
            await lifecycle.publish_native()
            payload = report.call_args.args[0]
            self.assertEqual(set(payload["delete_endpoint_ids"]), {"native:fritz", "native:orphan"})
            self.assertEqual({e["endpointId"] for e in payload["native_endpoints"]}, {"native:desk"})
            await lifecycle.publish_native()
            self.assertEqual(report.await_count, 1)


class DebugPageTests(unittest.IsolatedAsyncioTestCase):
    async def test_page_shows_current_v5_and_v6_status_routes_without_delete_button(self):
        response = await server_clean.debug_ui(SimpleNamespace(headers={}))
        self.assertIn("/api/native-export/lifecycle", response.text)
        self.assertIn("/api/ha-export/event-sync/status", response.text)
        self.assertIn("Alexa-Bestand", response.text)
        self.assertNotIn("Delete-Probe (DELETE!)", response.text)

    async def test_debug_json_is_expandable_selectable_and_copyable_on_mobile(self):
        response = await server_clean.debug_ui(SimpleNamespace(headers={}))
        self.assertIn('id="btn-expand"', response.text)
        self.assertIn("toggleExpanded()", response.text)
        self.assertIn("-webkit-user-select: text", response.text)
        self.assertIn("navigator.clipboard.writeText(rawJson)", response.text)
        self.assertIn("document.execCommand('copy')", response.text)

    async def test_extended_app_registers_official_event_sync_status_and_action(self):
        app = server_extended.create_app()
        paths = {route.resource.canonical for route in app.router.routes()}
        self.assertIn("/api/ha-export/event-sync/status", paths)
        self.assertIn("/api/ha-export/event-sync", paths)

    async def test_destructive_delete_probe_is_disabled(self):
        request = SimpleNamespace(rel_url=SimpleNamespace(query={"delete": "1"}))
        response = await server_clean.delete_probe(request)
        self.assertEqual(response.status, 410)
        self.assertIn("deaktiviert", response.text)

if __name__ == "__main__":
    unittest.main()
