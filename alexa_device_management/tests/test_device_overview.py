from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import time
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, Mock, patch

WEB_DIR = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB_DIR))

import device_overview
import server_clean
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

    def test_opaque_alexa_uuid_joins_native_selection_by_enriched_endpoint_id(self):
        native = {"enabled": True, "devices": {
            "ha:light.wohnzimmer": {"name": "Wohnzimmer Licht", "capabilities": [
                {"entity_id": "light.wohnzimmer", "interface": "Alexa.PowerController"}
            ]}
        }}
        alexa = {
            "serial": "6d0bd9a9-9f50-4ee0-b299-a5d1d554c0b7",
            "appliance_id": "6d0bd9a9-9f50-4ee0-b299-a5d1d554c0b7",
            "name": "Heizrelais Keller Büro",
            "source": "smart_home",
            "family": "Alexa Device Management",
            "raw": {"id": "6d0bd9a9-9f50-4ee0-b299-a5d1d554c0b7",
                    "endpointId": "native:ha:light.wohnzimmer"},
        }

        result = build_overview(ha_inventory(), [alexa], [], {"entities": {}}, native)
        entity = result["devices"][0]["entities"][0]

        self.assertEqual(entity["status"], "synced")
        self.assertEqual(entity["alexa"]["count"], 1)
        self.assertEqual(result["summary"]["synced"], 1)
        self.assertEqual(result["alexa_only"], [])

    def test_opaque_alexa_uuid_joins_native_selection_by_graphql_appliance_entity_id(self):
        native = {"enabled": True, "devices": {
            "ha:switch.heizrelais_kellerbuero": {
                "name": "Heizrelais Keller Büro", "capabilities": [
                    {"entity_id": "switch.heizrelais_kellerbuero",
                     "interface": "Alexa.PowerController"}
                ]
            }
        }}
        alexa = {
            "serial": "amazon-generated-uuid",
            "appliance_id": "amazon-generated-uuid",
            "name": "Heizrelais Keller Büro",
            "source": "graphql",
            "family": "Alexa Device Management",
            "raw": {"legacyAppliance": {
                "entityId": "native:ha:switch.heizrelais_kellerbuero",
                "manufacturerName": "Alexa Device Management",
            }},
        }
        inventory = {"devices": [{"device_id": "heater", "name": "Heizung",
                                   "entities": [{"entity_id": "switch.heizrelais_kellerbuero",
                                                 "domain": "switch", "name": "Heizrelais"}]}]}

        result = build_overview(inventory, [alexa], [], {"entities": {}}, native)

        entity = result["devices"][0]["entities"][0]
        self.assertEqual(entity["status"], "synced")
        self.assertEqual(entity["alexa"]["count"], 1)
        self.assertEqual(result["summary"]["synced"], 1)

    def test_native_mapping_uses_ha_entity_id_and_counts_duplicate_alexa_endpoints(self):
        entity_id = "switch.heizrelais_kellerbuero"
        native = {"enabled": True, "devices": {
            "ha:" + entity_id: {"name": "Heizrelais Keller Büro", "capabilities": [
                {"entity_id": entity_id, "interface": "Alexa.PowerController"}
            ]}
        }}
        alexa = [
            {"serial": "amazon-uuid-one", "source": "smart_home", "name": "Relais",
             "raw": {"endpointId": "native:ha:" + entity_id,
                     "legacyAppliance": {"entityId": entity_id,
                                         "manufacturerName": "Alexa Device Management"}}},
            {"serial": "amazon-uuid-two", "source": "smart_home", "name": "Relais alt",
             "raw": {"endpointId": "amzn1.alexa.endpoint.native:ha:" + entity_id,
                     "legacyAppliance": {"entityId": "native:ha:" + entity_id,
                                         "manufacturerName": "Alexa Device Management"}}},
        ]
        inventory = {"devices": [{"device_id": "heater", "name": "Heizung",
                                   "entities": [{"entity_id": entity_id,
                                                 "domain": "switch", "name": "Heizrelais"}]}]}

        result = build_overview(inventory, alexa, [],
                                {"entities": {}, "export_mode": "native"}, native)

        entity = result["devices"][0]["entities"][0]
        self.assertEqual(entity["status"], "duplicate")
        self.assertEqual(entity["alexa"]["count"], 2)
        self.assertEqual(result["summary"]["synced"], 1)
        self.assertEqual(result["summary"]["pending"], 0)
        self.assertEqual(result["summary"]["duplicates"], 1)
        self.assertEqual(result["alexa_only"], [])

    def test_native_mapping_extracts_entity_from_skill_appliance_id_suffix(self):
        entity_id = "switch.test_mirror"
        endpoint_id = "native:ha:" + entity_id
        native = {"enabled": True, "devices": {
            "ha:" + entity_id: {"name": "Test mirror", "capabilities": [
                {"entity_id": entity_id, "interface": "Alexa.PowerController"}
            ]}
        }}
        alexa = {
            "serial": "opaque-endpoint-id",
            "appliance_id": "opaque-endpoint-id",
            "name": "Test mirror",
            "source": "smart_home",
            "family": "Alexa Device Management",
            "raw": {
                "endpointId": "amzn1.alexa.endpoint.opaque-endpoint-id",
                "legacyAppliance": {
                    "applianceId": "SKILL_opaque_native:ha:switch.test_mirror",
                    "entityId": "opaque-endpoint-id",
                    "manufacturerName": "Alexa Device Management",
                },
            },
        }
        inventory = {"devices": [{"device_id": "bathroom", "name": "Bathroom",
                                   "entities": [{"entity_id": entity_id,
                                                 "domain": "switch", "name": "Test mirror"}]}]}

        result = build_overview(
            inventory, [alexa], [], {"entities": {}, "export_mode": "native"}, native
        )
        entity = result["devices"][0]["entities"][0]

        self.assertEqual(entity["status"], "synced")
        self.assertEqual(entity["native"]["endpoint_ids"], [endpoint_id])
        self.assertEqual(entity["alexa"]["count"], 1)
        self.assertEqual(entity["alexa"]["matches"][0]["entity_id"], entity_id)
        self.assertEqual(result["summary"]["synced"], 1)
        self.assertEqual(result["summary"]["pending"], 0)
        self.assertEqual(result["summary"]["duplicates"], 0)
        self.assertEqual(result["alexa_only"], [])

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


    def test_connected_via_falls_back_to_amazon_skill_description(self):
        self.assertEqual(
            device_overview._connected_via({
                "connectedVia": "",
                "friendlyDescription": "Schalter via Alexa Device Management",
            }),
            ("Alexa Device Management", "friendlyDescription"),
        )


class DeviceOverviewRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        device_overview._OVERVIEW_CACHE_LOADED = True
        device_overview._OVERVIEW_SOURCE_CACHE.update({
            "ha_inventory": None,
            "ha_updated_at": 0,
            "groups": None,
            "groups_updated_at": 0,
            "alexa_configured": None,
            "warnings": [],
            "last_attempt_at": 0,
        })

    async def test_route_reads_native_yaml_and_survives_invalid_optional_native_config(self):
        server = Mock()
        server.is_configured.return_value = True
        server.session_data.return_value = {}
        server.refresh_devices_cache = AsyncMock()
        server._DEVICES_CACHE = {"updated_at": 1, "devices": [
            {"serial": "native:living", "source": "smart_home", "raw": {}}]}
        store = Mock()
        store.load.return_value = {"entities": {}}
        request = Mock()
        request.app = {"device_overview_server": server, "device_overview_store": store}
        request.rel_url.query = {"refresh": "1"}
        native = {"enabled": True, "devices": {"living": {"capabilities": [
            {"entity_id": "light.wohnzimmer"}]}}}
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

    async def test_cached_overview_does_not_wait_for_live_inventory_or_groups(self):
        now = time.time()
        device_overview._OVERVIEW_SOURCE_CACHE.update({
            "ha_inventory": ha_inventory(),
            "ha_updated_at": now,
            "groups": [],
            "groups_updated_at": now,
            "alexa_configured": True,
            "warnings": [],
            "last_attempt_at": now,
        })
        server = Mock()
        server.is_configured.return_value = True
        server._DEVICES_CACHE = {"updated_at": now, "devices": []}
        store = Mock()
        store.load.return_value = {"entities": {}}
        request = Mock()
        request.app = {"device_overview_server": server, "device_overview_store": store}
        request.rel_url.query = {}
        with patch.object(device_overview.ha_export, "_inventory", new=AsyncMock()) as inventory, \
             patch.object(device_overview.alexa_group_manager, "_load_groups", new=AsyncMock()) as groups, \
             patch.object(device_overview, "NativeSkillConfigStore") as native_store:
            native_store.return_value.load.return_value = {"enabled": False, "devices": {}}
            response = await device_overview.overview(request)
            body = json.loads(response.text)

        inventory.assert_not_awaited()
        groups.assert_not_awaited()
        self.assertFalse(body["source_cache_loading"])
        self.assertEqual(body["summary"]["ha_entities"], 2)

    async def test_cold_overview_returns_immediately_and_schedules_refresh(self):
        server = Mock()
        server.is_configured.return_value = True
        server._DEVICES_CACHE = {"devices": []}
        store = Mock()
        store.load.return_value = {"entities": {}}
        request = Mock()
        request.app = {"device_overview_server": server, "device_overview_store": store}
        request.rel_url.query = {}
        with patch.object(device_overview, "_schedule_overview_refresh") as schedule_sources, \
             patch.object(device_overview, "_schedule_alexa_device_refresh") as schedule_devices, \
             patch.object(device_overview.ha_export, "_inventory", new=AsyncMock()) as inventory, \
             patch.object(device_overview.alexa_group_manager, "_load_groups", new=AsyncMock()) as groups, \
             patch.object(device_overview, "NativeSkillConfigStore") as native_store:
            native_store.return_value.load.return_value = {"enabled": False, "devices": {}}
            response = await device_overview.overview(request)
            body = json.loads(response.text)

        schedule_sources.assert_called_once()
        schedule_devices.assert_called_once()
        inventory.assert_not_awaited()
        groups.assert_not_awaited()
        self.assertTrue(body["source_cache_loading"])
        self.assertEqual(body["devices"], [])

    async def test_background_refresh_updates_and_persists_source_snapshots(self):
        server = Mock()
        server.is_configured.return_value = True
        server.session_data.return_value = {"cookie": "must-not-be-persisted"}
        inventory = ha_inventory()
        groups = [{"id": "group-1", "name": "Wohnzimmer", "type": "room"}]
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = pathlib.Path(temp_dir) / "overview-cache.json"
            with patch.object(device_overview, "_OVERVIEW_CACHE_PATH", cache_path), \
                 patch.object(device_overview.ha_export, "_inventory", new=AsyncMock(return_value=inventory)), \
                 patch.object(device_overview.alexa_group_manager, "_load_groups", new=AsyncMock(return_value=groups)):
                await device_overview._refresh_overview_sources(server)
            persisted = cache_path.read_text(encoding="utf-8")

        self.assertEqual(device_overview._OVERVIEW_SOURCE_CACHE["ha_inventory"], inventory)
        self.assertEqual(device_overview._OVERVIEW_SOURCE_CACHE["groups"], groups)
        self.assertTrue(device_overview._OVERVIEW_SOURCE_CACHE["ha_updated_at"])
        self.assertTrue(device_overview._OVERVIEW_SOURCE_CACHE["groups_updated_at"])
        self.assertNotIn("must-not-be-persisted", persisted)
        self.assertNotIn("cookie", persisted)

    async def test_failed_group_refresh_keeps_snapshot_and_exposes_safe_http_error(self):
        previous = [{"id": "cached-group", "name": "Wohnzimmer"}]
        device_overview._OVERVIEW_SOURCE_CACHE.update({
            "ha_inventory": ha_inventory(),
            "groups": previous,
            "alexa_configured": True,
        })
        server = Mock()
        server.is_configured.return_value = True
        server.session_data.return_value = {}
        error = device_overview.alexa_group_manager.AlexaGroupError(
            "Alexa-Gruppen konnten nicht geladen werden (HTTP 299)."
        )
        with patch.object(device_overview.ha_export, "_inventory", new=AsyncMock(return_value=ha_inventory())), \
             patch.object(device_overview.alexa_group_manager, "_load_groups", new=AsyncMock(side_effect=error)):
            await device_overview._refresh_overview_sources(server)

        self.assertEqual(device_overview._OVERVIEW_SOURCE_CACHE["groups"], previous)
        self.assertIn("HTTP 299", device_overview._OVERVIEW_SOURCE_CACHE["warnings"][0])

    def test_recent_failed_attempt_suppresses_repeated_background_refresh(self):
        device_overview._OVERVIEW_SOURCE_CACHE["last_attempt_at"] = time.time()
        server = Mock()
        app = {}
        with patch.object(device_overview.asyncio, "create_task") as create_task:
            device_overview._schedule_overview_refresh(app, server)
        create_task.assert_not_called()


    async def test_device_details_fetch_fresh_graphql_and_extracts_connected_via(self):
        cached = {
            "serial": "entity-123",
            "appliance_id": "skill-device-123",
            "name": "iPhone Internetzugang",
            "source": "smart_home",
            "raw": {"entityId": "entity-123"},
        }
        endpoint = {
            "endpointId": "amzn1.alexa.endpoint.entity-123",
            "legacyIdentifiers": {"chrsIdentifier": {"entityId": "entity-123"}},
            "legacyAppliance": {
                "applianceId": "skill-device-123",
                "entityId": "entity-123",
                "friendlyName": "iPhone Internetzugang",
                "friendlyDescription": "Mobilfunkzugang via Alexa Device Management",
                "manufacturerName": "Home Assistant",
                "connectedVia": "Echo Show Küche",
                "modelName": "HA Skill",
                "applianceTypes": ["SWITCH"],
                "capabilities": [{"interfaceName": "Alexa.PowerController"}],
            },
        }
        server = Mock()
        server.is_configured.return_value = True
        server.session_data.return_value = {"session": "not-returned"}
        server.alexa_graphql = AsyncMock(return_value=(200, {
            "data": {"endpoints": {"items": [endpoint, {"endpointId": "other"}]}}
        }))
        server._DEVICES_CACHE = {"devices": [cached], "updated_at": 123, "warnings": []}
        server._load_devices_cache = Mock()
        request = Mock()
        request.json = AsyncMock(return_value={"key": "smart_home:entity-123"})
        request.app = {"device_overview_server": server}

        response = await device_overview.alexa_device_details(request)
        body = json.loads(response.text)

        self.assertEqual(body["alexa_api"]["status"], "matched")
        self.assertEqual(body["alexa_api"]["device"]["connected_via"], "Echo Show Küche")
        self.assertEqual(body["alexa_api"]["device"]["description"], "Mobilfunkzugang via Alexa Device Management")
        self.assertEqual(body["alexa_api"]["device"]["manufacturer"], "Home Assistant")
        self.assertEqual(body["device"]["name"], "iPhone Internetzugang")
        query, variables, session = server.alexa_graphql.await_args.args
        self.assertIn("connectedVia", query)
        self.assertIn("friendlyDescription", query)
        self.assertIsNone(variables)
        self.assertEqual(session, {"session": "not-returned"})
        self.assertNotIn("session", response.text)

    async def test_device_details_reports_live_api_failure_without_mislabeling_cache(self):
        server = Mock()
        server.is_configured.return_value = True
        server.session_data.return_value = {}
        server.alexa_graphql = AsyncMock(return_value=(429, {"errors": ["rate limit"]}))
        server._DEVICES_CACHE = {"devices": [alexa_device("entity-123", "light.x")], "updated_at": 123, "warnings": []}
        server._load_devices_cache = Mock()
        request = Mock()
        request.json = AsyncMock(return_value={"key": "smart_home:entity-123"})
        request.app = {"device_overview_server": server}

        response = await device_overview.alexa_device_details(request)
        body = json.loads(response.text)

        self.assertEqual(body["alexa_api"]["status"], "error")
        self.assertEqual(body["alexa_api"]["http_status"], 429)
        self.assertEqual(body["device"]["name"], "Wohnzimmer Licht")
        self.assertNotIn("rate limit", response.text)

if __name__ == "__main__":
    unittest.main()
