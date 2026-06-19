"""Standalone Alexa Device Management login test app.

This server deliberately avoids Home Assistant ingress, panels and iframe routing.
It runs as a normal browser-facing aiohttp application and exposes only the
minimum routes needed to test the Amazon/Alexa app-registration login path.
"""

from __future__ import annotations

import html
import json
import os
import pathlib
import re
import sys
import types
import urllib.parse
from typing import Any

from aiohttp import web

BASE_DIR = pathlib.Path(__file__).resolve().parent
DEFAULT_HELPER_PATH = (
    BASE_DIR.parent
    / "alexa_device_management"
    / "rootfs"
    / "opt"
    / "alexa_device_management"
    / "web"
    / "alexa_openhab_login.py"
)
DATA_DIR = pathlib.Path(os.environ.get("ALEXA_TEST_DATA_DIR", "/data"))
SESSION_PATH = DATA_DIR / "alexa_web_session.json"
LOGIN_STATE_PATH = DATA_DIR / "alexa_web_login_state.json"
DEFAULT_ALEXA_HOST = os.environ.get("ALEXA_HOST", "alexa.amazon.de")


def _safe_host(value: str) -> str:
    host = (value or "").strip().lower()
    host = host.removeprefix("https://").removeprefix("http://").split("/")[0]
    if not re.fullmatch(r"[a-z0-9.-]+", host):
        return "alexa.amazon.de"
    return host


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _patch_login_helper_source(source: str) -> str:
    """Normalize the shared legacy helper for standalone HA-app testing."""
    if source.startswith("Local-only login proxy:\n"):
        source = '"""' + source

    start_replacement = '''async def start(request: web.Request) -> web.StreamResponse:
    alexa_host = safe_host(request.query.get("host", "alexa.amazon.de"))

    session = await reset_proxy_session(request.app)
    state = new_login_state(alexa_host)

    seed_login_cookies(session, state)

    login_url = build_login_url(state)
    parsed_login_url = urllib.parse.urlsplit(login_url)

    if not parsed_login_url.netloc:
        raise web.HTTPInternalServerError(text="Amazon login URL has no target host")

    local_path = (
        "/auth/alexa-app/FORWARD/"
        + parsed_login_url.netloc
        + parsed_login_url.path
    )

    if parsed_login_url.query:
        local_path += "?" + parsed_login_url.query

    raise web.HTTPFound(external_url(request, local_path))
'''
    source, count = re.subn(
        r"async def start\(request: web\.Request\) -> web\.StreamResponse:\n"
        r".*?\n\nasync def register_app",
        start_replacement + "\n\nasync def register_app",
        source,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError("Could not patch helper start()")

    proxy_target_old = '''    if tail.startswith("FORWARD/"):
        target = retail_url.rstrip("/") + "/" + tail[len("FORWARD/") :]
    elif tail.startswith("PROXY/"):
        target = website_api_url.rstrip("/") + "/" + tail[len("PROXY/") :]
    else:
        return web.Response(text="Ungültiger Proxy-Pfad", status=400)

    if request.query_string:
        target += "?" + request.query_string
'''
    proxy_target_new = '''    if tail.startswith("FORWARD/"):
        forward_tail = tail[len("FORWARD/") :]
        forward_host, separator, forward_path = forward_tail.partition("/")

        if separator and "." in forward_host:
            target = "https://" + safe_host(forward_host) + "/" + forward_path
        else:
            target = retail_url.rstrip("/") + "/" + forward_tail
    elif tail.startswith("PROXY/"):
        target = website_api_url.rstrip("/") + "/" + tail[len("PROXY/") :]
    else:
        return web.Response(text="Ungültiger Proxy-Pfad", status=400)

    query_items = []
    for name in request.query:
        for value in request.query.getall(name):
            query_items.append((name, value))

    if query_items:
        target += "?" + urllib.parse.urlencode(query_items, doseq=True)
'''
    source = source.replace(proxy_target_old, proxy_target_new, 1)

    source = source.replace("/auth/alexa-openhab", "/auth/alexa-app")

    setup_replacement = '''def setup_routes(app: web.Application) -> None:
    app.router.add_route("*", "/auth/alexa-app/{tail:.*}", proxy)
    app.on_cleanup.append(cleanup)
'''
    source, count = re.subn(
        r"def setup_routes\(app: web\.Application\) -> None:\n(?:    .*\n)+",
        setup_replacement,
        source,
        count=1,
    )
    if count != 1:
        raise RuntimeError("Could not patch helper setup_routes()")

    return source


def load_login_helper() -> types.ModuleType:
    helper_path = pathlib.Path(os.environ.get("ALEXA_HELPER_PATH", DEFAULT_HELPER_PATH))
    source = _patch_login_helper_source(helper_path.read_text(encoding="utf-8"))

    module = types.ModuleType("standalone_alexa_app_login")
    module.__file__ = str(helper_path)
    module.__package__ = ""
    module.__cached__ = None
    sys.modules[module.__name__] = module
    exec(compile(source, str(helper_path), "exec"), module.__dict__)

    module.SESSION_PATH = SESSION_PATH
    module.LOGIN_STATE_PATH = LOGIN_STATE_PATH
    return module


LOGIN_HELPER = load_login_helper()


async def index(request: web.Request) -> web.Response:
    session = _load_json(SESSION_PATH)
    state = _load_json(LOGIN_STATE_PATH)
    host = _safe_host(request.query.get("host", session.get("host") or DEFAULT_ALEXA_HOST))
    login_url = f"/auth/login?host={urllib.parse.quote(host)}"

    session_status = "vorhanden" if session.get("cookie") and session.get("csrf") else "nicht vorhanden"
    last_host = html.escape(str(session.get("host") or "—"))
    state_retail_url = html.escape(str(state.get("retailUrl") or "—"))
    state_website_api_url = html.escape(str(state.get("websiteApiUrl") or "—"))

    body = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Standalone Alexa Test App</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; padding: 32px; background: #f5f6fa; }}
    .card {{ max-width: 920px; margin: 0 auto; background: white; border-radius: 14px; padding: 28px; box-shadow: 0 8px 30px rgba(0,0,0,.10); }}
    .btn {{ display: inline-block; padding: 12px 18px; border-radius: 8px; background: #00a8e8; color: white; text-decoration: none; font-weight: 700; }}
    code {{ background: #f1f2f6; padding: 2px 5px; border-radius: 4px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 18px; }}
    td {{ border-top: 1px solid #ddd; padding: 8px; vertical-align: top; }}
    td:first-child {{ font-weight: 700; width: 220px; }}
    .warn {{ color: #9a6700; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Standalone Alexa Test App</h1>
    <p>Diese App läuft ohne Home Assistant Ingress, ohne Panel-Iframe und ohne HA-URL-Umschreibung.</p>
    <p><a class="btn" href="{html.escape(login_url)}">Alexa-App-Login starten</a></p>
    <p class="warn">Testziel: Prüfen, ob der Amazon-App-Login-Pfad grundsätzlich funktioniert.</p>

    <table>
      <tr><td>Login-Route</td><td><code>/auth/alexa-app/...</code></td></tr>
      <tr><td>Alexa Host</td><td><code>{html.escape(host)}</code></td></tr>
      <tr><td>Session</td><td>{html.escape(session_status)}</td></tr>
      <tr><td>Session Host</td><td>{last_host}</td></tr>
      <tr><td>Retail URL</td><td>{state_retail_url}</td></tr>
      <tr><td>Website API URL</td><td>{state_website_api_url}</td></tr>
      <tr><td>Session-Datei</td><td><code>{html.escape(str(SESSION_PATH))}</code></td></tr>
    </table>
  </div>
</body>
</html>"""
    return web.Response(text=body, content_type="text/html")


async def auth_login(request: web.Request) -> web.StreamResponse:
    host = _safe_host(request.query.get("host", DEFAULT_ALEXA_HOST))
    raise web.HTTPFound(f"/auth/alexa-app/start?host={urllib.parse.quote(host)}")


async def session_status(request: web.Request) -> web.Response:
    session = _load_json(SESSION_PATH)
    safe_session = {
        "configured": bool(session.get("cookie") and session.get("csrf")),
        "host": session.get("host"),
        "createdAt": session.get("createdAt"),
        "loginMode": session.get("loginMode"),
        "hasCookie": bool(session.get("cookie")),
        "hasCsrf": bool(session.get("csrf")),
        "hasRefreshToken": bool(session.get("refreshToken")),
    }
    return web.json_response(safe_session)


def create_app() -> web.Application:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/auth/login", auth_login)
    app.router.add_get("/api/session", session_status)
    LOGIN_HELPER.setup_routes(app)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8099"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
