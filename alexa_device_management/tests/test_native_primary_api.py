"""Exercise the app's registered main routes, not a separate migration UI."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "rootfs/opt/alexa_device_management/web"))
import native_export
import native_lifecycle
import server_clean
import server_extended
import ha_export
import ha_control
from yaml_generator import AlexaYamlGenerator
from native_skill_config import NativeSkillConfigStore


class PrimaryAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NativeSkillConfigStore(Path(self.temp.name) / "native.yaml")
        self.store.save({"schema_version": 6, "enabled": True, "locale": "de-DE", "devices": {
            "desk": {"name": "Desk", "capabilities": [{"interface": "Alexa.PowerController", "entity_id": "light.desk"}]}}})
        self.preferences = {"entities": {"light.old": {"enabled": True, "name": "Archived"}}, "ui": {}}
        self.prefs = Mock()
        self.prefs.load.side_effect = lambda: copy.deepcopy(self.preferences)
        def save(value):
            self.preferences = copy.deepcopy(value)
            return copy.deepcopy(value)
        self.prefs.save.side_effect = save
        self.patches = [patch.object(native_export, "STORE", self.store),
                        patch.object(ha_export, "CONFIG_STORE", self.prefs),
                        patch.object(ha_export, "_inventory", AsyncMock(return_value={"devices": []})),
                        patch.object(native_lifecycle, "reconcile", AsyncMock(return_value={})),
                        patch.object(server_clean, "_on_startup", AsyncMock()),
                        patch.object(server_clean, "_on_cleanup", AsyncMock())]
        for item in self.patches:
            item.start()
        self.client = TestClient(TestServer(server_extended.create_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    async def test_main_configuration_and_autosave_edit_native_only(self):
        response = await self.client.get("/api/ha-export/config")
        data = await response.json()
        body = data["configuration"]
        self.assertEqual(body["export_mode"], "native")
        self.assertNotIn("light.old", body["entities"])
        body["entities"]["light.desk"]["name"] = "New name"
        response = await self.client.post("/api/ha-export/autosave", json=body)
        self.assertEqual(response.status, 200)
        self.assertEqual(self.store.load()["devices"]["desk"]["name"], "New name")
        self.assertEqual(self.preferences["entities"]["light.old"]["name"], "Archived")
        self.assertFalse(self.preferences["legacy_export_enabled"])
        # The same revision cannot overwrite the update.
        self.assertEqual((await self.client.post("/api/ha-export/autosave", json=body)).status, 409)

    async def test_native_selection_autosave_queues_immediate_lifecycle_reconciliation(self):
        body = (await (await self.client.get("/api/ha-export/config")).json())["configuration"]
        body["entities"]["light.desk"]["enabled"] = False
        trigger = Mock()
        self.client.server.app["native_reconcile_trigger"] = trigger

        response = await self.client.post("/api/ha-export/autosave", json=body)
        result = await response.json()

        self.assertEqual(response.status, 200)
        self.assertTrue(result["reconciliation_queued"])
        self.assertFalse(self.store.load()["devices"]["desk"].get("enabled", True))
        trigger.assert_called_once_with(force=True)

    async def test_group_api_saves_named_combined_endpoint_and_queues_reconciliation(self):
        inventory = {"devices": [{
            "device_id": "relay-device", "name": "Doppelrelais", "entities": [
                {"entity_id": "switch.relay_a", "domain": "switch", "name": "Relais A",
                 "category_suggestion": "SWITCH"},
                {"entity_id": "switch.relay_b", "domain": "switch", "name": "Relais B",
                 "category_suggestion": "SWITCH"},
            ],
        }]}
        with patch.object(ha_export, "_inventory", AsyncMock(return_value=inventory)):
            body = (await (await self.client.get("/api/ha-export/config")).json())["configuration"]
            trigger = Mock()
            self.client.server.app["native_reconcile_trigger"] = trigger
            response = await self.client.post("/api/native-export/group", json={
                "native_revision": body["native_revision"],
                "device_id": "relay-device",
                "entity_ids": ["switch.relay_a", "switch.relay_b"],
                "mode": "combined",
                "name": "Heizrelais",
                "names": {"switch.relay_a": "Büro", "switch.relay_b": "Keller"},
            })
            result = await response.json()

        self.assertEqual(response.status, 200, result)
        self.assertTrue(result["reconciliation_queued"])
        group = next(device for device in self.store.load()["devices"].values()
                     if device.get("group_mode") == "combined")
        self.assertEqual(group["name"], "Heizrelais")
        self.assertEqual({cap["interface"] for cap in group["capabilities"]}, {"Alexa.ToggleController"})
        self.assertEqual(result["configuration"]["entities"]["switch.relay_a"]["logical_device_name"], "Heizrelais")
        trigger.assert_called_once_with(force=True)

    async def test_group_api_rejects_stale_configuration_revision(self):
        with patch.object(ha_export, "_inventory", AsyncMock()) as inventory:
            response = await self.client.post("/api/native-export/group", json={
                "native_revision": "stale", "device_id": "relay-device",
                "entity_ids": ["switch.relay_a"], "mode": "separate", "name": "",
            })
        self.assertEqual(response.status, 409)
        inventory.assert_not_awaited()

    async def test_old_browser_cannot_enable_v5_and_migration_page_is_retired(self):
        response = await self.client.post("/api/ha-export/autosave", json={"entities": {"light.bad": {"enabled": True}}})
        self.assertEqual(response.status, 409)
        response = await self.client.get("/migration", allow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertEqual(response.headers["Location"], "/devices")
        self.assertEqual((await self.client.get("/api/native-migration")).status, 404)
        response = await self.client.get("/devices")
        self.assertNotIn("v5 → v6 Migration", await response.text())

    async def test_failed_core_check_restores_existing_bridge_file(self):
        target = Path(self.temp.name) / "alexa.yaml"
        original = b"alexa:\n  smart_home:\n    locale: de-DE\n"
        target.write_bytes(original)
        with patch.object(ha_export, "ALEXA_YAML_PATH", target), \
             patch.object(ha_export, "YAML_GENERATOR", AlexaYamlGenerator(target)), \
             patch.object(ha_control, "check_config", AsyncMock(return_value={"valid": False, "message": "Missing secret"})):
            response = await self.client.post("/api/ha-export/deploy", json={})
            self.assertEqual(response.status, 400)
            self.assertEqual(target.read_bytes(), original)

    async def test_disabled_sync_setting_never_installs_or_writes_ha_config(self):
        with patch.object(native_export.support, "deploy_component") as install, \
             patch.object(ha_export.YAML_GENERATOR, "deploy") as write, \
             patch.object(ha_control, "check_config", AsyncMock()) as check:
            response = await self.client.post("/api/native-export/set