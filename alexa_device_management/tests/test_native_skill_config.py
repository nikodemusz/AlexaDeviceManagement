from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

WEB_DIR = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB_DIR))

from config_store import ConfigStore
from native_skill_config import NativeSkillConfigError, NativeSkillConfigStore


class NativeSkillConfigTests(unittest.TestCase):
    def test_separate_config_is_disabled_and_not_created_on_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "native" / "config.yaml"
            self.assertFalse(path.exists())
            self.assertEqual(NativeSkillConfigStore(path).load()["devices"], {})
            self.assertFalse(path.exists())

    def test_native_save_does_not_touch_legacy_json_or_alexa_yaml(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            legacy = ConfigStore(root / "config.json", root / "legacy.json", root / "alexa.yaml")
            legacy.save({"entities": {"light.desk": {"enabled": True}}}, create_backup=False)
            (root / "alexa.yaml").write_text("existing legacy export\n")
            json_before = (root / "config.json").read_bytes()
            yaml_before = (root / "alexa.yaml").read_bytes()
            native = NativeSkillConfigStore(root / "native" / "config.yaml")
            config = native.default()
            config["devices"]["zisterne"] = {"name": "Zisterne", "capabilities": [
                {"interface": "Alexa.RangeController", "instance": "volume",
                 "entity_id": "sensor.zisterne_liter", "unit": "Volume.Liters"},
                {"interface": "Alexa.RangeController", "instance": "fill",
                 "entity_id": "sensor.zisterne_prozent", "unit": "Percent"},
            ]}
            native.save(config)
            self.assertEqual(len(native.load()["devices"]["zisterne"]["capabilities"]), 2)
            self.assertEqual((root / "config.json").read_bytes(), json_before)
            self.assertEqual((root / "alexa.yaml").read_bytes(), yaml_before)

    def test_invalid_yaml_and_invalid_update_cannot_replace_existing_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "native" / "config.yaml"
            store = NativeSkillConfigStore(path)
            store.save(store.default())
            before = path.read_bytes()
            with self.assertRaises(NativeSkillConfigError):
                store.save({"schema_version": 6, "enabled": "yes", "locale": "de-DE", "devices": {}})
            self.assertEqual(path.read_bytes(), before)
            path.write_text("devices: [\n")
            with self.assertRaises(NativeSkillConfigError):
                store.load()


if __name__ == "__main__":
    unittest.main()
