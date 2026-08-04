from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

WEB_DIR = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB_DIR))

from yaml_generator import (
    AlexaYamlGenerator,
    GeneratorValidationError,
    load_yaml_with_secrets,
)


class AlexaYamlGeneratorTests(unittest.TestCase):
    def test_generates_sorted_selected_entities_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            generator = AlexaYamlGenerator(pathlib.Path(directory) / "alexa.yaml")
            result = generator.generate({
                "locale": "de-DE",
                "entities": {
                    "switch.zweite": {
                        "enabled": True,
                        "name": "Zweite",
                        "display_category": "switch",
                    },
                    "light.erste": {
                        "enabled": True,
                        "name": "Erste",
                        "description": "Testlicht",
                        "display_category": "LIGHT",
                    },
                    "sensor.ignoriert": {"enabled": False},
                },
            })

        self.assertEqual(result.selected_count, 2)
        smart_home = result.document["alexa"]["smart_home"]
        self.assertEqual(
            smart_home["filter"]["include_entities"],
            ["light.erste", "switch.zweite"],
        )
        self.assertEqual(
            smart_home["entity_config"]["switch.zweite"]["display_categories"],
            "SWITCH",
        )
        self.assertNotIn("sensor.ignoriert", result.yaml_text)

    def test_generates_event_gateway_and_secret_references(self) -> None:
        generator = AlexaYamlGenerator(pathlib.Path("/tmp/alexa.yaml"))
        result = generator.generate({
            "locale": "de-DE",
            "entities": {"light.test": {"enabled": True, "name": "Test"}},
            "event_gateway": {
                "enabled": True,
                "endpoint": "https://api.eu.amazonalexa.com/v3/events",
                "client_id_secret": "alexa_skill_client_id",
                "client_secret_secret": "alexa_skill_client_secret",
            },
        })

        self.assertIn("client_id: !secret 'alexa_skill_client_id'", result.yaml_text)
        self.assertIn("client_secret: !secret 'alexa_skill_client_secret'", result.yaml_text)
        parsed = load_yaml_with_secrets(result.yaml_text)
        self.assertEqual(
            parsed["alexa_device_management_sync"]["endpoint"],
            "https://api.eu.amazonalexa.com/v3/events",
        )
        self.assertEqual(
            parsed["alexa"]["smart_home"]["client_id"],
            "alexa_skill_client_id",
        )

    def test_rejects_invalid_entity_id(self) -> None:
        generator = AlexaYamlGenerator(pathlib.Path("/tmp/alexa.yaml"))
        with self.assertRaises(GeneratorValidationError):
            generator.generate({"entities": {"invalid": {"enabled": True}}})

    def test_rejects_unknown_category(self) -> None:
        generator = AlexaYamlGenerator(pathlib.Path("/tmp/alexa.yaml"))
        with self.assertRaises(GeneratorValidationError):
            generator.generate({
                "entities": {
                    "switch.test": {
                        "enabled": True,
                        "display_category": "NOT_A_CATEGORY",
                    }
                }
            })

    def test_rejects_invalid_event_gateway_secret_name(self) -> None:
        generator = AlexaYamlGenerator(pathlib.Path("/tmp/alexa.yaml"))
        with self.assertRaises(GeneratorValidationError):
            generator.generate({
                "entities": {},
                "event_gateway": {
                    "enabled": True,
                    "client_id_secret": "not a secret name",
                    "client_secret_secret": "valid_name",
                },
            })

    def test_deploy_replaces_atomically_without_backup_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "alexa.yaml"
            target.write_text("old: value\n", encoding="utf-8")
            generator = AlexaYamlGenerator(target)
            result = generator.deploy({
                "entities": {"light.test": {"enabled": True, "name": "Test"}}
            })

            self.assertTrue(target.exists())
            self.assertIsNone(result.backup)
            self.assertEqual(target.read_text(encoding="utf-8"), result.yaml_text)
            self.assertEqual(list(target.parent.glob("alexa.yaml.backup-*")), [])

    def test_deploy_allows_empty_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "alexa.yaml"
            generator = AlexaYamlGenerator(target)
            result = generator.deploy({"entities": {"light.test": {"enabled": False}}})
            self.assertTrue(target.exists())
            self.assertEqual(result.selected_count, 0)
            parsed = load_yaml_with_secrets(result.yaml_text)
            self.assertEqual(
                parsed["alexa"]["smart_home"]["filter"]["include_entities"],
                [],
            )


if __name__ == "__main__":
    unittest.main()
