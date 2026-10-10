"""Migration UI must preserve legacy export and existing native devices."""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web

ROOT = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(ROOT))
from config_store import ConfigStore
from native_skill_config import NativeSkillConfigStore
import native_migration_ui


class MigrationUITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.legacy = ConfigStore(root / "config.json", root / "legacy.json", root / "alexa.yaml")
        self.legacy.save({"entities": {
            "light.desk": {"enabled": True, "name": "Desk"},
            "cover.blind": {"enabled": True, "name": "Blind"}}}, create_backup=False)
        self.native = NativeSkillConfigStore(root / "native/config.yaml")
        current = self.native.default()
        current["enabled"] = True
        current["devices"]["zisterne"] = {"name": "Zisterne", "capabilities": [
            {"interface": "Alexa.RangeController", "instance": "fill", "entity_id": "sensor.fill",
             "unit": "Alexa.Unit.Percent"}]}
        self.native.save(current)
        self.original = (root / "config.json").read_bytes()
        old_store = native_migration_ui.NATIVE_STORE
        self.addCleanup(setattr, native_migration_ui, "NATIVE_STORE", old_store)
        native_migration_ui.NATIVE_STORE = self.native
        app = web.Application()
        native_migration_ui.register_routes(app, self.legacy)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def test_preview_import_activate_and_rollback(self):
        r = await self.client.get("/api/native-migration")
        self.assertEqual(r.status, 200)
        data = await r.json()
        self.assertEqual(data["preview"]["added"], ["cover.blind", "light.desk"])
        self.assertEqual(len(data["rows"]), 2)
        self.assertEqual(len(self.native.load()["devices"]), 1)

        r = await self.client.post("/api/native-migration/import")
        self.assertEqual(r.status, 200)
        data = await r.json()
        self.assertEqual(len(data["report"]["added"]), 2)
        self.assertFalse(self.native.load()["devices"]["ha:light.desk"]["enabled"])
        self.assertIn("zisterne", self.native.load()["devices"])

        r = await self.client.post("/api/native-migration/activate", json={
            "id": "ha:light.desk", "enabled": True})
        self.assertEqual(r.status, 200)
        self.assertTrue(self.native.load()["devices"]["ha:light.desk"]["enabled"])

        r = await self.client.post("/api/native-migration/activate", json={
            "id": "ha:light.desk", "enabled": False})
        self.assertEqual(r.status, 200)
        self.assertFalse(self.native.load()["devices"]["ha:light.desk"]["enabled"])
        self.assertEqual(self.original, self.legacy.path.read_bytes())

    async def test_cannot_activate_when_native_skill_is_disabled(self):
        await self.client.post("/api/native-migration/import")
        config = self.native.load()
        config["enabled"] = False
        self.native.save(config)
        r = await self.client.post("/api/native-migration/activate", json={
            "id": "ha:light.desk", "enabled": True})
        self.assertEqual(r.status, 409)

    async def test_global_activation_and_yaml_editor_validation(self):
        response = await self.client.get("/api/native-migration/config")
        self.assertEqual(response.status, 200)
        loaded = await response.json()
        self.assertIn("zisterne", loaded["yaml"])
        revision = loaded["revision"]
        r = await self.client.post("/api/native-migration/global",
                                   json={"enabled": False, "revision": revision})
        self.assertEqual(r.status, 200)
        self.assertFalse(self.native.load()["enabled"])

        r = await self.client.post("/api/native-migration/config/validate",
                                   json={"yaml": "schema_version: 5\\nenabled: true\\nlocale: de-DE\\ndevices: {}"})
        self.assertEqual(r.status, 400)
        self.assertEqual(self.native.load()["devices"]["zisterne"]["name"], "Zisterne")

        current = await (await self.client.get("/api/native-migration/config")).json()
        modified = current["yaml"].replace("enabled: false", "enabled: true", 1)
        r = await self.client.post("/api/native-migration/config/validate",
                                   json={"yaml": modified})
        self.assertEqual(r.status, 200)
        r = await self.client.post("/api/native-migration/config/save",
                                   json={"yaml": modified, "revision": current["revision"]})
        self.assertEqual(r.status, 200)
        self.assertTrue(self.native.load()["enabled"])
        self.assertEqual(self.original, self.legacy.path.read_bytes())

    async def test_rejects_stale_editor_without_modifying_file(self):
        before = await (await self.client.get("/api/native-migration/config")).json()
        self.native.save({**self.native.load(), "locale": "en-US"})
        r = await self.client.post("/api/native-migration/config/save",
                                   json={"yaml": before["yaml"], "revision": before["revision"]})
        self.assertEqual(r.status, 409)
        self.assertEqual(self.native.load()["locale"], "en-US")

    async def test_unknown_device_rejected(self):
        r = await self.client.post("/api/native-migration/activate", json={
            "id": "zisterne", "enabled": False})
        self.assertEqual(r.status, 400)


if __name__ == "__main__":
    unittest.main()
