from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def test_home_assistant_config_is_mounted_writable_at_export_path():
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

    assert {
        "type": "homeassistant_config",
        "read_only": False,
        "path": "/config",
    } in config["map"]
