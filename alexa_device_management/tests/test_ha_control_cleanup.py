from __future__ import annotations

import pathlib
import sys
import unittest

WEB_DIR = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB_DIR))

from ha_control import _cleanup_plan, _ha_entity_id_for_device


class AlexaCleanupTests(unittest.TestCase):
    def test_extracts_entity_id_from_description(self) -> None:
        device = {
            "family": "Home Assistant",
            "raw": {"description": "light.wohnzimmer via Home Assistant"},
        }
        self.assertEqual(_ha_entity_id_for_device(device), "light.wohnzimmer")

    def test_explicitly_disabled_entity_is_removed(self) -> None:
        disabled = {
            "serial": "old",
            "online": False,
            "raw": {"description": "switch.stehlampe via Home Assistant"},
        }
        removed, duplicates = _cleanup_plan(
            [disabled], {"switch.stehlampe"}, set()
        )
        self.assertEqual(removed, [disabled])
        self.assertEqual(duplicates, [])

    def test_only_unreachable_duplicate_is_removed(self) -> None:
        reachable = {
            "serial": "new",
            "online": True,
            "raw": {"description": "light.kueche via Home Assistant"},
        }
        unreachable = {
            "serial": "old",
            "online": False,
            "raw": {"description": "light.kueche via Home Assistant"},
        }
        removed, duplicates = _cleanup_plan(
            [unreachable, reachable], set(), {"light.kueche"}
        )
        self.assertEqual(removed, [])
        self.assertEqual(duplicates, [unreachable])

    def test_does_not_guess_when_all_duplicates_are_offline(self) -> None:
        first = {
            "serial": "one",
            "online": False,
            "raw": {"description": "cover.buero via Home Assistant"},
        }
        second = {
            "serial": "two",
            "online": False,
            "raw": {"description": "cover.buero via Home Assistant"},
        }
        _, duplicates = _cleanup_plan(
            [first, second], set(), {"cover.buero"}
        )
        self.assertEqual(duplicates, [])


if __name__ == "__main__":
    unittest.main()
