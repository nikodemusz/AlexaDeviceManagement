from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "rootfs/opt/alexa_device_management/web/static/device_export_guard.js"
).read_text(encoding="utf-8")


def test_mutation_observer_relabel_is_idempotent():
    assert 'button.textContent !== "Gerät exportieren"' in SCRIPT
    assert 'button.textContent = "Gerät exportieren";' in SCRIPT
    assert "button.title" not in SCRIPT
