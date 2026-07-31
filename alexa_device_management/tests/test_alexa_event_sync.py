from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

WEB_DIR = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB_DIR))

import alexa_event_sync


class AlexaEventSyncTests(unittest.TestCase):
    def test_deployment_plan_uses_last_deployed_snapshot(self) -> None:
        plan = alexa_event_sync.deployment_plan(
            {"light.keep", "switch.remove"},
            {"light.keep", "cover.new"},
            True,
        )
        self.assertEqual(plan["removed"], {"switch.remove"})
        self.assertEqual(plan["delete"], {"switch.remove"})
        self.assertEqual(plan["add_or_update"], {"light.keep", "cover.new"})

    def test_disabled_gateway_only_plans_private_cleanup(self) -> None:
        plan = alexa_event_sync.deployment_plan(
            {"switch.remove"}, set(), False
        )
        self.assertEqual(plan["removed"], {"switch.remove"})
        self.assertEqual(plan["delete"], set())
        self.assertEqual(plan["add_or_update"], set())

    def test_entity_config_uses_alexa_field_names(self) -> None:
        result = alexa_event_sync._entity_config({
            "entities": {
                "light.test": {
                    "enabled": True,
                    "name": "Lampe",
                    "description": "light.test via Home Assistant",
                    "display_category": "light",
                }
            }
        }, {"light.test"})
        self.assertEqual(result, {
            "light.test": {
                "name": "Lampe",
                "description": "light.test via Home Assistant",
                "display_categories": "LIGHT",
            }
        })

    def test_reads_previous_entities_from_yaml_with_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "alexa.yaml"
            path.write_text(
                """alexa:\n  smart_home:\n    client_id: !secret alexa_client\n    filter:\n      include_entities:\n        - light.test\n        - switch.test\n""",
                encoding="utf-8",
            )
            self.assertEqual(
                alexa_event_sync._entities_from_yaml(path),
                {"light.test", "switch.test"},
            )


if __name__ == "__main__":
    unittest.main()
