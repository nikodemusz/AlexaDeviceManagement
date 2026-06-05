"""Patched entrypoint for Alexa Device Management.

Adds read-only discovery through the Alexa web endpoints used by the Alexa web app.
Adds a small Alexa Web session assistant so the add-on can store and reuse the
Alexa web session in /data instead of requiring repeated option edits.
"""

from __future__ import annotations

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

import server as base

_LOGGER = logging.getLogger(__name__)

ALEXA_WEB_SESSION_PATH = pathlib.Path("/data/alexa_web_session.json")

_DEFAULT_ALEXA_HOST_BY_REGION: dict[str, str] = {
    "eu": "alexa.amazon.de",
    "na": "alexa.amazon.com",
    "fe": "alexa.amazon.co.jp",
}

_SECRET_FIELDS = {"alexa_cookie", "alexa_csrf", "client_secret", "refresh_token", "cookie", "csrf"}

_original_handle_api_devices = base.handle_api_devices
_original_handle_api_config_status = base.handle_api_config_status
_original_handle_api_app_info = base.handle_api_app_info
_original_handle_auth_logout = base.handle_auth_logout
_original_create_app = base.create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_host(value: str) -> str:
    """Allow only normal host names, no scheme/path/header injection."""
    host = (value or "").strip().lower()
    host = host.removeprefix("https://").removeprefix("http://").split("/")[0]
    if not re.fullmatch(r"[a-z0-9.-]+", host):
        return ""
    return host


def _read_session() -> dict[str, Any]:
    if not ALEXA_WEB_SESSION_PATH.exists():
        return {}
    try:
        return json.loads(ALEXA_WEB_SESSION_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _write_session(data: dict[str, Any]) -> None:
    ALEXA_WEB_SESSION_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _clear_session() -> None:
    try:
        if ALEXA_WEB_SESSION_PATH.exists():
            ALEXA_WEB_SESSION_PATH.unlink()
    except OSError:
        pass


def _csrf_from_cookie_header(cookie: str) -> str:
    match = re.search(r"(?:^|;\s*)csrf=([^;]+)", cookie or "")
    return match.group(1) if match else ""


def _default_host() -> str:
    options = base.load_options()
    region = options.get("amazon_region", "eu")
    return _DEFAULT_ALEXA_HOST_BY_REGION.get(region, "alexa.amazon.de")


def _get_alexa_web_options() -> tuple[str, str, str]:
    """Return Alexa web host, cookie and csrf from session storage or add-on options."""
    session = _read_session()
    host = _safe_host(str(session.get("host", ""))) or _default_host()
    cookie = str(session.get("cookie", "") or "").strip()
    csrf = str(session.get("csrf", "") or "").strip()

    if not cookie:
        options = base.load_options()
        host = _safe_host(str(options.get("alexa_host", ""))) or host
        cookie = str(options.get("alexa_cookie", "") or "").strip()
        csrf = str(options.get("alexa_csrf", "") or "").strip()

    if cookie and not csrf:
        csrf = _csrf_from_cookie_header(cookie)

    return host, cookie, csrf


def _ingress_path(request: web.Request) -> str:
    ingress_path = request.headers.get("X-Ingress-Path", "")
    if not re.match(r"^[a-zA-Z0-9/_-]*$", ingress_path):
        return ""
    return ingress_path


def _external_url(request: web.Request, path: str) -> str:
    host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host", "")
    ingress_path = _ingress_path(request).rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    if host:
        return f"https://{host}{ingress_path}{path}"
    return f"{ingress_path}{path}"


# ---------------------------------------------------------------------------
# Alexa Web discovery
# ---------------------------------------------------------------------------


def _normalize_capabilities(raw: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("capabilities", "supportedOperations", "actions", "interfaces"):
        current = raw.get(key)
        if isinstance(current, list):
            for item in current:
                if isinstance(item, str) and item:
                    values.append(item)
                elif isinstance(item, dict):
                    name = item.get("interface") or item.get("name") or item.get("type")
                    if isinstance(name, str) and name:
                        values.append(name)
    return sorted(set(values))


def _normalize_echo_device(raw: dict[str, Any]) -> dict[str, Any]:
    serial = str(raw.get("serialNumber") or raw.get("deviceSerialNumber") or "")
    name = (
        raw.get("accountName")
        or raw.get("deviceAccountName")
        or raw.get("deviceTypeFriendlyName")
        or serial
        or "Unbekanntes Gerät"
    )
    return {
        "id": serial or str(raw.get("deviceType") or name),
        "name": str(name),
        "type": str(raw.get("deviceType") or "ECHO_DEVICE"),
        "family": str(raw.get("deviceFamily") or "ECHO"),
        "online": bool(raw.get("online", raw.get("isOnline", False))),
        "serial": serial,
        "firmware": str(raw.get("softwareVersion") or ""),
        "capabilities": _normalize_capabilities(raw),
        "room": "",
        "source": "alexa_web_devices_v2",
        "raw": raw,
    }


def _extract_smart_home_items(payload: Any) -> list[dict[str, Any]]:
    """Extract smart-home entities from several known Alexa web shapes."""
    items: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for entry in value:
                walk(entry)
            return
        if not isinstance(value, dict):
            return

        legacy = value.get("legacyAppliance")
        if not isinstance(legacy, dict):
            legacy = {}

        entity_id = (
            value.get("entityId")
            or value.get("applianceId")
            or value.get("id")
            or legacy.get("applianceId")
        )
        name = (
            value.get("friendlyName")
            or value.get("name")
            or value.get("displayName")
            or value.get("applianceName")
            or legacy.get("friendlyName")
        )
        if entity_id and name:
            items.append(value)
            return

        for key in ("entities", "appliances", "devices", "items", "nodes", "payload"):
            if key in value:
                walk(value[key])

    walk(payload)
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        legacy = item.get("legacyAppliance")
        if not isinstance(legacy, dict):
            legacy = {}
        key = str(
            item.get("entityId")
            or item.get("applianceId")
            or item.get("id")
            or legacy.get("applianceId")
        )
        deduped[key] = item
    return list(deduped.values())


def _normalize_smart_home_device(raw: dict[str, Any]) -> dict[str, Any]:
    legacy = raw.get("legacyAppliance") if isinstance(raw.get("legacyAppliance"), dict) else {}
    details = raw.get("additionalApplianceDetails") if isinstance(raw.get("additionalApplianceDetails"), dict) else {}
    display_categories = raw.get("displayCategories")
    category = display_categories[0] if isinstance(display_categories, list) and display_categories else None

    device_id = (
        raw.get("entityId")
        or raw.get("applianceId")
        or raw.get("id")
        or legacy.get("applianceId")
        or ""
    )
    name = (
        raw.get("friendlyName")
        or raw.get("name")
        or raw.get("displayName")
        or raw.get("applianceName")
        or legacy.get("friendlyName")
        or device_id
        or "Unbekanntes Gerät"
    )
    device_type = (
        raw.get("entityType")
        or raw.get("applianceType")
        or category
        or raw.get("deviceType")
        or legacy.get("applianceType")
        or "SMART_HOME"
    )
    provider = (
        raw.get("providerName")
        or raw.get("manufacturerName")
        or raw.get("skillName")
        or legacy.get("manufacturerName")
        or details.get("manufacturer")
        or "SMART_HOME"
    )
    room = (
        raw.get("roomName")
        or raw.get("location")
        or raw.get("groupName")
        or details.get("roomName")
        or ""
    )
    return {
        "id": str(device_id),
        "name": str(name),
        "type": str(device_type),
        "family": str(provider),
        "online": bool(raw.get("isReachable", raw.get("reachable", raw.get("online", False)))),
        "serial": str(raw.get("serialNumber") or raw.get("applianceId") or device_id),
        "firmware": str(raw.get("softwareVersion") or raw.get("version") or ""),
        "capabilities": _normalize_capabilities(raw),
        "room": str(room),
        "source": "alexa_web_smart_home",
        "raw": raw,
    }


async def _get_json(session: aiohttp.ClientSession, host: str, path: str, headers: dict[str, str]) -> Any:
    url = f"https://{host}{path}"
    async with session.get(url, headers=headers) as resp:
        text = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"{path} failed ({resp.status}): {text[:300]}")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{path} did not return JSON: {text[:120]}") from exc


async def fetch_alexa_web_devices(
    session: aiohttp.ClientSession,
    host: str,
    cookie: str,
    csrf: str,
) -> list[dict[str, Any]]:
    """Fetch Alexa devices via the unofficial Alexa web endpoints, read-only."""
    if not cookie or not csrf:
        raise RuntimeError("Alexa Web Session fehlt.")

    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Cookie": cookie,
        "csrf": csrf,
        "Referer": f"https://{host}/spa/index.html",
        "Origin": f"https://{host}",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
    }

    devices_by_key: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    try:
        payload = await _get_json(session, host, "/api/devices-v2/device?cached=false", headers)
        for raw in payload.get("devices", []) if isinstance(payload, dict) else []:
            if isinstance(raw, dict):
                device = _normalize_echo_device(raw)
                devices_by_key[f"echo:{device['id']}"] = device
    except RuntimeError as exc:
        errors.append(str(exc))

    try:
        payload = await _get_json(
            session,
            host,
            "/api/behaviors/entities?skillId=amzn1.ask.1p.smarthome",
            headers,
        )
        for raw in _extract_smart_home_items(payload):
            device = _normalize_smart_home_device(raw)
            devices_by_key[f"smart_home:{device['id']}"] = device
    except RuntimeError as exc:
        errors.append(str(exc))

    if devices_by_key:
        return sorted(devices_by_key.values(), key=lambda item: item.get("name", "").lower())
    if errors:
        raise RuntimeError("; ".join(errors))
    return []


# ---------------------------------------------------------------------------
# Session assistant
# ---------------------------------------------------------------------------


def _session_assistant_page(request: web.Request, message: str = "", error: str = "") -> web.Response:
    host, _, _ = _get_alexa_web_options()
    safe_message = html.escape(message)
    safe_error = html.escape(error)
    safe_host = html.escape(host, quote=True)
    ingress_path = html.escape(_ingress_path(request) or "/", quote=True)

    body = f"""<!DOCTYPE html>
<html lang=\"de\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Alexa Web Session</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background:#f5f6fa; margin:0; padding:24px; }}
    .card {{ max-width:900px; margin:0 auto; background:#fff; border-radius:14px; padding:28px; box-shadow:0 8px 30px rgba(0,0,0,.10); }}
    textarea, input {{ width:100%; box-sizing:border-box; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
    textarea {{ min-height:160px; }}
    label {{ display:block; font-weight:700; margin-top:16px; }}
    button, a.btn {{ display:inline-block; border:0; padding:11px 18px; border-radius:8px; background:#00a8e8; color:#fff; text-decoration:none; cursor:pointer; font-weight:700; }}
    .danger {{ background:#d63031; }}
    .ok {{ color:#078b3e; font-weight:700; }}
    .err {{ color:#c0392b; font-weight:700; }}
    code {{ background:#f1f2f6; padding:2px 5px; border-radius:4px; }}
    ol li {{ margin-bottom:8px; }}
    .actions {{ margin-top:20px; display:flex; gap:10px; flex-wrap:wrap; }}
  </style>
</head>
<body>
  <div class=\"card\">
    <h1>Alexa-Web-Session verbinden</h1>
    <p>Diese Seite speichert die Alexa-Web-Session im Add-on unter <code>/data/alexa_web_session.json</code>. Danach nutzt <code>/api/devices</code> automatisch diese Session.</p>
    {f'<p class=\"ok\">{safe_message}</p>' if message else ''}
    {f'<p class=\"err\">{safe_error}</p>' if error else ''}
    <ol>
      <li>Öffne <code>https://alexa.amazon.de/spa/index.html</code> im Browser und melde dich an.</li>
      <li>Öffne die Entwicklerwerkzeuge, Netzwerk-Tab, lade die Seite neu.</li>
      <li>Klicke einen Request zu <code>/api/devices-v2/device</code> an.</li>
      <li>Kopiere den kompletten Request-Header <code>cookie</code>. Falls vorhanden, kopiere auch <code>csrf</code>.</li>
      <li>Hier einfügen und speichern. Die App testet die Session direkt gegen Alexa.</li>
    </ol>
    <form method=\"post\" action=\"{html.escape(_external_url(request, '/auth/alexa-web/session'), quote=True)}\">
      <label for=\"host\">Alexa Host</label>
      <input id=\"host\" name=\"host\" value=\"{safe_host}\" />
      <label for=\"cookie\">Cookie Header</label>
      <textarea id=\"cookie\" name=\"cookie\" placeholder=\"session-id=...; ubid-acbde=...; csrf=...\"></textarea>
      <label for=\"csrf\">CSRF Header optional</label>
      <input id=\"csrf\" name=\"csrf\" placeholder=\"wird sonst aus csrf=... im Cookie gelesen\" />
      <div class=\"actions\">
        <button type=\"submit\">Session speichern und testen</button>
        <a class=\"btn\" href=\"{ingress_path}\">Zurück</a>
      </div>
    </form>
    <form method=\"post\" action=\"{html.escape(_external_url(request, '/auth/alexa-web/logout'), quote=True)}\" class=\"actions\">
      <button class=\"danger\" type=\"submit\">Gespeicherte Alexa-Web-Session löschen</button>
    </form>
  </div>
  <script>
    if (window.opener) {{ window.opener.postMessage({{ type: 'oauth_callback', success: {str(bool(message and not error)).lower()} }}, window.location.origin); }}
  </script>
</body>
</html>"""
    return web.Response(text=body, content_type="text/html")


async def handle_alexa_web_login(request: web.Request) -> web.Response:
    return web.json_response({
        "auth_url": _external_url(request, "/auth/alexa-web/session"),
        "message": "Alexa-Web-Session-Assistent öffnen.",
    })


async def handle_alexa_web_session_get(request: web.Request) -> web.Response:
    return _session_assistant_page(request)


async def handle_alexa_web_session_post(request: web.Request) -> web.Response:
    data = await request.post()
    host = _safe_host(str(data.get("host", ""))) or _default_host()
    cookie = str(data.get("cookie", "") or "").strip()
    csrf = str(data.get("csrf", "") or "").strip() or _csrf_from_cookie_header(cookie)

    if not cookie or not csrf:
        return _session_assistant_page(request, error="Cookie oder CSRF fehlt. Der csrf-Wert kann auch als csrf=... im Cookie enthalten sein.")

    try:
        devices = await fetch_alexa_web_devices(request.app["http_session"], host, cookie, csrf)
    except RuntimeError as exc:
        return _session_assistant_page(request, error=f"Session-Test fehlgeschlagen: {exc}")

    _write_session({
        "host": host,
        "cookie": cookie,
        "csrf": csrf,
        "createdAt": int(time.time()),
        "lastValidatedAt": int(time.time()),
        "lastDeviceCount": len(devices),
    })
    return _session_assistant_page(request, message=f"Session gespeichert. {len(devices)} Geräte/Entities gefunden.")


async def handle_alexa_web_status(request: web.Request) -> web.Response:
    session = _read_session()
    return web.json_response({
        "configured": bool(session.get("cookie") and session.get("csrf")),
        "host": _safe_host(str(session.get("host", ""))) or _default_host(),
        "createdAt": session.get("createdAt"),
        "lastValidatedAt": session.get("lastValidatedAt"),
        "lastDeviceCount": session.get("lastDeviceCount"),
    })


async def handle_alexa_web_logout(request: web.Request) -> web.Response:
    _clear_session()
    if request.method == "POST" and request.headers.get("Accept", "").find("text/html") >= 0:
        return _session_assistant_page(request, message="Gespeicherte Alexa-Web-Session gelöscht.")
    return web.json_response({"status": "ok", "message": "Alexa-Web-Session gelöscht."})


# ---------------------------------------------------------------------------
# Existing API route replacements
# ---------------------------------------------------------------------------


async def handle_api_devices(request: web.Request) -> web.Response:
    """Return device list as JSON, preferring Alexa Web discovery when configured."""
    host, cookie, csrf = _get_alexa_web_options()
    if cookie and csrf:
        try:
            devices = await fetch_alexa_web_devices(request.app["http_session"], host, cookie, csrf)
            session = _read_session()
            if session:
                session["lastValidatedAt"] = int(time.time())
                session["lastDeviceCount"] = len(devices)
                _write_session(session)
            return web.json_response({"devices": devices, "source": "alexa_web"})
        except RuntimeError as exc:
            _LOGGER.error("Failed to fetch devices from Alexa Web API: %s", exc)
            return web.json_response({
                "devices": base.get_demo_devices(),
                "api_error": str(exc),
                "source": "demo",
            })

    return await _original_handle_api_devices(request)


async def handle_api_config_status(request: web.Request) -> web.Response:
    """Return config status including Alexa Web credentials."""
    response = await _original_handle_api_config_status(request)
    try:
        data = json.loads(response.text)
    except (TypeError, json.JSONDecodeError):
        data = {}
    host, cookie, csrf = _get_alexa_web_options()
    data["alexa_web_configured"] = bool(cookie and csrf)
    data["alexa_host"] = host
    data["configured"] = bool(data.get("configured") or data["alexa_web_configured"])
    data["login_available"] = True
    data["region"] = data.get("region") or base.load_options().get("amazon_region", "eu")
    return web.json_response(data)


async def handle_api_app_info(request: web.Request) -> web.Response:
    """Return app metadata and include Alexa Web auth source information."""
    response = await _original_handle_api_app_info(request)
    try:
        data = json.loads(response.text)
    except (TypeError, json.JSONDecodeError):
        data = {}
    host, cookie, csrf = _get_alexa_web_options()
    session = _read_session()
    if cookie and csrf:
        data["configured"] = True
        data["authenticated"] = True
        data["token_source"] = "alexa_web_session" if session else "alexa_web_cookie"
        data["auth_message"] = f"Alexa-Web-Session vorhanden ({host})."
        data["amazon_user"] = data.get("amazon_user") or {}
    else:
        data["token_source"] = data.get("token_source") or "not_connected"
    return web.json_response(data)


async def handle_auth_logout(request: web.Request) -> web.Response:
    _clear_session()
    return await _original_handle_auth_logout(request)


# Patch route handlers before create_app() registers them.
base.handle_api_devices = handle_api_devices
base.handle_api_config_status = handle_api_config_status
base.handle_api_app_info = handle_api_app_info
base.handle_auth_login = handle_alexa_web_login
base.handle_auth_logout = handle_auth_logout


def create_app() -> web.Application:
    app = _original_create_app()
    app.router.add_get("/auth/alexa-web/session", handle_alexa_web_session_get)
    app.router.add_post("/auth/alexa-web/session", handle_alexa_web_session_post)
    app.router.add_get("/auth/alexa-web/status", handle_alexa_web_status)
    app.router.add_post("/auth/alexa-web/logout", handle_alexa_web_logout)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("INGRESS_PORT", "8099"))
    _LOGGER.info("Starting Alexa Device Management patched web server on port %d", port)
    web.run_app(create_app(), host="0.0.0.0", port=port)
