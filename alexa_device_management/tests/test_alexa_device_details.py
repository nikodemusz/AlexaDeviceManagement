import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web


ROOT = Path(__file__).parents[1]
WEB = ROOT / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB))

import device_overview
import server_clean


def test_details_returns_only_the_exact_cached_device_and_redacts_credentials(monkeypatch):
    device = {
        "source": "smart_home",
        "serial": "uuid-one",
        "name": "Hall lamp",
        "raw": {
            "deviceType": "LIGHT",
            "capabilities": ["PowerController", "BrightnessController"],
            "access_token": "never-return-this",
            "nested": {"clientSecret": "also-private", "friendlyName": "Hall lamp"},
        },
    }
    cache = {
        "devices": [device, {"source": "smart_home", "serial": "uuid-two", "name": "Other"}],
        "updated_at": 1234,
        "warnings": ["Smart-Home-Geräte: private upstream response"],
    }
    monkeypatch.setattr(server_clean, "is_configured", lambda: True)
    monkeypatch.setattr(server_clean, "_load_devices_cache", lambda: None)
    monkeypatch.setattr(server_clean, "_DEVICES_CACHE", cache)
    request = SimpleNamespace(
        app={"device_overview_server": server_clean},
        json=AsyncMock(return_value={"key": "smart_home:uuid-one"}),
    )

    response = asyncio.run(device_overview.alexa_device_details(request))
    payload = json.loads(response.text)

    assert payload["device"]["serial"] == "uuid-one"
    assert payload["device"]["raw"]["capabilities"] == ["PowerController", "BrightnessController"]
    assert payload["device"]["raw"]["access_token"] == "[redigiert]"
    assert payload["device"]["raw"]["nested"]["clientSecret"] == "[redigiert]"
    assert payload["warning_sources"] == ["Smart-Home-Geräte"]
    assert "private upstream response" not in response.text


def test_details_refuses_unknown_devices_and_unconfigured_sessions(monkeypatch):
    monkeypatch.setattr(server_clean, "is_configured", lambda: True)
    monkeypatch.setattr(server_clean, "_load_devices_cache", lambda: None)
    monkeypatch.setattr(server_clean, "_DEVICES_CACHE", {"devices": [], "updated_at": 0})
    request = SimpleNamespace(
        app={"device_overview_server": server_clean},
        json=AsyncMock(return_value={"key": "smart_home:missing"}),
    )
    with pytest.raises(web.HTTPNotFound):
        asyncio.run(device_overview.alexa_device_details(request))

    monkeypatch.setattr(server_clean, "is_configured", lambda: False)
    with pytest.raises(web.HTTPUnauthorized):
        asyncio.run(device_overview.alexa_device_details(request))


def test_alexa_cards_have_details_action_and_selectable_json_dialog():
    script = (ROOT / "rootfs/opt/alexa_device_management/web/static/device_overview.js").read_text(encoding="utf-8")
    html = (ROOT / "rootfs/opt/alexa_device_management/web/static/device_overview.html").read_text(encoding="utf-8")
    css = (ROOT / "rootfs/opt/alexa_device_management/web/static/device_overview.css").read_text(encoding="utf-8")

    assert script.count('data-action="details-alexa"') >= 2
    assert 'request("/api/device-overview/alexa-details"' in script
    assert 'id="alexa-details-json"' in html
    assert "resize:both" in css
