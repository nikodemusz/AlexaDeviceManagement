"""Safe staged migration: preview, idempotency and conditional cutover."""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile
import unittest

WEB = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB))
from native_migration import prepare
from native_skill_config import NativeSkillConfigStore
from device_model import DeviceModelError

LAMBDA = pathlib.Path(__file__).resolve().parents[1] / "native_skill/lambda_function.py"
spec = importlib.util.spec_from_file_location("migration_lambda", LAMBDA)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.legacy = {"entities": {
            "light.desk": {"enabled": True, "name": "Schreibtisch"},
            "switch.plug": {"enabled": True, "name": "Steckdose"},
            "sensor.temp": {"enabled": True},
            "cover.blind": {"enabled": True},
            "light.ignored": {"enabled": False},
        }}
        self.native = NativeSkillConfigStore.default()
        self.native["enabled"] = True
        self.native["devices"]["zisterne"] = {
            "name": "Zisterne",
            "capabilities": [{"interface": "Alexa.RangeController", "instance": "fill",
                              "entity_id": "sensor.zisterne_fullstand",
                              "unit": "Alexa.Unit.Percent"}],
        }

    def test_preview_only_adds_disabled_supported_drafts(self):
        import copy
        original = copy.deepcopy(self.native)
        result, report = prepare(self.legacy, self.native)
        self.assertEqual(self.native, original)
        self.assertEqual(report["added"], ["cover.blind", "light.desk", "switch.plug"])
        self.assertEqual(report["unsupported"], ["sensor.temp"])
        self.assertFalse(result["devices"]["ha:light.desk"]["enabled"])
        self.assertEqual(result["devices"]["ha:light.desk"]["replaces_legacy_endpoint"],
                         "light#desk")
        self.assertIn("zisterne", result["devices"])
        self.assertEqual(result["devices"]["ha:cover.blind"]["display_category"], "INTERIOR_BLIND")
        self.assertEqual([cap["interface"] for cap in result["devices"]["ha:cover.blind"]["capabilities"]],
                         ["Alexa.RangeController", "Alexa.PlaybackController"])
        NativeSkillConfigStore.validate(result)
        self.assertEqual(module.migrated_legacy_ids(result), set())

    def test_activation_and_rollback_restore_discovery(self):
        proposed, _ = prepare(self.legacy, self.native)
        proposed["devices"]["ha:light.desk"]["enabled"] = True
        self.assertEqual(module.migrated_legacy_ids(proposed), {"light#desk"})
        proposed["devices"]["ha:light.desk"]["enabled"] = False
        self.assertEqual(module.migrated_legacy_ids(proposed), set())

    def test_second_run_is_idempotent(self):
        first, _ = prepare(self.legacy, self.native)
        second, report = prepare(self.legacy, first)
        self.assertEqual(second, first)
        self.assertEqual(report["added"], [])

    def test_duplicates_are_rejected(self):
        proposed, _ = prepare(self.legacy, self.native)
        proposed["devices"]["duplicate"] = {
            "name": "Duplikat", "enabled": False,
            "replaces_legacy_endpoint": "light#desk",
            "capabilities": [{"interface": "Alexa.PowerController",
                              "entity_id": "light.desk"}]}
        with self.assertRaises(DeviceModelError):
            NativeSkillConfigStore.validate(proposed)

    def test_file_is_not_created_in_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "native/config.yaml"
            store = NativeSkillConfigStore(path)
            proposed, _ = prepare(self.legacy, store.load())
            self.assertFalse(path.exists())
            store.save(proposed)
            self.assertTrue(path.exists())
            self.assertEqual(store.load(), NativeSkillConfigStore.validate(proposed))


if __name__ == "__main__":
    unittest.main()
