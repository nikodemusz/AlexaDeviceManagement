from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

WEB_DIR = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB_DIR))

from config_store import ConfigStore
from device_model import DeviceModelError, device_preview, validate_devices


class DeviceModelTests(unittest.TestCase):
    def store(self, root):
        return ConfigStore(root / "config.json", root / "legacy.json", root / "alexa.yaml")

    def test_migration_preserves_legacy_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(pathlib.Path(directory))
            old = {"schema_version": 5, "entities": {
                "light.desk": {"enabled": True, "name": "Desk"},
                "sensor.hidden": {"enabled": False},
                "sensor.tank": {"enabled": True, "name": "Zisterne"},
            }}
            first = store.save(old, create_backup=False)
            second = store.load()
            self.assertEqual(first["schema_version"], 6)
            self.assertEqual(first["devices"], second["devices"])
            self.assertEqual(first["entities"], old["entities"])
            self.assertEqual(set(first["devices"]), {"ha:light.desk", "ha:sensor.tank"})
            self.assertEqual(first["devices"]["ha:sensor.tank"]["capabilities"], [])

    def test_multiple_bindings_still_one_endpoint(self):
        devices = {"zisterne": {"name": "Zisterne", "capabilities": [
            {"interface": "Alexa.RangeController", "instance": "volume",
             "entity_id": "sensor.tank_liters", "unit": "Volume.Liters"},
            {"interface": "Alexa.RangeController", "instance": "fill",
             "entity_id": "sensor.tank_percent", "unit": "Percent"},
            {"interface": "Alexa.ToggleController", "instance": "pump",
             "entity_id": "switch.tank_pump"},
        ]}}
        self.assertEqual(len(device_preview(devices)), 1)
        self.assertEqual(len(device_preview(devices)[0]["capabilities"]), 3)
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(pathlib.Path(directory))
            saved = store.save({"devices": devices}, create_backup=False)
            self.assertEqual(store.load()["devices"], saved["devices"])

    def test_one_light_multiple_capabilities(self):
        devices = {"living_light": {"name": "Wohnzimmerlicht", "capabilities": [
            {"interface": "Alexa.PowerController", "entity_id": "light.living"},
            {"interface": "Alexa.BrightnessController", "entity_id": "light.living"},
            {"interface": "Alexa.RangeController", "instance": "watts",
             "entity_id": "sensor.living_watts", "unit": "Power.Watts"},
        ]}}
        self.assertEqual(len(device_preview(devices)), 1)

    def test_rejects_ambiguous_duplicate_controller(self):
        data = {"tank": {"name": "Tank", "capabilities": [
            {"interface": "Alexa.RangeController", "instance": "fill",
             "entity_id": "sensor.a", "unit": "Percent"},
            {"interface": "Alexa.RangeController", "instance": "fill",
             "entity_id": "sensor.b", "unit": "Percent"},
        ]}}
        with self.assertRaises(DeviceModelError):
            validate_devices(data)

    def test_invalid_save_does_not_overwrite_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            store = self.store(root)
            store.save({"devices": {"good": {"name": "Gut", "capabilities": []}}}, create_backup=False)
            before = (root / "config.json").read_bytes()
            with self.assertRaises(DeviceModelError):
                store.save({"devices": {"bad": {"name": "", "capabilities": []}}})
            self.assertEqual(before, (root / "config.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
