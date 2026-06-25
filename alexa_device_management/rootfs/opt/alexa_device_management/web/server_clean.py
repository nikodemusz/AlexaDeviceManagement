"""Clean Home Assistant OS app server for Alexa Device Management."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import aiohttp
from aiohttp import web

import oh_style_login

APP_VERSION = "1.1.1"
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


async def alexa_delete(path: str, data: dict[str, Any]) -> None:
    if not is_configured():
        raise web.HTTPUnauthorized(text="Alexa session missing")
    base = data.get("websiteApiUrl", "https://alexa.amazon.com").rstrip("/")
    headers = alexa_headers(data)
    headers["Content-Type"] = "application/json; charset=UTF-8"
    async with aiohttp.ClientSession() as session:
        async with session.delete(base + path, headers=headers, allow_redirects=False) as resp:
            if resp.status not in (200, 204):
                text = await resp.text()
                raise web.HTTPBadGateway(text=f"Alexa API DELETE {resp.status}: {text[:200]}")


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
    return {
        "name": str(name),
        "serial": str(device_id),
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
        if not serial:
            results.append({"serial": serial, "ok": False, "error": "Missing serial"})
            continue
        try:
            if source == "echo":
                await alexa_delete(f"/api/devices-v2/device/{serial}", data)
            else:
                await alexa_delete(f"/api/phoenix/v1/appliance/{serial}", data)
            results.append({"serial": serial, "ok": True})
        except web.HTTPException as exc:
            results.append({"serial": serial, "ok": False, "error": exc.reason or str(exc)})
        except Exception as exc:
            results.append({"serial": serial, "ok": False, "error": str(exc)})

    return web.json_response({"results": results})


async def devices_debug(request: web.Request) -> web.Response:
    """Return raw API payloads (first 3 smart-home items) to inspect field structure."""
    if not is_configured():
        raise web.HTTPUnauthorized(text="Not configured")
    data = session_data()
    result: dict[str, Any] = {}
    try:
        payload = await alexa_get_json("/api/behaviors/entities?skillId=amzn1.ask.1p.smarthome", data)
        items = _extract_smart_home_items(payload)
        result["smart_home_raw_sample"] = items[:3]
        result["smart_home_total"] = len(items)
    except Exception as exc:
        result["smart_home_error"] = str(exc)
    return web.json_response(result)


async def debug_ui(request: web.Request) -> web.Response:
    ingress_path = request.headers.get("X-Ingress-Path", "").rstrip("/")
    endpoints = [
        ("/api/app-info",            "App-Info"),
        ("/api/config-status",       "Config-Status"),
        ("/auth/session",            "Session"),
        ("/api/token-refresh-status","Token-Refresh-Status"),
        ("/api/devices",             "Geräteliste (normalisiert)"),
        ("/api/devices-debug",       "Geräte Rohdaten (Smart Home Sample)"),
    ]
    buttons = "\n".join(
        f'<button onclick="load(\'{ingress_path}{ep}\')">{label}<br><small>{ep}</small></button>'
        for ep, label in endpoints
    )
    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Debug – Alexa Device Management</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: system-ui, sans-serif; background: #f5f6fa; color: #2d3436; display: flex; height: 100vh; }}
    nav {{ width: 260px; min-width: 220px; background: #fff; border-right: 1px solid #e0e0e0; padding: 20px 12px; display: flex; flex-direction: column; gap: 8px; overflow-y: auto; }}
    nav h2 {{ margin: 0 0 16px; font-size: 15px; color: #636e72; }}
    nav button {{
      width: 100%; border: 1px solid #dfe6e9; border-radius: 8px; padding: 10px 12px;
      background: #f8f9fa; cursor: pointer; text-align: left; font-size: 13px;
      font-weight: 600; color: #2d3436; transition: background .15s;
    }}
    nav button small {{ font-weight: 400; color: #636e72; font-size: 11px; display: block; margin-top: 2px; word-break: break-all; }}
    nav button:hover {{ background: #e8f4fd; border-color: #00caff; }}
    nav button.active {{ background: #e8f4fd; border-color: #00caff; color: #0098c8; }}
    main {{ flex: 1; display: flex; flex-direction: column; overflow: hidden; }}
    #url-bar {{ padding: 12px 20px; background: #fff; border-bottom: 1px solid #e0e0e0; font-size: 13px; color: #636e72; display: flex; align-items: center; gap: 10px; }}
    #url-bar code {{ color: #2d3436; font-size: 13px; }}
    #url-bar button {{ border: none; background: #00caff; color: #fff; border-radius: 6px; padding: 5px 12px; cursor: pointer; font-size: 12px; }}
    #output {{ flex: 1; overflow: auto; padding: 20px; }}
    pre {{ margin: 0; font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-all; }}
    .loading {{ color: #636e72; font-style: italic; }}
    .error {{ color: #c0392b; }}
    .key {{ color: #2980b9; }}
    .str {{ color: #27ae60; }}
    .num {{ color: #e67e22; }}
    .bool {{ color: #8e44ad; }}
    .null {{ color: #95a5a6; }}
    a.back {{ display: inline-block; margin-top: 4px; font-size: 12px; color: #636e72; text-decoration: none; }}
    a.back:hover {{ color: #00caff; }}
  </style>
</head>
<body>
  <nav>
    <h2>🛠 Debug-Endpunkte</h2>
    {buttons}
    <a class="back" href="{ingress_path}/">← Zurück zur App</a>
  </nav>
  <main>
    <div id="url-bar">
      <span>URL:</span><code id="current-url">—</code>
      <button onclick="reload()">↻ Neu laden</button>
    </div>
    <div id="output"><pre class="loading">Endpunkt links auswählen…</pre></div>
  </main>
  <script>
    let currentUrl = null;

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

    async function load(url) {{
      currentUrl = url;
      document.getElementById('current-url').textContent = url;
      document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
      event.currentTarget.classList.add('active');
      const out = document.getElementById('output');
      out.innerHTML = '<pre class="loading">Lade…</pre>';
      try {{
        const resp = await fetch(url);
        const text = await resp.text();
        let json;
        try {{ json = JSON.parse(text); }} catch {{ json = null; }}
        if (json !== null) {{
          out.innerHTML = '<pre>' + syntaxHL(json) + '</pre>';
        }} else {{
          out.innerHTML = '<pre class="error">Kein JSON: ' + text.replace(/</g,'&lt;') + '</pre>';
        }}
      }} catch(e) {{
        out.innerHTML = '<pre class="error">Fehler: ' + e.message + '</pre>';
      }}
    }}

    function reload() {{
      if (currentUrl) load(currentUrl);
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
