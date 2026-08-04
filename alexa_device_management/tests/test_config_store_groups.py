from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

WEB_DIR = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB_DIR))

from config_store import ConfigStore


class ConfigStoreGroupTests(unittest.TestCase):
    def test_preserves_group_and_event_sync_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            store = ConfigStore(root / "config.json", root / "legacy.json", root / "alexa.yaml")
            saved = store.save({
                "entities": {
                    "light.test": {
                        "enabled": True,
                        "name": "Test",
                        "alexa_group": "Wohnzimmer",
                    }
                },
                "group_sync": {
                    "enabled": True,
                    "create_missing": False,
                    "remove_from_other_groups": True,
                },
                "event_gateway": {
                    "enabled": True,
                    "endpoint": "https://api.eu.amazonalexa.com/v3/events",
                    "client_id_secret": "my_alexa_client_id",
                    "client_secret_secret": "my_alexa_client_secret",
                    "fallback_web_cleanup": False,
                },
            }, create_backup=False)

            self.assertEqual(saved["schema_version"], 5)
            self.assertEqual(saved["entities"]["light.test"]["alexa_group"], "Wohnzimmer")
            self.assertEqual(saved["group_sync"], {
                "enabled": True,
                "create_missing": False,
                "remove_from_other_groups": True,
            })
            self.assertEqual(saved["event_gateway"], {
                "enabled": True,
                "endpoint": "https://api.eu.amazonalexa.com/v3/events",
                "client_id_secret": "my_alexa_client_id",
                "client_secret_secret": "my_alexa_client_secret",
                "fallback_web_cleanup": False,
            })


if __name__ == "__main__":
    unittest.main()
