from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

WEB_DIR = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB_DIR))

from yaml_generator import AlexaYamlGenerator, GeneratorValidationError


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

    def test_deploy_creates_backup_and_replaces_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "alexa.yaml"
            target.write_text("old: value\n", encoding="utf-8")
            generator = AlexaYamlGenerator(target)
            result = generator.deploy({
                "entities": {"light.test": {"enabled": True, "name": "Test"}}
            })

            self.assertTrue(target.exists())
            self.assertIsNotNone(result.backup)
            self.assertEqual(pathlib.Path(result.backup).read_text(encoding="utf-8"), "old: value\n")
            self.assertEqual(target.read_text(encoding="utf-8"), result.yaml_text)

    def test_deploy_rotates_old_backups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "alexa.yaml"
            target.write_text("initial: true\n", encoding="utf-8")
            generator = AlexaYamlGenerator(target, backup_limit=3)

            for index in range(6):
                generator.deploy({
                    "entities": {
                        "light.test": {"enabled": True, "name": f"Test {index}"}
                    }
                })

            backups = list(target.parent.glob("alexa.yaml.backup-*"))
            self.assertEqual(len(backups), 3)


if __name__ == "__main__":
    unittest.main()
