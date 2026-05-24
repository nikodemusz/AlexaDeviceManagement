"""Alexa Device Management – Ingress Web Server.

Serves the device management UI and proxies requests to the Amazon Alexa API.
Configuration is read from the Home Assistant add-on options.
"""

import json
import logging
import os
import pathlib
from typing import Any

from aiohttp import web

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)

OPTIONS_PATH = pathlib.Path("/data/options.json")
STATIC_DIR = pathlib.Path(__file__).parent / "static"


def load_options() -> dict[str, Any]:
    """Load add-on options from the HA options file."""
    if OPTIONS_PATH.exists():
        return json.loads(OPTIONS_PATH.read_text())
    return {}


def get_demo_devices() -> list[dict[str, Any]]:
    """Return demo devices until real API is connected."""
    return [
        {
            "id": "echo-dot-living",
            "name": "Echo Dot Wohnzimmer",
            "type": "ECHO_DOT",
            "family": "ECHO",
            "online": True,
            "serial": "G0911W079412345X",
            "firmware": "711473420",
            "capabilities": ["AUDIO_PLAYER", "MICROPHONE", "SPEAKER"],
            "room": "Wohnzimmer",
        },
        {
            "id": "echo-show-kitchen",
            "name": "Echo Show Küche",
            "type": "ECHO_SHOW_5",
            "family": "ECHO",
            "online": True,
            "serial": "G0712K039487621Y",
            "firmware": "711473420",
            "capabilities": [
                "AUDIO_PLAYER",
                "MICROPHONE",
                "SPEAKER",
                "DISPLAY",
                "CAMERA",
            ],
            "room": "Küche",
        },
        {
            "id": "smart-plug-office",
            "name": "Smart Plug Büro",
            "type": "SMART_PLUG",
            "family": "SMART_HOME",
            "online": False,
            "serial": "SP-0048271635",
            "firmware": "1.2.3",
            "capabilities": ["POWER_SWITCH"],
            "room": "Büro",
        },
        {
            "id": "fire-tv-bedroom",
            "name": "Fire TV Schlafzimmer",
            "type": "FIRE_TV_STICK_4K",
            "family": "FIRE_TV",
            "online": True,
            "serial": "FT4K-90125634",
            "firmware": "PS7633/2108",
            "capabilities": ["AUDIO_PLAYER", "VIDEO_PLAYER", "MICROPHONE"],
            "room": "Schlafzimmer",
        },
        {
            "id": "echo-studio-music",
            "name": "Echo Studio Musikzimmer",
            "type": "ECHO_STUDIO",
            "family": "ECHO",
            "online": True,
            "serial": "ES-77341289",
            "firmware": "711473420",
            "capabilities": ["AUDIO_PLAYER", "MICROPHONE", "SPEAKER", "DOLBY_ATMOS"],
            "room": "Musikzimmer",
        },
    ]


# ---------------------------------------------------------------------------
# HTTP Handlers
# ---------------------------------------------------------------------------


async def handle_index(request: web.Request) -> web.Response:
    """Serve the main UI page."""
    ingress_path = request.headers.get("X-Ingress-Path", "")
    html = (STATIC_DIR / "index.html").read_text()
    # Inject the ingress base path so the frontend can resolve API calls
    html = html.replace("{{INGRESS_PATH}}", ingress_path)
    return web.Response(text=html, content_type="text/html")


async def handle_api_devices(request: web.Request) -> web.Response:
    """Return device list as JSON."""
    options = load_options()
    # TODO: When real Amazon auth is configured, call the Alexa API here.
    # For now return demo devices if credentials are not yet set.
    if options.get("refresh_token"):
        # Placeholder for real API call
        _LOGGER.info("Would fetch devices from Amazon Alexa API (region=%s)", options.get("amazon_region"))
    devices = get_demo_devices()
    return web.json_response({"devices": devices})


async def handle_api_config_status(request: web.Request) -> web.Response:
    """Return whether the add-on is configured (credentials present)."""
    options = load_options()
    configured = bool(options.get("refresh_token"))
    return web.json_response({
        "configured": configured,
        "region": options.get("amazon_region", "eu"),
    })


# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------


def create_app() -> web.Application:
    """Create the aiohttp application."""
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/devices", handle_api_devices)
    app.router.add_get("/api/config-status", handle_api_config_status)
    # Serve static assets (CSS, JS)
    if STATIC_DIR.exists():
        app.router.add_static("/static", STATIC_DIR, show_index=False)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("INGRESS_PORT", "8099"))
    _LOGGER.info("Starting Alexa Device Management web server on port %d", port)
    web.run_app(create_app(), host="0.0.0.0", port=port)
