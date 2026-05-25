"""Alexa Device Management – Ingress Web Server.

Serves the device management UI and proxies requests to the Amazon Alexa API.
Configuration is read from the Home Assistant add-on options.
"""

import html
import json
import logging
import os
import pathlib
import re
import time
from typing import Any

import aiohttp
from aiohttp import web

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)

OPTIONS_PATH = pathlib.Path("/data/options.json")
STATIC_DIR = pathlib.Path(__file__).parent / "static"

# Amazon OAuth2 / LWA endpoints per region
AMAZON_TOKEN_URLS: dict[str, str] = {
    "eu": "https://api.amazon.co.uk/auth/o2/token",
    "na": "https://api.amazon.com/auth/o2/token",
    "fe": "https://api.amazon.co.jp/auth/o2/token",
}

ALEXA_API_URLS: dict[str, str] = {
    "eu": "https://api.eu.amazonalexa.com",
    "na": "https://api.amazonalexa.com",
    "fe": "https://api.fe.amazonalexa.com",
}

# ---------------------------------------------------------------------------
# Token cache (in-memory, lives as long as the process)
# ---------------------------------------------------------------------------

_token_cache: dict[str, Any] = {
    "access_token": None,
    "expires_at": 0,
}


def load_options() -> dict[str, Any]:
    """Load add-on options from the HA options file."""
    if OPTIONS_PATH.exists():
        return json.loads(OPTIONS_PATH.read_text())
    return {}


def _get_token_url(region: str) -> str:
    """Return the Amazon token endpoint for a given region."""
    return AMAZON_TOKEN_URLS.get(region, AMAZON_TOKEN_URLS["eu"])


def _get_alexa_api_url(region: str) -> str:
    """Return the Alexa API base URL for a given region."""
    return ALEXA_API_URLS.get(region, ALEXA_API_URLS["eu"])


async def refresh_access_token(
    session: aiohttp.ClientSession,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    region: str = "eu",
) -> dict[str, Any]:
    """Exchange a refresh token for a new access token via Amazon LWA.

    Returns a dict with 'access_token', 'token_type', 'expires_in' on success,
    or raises an exception on failure.
    """
    token_url = _get_token_url(region)
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }

    async with session.post(token_url, data=payload) as resp:
        body = await resp.json()
        if resp.status != 200:
            error_desc = body.get("error_description", body.get("error", "Unknown error"))
            raise RuntimeError(f"Token refresh failed ({resp.status}): {error_desc}")
        return body


async def get_valid_access_token(app: web.Application) -> str | None:
    """Return a valid access token, refreshing if necessary.

    Returns None if credentials are not configured.
    """
    options = load_options()
    client_id = options.get("client_id", "")
    client_secret = options.get("client_secret", "")
    refresh_token = options.get("refresh_token", "")
    region = options.get("amazon_region", "eu")

    if not all([client_id, client_secret, refresh_token]):
        return None

    # Check if cached token is still valid (with 60s buffer)
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]

    # Refresh the token
    session = app["http_session"]
    token_data = await refresh_access_token(
        session, client_id, client_secret, refresh_token, region
    )

    _token_cache["access_token"] = token_data["access_token"]
    _token_cache["expires_at"] = time.time() + token_data.get("expires_in", 3600)

    _LOGGER.info("Access token refreshed successfully (region=%s)", region)
    return _token_cache["access_token"]


async def fetch_alexa_devices(
    session: aiohttp.ClientSession, access_token: str, region: str
) -> list[dict[str, Any]]:
    """Fetch the list of Alexa devices from the Amazon API."""
    base_url = _get_alexa_api_url(region)
    url = f"{base_url}/v2/appliances"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    async with session.get(url, headers=headers) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise RuntimeError(
                f"Alexa API request failed ({resp.status}): {text[:200]}"
            )
        data = await resp.json()
        return data.get("appliances", [])


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
    # Validate ingress path: only allow path-like strings (letters, digits, hyphens, slashes)
    if not re.match(r"^[a-zA-Z0-9/_-]*$", ingress_path):
        ingress_path = ""
    html_content = (STATIC_DIR / "index.html").read_text()
    # Safely inject the ingress base path
    safe_path = html.escape(ingress_path, quote=True)
    html_content = html_content.replace("{{INGRESS_PATH}}", safe_path)
    return web.Response(text=html_content, content_type="text/html")


async def handle_api_devices(request: web.Request) -> web.Response:
    """Return device list as JSON.

    If OAuth credentials are configured and valid, fetches real devices from the
    Alexa API. Otherwise, returns demo devices.
    """
    try:
        access_token = await get_valid_access_token(request.app)
    except RuntimeError as exc:
        _LOGGER.error("Failed to obtain access token: %s", exc)
        return web.json_response(
            {"devices": get_demo_devices(), "auth_error": str(exc)},
        )

    if access_token:
        options = load_options()
        region = options.get("amazon_region", "eu")
        try:
            devices = await fetch_alexa_devices(
                request.app["http_session"], access_token, region
            )
            return web.json_response({"devices": devices})
        except RuntimeError as exc:
            _LOGGER.error("Failed to fetch devices from Alexa API: %s", exc)
            return web.json_response(
                {"devices": get_demo_devices(), "api_error": str(exc)},
            )

    # No credentials configured – show demo devices
    return web.json_response({"devices": get_demo_devices(), "demo": True})


async def handle_api_config_status(request: web.Request) -> web.Response:
    """Return whether the add-on is configured (credentials present)."""
    options = load_options()
    configured = bool(
        options.get("client_id")
        and options.get("client_secret")
        and options.get("refresh_token")
    )
    return web.json_response({
        "configured": configured,
        "region": options.get("amazon_region", "eu"),
    })


async def handle_api_auth_status(request: web.Request) -> web.Response:
    """Check the OAuth2 authentication status.

    Attempts to refresh the access token and returns the result.
    This allows the UI to show whether the connection to Amazon is working.
    """
    options = load_options()
    client_id = options.get("client_id", "")
    client_secret = options.get("client_secret", "")
    refresh_token = options.get("refresh_token", "")
    region = options.get("amazon_region", "eu")

    # Check if credentials are configured at all
    if not all([client_id, client_secret, refresh_token]):
        return web.json_response({
            "authenticated": False,
            "status": "not_configured",
            "message": "OAuth2-Zugangsdaten sind nicht vollständig konfiguriert. "
                       "Bitte Client-ID, Client-Secret und Refresh-Token eintragen.",
        })

    # Try to refresh the access token
    try:
        session = request.app["http_session"]
        token_data = await refresh_access_token(
            session, client_id, client_secret, refresh_token, region
        )

        # Update the cache
        _token_cache["access_token"] = token_data["access_token"]
        _token_cache["expires_at"] = time.time() + token_data.get("expires_in", 3600)

        return web.json_response({
            "authenticated": True,
            "status": "ok",
            "message": "Authentifizierung erfolgreich. Verbindung zu Amazon hergestellt.",
            "token_type": token_data.get("token_type", "bearer"),
            "expires_in": token_data.get("expires_in", 3600),
        })
    except RuntimeError as exc:
        _LOGGER.warning("Auth status check failed: %s", exc)
        return web.json_response({
            "authenticated": False,
            "status": "auth_failed",
            "message": f"Authentifizierung fehlgeschlagen: {exc}",
        })
    except aiohttp.ClientError as exc:
        _LOGGER.warning("Auth status check – network error: %s", exc)
        return web.json_response({
            "authenticated": False,
            "status": "network_error",
            "message": f"Netzwerkfehler bei der Verbindung zu Amazon: {exc}",
        })


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------


async def on_startup(app: web.Application) -> None:
    """Create the shared HTTP client session on startup."""
    app["http_session"] = aiohttp.ClientSession()


async def on_cleanup(app: web.Application) -> None:
    """Close the shared HTTP client session on shutdown."""
    await app["http_session"].close()


# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------


def create_app() -> web.Application:
    """Create the aiohttp application."""
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/devices", handle_api_devices)
    app.router.add_get("/api/config-status", handle_api_config_status)
    app.router.add_get("/api/auth-status", handle_api_auth_status)
    # Serve static assets (CSS, JS)
    if STATIC_DIR.exists():
        app.router.add_static("/static", STATIC_DIR, show_index=False)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("INGRESS_PORT", "8099"))
    _LOGGER.info("Starting Alexa Device Management web server on port %d", port)
    web.run_app(create_app(), host="0.0.0.0", port=port)
