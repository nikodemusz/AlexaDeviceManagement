from __future__ import annotations

import hashlib
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rootfs/opt/alexa_device_management/web"))

from native_export import (
    apply_device_group, apply_virtual_device_group, entity_settings,
    normalize_active_device_groups, standard_device_group,
)
from native_skill_config import NativeSkillConfigStore


def relay_inventory():
    return {"devices": [{
        "device_id": "relay-device",
        "name": "Doppelrelais",
        "display_category": "SWITCH",
        "entities": [
            {"entity_id": "switch.relay_a", "domain": "switch", "name": "Relais A",
             "category_suggestion": "SWITCH"},
            {"entity_id": "switch.relay_b", "domain": "switch", "name": "Relais B",
             "category_suggestion": "SWITCH"},
        ],
    }, {
        "device_id": "other-device",
        "entities": [{"entity_id": "switch.other", "domain": "switch", "name": "Andere",
                      "category_suggestion": "SWITCH"}],
    }]}


class NativeDeviceGroupingTests(unittest.TestCase):
    def setUp(self):
        self.native = NativeSkillConfigStore.default()
        self.native["enabled"] = True
        self.inventory = relay_inventory()

    def test_automatic_standard_keeps_a_multi_switch_device_as_one_named_alexa_device(self):
        result = standard_device_group(self.inventory["devices"][0])

        self.assertEqual(result["mode"], "combined")
        self.assertEqual(result["entity_ids"], ["switch.relay_a", "switch.relay_b"])
        self.assertEqual(result["endpoint_count"], 1)
        self.assertEqual(result["reason"], "relay_outputs")

    def test_manual_sync_regroups_previously_enabled_relay_endpoints(self):
        legacy = NativeSkillConfigStore.default()
        legacy["enabled"] = True
        legacy["devices"] = {
            "ha:switch.relay_a": {"name": "Relais A", "capabilities": [
                {"interface": "Alexa.PowerController", "entity_id": "switch.relay_a"}]},
            "ha:switch.relay_b": {"name": "Relais B", "capabilities": [
                {"interface": "Alexa.PowerController", "entity_id": "switch.relay_b"}]},
        }

        normalized, groups = normalize_active_device_groups(legacy, self.inventory)

        self.assertEqual(groups[0]["old_endpoint_count"], 2)
        self.assertEqual(groups[0]["endpoint_count"], 1)
        self.assertEqual(set(normalized["devices"]), {"ha:group:7e02b2c213f2674b"})
        self.assertEqual(normalized["devices"]["ha:group:7e02b2c213f2674b"]["group_mode"], "combined")

    def test_sync_removes_duplicate_thermostat_temperature_endpoint(self):
        legacy = NativeSkillConfigStore.default()
        legacy["enabled"] = True
        legacy["devices"] = {
            "ha:climate.bath": {"name": "Thermostat Bad", "capabilities": [
                {"interface": "Alexa.ThermostatController", "entity_id": "climate.bath",
                 "supported_modes": ["HEAT"]}]},
            "ha:sensor.bath_temperature": {"name": "Temperatur Bad", "capabilities": [
                {"interface": "Alexa.TemperatureSensor", "entity_id": "sensor.bath_temperature"}]},
            "ha:number.bath_setpoint": {"name": "Wunschtemperatur Bad", "capabilities": [
                {"interface": "Alexa.RangeController", "instance": "thermostat.setpoint_helper",
                 "entity_id": "number.bath_setpoint", "unit": "Alexa.Unit.Temperature",
                 "minimum": 5, "maximum": 35, "precision": 0.1, "read_only": True}]},
        }
        inventory = {"devices": [{
            "device_id": "bath-thermostat", "name": "Thermostat Bad", "entities": [
                {"entity_id": "climate.bath", "domain": "climate", "name": "Thermostat Bad",
                 "hvac_modes": ["off", "heat"]},
                {"entity_id": "sensor.bath_temperature", "domain": "sensor",
                 "device_class": "temperature", "name": "Temperatur Bad"},
                {"entity_id": "number.bath_setpoint", "domain": "number",
                 "name": "Wunschtemperatur Bad"},
            ],
        }]}

        normalized, groups = normalize_active_device_groups(legacy, inventory)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["removed_helpers"], 2)
        self.assertEqual(set(normalized["devices"]), {"ha:climate.bath"})
        thermostat = normalized["devices"]["ha:climate.bath"]
        self.assertEqual(thermostat["group_mode"], "combined")
        self.assertEqual([cap["interface"] for cap in thermostat["capabilities"]],
                         ["Alexa.ThermostatController"])

    def test_sync_preserves_explicit_separate_choice_and_does_not_enable_other_entities(self):
        separate = apply_device_group(
            self.native, "relay-device", ["switch.relay_a", "switch.relay_b"],
            "separate", "", self.inventory,
        )
        unchanged, groups = normalize_active_device_groups(separate, self.inventory)
        self.assertEqual(groups, [])
        self.assertEqual(unchanged, separate)

        only_one = NativeSkillConfigStore.default()
        only_one["enabled"] = True
        only_one["devices"] = {"ha:switch.relay_a": {"name": "Relais A", "capabilities": [
            {"interface": "Alexa.PowerController", "entity_id": "switch.relay_a"}]}}
        unchanged, groups = normalize_active_device_groups(only_one, self.inventory)
        self.assertEqual(groups, [])
        self.assertEqual(unchanged, NativeSkillConfigStore.validate(only_one))

    def test_single_function_combined_endpoint_keeps_its_stable_entity_key(self):
        inventory = {"devices": [{
            "device_id": "light-device", "name": "Wohnzimmerlicht", "entities": [
                {"entity_id": "light.room", "domain": "light", "name": "Deckenlicht",
                 "supported_color_modes": ["brightness"]},
            ],
        }]}
        proposed = apply_device_group(
            self.native, "light-device", ["light.room"], "combined", "Wohnzimmerlicht", inventory,
        )

        self.assertEqual(set(proposed["devices"]), {"ha:light.room"})
        self.assertEqual(proposed["devices"]["ha:light.room"]["name"], "Wohnzimmerlicht")
        self.assertEqual(proposed["devices"]["ha:light.room"]["group_mode"], "combined")

    def test_combines_switches_as_named_independent_toggle_controls(self):
        proposed = apply_device_group(
            self.native, "relay-device", ["switch.relay_a", "switch.relay_b"],
            "combined", "Heizrelais", self.inventory,
            {"switch.relay_a": "Büro", "switch.relay_b": "Keller"},
        )

        self.assertEqual(list(proposed["devices"]), ["ha:group:7e02b2c213f2674b"])
        group = next(iter(proposed["devices"].values()))
        self.assertEqual(group["name"], "Heizrelais")
        self.assertEqual(group["members"], ["switch.relay_a", "switch.relay_b"])
        self.assertEqual([cap["interface"] for cap in group["capabilities"]],
                         ["Alexa.ToggleController", "Alexa.ToggleController"])
        self.assertEqual({cap["instance"] for cap in group["capabilities"]},
                         {"power_" + hashlib.sha256(eid.encode()).hexdigest()[:12]
                          for eid in ("switch.relay_a", "switch.relay_b")})
        settings = entity_settings(proposed)
        self.assertEqual(settings["switch.relay_a"]["name"], "Büro")
        self.assertEqual(settings["switch.relay_b"]["name"], "Keller")
        self.assertEqual(settings["switch.relay_a"]["logical_device_name"], "Heizrelais")
        self.assertTrue(all(value["enabled"] for value in settings.values()))

    def test_combined_roller_shutters_get_distinct_position_sliders(self):
        inventory = {"devices": [{
            "device_id": "shutter-device", "name": "Rollläden Schlafzimmer", "entities": [
                {"entity_id": "cover.window_left", "domain": "cover", "name": "Links",
                 "supported_features": 4},
                {"entity_id": "cover.window_right", "domain": "cover", "name": "Rechts",
                 "supported_features": 4},
            ],
        }]}
        combined = apply_device_group(
            self.native, "shutter-device", ["cover.window_left", "cover.window_right"],
            "combined", "Rollläden Schlafzimmer", inventory,
        )
        group = next(iter(combined["devices"].values()))
        self.assertEqual(group["group_mode"], "combined")
        self.assertEqual({capability["interface"] for capability in group["capabilities"]},
                         {"Alexa.RangeController"})
        self.assertEqual({capability["instance"] for capability in group["capabilities"]}, {
            "cover.position_" + hashlib.sha256(entity_id.encode()).hexdigest()[:12]
            for entity_id in ("cover.window_left", "cover.window_right")
        })

        separate = apply_device_group(
            combined, "shutter-device", ["cover.window_left", "cover.window_right"],
            "separate", "", inventory,
        )
        self.assertEqual({device["capabilities"][0]["instance"]
                          for device in separate["devices"].values()}, {"cover.position"})

    def test_unchecked_member_is_removed_and_separate_mode_restores_power_controllers(self):
        combined = apply_device_group(
            self.native, "relay-device", ["switch.relay_a", "switch.relay_b"],
            "combined", "Heizrelais", self.inventory,
        )
        partial = apply_device_group(
            combined, "relay-device", ["switch.relay_a"], "combined", "Heizrelais",
            self.inventory,
        )
        self.assertEqual(partial["devices"]["ha:group:7e02b2c213f2674b"]["members"],
                         ["switch.relay_a"])
        self.assertNotIn("switch.relay_b", entity_settings(partial))

        separate = apply_device_group(
            combined, "relay-device", ["switch.relay_a", "switch.relay_b"],
            "separate", "", self.inventory,
            {"switch.relay_a": "Büro", "switch.relay_b": "Keller"},
        )
        self.assertEqual(set(separate["devices"]), {"ha:switch.relay_a", "ha:switch.relay_b"})
        self.assertEqual({device["capabilities"][0]["interface"]
                          for device in separate["devices"].values()}, {"Alexa.PowerController"})
        self.assertEqual({device["group_mode"] for device in separate["devices"].values()}, {"separate"})
        self.assertEqual({device["ha_device_id"] for device in separate["devices"].values()}, {"relay-device"})
        self.assertEqual(entity_settings(separate)["switch.relay_a"]["group_mode"], "separate")

    def test_entities_from_another_ha_device_cannot_be_mixed(self):
        with self.assertRaisesRegex(ValueError, "selben Home-Assistant-Gerät"):
            apply_device_group(self.native, "relay-device", ["switch.relay_a", "switch.other"],
                               "combined", "Falsche Gruppe", self.inventory)

    def test_custom_profile_is_saved_and_standard_profile_can_be_selected_explicitly(self):
        custom = apply_device_group(
            self.native, "relay-device", ["switch.relay_a"], "separate", "", self.inventory,
            profiles={"switch.relay_a": {"mode": "custom", "capabilities": ["Alexa.PowerController"],
                                           "display_category": "SMARTPLUG",
                                           "display_category_mode": "custom"}},
        )
        capability = custom["devices"]["ha:switch.relay_a"]["capabilities"][0]
        self.assertEqual(capability["capability_mode"], "custom")
        self.assertEqual(custom["devices"]["ha:switch.relay_a"]["display_category"], "SMARTPLUG")
        settings = entity_settings(custom)["switch.relay_a"]
        self.assertEqual(settings["capability_mode"], "custom")

        standard = apply_device_group(
            custom, "relay-device", ["switch.relay_a"], "separate", "", self.inventory,
            profiles={"switch.relay_a": {"mode": "standard", "capabilities": ["Alexa.PowerController"]}},
        )
        capability = standard["devices"]["ha:switch.relay_a"]["capabilities"][0]
        self.assertNotIn("capability_mode", capability)
        self.assertEqual(entity_settings(standard)["switch.relay_a"]["capability_mode"], "standard")

    def test_stale_group_members_missing_from_ha_inventory_are_retired(self):
        combined = apply_device_group(
            self.native, "relay-device", ["switch.relay_a", "switch.relay_b"],
            "combined", "Heizrelais", self.inventory,
        )
        current_inventory = {"devices": [{
            "device_id": "relay-device", "name": "Doppelrelais",
            "entities": [self.inventory["devices"][0]["entities"][0]],
        }]}

        separate = apply_device_group(combined, "relay-device", ["switch.relay_a"],
                                      "separate", "", current_inventory)

        self.assertEqual(set(separate["devices"]), {"ha:switch.relay_a"})

    def test_virtual_group_combines_entities_from_different_ha_devices(self):
        native = NativeSkillConfigStore.default()
        native["enabled"] = True
        native["devices"] = {"ha:relay-group": {
            "name": "Doppelrelais", "enabled": True, "group_mode": "combined",
            "ha_device_id": "relay-device", "members": ["switch.relay_a", "switch.relay_b"],
            "capabilities": [
                {"interface": "Alexa.ToggleController", "instance": "power_a",
                 "entity_id": "switch.relay_a", "capability_names": ["Relais A"]},
                {"interface": "Alexa.ToggleController", "instance": "power_b",
                 "entity_id": "switch.relay_b", "capability_names": ["Relais B"]},
            ],
        }}
        inventory = relay_inventory()
        inventory["devices"][1]["entities"].append({
            "entity_id": "sensor.tank_liters", "domain": "sensor", "name": "Zisterne Liter",
            "unit_of_measurement": "L", "state": "2500",
        })

        grouped = apply_virtual_device_group(
            native, "virtual:tank", ["switch.relay_a", "sensor.tank_liters"],
            "Zisterne", inventory,
            {"switch.relay_a": "Pumpe", "sensor.tank_liters": "Wassermenge"},
            {"sensor.tank_liters": {"mode": "read_only_range", "unit": "Alexa.Unit.Liters",
                                     "instance": "value_liters", "minimum": 0,
                                     "maximum": 4000, "precision": 1}},
        )

        virtual = grouped["devices"]["virtual:tank"]
        self.assertTrue(virtual["virtual_device"])
        self.assertEqual(virtual["ha_device_id"], "virtual:tank")
        self.assertEqual(set(virtual["members"]), {"switch.relay_a", "sensor.tank_liters"})
        self.assertEqual({cap["interface"] for cap in virtual["capabilities"]},
                         {"Alexa.PowerController", "Alexa.RangeController"})
        self.assertEqual(grouped["devices"]["ha:relay-group"]["members"], ["switch.relay_b"])

    def test_virtual_group_edit_restores_unchecked_members_as_individual_endpoints(self):
        inventory = relay_inventory()
        inventory["devices"][1]["entities"].append({
            "entity_id": "sensor.tank_liters", "domain": "sensor", "name": "Zisterne Liter",
            "unit_of_measurement": "L", "state": "2500",
        })
        initial = apply_virtual_device_group(
            self.native, "virtual:tank", ["switch.relay_a", "sensor.tank_liters"],
            "Zisterne", inventory,
            {"switch.relay_a": "Pumpe", "sensor.tank_liters": "Wassermenge"},
            {"sensor.tank_liters": {"mode": "read_only_range", "unit": "Alexa.Unit.Liters",
                                     "instance": "value_liters", "minimum": 0,
                                     "maximum": 4000, "precision": 1}},
        )
        updated = apply_virtual_device_group(
            initial, "virtual:tank", ["sensor.tank_liters"], "Zisterne", inventory,
            {"sensor.tank_liters": "Wassermenge"},
            {"sensor.tank_liters": {"mode": "preserve"}},
        )

        self.assertEqual(updated["devices"]["virtual:tank"]["members"], ["sensor.tank_liters"])
        self.assertEqual(updated["devices"]["ha:switch.relay_a"]["capabilities"][0]["interface"],
                         "Alexa.PowerController")

    def test_dissolving_virtual_group_restores_members_as_individual_endpoints(self):
        from native_export import _dissolve_virtual_group

        inventory = relay_inventory()
        inventory["devices"][1]["entities"].append({
            "entity_id": "sensor.tank_liters", "domain": "sensor", "name": "Zisterne Liter",
            "unit_of_measurement": "L", "state": "2500",
        })
        grouped = apply_virtual_device_group(
            self.native, "virtual:tank", ["switch.relay_a", "sensor.tank_liters"],
            "Zisterne", inventory,
            {"switch.relay_a": "Pumpe", "sensor.tank_liters": "Wassermenge"},
            {"sensor.tank_liters": {"mode": "read_only_range", "unit": "Alexa.Unit.Liters",
                                     "instance": "value_liters", "minimum": 0,
                                     "maximum": 4000, "precision": 1}},
        )
        dissolved = _dissolve_virtual_group(grouped, "virtual:tank")

        self.assertNotIn("virtual:tank", dissolved["devices"])
        self.assertIn("ha:switch.relay_a", dissolved["devices"])
        self.assertIn("ha:sensor.tank_liters", dissolved["devices"])


if __name__ == "__main__":
    unittest.main()
