from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "rootfs/opt/alexa_device_management/web/static/device_overview.js"
).read_text(encoding="utf-8")


def test_simple_entity_editor_exposes_alexa_name():
    assert 'const entityRow = document.createElement("div")' in SCRIPT
    assert 'nameInput.className = "export-name"' in SCRIPT
    assert 'nameInput.dataset.entity = String(entity.entity_id || "")' in SCRIPT
    assert 'nameInput.value = String(entity.export?.name || "")' in SCRIPT
    assert 'nameInput.placeholder = suggestedName(entity, device)' in SCRIPT
    assert 'suggestion.dataset.action = "suggest-simple-name"' in SCRIPT
    assert 'if (nameInput && !nameInput.value) nameInput.value = settings.name' in SCRIPT
