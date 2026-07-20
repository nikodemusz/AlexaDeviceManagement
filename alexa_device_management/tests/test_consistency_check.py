from pathlib import Path
import sys

WEB = Path(__file__).parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB))

from consistency_check import analyse, _load_home_assistant_yaml, _packages_enabled


def inventory(*entity_ids):
    return {
        "devices": [{
            "device_id": "device-1",
            "entities": [{"entity_id": entity_id, "domain": entity_id.split('.', 1)[0]} for entity_id in entity_ids],
        }]
    }


def test_detects_missing_duplicate_and_not_deployed():
    config = {
        "entities": {
            "light.kitchen": {"enabled": True, "name": "Licht"},
            "switch.office": {"enabled": True, "name": "Licht"},
            "light.missing": {"enabled": True, "name": "Fehlt"},
        }
    }
    deployed = {
        "alexa": {"smart_home": {"filter": {"include_entities": ["light.kitchen", "sensor.old"]}}}
    }

    result = analyse(
        config,
        inventory("light.kitchen", "switch.office"),
        deployed,
        target_exists=True,
        target_writable=True,
        packages_enabled=True,
    )

    codes = {finding["code"] for finding in result["findings"]}
    assert result["ok"] is False
    assert "entity_missing" in codes
    assert "duplicate_name" in codes
    assert "not_deployed" in codes
    assert "stale_deployment" in codes


def test_permission_and_packages_errors():
    result = analyse(
        {"entities": {}},
        inventory(),
        {},
        target_exists=False,
        target_writable=False,
        packages_enabled=False,
    )
    codes = {finding["code"] for finding in result["findings"]}
    assert {"yaml_missing", "yaml_not_writable", "packages_not_enabled"} <= codes
    assert result["errors"] == 2


def test_packages_detection():
    assert _packages_enabled({"homeassistant": {"packages": "packages"}})
    assert _packages_enabled({"homeassistant": {"packages": {"alexa": "x"}}})
    assert not _packages_enabled({"homeassistant": {}})


def test_home_assistant_include_dir_named_is_loaded(tmp_path):
    configuration = tmp_path / "configuration.yaml"
    configuration.write_text(
        "homeassistant:\n  packages: !include_dir_named packages\ndefault_config:\n",
        encoding="utf-8",
    )

    document = _load_home_assistant_yaml(configuration)

    assert document["homeassistant"]["packages"] == "packages"
    assert _packages_enabled(document)


def test_other_home_assistant_include_tags_are_tolerated(tmp_path):
    configuration = tmp_path / "configuration.yaml"
    configuration.write_text(
        "frontend:\n  themes: !include_dir_merge_named themes\n"
        "homeassistant:\n  packages: !include_dir_merge_named packages\n",
        encoding="utf-8",
    )

    document = _load_home_assistant_yaml(configuration)

    assert document["frontend"]["themes"] == "themes"
    assert _packages_enabled(document)
