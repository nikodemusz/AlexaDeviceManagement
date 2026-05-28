"""Alexa Device Management – Ingress Web Server.

Serves the device management UI and proxies requests to the Amazon Alexa API.
Configuration is read from the Home Assistant add-on options.

Implements the full OAuth2 Authorization Code flow with Login with Amazon (LWA):
1. User clicks "Mit Amazon anmelden" in the UI
2. Browser redirects to Amazon login page
3. After login, Amazon redirects back to /auth/callback with an authorization code
4. The app exchanges the code for access_token + refresh_token
5. Tokens are stored persistently and refreshed automatically in the background
"""

import asyncio
import html
import json
import logging
import os
import pathlib
import re
import secrets
import time
import urllib.parse
from typing import Any

import aiohttp
from aiohttp import web

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)

OPTIONS_PATH = pathlib.Path("/data/options.json")
TOKEN_CACHE_PATH = pathlib.Path("/data/token_cache.json")
OAUTH_TOKENS_PATH = pathlib.Path("/data/oauth_tokens.json")
STATIC_DIR = pathlib.Path(__file__).parent / "static"
ADDON_CONFIG_PATH = pathlib.Path(__file__).resolve().parents[4] / "config.yaml"

# Background refresh interval: refresh 5 minutes before expiry, check every 60s
_REFRESH_CHECK_INTERVAL = 60  # seconds between checks
_REFRESH_BUFFER = 300  # refresh 5 minutes before expiry
_MAX_APPLIANCE_PAGES = 100

# Amazon OAuth2 / LWA endpoints per region
AMAZON_AUTH_URLS: dict[str, str] = {
    "eu": "https://eu.account.amazon.com/ap/oa",
    "na": "https://www.amazon.com/ap/oa",
    "fe": "https://www.amazon.co.jp/ap/oa",
}

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

AMAZON_PROFILE_URL = "https://api.amazon.com/user/profile"

# OAuth2 scopes needed for Alexa device management
OAUTH_SCOPES = "alexa:all profile"

# ---------------------------------------------------------------------------
# Token cache (persistent + in-memory)
# ---------------------------------------------------------------------------

_token_cache: dict[str, Any] = {
    "access_token": None,
    "expires_at": 0,
    "last_refresh": 0,
    "last_refresh_error": None,
    "refresh_count": 0,
}

# OAuth state for CSRF protection during login flow
_oauth_state: dict[str, Any] = {}


def _load_token_cache() -> None:
    """Load token cache from persistent storage."""
    if TOKEN_CACHE_PATH.exists():
        try:
            data = json.loads(TOKEN_CACHE_PATH.read_text())
            _token_cache["access_token"] = data.get("access_token")
            _token_cache["expires_at"] = data.get("expires_at", 0)
            _token_cache["last_refresh"] = data.get("last_refresh", 0)
            _token_cache["refresh_count"] = data.get("refresh_count", 0)
            _LOGGER.info("Token cache loaded from persistent storage")
        except (json.JSONDecodeError, OSError) as exc:
            _LOGGER.warning("Could not load token cache: %s", exc)


def _save_token_cache() -> None:
    """Persist token cache to disk."""
    try:
        data = {
            "access_token": _token_cache["access_token"],
            "expires_at": _token_cache["expires_at"],
            "last_refresh": _token_cache["last_refresh"],
            "refresh_count": _token_cache["refresh_count"],
        }
        TOKEN_CACHE_PATH.write_text(json.dumps(data))
    except OSError as exc:
        _LOGGER.warning("Could not save token cache: %s", exc)


# ---------------------------------------------------------------------------
# OAuth Tokens (persistent refresh token from login flow)
# ---------------------------------------------------------------------------


def _load_oauth_tokens() -> dict[str, Any]:
    """Load stored OAuth tokens (refresh_token) from persistent storage."""
    if OAUTH_TOKENS_PATH.exists():
        try:
            return json.loads(OAUTH_TOKENS_PATH.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            _LOGGER.warning("Could not load OAuth tokens: %s", exc)
    return {}


def _save_oauth_tokens(tokens: dict[str, Any]) -> None:
    """Persist OAuth tokens to disk."""
    try:
        OAUTH_TOKENS_PATH.write_text(json.dumps(tokens))
        _LOGGER.info("OAuth tokens saved to persistent storage")
    except OSError as exc:
        _LOGGER.warning("Could not save OAuth tokens: %s", exc)


def _get_refresh_token() -> str:
    """Get the refresh token from either OAuth storage or add-on config."""
    # First check persistent OAuth tokens (from browser login flow)
    oauth_tokens = _load_oauth_tokens()
    if oauth_tokens.get("refresh_token"):
        return oauth_tokens["refresh_token"]
    # Fall back to manually configured refresh_token in add-on options
    options = load_options()
    return options.get("refresh_token", "")


def load_options() -> dict[str, Any]:
    """Load add-on options from the HA options file."""
    if OPTIONS_PATH.exists():
        return json.loads(OPTIONS_PATH.read_text())
    return {}


def get_addon_version() -> str:
    """Read the add-on version from config.yaml."""
    if not ADDON_CONFIG_PATH.exists():
        return "unbekannt"

    match = re.search(
        r'^version:\s*["\']?([^"\']+)["\']?\s*$',
        ADDON_CONFIG_PATH.read_text(),
        re.MULTILINE,
    )
    if not match:
        return "unbekannt"
    return match.group(1).strip()


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


async def fetch_amazon_profile(
    session: aiohttp.ClientSession,
    access_token: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Fetch the currently logged-in Amazon profile."""
    headers = {
        "Authorization": "Bearer " + access_token,
        "Accept": "application/json",
    }

    async with session.get(AMAZON_PROFILE_URL, headers=headers) as resp:
        if resp.status == 200:
            body = await resp.json()
            return {
                "name": str(body.get("name") or "").strip(),
                "email": str(body.get("email") or "").strip(),
                "user_id": str(body.get("user_id") or "").strip(),
            }, None

        if resp.status in {401, 403}:
            return None, (
                "Amazon-Benutzerprofil konnte mit dem aktuellen Token nicht gelesen werden. "
                "Bitte erneut anmelden, damit die Profil-Berechtigung übernommen wird."
            )

        text = await resp.text()
        raise RuntimeError(
            f"Amazon profile request failed ({resp.status}): {text[:300]}"
        )


async def get_valid_access_token(app: web.Application) -> str | None:
    """Return a valid access token, refreshing if necessary.

    Returns None if credentials are not configured.
    """
    options = load_options()
    client_id = options.get("client_id", "")
    client_secret = options.get("client_secret", "")
    refresh_token = _get_refresh_token()
    region = options.get("amazon_region", "eu")

    if not all([client_id, client_secret, refresh_token]):
        return None

    # Check if cached token is still valid (with 5min buffer)
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"] - _REFRESH_BUFFER:
        return _token_cache["access_token"]

    # Refresh the token
    session = app["http_session"]
    token_data = await refresh_access_token(
        session, client_id, client_secret, refresh_token, region
    )

    _token_cache["access_token"] = token_data["access_token"]
    _token_cache["expires_at"] = time.time() + token_data.get("expires_in", 3600)
    _token_cache["last_refresh"] = time.time()
    _token_cache["refresh_count"] = _token_cache.get("refresh_count", 0) + 1
    _token_cache["last_refresh_error"] = None
    _save_token_cache()

    # If Amazon returned a new refresh_token, store it
    if token_data.get("refresh_token"):
        oauth_tokens = _load_oauth_tokens()
        oauth_tokens["refresh_token"] = token_data["refresh_token"]
        oauth_tokens["updated_at"] = time.time()
        _save_oauth_tokens(oauth_tokens)

    _LOGGER.info("Access token refreshed successfully (region=%s)", region)
    return _token_cache["access_token"]


async def fetch_alexa_devices(
    session: aiohttp.ClientSession, access_token: str, region: str
) -> list[dict[str, Any]]:
    """Fetch all Alexa home automation devices from the Amazon API."""
    base_url = _get_alexa_api_url(region)
    headers = {
        "Authorization": "Bearer " + access_token,
        "Accept": "application/json",
    }

    def _extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
        for key in ("appliances", "devices"):
            items = payload.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        nested = payload.get("payload")
        if isinstance(nested, dict):
            for key in ("appliances", "devices"):
                items = nested.get(key)
                if isinstance(items, list):
                    return [item for item in items if isinstance(item, dict)]
        return []

    def _normalize_capability(value: Any) -> str | None:
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            for key in ("name", "interface", "type"):
                capability = value.get(key)
                if isinstance(capability, str) and capability:
                    return capability
        return None

    def _normalize_device(raw: dict[str, Any]) -> dict[str, Any]:
        details = raw.get("additionalApplianceDetails")
        if not isinstance(details, dict):
            details = {}

        appliance_types = raw.get("applianceTypes")
        if not isinstance(appliance_types, list):
            appliance_types = []

        raw_capabilities = raw.get("actions")
        if not isinstance(raw_capabilities, list):
            raw_capabilities = raw.get("capabilities")
        if not isinstance(raw_capabilities, list):
            raw_capabilities = []

        name = (
            raw.get("friendlyName")
            or raw.get("accountName")
            or raw.get("name")
            or raw.get("modelName")
            or raw.get("applianceId")
            or "Unbekanntes Gerät"
        )
        device_type = (
            appliance_types[0]
            if appliance_types
            else raw.get("deviceType")
            or raw.get("modelName")
            or "UNKNOWN"
        )
        device_id = (
            raw.get("applianceId")
            or raw.get("id")
            or details.get("applianceId")
            or details.get("deviceSerialNumber")
            or ""
        )
        serial = (
            details.get("serialNumber")
            or details.get("applianceSerialNumber")
            or details.get("deviceSerialNumber")
            or raw.get("serialNumber")
            or raw.get("deviceSerialNumber")
            or device_id
        )
        room = (
            details.get("roomName")
            or details.get("location")
            or details.get("groupName")
            or raw.get("roomName")
            or raw.get("location")
            or ""
        )
        capabilities = [
            capability
            for capability in (
                _normalize_capability(entry) for entry in raw_capabilities
            )
            if capability
        ]

        return {
            "id": str(device_id),
            "name": str(name),
            "type": str(device_type),
            "family": str(raw.get("manufacturerName") or raw.get("deviceFamily") or "UNKNOWN"),
            "online": bool(raw.get("isReachable", raw.get("connected", raw.get("online", False)))),
            "serial": str(serial),
            "firmware": str(raw.get("version") or raw.get("softwareVersion") or ""),
            "capabilities": capabilities,
            "room": str(room),
        }

    endpoint_paths = ("/v2/devices", "/v2/appliances")
    devices_by_id: dict[str, dict[str, Any]] = {}
    endpoint_errors: list[str] = []

    for endpoint_path in endpoint_paths:
        next_token: str | None = None
        seen_tokens: set[str] = set()
        page_count = 0

        while True:
            page_count += 1
            if page_count > _MAX_APPLIANCE_PAGES:
                raise RuntimeError(
                    f"Alexa API pagination exceeded safe page limit ({_MAX_APPLIANCE_PAGES})"
                )

            params = {"nextToken": next_token} if next_token else None
            url = f"{base_url}{endpoint_path}"

            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 404:
                    break
                if resp.status != 200:
                    text = await resp.text()
                    endpoint_errors.append(
                        f"{endpoint_path} failed ({resp.status}): {text[:120]}"
                    )
                    break
                data = await resp.json(content_type=None)

            items = _extract_items(data) if isinstance(data, dict) else []
            for item in items:
                device = _normalize_device(item)
                key = device["id"] or (
                    f"{endpoint_path}:{device['serial']}:{device['name']}:{len(devices_by_id)}"
                )
                devices_by_id[key] = device

            next_token = data.get("nextToken") if isinstance(data, dict) else None
            if not next_token and isinstance(data, dict):
                nested = data.get("payload")
                if isinstance(nested, dict):
                    next_token = nested.get("nextToken")
            if not next_token or next_token in seen_tokens:
                break
            seen_tokens.add(next_token)

    if devices_by_id:
        return list(devices_by_id.values())
    if endpoint_errors:
        raise RuntimeError("; ".join(endpoint_errors))
    return []


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
    refresh_token = _get_refresh_token()
    configured = bool(
        options.get("client_id")
        and options.get("client_secret")
        and refresh_token
    )
    oauth_tokens = _load_oauth_tokens()
    return web.json_response({
        "configured": configured,
        "region": options.get("amazon_region", "eu"),
        "has_oauth_token": bool(oauth_tokens.get("refresh_token")),
        "login_available": bool(options.get("client_id") and options.get("client_secret")),
    })


async def handle_api_app_info(request: web.Request) -> web.Response:
    """Return app metadata and Amazon account information for the overview UI."""
    options = load_options()
    oauth_tokens = _load_oauth_tokens()
    refresh_token = _get_refresh_token()
    login_available = bool(options.get("client_id") and options.get("client_secret"))
    configured = bool(login_available and refresh_token)
    info: dict[str, Any] = {
        "app_version": get_addon_version(),
        "region": options.get("amazon_region", "eu"),
        "configured": configured,
        "login_available": login_available,
        "has_oauth_token": bool(oauth_tokens.get("refresh_token")),
        "token_source": "oauth" if oauth_tokens.get("refresh_token") else "config",
        "authenticated": False,
        "auth_message": (
            "Nicht angemeldet."
            if login_available
            else "Client-ID und Client-Secret fehlen."
        ),
        "amazon_user": {
            "name": "",
            "email": "",
            "user_id": "",
        },
    }

    if not configured:
        return web.json_response(info)

    try:
        access_token = await get_valid_access_token(request.app)
        if not access_token:
            return web.json_response(info)

        info["authenticated"] = True
        info["auth_message"] = "Mit Amazon verbunden."

        profile, profile_message = await fetch_amazon_profile(
            request.app["http_session"],
            access_token,
        )
        if profile:
            info["amazon_user"] = profile
            oauth_tokens["profile"] = profile
            oauth_tokens["profile_updated_at"] = time.time()
            _save_oauth_tokens(oauth_tokens)
        elif oauth_tokens.get("profile"):
            info["amazon_user"] = oauth_tokens["profile"]
            info["auth_message"] = profile_message or (
                "Mit Amazon verbunden. Gespeichertes Benutzerprofil wird angezeigt."
            )
        elif profile_message:
            info["auth_message"] = profile_message
    except RuntimeError as exc:
        info["auth_message"] = str(exc)
    except aiohttp.ClientError as exc:
        info["auth_message"] = f"Netzwerkfehler beim Laden der Amazon-Informationen: {exc}"

    return web.json_response(info)


async def handle_api_auth_status(request: web.Request) -> web.Response:
    """Check the OAuth2 authentication status.

    Attempts to refresh the access token and returns the result.
    This allows the UI to show whether the connection to Amazon is working.
    """
    options = load_options()
    client_id = options.get("client_id", "")
    client_secret = options.get("client_secret", "")
    refresh_token = _get_refresh_token()
    region = options.get("amazon_region", "eu")

    # Check if credentials are configured at all
    if not all([client_id, client_secret, refresh_token]):
        return web.json_response({
            "authenticated": False,
            "status": "not_configured",
            "message": "OAuth2-Zugangsdaten nicht vollständig. "
                       "Bitte Client-ID und Client-Secret eintragen und "
                       "über 'Mit Amazon anmelden' einloggen.",
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


async def handle_api_token_refresh_status(request: web.Request) -> web.Response:
    """Return the status of the automatic token refresh process."""
    now = time.time()
    expires_at = _token_cache["expires_at"]
    last_refresh = _token_cache["last_refresh"]
    has_token = _token_cache["access_token"] is not None

    # Calculate next refresh time (5 minutes before expiry)
    next_refresh = max(0, expires_at - _REFRESH_BUFFER - now) if has_token else 0

    task = request.app.get("token_refresh_task")
    return web.json_response({
        "auto_refresh_active": task is not None and not task.done(),
        "has_valid_token": has_token and now < expires_at,
        "expires_in": max(0, int(expires_at - now)) if has_token else 0,
        "next_refresh_in": int(next_refresh),
        "last_refresh_ago": int(now - last_refresh) if last_refresh > 0 else None,
        "refresh_count": _token_cache["refresh_count"],
        "last_error": _token_cache.get("last_refresh_error"),
    })


# ---------------------------------------------------------------------------
# OAuth2 Authorization Code Flow (Login with Amazon)
# ---------------------------------------------------------------------------


def _get_auth_url(region: str) -> str:
    """Return the Amazon authorization endpoint for a given region."""
    return AMAZON_AUTH_URLS.get(region, AMAZON_AUTH_URLS["eu"])


async def handle_auth_login(request: web.Request) -> web.Response:
    """Initiate the OAuth2 Authorization Code flow.

    Generates the Amazon login URL and redirects the user's browser there.
    The user logs in at Amazon and is redirected back to /auth/callback.
    """
    options = load_options()
    client_id = options.get("client_id", "")
    region = options.get("amazon_region", "eu")

    if not client_id:
        return web.json_response(
            {"error": "Client-ID ist nicht konfiguriert. Bitte in den Add-on-Einstellungen eintragen."},
            status=400,
        )

    # Determine the callback URL based on the ingress path
    ingress_path = request.headers.get("X-Ingress-Path", "")
    if not re.match(r"^[a-zA-Z0-9/_-]*$", ingress_path):
        ingress_path = ""

    # Build the redirect_uri – Amazon LWA requires a full absolute URL
    # Derive the external base URL from proxy headers set by Home Assistant ingress
    # Always use https – Amazon LWA requires it and HA external URLs must be https
    scheme = "https"
    host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host", "")
    if not host:
        return web.json_response(
            {"error": "Externe URL konnte nicht ermittelt werden. "
                      "Bitte stelle sicher, dass eine externe URL in Home Assistant konfiguriert ist "
                      "(Einstellungen → System → Netzwerk → Internet-URL)."},
            status=400,
        )
    redirect_uri = f"{scheme}://{host}{ingress_path}/auth/callback"

    # Generate CSRF state token
    state = secrets.token_urlsafe(32)

    # Store state for verification in callback
    _oauth_state[state] = {
        "redirect_uri": redirect_uri,
        "created_at": time.time(),
        "region": region,
    }

    # Clean up old states (older than 10 minutes)
    now = time.time()
    expired_states = [k for k, v in _oauth_state.items() if now - v["created_at"] > 600]
    for k in expired_states:
        del _oauth_state[k]

    # Build Amazon authorization URL
    auth_url = _get_auth_url(region)
    params = {
        "client_id": client_id,
        "scope": OAUTH_SCOPES,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    }

    full_auth_url = f"{auth_url}?{urllib.parse.urlencode(params)}"

    return web.json_response({
        "auth_url": full_auth_url,
        "redirect_uri": redirect_uri,
        "message": "Bitte im Amazon Developer Console folgende Redirect-URI registrieren "
                   "(falls noch nicht geschehen).",
    })


async def handle_auth_callback(request: web.Request) -> web.Response:
    """Handle the OAuth2 callback from Amazon after user login.

    Amazon redirects here with an authorization code which we exchange
    for access_token + refresh_token.
    """
    code = request.query.get("code")
    state = request.query.get("state")
    error = request.query.get("error")
    error_description = request.query.get("error_description", "")

    ingress_path = request.headers.get("X-Ingress-Path", "")
    if not re.match(r"^[a-zA-Z0-9/_-]*$", ingress_path):
        ingress_path = ""

    # Handle error from Amazon
    if error:
        _LOGGER.warning("OAuth callback error: %s – %s", error, error_description)
        return web.Response(
            text=_render_callback_page(
                ingress_path,
                success=False,
                message=f"Amazon Login fehlgeschlagen: {error_description or error}",
            ),
            content_type="text/html",
        )

    # Validate state (CSRF protection)
    if not state or state not in _oauth_state:
        _LOGGER.warning("OAuth callback: invalid or missing state parameter")
        return web.Response(
            text=_render_callback_page(
                ingress_path,
                success=False,
                message="Ungültiger State-Parameter. Bitte erneut anmelden.",
            ),
            content_type="text/html",
        )

    if not code:
        return web.Response(
            text=_render_callback_page(
                ingress_path,
                success=False,
                message="Kein Authorization-Code erhalten. Bitte erneut anmelden.",
            ),
            content_type="text/html",
        )

    # Retrieve stored state data
    state_data = _oauth_state.pop(state)
    redirect_uri = state_data["redirect_uri"]
    region = state_data["region"]

    # Exchange authorization code for tokens
    options = load_options()
    client_id = options.get("client_id", "")
    client_secret = options.get("client_secret", "")

    if not all([client_id, client_secret]):
        return web.Response(
            text=_render_callback_page(
                ingress_path,
                success=False,
                message="Client-ID oder Client-Secret fehlt in der Add-on-Konfiguration.",
            ),
            content_type="text/html",
        )

    token_url = _get_token_url(region)
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }

    try:
        session = request.app["http_session"]
        async with session.post(token_url, data=payload) as resp:
            body = await resp.json()
            if resp.status != 200:
                error_desc = body.get("error_description", body.get("error", "Unknown error"))
                _LOGGER.error("Token exchange failed (%d): %s", resp.status, error_desc)
                return web.Response(
                    text=_render_callback_page(
                        ingress_path,
                        success=False,
                        message=f"Token-Austausch fehlgeschlagen: {error_desc}",
                    ),
                    content_type="text/html",
                )

            # Store the refresh token persistently
            oauth_tokens = {
                "refresh_token": body["refresh_token"],
                "obtained_at": time.time(),
                "region": region,
            }
            _save_oauth_tokens(oauth_tokens)

            # Update the access token cache
            _token_cache["access_token"] = body["access_token"]
            _token_cache["expires_at"] = time.time() + body.get("expires_in", 3600)
            _token_cache["last_refresh"] = time.time()
            _token_cache["refresh_count"] = _token_cache.get("refresh_count", 0) + 1
            _token_cache["last_refresh_error"] = None
            _save_token_cache()

            _LOGGER.info("OAuth2 login successful! Tokens obtained and stored.")

            return web.Response(
                text=_render_callback_page(
                    ingress_path,
                    success=True,
                    message="Erfolgreich mit Amazon angemeldet! "
                            "Der Refresh-Token wurde gespeichert und wird automatisch erneuert.",
                ),
                content_type="text/html",
            )

    except aiohttp.ClientError as exc:
        _LOGGER.error("OAuth token exchange – network error: %s", exc)
        return web.Response(
            text=_render_callback_page(
                ingress_path,
                success=False,
                message="Netzwerkfehler beim Token-Austausch. Bitte erneut versuchen.",
            ),
            content_type="text/html",
        )


async def handle_auth_logout(request: web.Request) -> web.Response:
    """Remove stored OAuth tokens (logout)."""
    if OAUTH_TOKENS_PATH.exists():
        OAUTH_TOKENS_PATH.unlink()

    # Clear token cache
    _token_cache["access_token"] = None
    _token_cache["expires_at"] = 0
    _token_cache["last_refresh_error"] = None
    if TOKEN_CACHE_PATH.exists():
        TOKEN_CACHE_PATH.unlink()

    _LOGGER.info("OAuth tokens removed (logout)")
    return web.json_response({
        "status": "ok",
        "message": "Abgemeldet. Gespeicherte Tokens wurden entfernt.",
    })


def _render_callback_page(ingress_path: str, success: bool, message: str) -> str:
    """Render a simple HTML page for the OAuth callback result."""
    safe_message = html.escape(message)
    safe_path = html.escape(ingress_path, quote=True)
    icon = "✅" if success else "❌"
    color = "#27ae60" if success else "#e74c3c"

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Amazon Login – {'Erfolg' if success else 'Fehler'}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh; margin: 0; background: #f5f6fa;
    }}
    .card {{
      background: #fff; border-radius: 12px; padding: 40px;
      box-shadow: 0 4px 20px rgba(0,0,0,0.08); text-align: center;
      max-width: 500px; width: 90%;
    }}
    .icon {{ font-size: 48px; margin-bottom: 16px; }}
    .message {{ color: #2d3436; font-size: 16px; line-height: 1.5; }}
    .status {{ color: {color}; font-weight: 600; font-size: 18px; margin-bottom: 12px; }}
    .btn {{
      display: inline-block; margin-top: 20px; padding: 10px 24px;
      background: #00caff; color: #fff; border-radius: 6px;
      text-decoration: none; font-weight: 500;
    }}
    .btn:hover {{ background: #00b4e6; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">{icon}</div>
    <div class="status">{'Anmeldung erfolgreich!' if success else 'Anmeldung fehlgeschlagen'}</div>
    <div class="message">{safe_message}</div>
    <a class="btn" href="{safe_path}/">Zurück zur Übersicht</a>
  </div>
  <script>
    // Notify opener window if this was opened as popup
    if (window.opener) {{
      window.opener.postMessage({{ type: 'oauth_callback', success: {'true' if success else 'false'} }}, window.location.origin);
    }}
  </script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Background Token Refresh Task
# ---------------------------------------------------------------------------


async def _background_token_refresh(app: web.Application) -> None:
    """Periodically refresh the OAuth access token in the background.

    This ensures the token is always fresh and API calls never fail due to
    an expired token. Runs every 60 seconds and refreshes 5 minutes before expiry.
    """
    _LOGGER.info("Background token refresh task started")

    while True:
        try:
            await asyncio.sleep(_REFRESH_CHECK_INTERVAL)

            options = load_options()
            client_id = options.get("client_id", "")
            client_secret = options.get("client_secret", "")
            refresh_token = _get_refresh_token()
            region = options.get("amazon_region", "eu")

            if not all([client_id, client_secret, refresh_token]):
                continue

            now = time.time()
            expires_at = _token_cache["expires_at"]

            # Refresh if token is expired or will expire within the buffer period
            if _token_cache["access_token"] and now < expires_at - _REFRESH_BUFFER:
                continue  # Token is still valid, no refresh needed

            _LOGGER.info("Background refresh: token expired or expiring soon, refreshing...")

            session = app["http_session"]
            token_data = await refresh_access_token(
                session, client_id, client_secret, refresh_token, region
            )

            _token_cache["access_token"] = token_data["access_token"]
            _token_cache["expires_at"] = now + token_data.get("expires_in", 3600)
            _token_cache["last_refresh"] = now
            _token_cache["refresh_count"] = _token_cache.get("refresh_count", 0) + 1
            _token_cache["last_refresh_error"] = None
            _save_token_cache()

            _LOGGER.info(
                "Background refresh successful (region=%s, expires_in=%ds, total_refreshes=%d)",
                region,
                token_data.get("expires_in", 3600),
                _token_cache["refresh_count"],
            )

        except asyncio.CancelledError:
            _LOGGER.info("Background token refresh task cancelled")
            break
        except RuntimeError as exc:
            _token_cache["last_refresh_error"] = str(exc)
            _LOGGER.error("Background token refresh failed: %s", exc)
        except aiohttp.ClientError as exc:
            _token_cache["last_refresh_error"] = f"Network error: {exc}"
            _LOGGER.error("Background token refresh – network error: %s", exc)
        except Exception as exc:  # noqa: BLE001
            _token_cache["last_refresh_error"] = f"{type(exc).__name__}: {exc}"
            _LOGGER.exception("Background token refresh – unexpected error")


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------


async def on_startup(app: web.Application) -> None:
    """Create the shared HTTP client session and start background tasks."""
    app["http_session"] = aiohttp.ClientSession()
    _load_token_cache()
    app["token_refresh_task"] = asyncio.create_task(_background_token_refresh(app))


async def on_cleanup(app: web.Application) -> None:
    """Stop background tasks and close the shared HTTP client session."""
    task = app.get("token_refresh_task")
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
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
    app.router.add_get("/api/app-info", handle_api_app_info)
    app.router.add_get("/api/config-status", handle_api_config_status)
    app.router.add_get("/api/auth-status", handle_api_auth_status)
    app.router.add_get("/api/token-refresh-status", handle_api_token_refresh_status)
    # OAuth2 login flow
    app.router.add_get("/auth/login", handle_auth_login)
    app.router.add_get("/auth/callback", handle_auth_callback)
    app.router.add_post("/auth/logout", handle_auth_logout)
    # Serve static assets (CSS, JS)
    if STATIC_DIR.exists():
        app.router.add_static("/static", STATIC_DIR, show_index=False)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("INGRESS_PORT", "8099"))
    _LOGGER.info("Starting Alexa Device Management web server on port %d", port)
    web.run_app(create_app(), host="0.0.0.0", port=port)
