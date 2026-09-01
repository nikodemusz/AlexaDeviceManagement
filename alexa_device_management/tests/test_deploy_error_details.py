from pathlib import Path


WEB = Path(__file__).parents[1] / "rootfs/opt/alexa_device_management/web"
CONTROL = (WEB / "ha_control.py").read_text(encoding="utf-8")
EVENT_SYNC = (WEB / "alexa_event_sync.py").read_text(encoding="utf-8")
SCRIPT = (WEB / "static/device_overview.js").read_text(encoding="utf-8")


def test_home_assistant_check_error_is_returned_to_ui():
    assert 'check_detail = str(check.get("message")' in CONTROL
    assert "Ursache: {check_detail}" in CONTROL
    assert "error.body?.check?.message" in SCRIPT


def test_changed_event_component_requires_restart_before_deploy():
    assert 'if component.get("restart_required")' in EVENT_SYNC
    assert '"bootstrap_required": True' in EVENT_SYNC
    assert "alexa.yaml wurde noch nicht verändert" in EVENT_SYNC
