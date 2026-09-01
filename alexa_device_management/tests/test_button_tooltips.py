from pathlib import Path


STATIC = Path(__file__).parents[1] / "rootfs/opt/alexa_device_management/web/static"
SCRIPT = (STATIC / "device_overview.js").read_text(encoding="utf-8")
HTML = (STATIC / "device_overview.html").read_text(encoding="utf-8")
CSS = (STATIC / "device_overview.css").read_text(encoding="utf-8")


def test_event_gateway_button_has_clear_description():
    assert "Änderungen an Alexa senden" in HTML
    assert '"btn-event-sync"' in SCRIPT
    assert "AddOrUpdateReport" in SCRIPT
    assert "DeleteReport" in SCRIPT
    assert "Schreibt keine alexa.yaml" in SCRIPT


def test_readable_tooltips_cover_dynamic_actions_and_keyboard_focus():
    assert '"prepare-device"' in SCRIPT
    assert '"delete-alexa"' in SCRIPT
    assert 'document.addEventListener("focusin"' in SCRIPT
    assert 'id="button-tooltip"' in HTML
    assert "font-size:13px" in CSS
