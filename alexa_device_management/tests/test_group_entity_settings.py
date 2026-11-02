"""Editing member metadata must preserve logical Alexa endpoints and bindings."""
import pathlib
import sys
import unittest
import json
import jsonschema

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rootfs/opt/alexa_device_management/web"))
from native_export import apply_device_group, apply_entities, apply_virtual_device_group, entity_settings
from native_skill_config import NativeSkillConfigStore
from test_native_device_grouping import relay_inventory
from test_native_skill_lambda import mod, event
from unittest.mock import patch


class GroupEntitySettingsTests(unittest.TestCase):
    def setUp(self):
        self.inventory = relay_inventory()
        self.grouped = apply_device_group(
            NativeSkillConfigStore.default(), "relay-device",
            ["switch.relay_a", "switch.relay_b"], "combined", "Relais", self.inventory,
            {"switch.relay_a": "A", "switch.relay_b": "B"})

    def test_group_and_member_names_type_and_access_round_trip_independently(self):
        before = entity_settings(self.grouped)
        updated = apply_entities(self.grouped, {"switch.relay_a": {
            **before["switch.relay_a"], "name": "Deckenlicht",
            "logical_device_name": "Wohnzimmer", "display_category": "LIGHT",
            "display_category_mode": "custom", "read_only": True}}, self.inventory)
        after = entity_settings(updated)
        jsonschema.validate(updated, json.loads((ROOT / "schemas/native-skill.schema.json").read_text()))
        jsonschema.validate(updated, json.loads((ROOT / "schemas/device-config.schema.json").read_text()))
        self.assertEqual(set(updated["devices"]), set(self.grouped["devices"]))
        self.assertEqual(after["switch.relay_a"]["name"], "Deckenlicht")
        self.assertEqual(after["switch.relay_a"]["display_category"], "LIGHT")
        self.assertTrue(after["switch.relay_a"]["read_only"])
        self.assertEqual(after["switch.relay_b"]["name"], "B")
        self.assertEqual(after["switch.relay_b"]["display_category"], "SWITCH")
        self.assertFalse(after["switch.relay_b"]["read_only"])
        self.assertEqual(after["switch.relay_b"]["logical_device_name"], "Wohnzimmer")
        self.assertEqual(apply_entities(updated, after, self.inventory), updated)
        separate = apply_device_group(updated, "relay-device", ["switch.relay_a", "switch.relay_b"],
                                      "separate", "", self.inventory)
        self.assertEqual(separate["devices"]["ha:switch.relay_a"]["display_category"], "LIGHT")
        self.assertTrue(entity_settings(separate)["switch.relay_a"]["read_only"])
        restored = apply_entities(updated, {"switch.relay_a": {
            **after["switch.relay_a"], "read_only": False,
            "display_category_mode": "standard", "display_category": ""}}, self.inventory)
        settings = entity_settings(restored)["switch.relay_a"]
        self.assertFalse(settings["read_only"])
        self.assertEqual(settings["display_category"], "SWITCH")

    def test_virtual_member_name_survives_reopening_group_editor(self):
        grouped = apply_virtual_device_group(self.grouped, "virtual:room",
            ["switch.relay_a", "switch.other"], "Zimmer", self.inventory)
        settings = entity_settings(grouped)
        updated = apply_entities(grouped, {"switch.relay_a": {
            **settings["switch.relay_a"], "name": "Leselicht", "display_category": "LIGHT",
            "display_category_mode": "custom", "read_only": True}}, self.inventory)
        self.assertEqual(updated["devices"]["virtual:room"]["member_names"]["switch.relay_a"], "Leselicht")
        from native_export import _dissolve_virtual_group
        separate = _dissolve_virtual_group(updated, "virtual:room")
        self.assertEqual(separate["devices"]["ha:switch.relay_a"]["display_category"], "LIGHT")
        self.assertTrue(entity_settings(separate)["switch.relay_a"]["read_only"])

    def test_sensor_cannot_be_made_writable(self):
        native = NativeSkillConfigStore.default()
        native["devices"] = {"sensor": {"name": "Temperatur", "capabilities": [{
            "interface": "Alexa.TemperatureSensor", "entity_id": "sensor.temperature"}]}}
        with self.assertRaisesRegex(ValueError, "nur lesenden"):
            apply_entities(native, {"sensor.temperature": {"enabled": True, "read_only": False}}, {"devices": []})

    def test_read_only_switch_is_discovered_and_rejects_commands_without_control_call(self):
        binding = {"interface": "Alexa.PowerController", "entity_id": "switch.relay_a", "read_only": True}
        self.assertTrue(mod.capability_config(binding)["properties"]["nonControllable"])
        config = {"devices": {"relay": {"name": "Relais", "capabilities": [binding]}}}
        def gateway(path, *args, **kwargs):
            if path == "/v1/authorize":
                return {"authorized": True}
            self.assertEqual(path, "/v1/config")
            return config
        with patch.object(mod, "gateway", side_effect=gateway):
            result = mod.lambda_handler(event("Alexa.PowerController", "TurnOn", "native:relay"), None)
        self.assertEqual(result["event"]["payload"]["type"], "INVALID_DIRECTIVE")


if __name__ == "__main__":
    unittest.main()
