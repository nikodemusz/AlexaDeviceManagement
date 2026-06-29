"""Clean Home Assistant OS app server for Alexa Device Management."""

from __future__ import annotations

import json
import pathlib
from typing import Any
from urllib.parse import quote

import aiohttp
from aiohttp import web

import oh_style_login

APP_VERSION = "1.1.15"
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


async def alexa_delete(path: str, data: dict[str, Any], body: bytes | None = None) -> str:
    """Returns response body on success (empty string for 204)."""
    if not is_configured():
        raise Exception("Alexa session missing")
    base = data.get("websiteApiUrl", "https://alexa.amazon.com").rstrip("/")
    headers = alexa_headers(data)
    if body is not None:
        headers["Content-Type"] = "application/json; charset=UTF-8"
    async with aiohttp.ClientSession() as session:
        async with session.delete(base + path, headers=headers, data=body, allow_redirects=False) as resp:
            resp_body = await resp.text()
            if resp.status not in (200, 204):
                raise Exception(f"HTTP {resp.status}: {resp_body[:300]}")
            return resp_body


async def alexa_raw_get(path: str, data: dict[str, Any]) -> tuple[int, str]:
    """Returns (status, body) without throwing on non-200."""
    if not is_configured():
        return 0, "Alexa session missing"
    base = data.get("websiteApiUrl", "https://alexa.amazon.com").rstrip("/")
    async with aiohttp.ClientSession() as session:
        async with session.get(base + path, headers=alexa_headers(data), allow_redirects=False) as resp:
            return resp.status, await resp.text()


async def alexa_raw_delete(path: str, data: dict[str, Any]) -> tuple[int, str]:
    """Returns (status, body) without throwing on non-2xx."""
    if not is_configured():
        return 0, "Alexa session missing"
    base = data.get("websiteApiUrl", "https://alexa.amazon.com").rstrip("/")
    async with aiohttp.ClientSession() as session:
        async with session.delete(base + path, headers=alexa_headers(data), allow_redirects=False) as resp:
            return resp.status, await resp.text()


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
        "skill": "",
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
    provider_data = raw.get("providerData") if isinstance(raw.get("providerData"), dict) else {}
    icon = raw.get("icon") if isinstance(raw.get("icon"), dict) else {}
    display_categories = raw.get("displayCategories")
    category = display_categories[0] if isinstance(display_categories, list) and display_categories else None

    device_id = (
        raw.get("id") or raw.get("entityId") or raw.get("applianceId")
        or legacy.get("applianceId") or ""
    )
    name = (
        raw.get("displayName") or raw.get("friendlyName") or raw.get("name")
        or raw.get("applianceName") or legacy.get("friendlyName")
        or device_id or "Unbekanntes Gerät"
    )
    device_type = (
        provider_data.get("deviceType") or icon.get("value")
        or raw.get("entityType") or raw.get("applianceType") or category
        or raw.get("deviceType") or legacy.get("applianceType") or "SMART_HOME"
    )

    # description format: "entity_id via Skill Name"
    description = str(raw.get("description") or "")
    if " via " in description:
        entity_id, _, skill = description.partition(" via ")
        skill = skill.strip()
        manufacturer = entity_id.strip()
    else:
        skill = (
            raw.get("skillName") or raw.get("providerName")
            or legacy.get("skillName") or ""
        )
        manufacturer = (
            raw.get("manufacturerName") or legacy.get("manufacturerName")
            or details.get("manufacturer") or ""
        )

    room = (
        raw.get("roomName") or raw.get("location") or raw.get("groupName")
        or details.get("roomName") or ""
    )
    online = (
        raw.get("availability") == "AVAILABLE"
        or bool(raw.get("isReachable", raw.get("reachable", raw.get("online", False))))
    )
    # Phoenix API needs the legacy applianceId, not the behaviors entityId
    appliance_id = str(legacy.get("applianceId") or raw.get("applianceId") or device_id)
    return {
        "name": str(name),
        "serial": str(device_id),
        "appliance_id": appliance_id,
        "type": str(device_type),
        "family": str(manufacturer),
        "skill": str(skill),
        "online": online,
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


async def delete_devices(request: web.Request) -> web.Response:
    if not is_configured():
        raise web.HTTPUnauthorized(text="Alexa session missing")
    data = session_data()
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON body")
    targets = body.get("devices", [])
    if not isinstance(targets, list) or not targets:
        raise web.HTTPBadRequest(text="devices list required")

    results: list[dict[str, Any]] = []
    for target in targets:
        serial = str(target.get("serial", "")).strip()
        source = str(target.get("source", "")).strip()
        name = str(target.get("name", "")).strip() or serial
        if not serial:
            results.append({"serial": serial, "name": name, "ok": False, "error": "Missing serial"})
            continue
        try:
            if source == "echo":
                await alexa_delete(f"/api/devices-v2/device/{quote(serial, safe='')}", data)
            else:
                appliance_id = str(target.get("appliance_id", "")).strip()
                sid = quote(serial, safe='')
                has_legacy_id = appliance_id and appliance_id != serial
                if has_legacy_id:
                    # v2 Phoenix device — use the legacy applianceId format (AAA_...)
                    await alexa_delete(f"/api/phoenix/appliance/{quote(appliance_id, safe='')}", data)
                else:
                    # Pure v3 entity (e.g. openHAB3) — no legacy applianceId.
                    # Try candidate v3 endpoints in order; stop at first real 2xx.
                    v3_paths = [
                        f"/api/phoenix/entity/{sid}",
                        f"/api/smarthome/v2/entities/{sid}",
                        f"/api/smarthome/v1/presentation/entities/{sid}",
                        f"/api/phoenix/appliance/{sid}",
                        f"/api/phoenix/registration/{sid}",
                    ]
                    last_err: str = "No candidate endpoint returned 2xx"
                    for path in v3_paths:
                        st, bd = await alexa_raw_delete(path, data)
                        if st in (200, 204):
                            break
                        last_err = f"HTTP {st} on {path}: {bd[:120]}"
                    else:
                        raise Exception(last_err)
                    # Verify the device actually disappeared — phoenix/appliance
                    # returns 200 as a no-op for unknown v3 UUIDs.
                    chk_st, chk_body = await alexa_raw_get(
                        "/api/behaviors/entities?skillId=amzn1.ask.1p.smarthome", data
                    )
                    if chk_st == 200 and serial in chk_body:
                        raise Exception(
                            "Gerät wird vom Alexa Skill verwaltet und kann nicht über "
                            "die Web-API dauerhaft gelöscht werden. Gerät in der Skill-Quelle "
                            "entfernen (z.B. Item in openHAB deaktivieren/löschen)."
                        )
            results.append({"serial": serial, "name": name, "ok": True})
        except Exception as exc:
            results.append({"serial": serial, "name": name, "ok": False, "error": str(exc)})

    return web.json_response({"results": results})


async def devices_debug(request: web.Request) -> web.Response:
    """Return raw API payloads + extracted ID fields to diagnose delete issues."""
    if not is_configured():
        raise web.HTTPUnauthorized(text="Not configured")
    data = session_data()
    result: dict[str, Any] = {}
    try:
        payload = await alexa_get_json("/api/behaviors/entities?skillId=amzn1.ask.1p.smarthome", data)
        items = _extract_smart_home_items(payload)
        result["smart_home_total"] = len(items)
        result["smart_home_id_fields"] = [
            {
                "displayName": (item.get("displayName") or item.get("friendlyName") or "")[:60],
                "id": item.get("id"),
                "entityId": item.get("entityId"),
                "applianceId": item.get("applianceId"),
                "legacy_applianceId": (item.get("legacyAppliance") or {}).get("applianceId"),
                "description": (item.get("description") or "")[:80],
            }
            for item in items[:5]
        ]
        result["smart_home_raw_sample"] = items[:3]
    except Exception as exc:
        result["smart_home_error"] = str(exc)
    return web.json_response(result)


async def delete_probe(request: web.Request) -> web.Response:
    """Diagnostic: find the right delete endpoint by probing multiple API formats."""
    if not is_configured():
        raise web.HTTPUnauthorized(text="Not configured")
    data = session_data()
    device_id = request.rel_url.query.get("id", "").strip()
    if not device_id:
        raise web.HTTPBadRequest(text="?id= required")

    sid = quote(device_id, safe='')
    result: dict[str, Any] = {"id": device_id}

    # 1. Raw device data from behaviors/entities (all fields, not just known ones)
    try:
        payload = await alexa_get_json("/api/behaviors/entities?skillId=amzn1.ask.1p.smarthome", data)
        items = _extract_smart_home_items(payload)
        raw_item = next((item for item in items if item.get("id") == device_id), None)
        if raw_item:
            legacy = raw_item.get("legacyAppliance") if isinstance(raw_item.get("legacyAppliance"), dict) else {}
            result["behaviors_raw_keys"] = list(raw_item.keys())
            result["behaviors_key_values"] = {
                k: str(v)[:120] for k, v in raw_item.items()
                if v is not None and k not in ("capabilities", "connections", "relationships", "displayCategories")
            }
            result["legacy_appliance_keys"] = list(legacy.keys()) if legacy else []
            result["legacy_key_values"] = {k: str(v)[:120] for k, v in legacy.items() if v is not None}
        else:
            result["behaviors_raw_keys"] = "device not found in behaviors/entities"
    except Exception as exc:
        result["behaviors_error"] = str(exc)

    # 2. GET probes on multiple URL formats — find which one phoenix recognises
    arns = [
        f"/api/phoenix/appliance/{sid}",
        f"/api/phoenix/appliance/amzn1.alexa.endpoint.{sid}",
        f"/api/smarthome/appliance/{sid}",
    ]
    result["get_probes"] = {}
    for path in arns:
        status, body = await alexa_raw_get(path, data)
        result["get_probes"][path] = {"status": status, "body": body[:200]}

    # 3. GET /api/phoenix/appliance (list all) — shows ID format phoenix actually uses
    list_status, list_body = await alexa_raw_get("/api/phoenix/appliance", data)
    result["phoenix_list_status"] = list_status
    try:
        parsed = json.loads(list_body)
        entries = parsed if isinstance(parsed, list) else parsed.get("entities", parsed.get("appliances", []))
        result["phoenix_list_sample"] = [
            {k: v for k, v in (e.items() if isinstance(e, dict) else {}) if k in ("id", "entityId", "applianceId", "friendlyName", "displayName")}
            for e in (entries[:3] if isinstance(entries, list) else [])
        ]
    except Exception:
        result["phoenix_list_body_raw"] = list_body[:300]

    # 4. GET probes on v3 candidate endpoints
    v3_candidates = [
        f"/api/phoenix/entity/{sid}",
        f"/api/smarthome/v2/entities/{sid}",
        f"/api/smarthome/v1/presentation/entities/{sid}",
        f"/api/phoenix/registration/{sid}",
    ]
    result["v3_get_probes"] = {}
    for path in v3_candidates:
        status, body = await alexa_raw_get(path, data)
        result["v3_get_probes"][path] = {"status": status, "body": body[:200]}

    # 5. DELETE probes on all candidates (only when ?delete=1 is passed)
    if request.rel_url.query.get("delete") == "1":
        all_delete_candidates = [
            f"/api/phoenix/appliance/{sid}",
        ] + v3_candidates
        result["delete_attempts"] = {}
        for path in all_delete_candidates:
            status, body = await alexa_raw_delete(path, data)
            result["delete_attempts"][path] = {"status": status, "body": body[:200]}

        # Check whether device still exists in behaviors/entities after all DELETEs
        try:
            payload2 = await alexa_get_json("/api/behaviors/entities?skillId=amzn1.ask.1p.smarthome", data)
            items2 = _extract_smart_home_items(payload2)
            result["device_still_exists_after_delete"] = any(item.get("id") == device_id for item in items2)
            result["total_devices_after_delete"] = len(items2)
        except Exception as exc:
            result["post_delete_check_error"] = str(exc)

    return web.json_response(result)


async def debug_ui(request: web.Request) -> web.Response:
    ingress_path = request.headers.get("X-Ingress-Path", "").rstrip("/")
    endpoints = [
        ("/api/app-info",             "App-Info"),
        ("/api/config-status",        "Config-Status"),
        ("/auth/session",             "Session"),
        ("/api/token-refresh-status", "Token-Refresh"),
        ("/api/devices",              "Geräteliste"),
        ("/api/devices-debug",        "Geräte Rohdaten"),
    ]
    buttons = "\n".join(
        f'<button onclick="load(\'{ingress_path}{ep}\', this)">'
        f'<span class="btn-label">{label}</span>'
        f'<span class="btn-ep">{ep}</span>'
        f'</button>'
        for ep, label in endpoints
    )
    buttons += f"""
<button onclick="probeDelete('{ingress_path}', false)" style="background:#fff5f5;border-color:#e17055;">
  <span class="btn-label">🔬 Delete-Probe (GET)</span>
  <span class="btn-ep">/api/delete-probe?id=...</span>
</button>
<button onclick="probeDelete('{ingress_path}', true)" style="background:#ffe0e0;border-color:#c0392b;color:#7b241c;">
  <span class="btn-label">💥 Delete-Probe (DELETE!)</span>
  <span class="btn-ep">/api/delete-probe?id=...&amp;delete=1</span>
</button>"""
    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Debug – Alexa Device Management</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: system-ui, sans-serif; background: #f5f6fa; color: #2d3436;
           display: flex; flex-direction: column; height: 100vh; overflow: hidden; }}

    /* Top bar */
    .top-bar {{ background: #fff; border-bottom: 1px solid #e0e0e0;
                padding: 10px 14px; display: flex; align-items: center;
                justify-content: space-between; gap: 10px; flex-shrink: 0; }}
    .top-bar h2 {{ font-size: 14px; color: #636e72; white-space: nowrap; }}
    .top-bar a {{ font-size: 13px; color: #00caff; text-decoration: none; white-space: nowrap; }}

    /* Endpoint buttons */
    .ep-grid {{ display: flex; flex-wrap: wrap; gap: 8px; padding: 10px 14px;
                background: #fff; border-bottom: 1px solid #e0e0e0; flex-shrink: 0; }}
    .ep-grid button {{
      border: 1px solid #dfe6e9; border-radius: 8px; padding: 8px 12px;
      background: #f8f9fa; cursor: pointer; text-align: left; transition: background .15s;
      display: flex; flex-direction: column; gap: 2px;
    }}
    .btn-label {{ font-size: 13px; font-weight: 600; color: #2d3436; }}
    .btn-ep {{ font-size: 10px; color: #636e72; word-break: break-all; }}
    .ep-grid button:hover {{ background: #e8f4fd; border-color: #00caff; }}
    .ep-grid button.active {{ background: #e8f4fd; border-color: #00caff; }}
    .ep-grid button.active .btn-label {{ color: #0098c8; }}

    /* Action bar */
    .action-bar {{ padding: 8px 14px; background: #f8f9fa; border-bottom: 1px solid #e0e0e0;
                   display: flex; align-items: center; gap: 8px; flex-wrap: wrap; flex-shrink: 0; }}
    .action-bar code {{ font-size: 11px; color: #636e72; flex: 1; min-width: 0;
                        overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .action-bar button {{
      border: none; border-radius: 6px; padding: 6px 14px; cursor: pointer;
      font-size: 12px; font-weight: 600; white-space: nowrap;
    }}
    #btn-reload {{ background: #dfe6e9; color: #2d3436; }}
    #btn-copy   {{ background: #00caff; color: #fff; }}
    #btn-copy.copied {{ background: #27ae60; }}

    /* Output */
    #output {{ flex: 1; overflow: auto; padding: 14px; -webkit-overflow-scrolling: touch; }}
    pre {{ font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-all; }}
    .loading {{ color: #636e72; font-style: italic; }}
    .error   {{ color: #c0392b; }}
    .key  {{ color: #2980b9; }}
    .str  {{ color: #27ae60; }}
    .num  {{ color: #e67e22; }}
    .bool {{ color: #8e44ad; }}
    .null {{ color: #95a5a6; }}
  </style>
</head>
<body>
  <div class="top-bar">
    <h2>🛠 Debug-Endpunkte</h2>
    <a href="{ingress_path}/">← Zurück zur App</a>
  </div>

  <div class="ep-grid">
    {buttons}
  </div>

  <div class="action-bar">
    <code id="current-url">Endpunkt auswählen…</code>
    <button id="btn-reload" onclick="reload()">↻ Laden</button>
    <button id="btn-copy"   onclick="copyOutput()">📋 Kopieren</button>
  </div>

  <div id="output"><pre class="loading">Endpunkt oben auswählen…</pre></div>

  <script>
    let currentUrl = null;
    let rawJson = null;

    function syntaxHL(json) {{
      return JSON.stringify(json, null, 2)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/("(\\u[a-fA-F0-9]{{4}}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, m => {{
          if (/^"/.test(m)) return /:$/.test(m) ? `<span class="key">${{m}}</span>` : `<span class="str">${{m}}</span>`;
          if (/true|false/.test(m)) return `<span class="bool">${{m}}</span>`;
          if (/null/.test(m)) return `<span class="null">${{m}}</span>`;
          return `<span class="num">${{m}}</span>`;
        }});
    }}

    async function load(url, btn) {{
      currentUrl = url;
      rawJson = null;
      document.getElementById('current-url').textContent = url;
      document.querySelectorAll('.ep-grid button').forEach(b => b.classList.remove('active'));
      if (btn) btn.classList.add('active');
      const out = document.getElementById('output');
      out.innerHTML = '<pre class="loading">Lade…</pre>';
      try {{
        const resp = await fetch(url);
        const text = await resp.text();
        let json;
        try {{ json = JSON.parse(text); rawJson = text; }} catch {{ json = null; }}
        if (json !== null) {{
          out.innerHTML = '<pre>' + syntaxHL(json) + '</pre>';
        }} else {{
          rawJson = text;
          out.innerHTML = '<pre class="error">Kein JSON:\\n' + text.replace(/</g,'&lt;') + '</pre>';
        }}
      }} catch(e) {{
        out.innerHTML = '<pre class="error">Fehler: ' + e.message + '</pre>';
      }}
    }}

    function reload() {{
      const active = document.querySelector('.ep-grid button.active');
      if (currentUrl) load(currentUrl, active);
    }}

    async function probeDelete(ingressPath, withDelete) {{
      const id = prompt('Geräte-UUID aus der Geräteliste (data-serial) eingeben:');
      if (!id) return;
      const trimmed = id.trim();
      const url = ingressPath + '/api/delete-probe?id=' + encodeURIComponent(trimmed) + (withDelete ? '&delete=1' : '');
      load(url, null);
    }}

    async function copyOutput() {{
      if (!rawJson) return;
      try {{
        await navigator.clipboard.writeText(rawJson);
        const btn = document.getElementById('btn-copy');
        btn.textContent = '✓ Kopiert';
        btn.classList.add('copied');
        setTimeout(() => {{ btn.textContent = '📋 Kopieren'; btn.classList.remove('copied'); }}, 2000);
      }} catch(e) {{
        alert('Kopieren fehlgeschlagen: ' + e.message);
      }}
    }}
  </script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/app-info", app_info)
    app.router.add_get("/api/config-status", config_status)
    app.router.add_get("/api/devices", devices)
    app.router.add_get("/api/devices-debug", devices_debug)
    app.router.add_post("/api/devices/delete", delete_devices)
    app.router.add_get("/api/delete-probe", delete_probe)
    app.router.add_get("/debug", debug_ui)
    app.router.add_get("/api/token-refresh-status", token_refresh_status)
    app.router.add_get("/auth/login", auth_login)
    app.router.add_get("/auth/session", auth_session)
    app.router.add_post("/auth/logout", logout)
    app.router.add_static("/static/", STATIC_DIR)
    oh_style_login.setup_routes(app)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8099)
