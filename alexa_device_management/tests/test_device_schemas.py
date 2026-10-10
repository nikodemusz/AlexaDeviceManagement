"""Published JSON schemas must accept the same cover metadata as runtime."""
from __future__ import annotations

import json
import pathlib
import sys
import unittest
from copy import deepcopy

import yaml
from jsonschema import Draft202012Validator, ValidationError

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rootfs/opt/alexa_device_management/web"))
from device_model import DeviceModelError, SUPPORTED_INTERFACES, validate_devices
from native_migration import prepare
from native_skill_config import NativeSkillConfigStore


class DeviceSchemaTests(unittest.TestCase):
    def schemas(self):
        for name in ("device-config", "native-skill"):
            schema = json.loads((ROOT / f"schemas/{name}.schema.json").read_text())
            Draft202012Validator.check_schema(schema)
            yield schema

    def test_interfaces_match_runtime_and_examples_validate(self):
        config = yaml.safe_load((ROOT / "examples/native-config.yaml").read_text())
        NativeSkillConfigStore.validate(config)
        for schema in self.schemas():
            self.assertEqual(set(schema["$defs"]["capability"]["properties"]["interface"]["enum"]),
                             set(SUPPORTED_INTERFACES))
            Draft202012Validator(schema).validate(config)

    def test_generated_disabled_cover_drafts_validate_without_changing_legacy(self):
        legacy = {"entities": {"cover.blind": {"enabled": True, "name": "Rollladen"}}}
        before = deepcopy(legacy)
        config, report = prepare(legacy, NativeSkillConfigStore.default())
        self.assertEqual(report["added"], ["cover.blind"])
        self.assertEqual(legacy, before)
        self.assertFalse(config["enabled"])
        self.assertFalse(config["devices"]["ha:cover.blind"]["enabled"])
        NativeSkillConfigStore.validate(config)
        for schema in self.schemas():
            Draft202012Validator(schema).validate(config)

    def test_writable_sensor_ranges_and_non_cover_playback_stay_rejected(self):
        for binding in (
            {"interface": "Alexa.RangeController", "entity_id": "sensor.tank",
             "instance": "cover.position", "unit": "Alexa.Unit.Percent", "read_only": False},
            {"interface": "Alexa.RangeController", "entity_id": "cover.blind",
             "instance": "wrong", "unit": "Alexa.Unit.Percent", "read_only": False},
            {"interface": "Alexa.PlaybackController", "entity_id": "light.desk"},
            {"interface": "Alexa.PlaybackController", "entity_id": "cover.blind",
             "supported_operations": ["Pause"]},
        ):
            config = NativeSkillConfigStore.default()
            config["devices"] = {"bad": {"name": "Bad", "capabilities": [binding]}}
            with self.subTest(binding=binding):
                with self.assertRaises(DeviceModelError):
                    validate_devices(config["devices"])
                for schema in self.schemas():
                    with self.assertRaises(ValidationError):
                        Draft202012Validator(schema).validate(config)


if __name__ == "__main__":
    unittest.main()
