from pathlib import Path
import sys

import pytest

WEB = Path(__file__).parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB))
SCRIPT = (WEB / "static/device_overview.js").read_text(encoding="utf-8")

from ha_control import verify_deployed_configuration


def test_autosave_does_not_replace_newer_browser_configuration():
    assert "config = result.configuration || config" not in SCRIPT
    assert "if (result.configuration?.updated_at) config.updated_at" in SCRIPT
    assert "savePromise.catch(() => {}).then" in SCRIPT


def test_verifies_entities_and_names_from_written_yaml(tmp_path):
    target = tmp_path / "alexa.yaml"
    target.write_text(
        "alexa:\n  smart_home:\n    filter:\n      include_entities:\n      - light.kitchen\n"
        "    entity_config:\n      light.kitchen:\n        name: Küchenlicht\n",
        encoding="utf-8",
    )
    config = {"entities": {"light.kitchen": {"enabled": True, "name": "Küchenlicht"}}}

    assert verify_deployed_configuration(target, config) == ["light.kitchen"]


def test_rejects_stale_written_configuration(tmp_path):
    target = tmp_path / "alexa.yaml"
    target.write_text(
        "alexa:\n  smart_home:\n    filter:\n      include_entities:\n      - light.old\n",
        encoding="utf-8",
    )
    config = {"entities": {"light.new": {"enabled": True, "name": "Neu"}}}

    with pytest.raises(OSError, match="missing=.*light.new"):
        verify_deployed_configuration(target, config)
