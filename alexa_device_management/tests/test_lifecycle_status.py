from pathlib import Path
import json
import sys

WEB = Path(__file__).parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB))

import ha_control


class Store:
    def __init__(self, updated_at):
        self.updated_at = updated_at

    def load(self):
        return {"updated_at": self.updated_at, "entities": {}}


def write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_changes_pending_after_autosave(monkeypatch, tmp_path):
    deploy = tmp_path / "deploy.json"
    lifecycle = tmp_path / "lifecycle.json"
    write(deploy, {"state": "success", "finished_at": 100, "selected_count": 3})
    write(lifecycle, {"last_restart_requested_at": 100, "discovery_pending": False})
    monkeypatch.setattr(ha_control, "DEPLOY_STATUS_PATH", deploy)
    monkeypatch.setattr(ha_control, "LIFECYCLE_STATUS_PATH", lifecycle)
    monkeypatch.setattr(ha_control.ha_export, "CONFIG_STORE", Store(101))

    status = ha_control.lifecycle_snapshot()
    assert status["changes_pending"] is True
    assert status["restart_required"] is False


def test_restart_required_after_deploy(monkeypatch, tmp_path):
    deploy = tmp_path / "deploy.json"
    lifecycle = tmp_path / "lifecycle.json"
    write(deploy, {"state": "success", "finished_at": 200, "selected_count": 4})
    write(lifecycle, {"last_restart_requested_at": 150, "discovery_pending": False})
    monkeypatch.setattr(ha_control, "DEPLOY_STATUS_PATH", deploy)
    monkeypatch.setattr(ha_control, "LIFECYCLE_STATUS_PATH", lifecycle)
    monkeypatch.setattr(ha_control.ha_export, "CONFIG_STORE", Store(200))

    status = ha_control.lifecycle_snapshot()
    assert status["changes_pending"] is False
    assert status["restart_required"] is True
    assert status["deployed_count"] == 4


def test_discovery_pending_after_current_restart(monkeypatch, tmp_path):
    deploy = tmp_path / "deploy.json"
    lifecycle = tmp_path / "lifecycle.json"
    write(deploy, {"state": "success", "finished_at": 300, "selected": 5})
    write(lifecycle, {"last_restart_requested_at": 301, "discovery_pending": True})
    monkeypatch.setattr(ha_control, "DEPLOY_STATUS_PATH", deploy)
    monkeypatch.setattr(ha_control, "LIFECYCLE_STATUS_PATH", lifecycle)
    monkeypatch.setattr(ha_control.ha_export, "CONFIG_STORE", Store(300))

    status = ha_control.lifecycle_snapshot()
    assert status["restart_required"] is False
    assert status["discovery_pending"] is True
    assert status["alexa_discovery"]["automatic_supported"] is False
