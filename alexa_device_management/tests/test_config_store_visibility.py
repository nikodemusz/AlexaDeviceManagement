from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

WEB_DIR = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB_DIR))

from config_store import ConfigStore


class ConfigStoreVisibilityTests(unittest.TestCase):
    def test_preserves_hidden_devices_entities_and_alexa_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            store = ConfigStore(root / "config.json", root / "legacy.json", root / "alexa.yaml")
            saved = store.save({
                "ui": {
                    "hidden_devices": ["device-2", "device-1", "device-1"],
                    "hidden_entities": ["sensor.power"],
                    "hidden_alexa": ["smart_home:endpoint-1"],
                }
            }, create_backup=False)

        self.assertEqual(saved["schema_version"], 5)
        self.assertEqual(saved["ui"]["hidden_devices"], ["device-1", "device-2"])
        self.assertEqual(saved["ui"]["hidden_entities"], ["sensor.power"])
        self.assertEqual(saved["ui"]["hidden_alexa"], ["smart_home:endpoint-1"])


if __name__ == "__main__":
    unittest.main()
