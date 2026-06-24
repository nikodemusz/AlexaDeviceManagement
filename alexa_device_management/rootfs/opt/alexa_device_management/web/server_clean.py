"""Clean Home Assistant OS app server for Alexa Device Management."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import aiohttp
from aiohttp import web

import oh_style_login

APP_VERSION = "0.9.1"
BASE_DIR = pathlib.Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
SESSION_PATH = pathlib.Path("/data/alexa_session.json")
OPTIONS_PATH = pathlib.Path("/data/options.json")


def read_json(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def session_data() -> dict[str, Any]:
    return read_json(SESSION_PATH)


def is_configured() -> bool:
    data = session_data()
    return bool(data.get("cookie") and data.get("csrf") and data.get("websiteApiUrl"))


async def index(request: web.Request) -> web.Response:
    html_path = STATIC_DIR / "index.html"
    text = html_path.read_text(encoding="utf-8")
    ingress_path = request.headers.get("X-Ingress-Path", "")
    text = text.replace("{{INGRESS_PATH}}", ingress_path.rstrip("/"))
    return web.Response(text=text, content_type="text/html")


async def app_info(request: web.Request) -> web.Response:
    data = session_data()
    configured = is_configured()
    return web.json_response(
        {
            "app_version": APP_VERSION,
            "configured": configured,
            "authenticated": configured,
            "region": data.get("retailDomain", "amazon.com"),
            "token_source": "alexa_web_session" if configured else "not_connected",
            "auth_message": "Alexa-Web-Session aktiv" if configured else "Bitte Alexa-Login starten.",
            "amazon_user": {},
        }
    )


async def config_status(request: web.Request) -> web.Response:
    data = session_data()
    configured = is_configured()
    return web.json_response(
        {
            "configured": configured,
            "region": data.get("retailDomain", "amazon.com"),
            "host": data.get("host"),
            "loginMode": data.get("loginMode"),
        }
    )


async def logout(request: web.Request) -> web.Response:
    for path in (SESSION_PATH, oh_style_login.STATE_PATH):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return web.json_response({"ok": True})


async def auth_login(request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound(oh_style_login.external_url(request, "/auth/alexa-app/start"))


async def auth_session(request: web.Request) -> web.Response:
    data = session_data()
    return web.json_response(
        {
            "configured": is_configured(),
            "host": data.get("host"),
            "retailDomain": data.get("retailDomain"),
            "retailUrl": data.get("retailUrl"),
            "websiteApiUrl": data.get("websiteApiUrl"),
            "createdAt": data.get("createdAt"),
            "loginMode": data.get("loginMode"),
            "hasCookie": bool(data.get("cookie")),
            "hasCsrf": bool(data.get("csrf")),
            "hasRefreshToken": bool(data.get("refreshToken")),
        }
    )


def alexa_headers(data: dict[str, Any]) -> dict[str, str]:
    base_url = data.get("websiteApiUrl", "https://alexa.amazon.com").rstrip("/")
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Referer": f"{base_url}/spa/index.html",
        "Origin": base_url,
        "Cookie": data.get("cookie", ""),
    }
    if data.get("csrf"):
        headers["csrf"] = data["csrf"]
    return headers


async def alexa_get_json(path: str, data: dict[str, Any]) -> Any:
    if not is_configured():
        raise web.HTTPUnauthorized(text="Alexa session missing")
    base = data.get("websiteApiUrl", "https://alexa.amazon.com").rstrip("/")
    async with aiohttp.ClientSession() as session:
        async with session.get(base + path, headers=alexa_headers(data), allow_redirects=False) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise web.HTTPBadGateway(text=f"Alexa API failed ({resp.status}): {text[:300]}")
            return json.loads(text)


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


def _extract_smart_home_items(payload: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for entry in value:
                walk(entry)
            return
        if not isinstance(value, dict):
            return
        legacy = value.get("legacyAppliance") if isinstance(value.get("legacyAppliance"), dict) else {}
        entity_id = (
            value.get("entityId") or value.get("applianceId")
            or value.get("id") or legacy.get("applianceId")
        )
        name = (
            value.get("friendlyName") or value.get("name")
            or value.get("displayName") or value.get("applianceName")
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
        legacy = item.get("legacyAppliance") if isinstance(item.get("legacyAppliance"), dict) else {}
        key = str(
            item.get("entityId") or item.get("applianceId")
            or item.get("id") or legacy.get("applianceId")
        )
        deduped[key] = item
    return list(deduped.values())


def _normalize_echo_device(raw: dict[str, Any]) -> dict[str, Any]:
    serial = str(raw.get("serialNumber") or raw.get("deviceSerialNumber") or "")
    name = (
        raw.get("accountName") or raw.get("deviceAccountName")
        or raw.get("deviceTypeFriendlyName") or serial or "Unbekanntes Gerät"
    )
    return {
        "name": str(name),
        "serial": serial,
        "type": str(raw.get("deviceType") or "ECHO_DEVICE"),
        "family": str(raw.get("deviceFamily") or "ECHO"),
        "online": bool(raw.get("online", raw.get("isOnline", False))),
        "firmware": str(raw.get("softwareVersion") or ""),
        "capabilities": _normalize_capabilities(raw),
        "room": "",
        "source": "echo",
        "raw": raw,
    }


def _normalize_smart_home_device(raw: dict[str, Any]) -> dict[str, Any]:
    legacy = raw.get("legacyAppliance") if isinstance(raw.get("legacyAppliance"), dict) else {}
    details = raw.get("additionalApplianceDetails") if isinstance(raw.get("additionalApplianceDetails"), dict) else {}
    display_categories = raw.get("displayCategories")
    category = display_categories[0] if isinstance(display_categories, list) and display_categories else None
    device_id = (
        raw.get("entityId") or raw.get("applianceId")
        or raw.get("id") or legacy.get("applianceId") or ""
    )
    name = (
        raw.get("friendlyName") or raw.get("name") or raw.get("displayName")
        or raw.get("applianceName") or legacy.get("friendlyName")
        or device_id or "Unbekanntes Gerät"
    )
    device_type = (
        raw.get("entityType") or raw.get("applianceType") or category
        or raw.get("deviceType") or legacy.get("applianceType") or "SMART_HOME"
    )
    provider = (
        raw.get("providerName") or raw.get("manufacturerName") or raw.get("skillName")
        or legacy.get("manufacturerName") or details.get("manufacturer") or ""
    )
    room = (
        raw.get("roomName") or raw.get("location") or raw.get("groupName")
        or details.get("roomName") or ""
    )
    return {
        "name": str(name),
        "serial": str(raw.get("serialNumber") or raw.get("applianceId") or device_id),
        "type": str(device_type),
        "family": str(provider),
        "online": bool(raw.get("isReachable", raw.get("reachable", raw.get("online", False)))),
        "firmware": str(raw.get("softwareVersion") or raw.get("version") or ""),
        "capabilities": _normalize_capabilities(raw),
        "room": str(room),
        "source": "smart_home",
        "raw": raw,
    }


async def devices(request: web.Request) -> web.Response:
    if not is_configured():
        return web.json_response({"devices": [], "demo": False, "source": "not_connected", "warning": "Alexa-Web-Session fehlt. Bitte Alexa verbinden."})
    data = session_data()
    devices_by_key: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    try:
        payload = await alexa_get_json("/api/devices-v2/device?cached=true", data)
        for raw in (payload.get("devices") if isinstance(payload, dict) else []) or []:
            if isinstance(raw, dict):
                device = _normalize_echo_device(raw)
                devices_by_key[f"echo:{device['serial']}"] = device
    except web.HTTPException as exc:
        errors.append(f"Echo-Geräte: {exc.reason}")
    except Exception as exc:
        errors.append(f"Echo-Geräte: {exc}")

    try:
        payload = await alexa_get_json("/api/behaviors/entities?skillId=amzn1.ask.1p.smarthome", data)
        for raw in _extract_smart_home_items(payload):
            device = _normalize_smart_home_device(raw)
            devices_by_key[f"smart_home:{device['serial']}"] = device
    except web.HTTPException as exc:
        errors.append(f"Smart-Home-Geräte: {exc.reason}")
    except Exception as exc:
        errors.append(f"Smart-Home-Geräte: {exc}")

    device_list = sorted(devices_by_key.values(), key=lambda d: d.get("name", "").lower())
    result: dict[str, Any] = {"devices": device_list, "demo": False, "source": "alexa_web"}
    if errors:
        result["warnings"] = errors
    return web.json_response(result)


async def token_refresh_status(request: web.Request) -> web.Response:
    return web.json_response({"auto_refresh_active": False, "has_valid_token": is_configured(), "last_error": None})


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/app-info", app_info)
    app.router.add_get("/api/config-status", config_status)
    app.router.add_get("/api/devices", devices)
    app.router.add_get("/api/token-refresh-status", token_refresh_status)
    app.router.add_get("/auth/login", auth_login)
    app.router.add_get("/auth/session", auth_session)
    app.router.add_post("/auth/logout", logout)
    app.router.add_static("/static/", STATIC_DIR)
    oh_style_login.setup_routes(app)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8099)
