from __future__ import annotations

import hashlib
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rootfs/opt/alexa_device_management/web"))

from native_export import apply_device_group, entity_settings
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


if __name__ == "__main__":
    unittest.main()
