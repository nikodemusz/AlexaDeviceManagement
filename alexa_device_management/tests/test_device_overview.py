from __future__ import annotations

import pathlib
import sys
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, Mock, patch

WEB_DIR = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB_DIR))

import device_overview
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
    def test_one_native_endpoint_matches_multiple_bindings_without_legacy_changes(self):
        legacy = {"entities": {}, "devices": {"unrelated": {"name": "Ignored", "capabilities": []}}}
        native = {"enabled": True, "devices": {"living": {"capabilities": [
            {"entity_id": "light.wohnzimmer", "interface": "Alexa.PowerController"},
            {"entity_id": "light.wohnzimmer", "interface": "Alexa.BrightnessController"},
            {"entity_id": "sensor.wohnzimmer_power", "interface": "Alexa.RangeController"},
        ]}}}
        original = deepcopy((legacy, native))
        endpoint = {"serial": "native:living", "source": "smart_home", "raw": {}}
        result = build_overview(ha_inventory(), [endpoint], [], legacy, native)
        for entity in result["devices"][0]["entities"]:
            self.assertEqual(entity["status"], "synced")
            self.assertEqual(entity["alexa"]["count"], 1)
            self.assertEqual(entity["native"]["endpoint_ids"], ["native:living"])
            self.assertFalse(entity["export"]["enabled"])
        self.assertEqual(result["summary"]["selected"], 2)
        self.assertEqual(result["summary"]["native_selected"], 2)
        self.assertEqual(result["alexa_only"], [])
        self.assertEqual((legacy, native), original)

    def test_disabled_native_drafts_and_legacy_json_devices_are_not_active_exports(self):
        device = {"capabilities": [{"entity_id": "light.wohnzimmer"}]}
        endpoint = {"serial": "native:living", "source": "smart_home", "raw": {}}
        for global_enabled, device_enabled in ((False, True), (True, False)):
            native = {"enabled": global_enabled, "devices": {
                "living": {**device, "enabled": device_enabled}}}
            legacy = {"entities": {}, "devices": {"living": device}}
            result = build_overview(ha_inventory(), [endpoint], [], legacy, native)
            entity = result["devices"][0]["entities"][0]
            self.assertEqual(entity["status"], "not_exposed")
            self.assertFalse(entity["native"]["enabled"])
            self.assertEqual(result["summary"]["selected"], 0)

    def test_offline_matching_endpoint_is_associated_without_proving_connectivity(self):
        endpoint = alexa_device("endpoint-1", "light.wohnzimmer")
        endpoint["online"] = False
        result = build_overview(ha_inventory(), [endpoint], [], {
            "entities": {"light.wohnzimmer": {"enabled": True}}})
        entity = result["devices"][0]["entities"][0]
        self.assertEqual(entity["status"], "synced")
        self.assertFalse(entity["alexa"]["matches"][0]["online"])

    def test_graphql_source_alone_does_not_prove_orphaned_device(self):
        endpoint = {"serial": "unrelated", "source": "graphql", "raw": {}}
        result = build_overview(ha_inventory(), [endpoint], [], {})
        self.assertEqual(result["alexa_only"][0]["status"], "unmatched")

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


class DeviceOverviewRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_route_reads_native_yaml_and_survives_invalid_optional_native_config(self):
        server = Mock()
        server.is_configured.return_value = True
        server._DEVICES_CACHE = {"updated_at": 1, "devices": [
            {"serial": "native:living", "source": "smart_home", "raw": {}}]}
        store = Mock()
        store.load.return_value = {"entities": {}}
        request = Mock()
        request.app = {"device_overview_server": server, "device_overview_store": store}
        request.rel_url.query = {}
        native = {"enabled": True, "devices": {"living": {"capabilities": [
            {"entity_id": "light.wohnzimmer"}]}}}
        import json
        with patch.object(device_overview.ha_export, "_inventory", new=AsyncMock(return_value=ha_inventory())), \
             patch.object(device_overview.alexa_group_manager, "_load_groups", new=AsyncMock(return_value=[])), \
             patch.object(device_overview, "NativeSkillConfigStore") as native_store:
            native_store.return_value.load.return_value = native
            body = json.loads((await device_overview.overview(request)).text)
            self.assertEqual(body["summary"]["native_selected"], 1)
            native_store.return_value.load.side_effect = ValueError("bad native data")
            body = json.loads((await device_overview.overview(request)).text)
            self.assertTrue(body["ok"])
            self.assertTrue(body["warnings"])
            store.save.assert_not_called()
            native_store.return_value.save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
