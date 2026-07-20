from __future__ import annotations

import json
import pathlib
import sys
import unittest

WEB_DIR = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB_DIR))

from alexa_group_manager import (
    _ensure_assignment,
    extract_groups,
)


class FakeServer:
    def __init__(self) -> None:
        self.groups = [{
            "id": "room-1",
            "name": "Wohnzimmer",
            "type": "SPACE",
            "applianceIds": ["existing-device"],
        }]
        self.puts: list[tuple[str, dict]] = []
        self.posts: list[tuple[str, dict]] = []

    def _payload(self) -> str:
        return json.dumps({"networkDetail": json.dumps({"groups": self.groups})})

    async def alexa_raw_get(self, path: str, data: dict):
        self.assert_path(path, "/api/phoenix")
        return 200, self._payload()

    async def alexa_raw_put(self, path: str, body: bytes, data: dict):
        payload = json.loads(body)
        self.puts.append((path, payload))
        group_id = path.rsplit("/", 1)[-1]
        group = next(item for item in self.groups if item["id"] == group_id)
        group["name"] = payload["name"]
        group["applianceIds"] = payload["applianceIds"]
        return 200, "{}"

    async def alexa_raw_post(self, path: str, body: bytes, data: dict):
        payload = json.loads(body)
        self.posts.append((path, payload))
        self.groups.append({
            "id": f"room-{len(self.groups) + 1}",
            "name": payload["name"],
            "type": payload["type"],
            "applianceIds": payload["applianceIds"],
        })
        return 201, "{}"

    @staticmethod
    def assert_path(actual: str, expected: str) -> None:
        if actual != expected:
            raise AssertionError(f"Expected {expected!r}, got {actual!r}")


class AlexaGroupParserTests(unittest.TestCase):
    def test_extracts_groups_from_nested_network_detail(self) -> None:
        payload = {
            "networkDetail": json.dumps({
                "locationDetails": [{
                    "groups": [{
                        "groupId": "group-1",
                        "name": "Küche",
                        "type": "SPACE",
                        "applianceIds": ["device-1", {"applianceId": "device-2"}],
                    }]
                }]
            })
        }

        groups = extract_groups(payload)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["id"], "group-1")
        self.assertEqual(groups[0]["name"], "Küche")
        self.assertEqual(groups[0]["member_ids"], ["device-1", "device-2"])


class AlexaGroupAssignmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_adds_device_without_removing_existing_members(self) -> None:
        server = FakeServer()
        groups = extract_groups(json.loads(server._payload()))
        device = {
            "name": "Stehlampe",
            "serial": "device-2",
            "appliance_id": "device-2",
            "raw": {"entityId": "device-2"},
        }

        updated, changed = await _ensure_assignment(
            server,
            {"cookie": "at-acbde=token; ubid-acbde=user"},
            groups,
            device,
            "Wohnzimmer",
            create_missing=True,
            remove_from_other_groups=False,
        )

        self.assertTrue(changed)
        self.assertEqual(server.puts[0][1]["applianceIds"], ["existing-device", "device-2"])
        self.assertEqual(updated[0]["member_ids"], ["existing-device", "device-2"])

    async def test_creates_missing_group(self) -> None:
        server = FakeServer()
        groups = extract_groups(json.loads(server._payload()))
        device = {
            "name": "Deckenlicht",
            "serial": "device-3",
            "appliance_id": "device-3",
            "raw": {"entityId": "device-3"},
        }

        updated, changed = await _ensure_assignment(
            server,
            {"cookie": "at-acbde=token; ubid-acbde=user"},
            groups,
            device,
            "Küche",
            create_missing=True,
            remove_from_other_groups=False,
        )

        self.assertTrue(changed)
        self.assertEqual(server.posts[0][1], {
            "name": "Küche",
            "applianceIds": ["device-3"],
            "type": "SPACE",
        })
        self.assertEqual(next(group for group in updated if group["name"] == "Küche")["member_ids"], ["device-3"])


if __name__ == "__main__":
    unittest.main()
