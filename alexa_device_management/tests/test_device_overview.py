from __future__ import annotations

import pathlib
import sys
import unittest

WEB_DIR = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB_DIR))

from device_overview import build_overview


def ha_inventory() -> dict:
    return {
        "devices": [{
            "device_id": "device-1",
            "name": "Wohnzimmer Licht",
            "area_id": "living",
            "area_name": "Wohnzimmer",
            "entities": [
                {
                    "entity_id": "light.wohnzimmer",
                    "domain": "light",
                    "name": "Deckenlicht",
                    "category_suggestion": "LIGHT",
                },
                {
                    "entity_id": "sensor.wohnzimmer_power",
                    "domain": "sensor",
                    "name": "Leistung",
                    "category_suggestion": "OTHER",
                },
            ],
        }],
        "areas": [{"area_id": "living", "name": "Wohnzimmer"}],
        "display_categories": ["LIGHT", "OTHER"],
    }


def alexa_device(serial: str, entity_id: str, name: str = "Wohnzimmer Licht") -> dict:
    return {
        "serial": serial,
        "appliance_id": serial,
        "name": name,
        "source": "smart_home",
        "online": True,
        "raw": {
            "description": f"{entity_id} via Home Assistant",
            "entityId": serial,
        },
    }


class DeviceOverviewTests(unittest.TestCase):
    def test_matches_exact_home_assistant_entity(self) -> None:
        result = build_overview(
            ha_inventory(),
            [alexa_device("endpoint-1", "light.wohnzimmer")],
            [],
            {"entities": {"light.wohnzimmer": {"enabled": True}}, "ui": {}},
        )

        entity = result["devices"][0]["entities"][0]
        self.assertEqual(entity["status"], "synced")
        self.assertTrue(entity["alexa"]["present"])
        self.assertEqual(result["summary"]["synced"], 1)
        self.assertEqual(result["alexa_only"], [])

    def test_detects_duplicate_and_disabled_existing_endpoint(self) -> None:
        result = build_overview(
            ha_inventory(),
            [
                alexa_device("endpoint-1", "light.wohnzimmer"),
                alexa_device("endpoint-2", "light.wohnzimmer", "Altes Licht"),
                alexa_device("endpoint-3", "sensor.wohnzimmer_power", "Leistung"),
            ],
            [],
            {
                "entities": {
                    "light.wohnzimmer": {"enabled": True},
                    "sensor.wohnzimmer_power": {"enabled": False},
                },
                "ui": {},
            },
        )

        light, sensor = result["devices"][0]["entities"]
        self.assertEqual(light["status"], "duplicate")
        self.assertEqual(sensor["status"], "only_alexa")
        self.assertEqual(result["summary"]["duplicates"], 1)
        self.assertEqual(result["summary"]["only_alexa"], 1)

    def test_does_not_match_by_friendly_name_only(self) -> None:
        result = build_overview(
            ha_inventory(),
            [{
                "serial": "unrelated",
                "appliance_id": "unrelated",
                "name": "Wohnzimmer Licht",
                "source": "smart_home",
                "online": True,
                "raw": {},
            }],
            [],
            {"entities": {"light.wohnzimmer": {"enabled": True}}, "ui": {}},
        )

        entity = result["devices"][0]["entities"][0]
        self.assertEqual(entity["status"], "pending")
        self.assertEqual(len(result["alexa_only"]), 1)

    def test_preserves_independent_visibility_flags(self) -> None:
        result = build_overview(
            ha_inventory(),
            [alexa_device("endpoint-1", "light.wohnzimmer")],
            [],
            {
                "entities": {"light.wohnzimmer": {"enabled": True}},
                "ui": {
                    "hidden_devices": ["device-1"],
                    "hidden_entities": ["sensor.wohnzimmer_power"],
                    "hidden_alexa": [],
                },
            },
        )

        device = result["devices"][0]
        self.assertTrue(device["hidden"])
        self.assertTrue(all(entity["hidden"] for entity in device["entities"]))
        self.assertTrue(device["entities"][1]["hidden_directly"])


if __name__ == "__main__":
    unittest.main()
