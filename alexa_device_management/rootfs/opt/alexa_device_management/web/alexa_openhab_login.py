Local-only login proxy:
- creates an app-like Amazon device identity
- starts the device_auth_access flow
- registers the app session
- exchanges the refresh token for Alexa web cookies
- stores the resulting Alexa web session in /data/alexa_web_session.json

Do not log cookies, tokens or passwords.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import os
import pathlib
import re
import secrets
import time
import urllib.parse
from http.cookies import SimpleCookie
from typing import Any

import aiohttp
from aiohttp import web
from yarl import URL

_LOGGER = logging.getLogger(__name__)

SESSION_PATH = pathlib.Path("/data/alexa_web_session.json")
LOGIN_STATE_PATH = pathlib.Path("/data/alexa_web_login_state.json")

APP_VERSION = "2.2.556530.0"
DI_OS_VERSION = "16.6"
DI_SDK_VERSION = "6.12.4"
DEVICE_TYPE = "A2IVLV5VM2W81"

DEFAULTS_BY_ALEXA_HOST: dict[str, dict[str, str]] = {
    "alexa.amazon.de": {
        "retailDomain": "amazon.de",
        "retailUrl": "https://www.amazon.de",
        "websiteApiUrl": "https://alexa.amazon.de",
    },
    "alexa.amazon.com": {
        "retailDomain": "amazon.com",
        "retailUrl": "https://www.amazon.com",
        "websiteApiUrl": "https://alexa.amazon.com",
    },
    "alexa.amazon.co.jp": {
        "retailDomain": "amazon.co.jp",
        "retailUrl": "https://www.amazon.co.jp",
        "websiteApiUrl": "https://alexa.amazon.co.jp",
    },
}

FALLBACK_DEFAULTS = DEFAULTS_BY_ALEXA_HOST["alexa.amazon.de"]


def safe_host(value: str) -> str:
    host = (value or "").strip().lower()
    host = host.removeprefix("https://").removeprefix("http://").split("/")[0]

    if not re.fullmatch(r"[a-z0-9.-]+", host):
        return ""

    return host


def read_json(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def csrf_from_cookie_header(cookie: str) -> str:
    match = re.search(r"(?:^|;\s*)csrf=([^;]+)", cookie or "")
    return match.group(1) if match else ""


def external_url(request: web.Request, path: str) -> str:
    ingress_path = request.headers.get("X-Ingress-Path", "")

    if not re.match(r"^[a-zA-Z0-9/_-]*$", ingress_path):
        ingress_path = ""

    host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host", "")
    proto = request.headers.get("X-Forwarded-Proto", "https")

    if not path.startswith("/"):
        path = "/" + path

    if host:
        return f"{proto}://{host}{ingress_path.rstrip('/')}{path}"

    return f"{ingress_path.rstrip('/')}{path}"


def defaults_for_host(host: str) -> dict[str, str]:
    host = safe_host(host)
    return DEFAULTS_BY_ALEXA_HOST.get(host, FALLBACK_DEFAULTS).copy()


def new_login_state(alexa_host: str) -> dict[str, Any]:
    defaults = defaults_for_host(alexa_host)

    serial = secrets.token_hex(16)
    device_identity = f"{secrets.token_hex(16).upper()}#{DEVICE_TYPE}"
    device_id = device_identity.encode().hex()

    state = {
        "frc": base64.b64encode(os.urandom(313)).decode(),
        "serial": serial,
        "deviceId": device_id,
        "deviceType": DEVICE_TYPE,
        "alexaHost": safe_host(alexa_host) or "alexa.amazon.de",
        "retailDomain": defaults["retailDomain"],
        "retailUrl": defaults["retailUrl"],
        "websiteApiUrl": defaults["websiteApiUrl"],
        "createdAt": int(time.time()),
    }

    write_json(LOGIN_STATE_PATH, state)
    return state


def build_login_url(state: dict[str, Any]) -> str:
    retail_url = state.get("retailUrl") or FALLBACK_DEFAULTS["retailUrl"]

    params = {
        "openid.return_to": retail_url.rstrip("/") + "/ap/maplanding",
        "openid.assoc_handle": "amzn_dp_project_dee_ios",
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
        "pageId": "amzn_dp_project_dee_ios",
        "accountStatusPolicy": "P1",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.mode": "checkid_setup",
        "openid.ns.oa2": "http://www.amazon.com/ap/ext/oauth/2",
        "openid.oa2.client_id": "device:" + state["deviceId"],
        "openid.ns.pape": "http://specs.openid.net/extensions/pape/1.0",
        "openid.oa2.response_type": "token",
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.pape.max_auth_age": "0",
        "openid.oa2.scope": "device_auth_access",
    }

    return retail_url.rstrip("/") + "/ap/signin?" + urllib.parse.urlencode(params)


def seed_login_cookies(session: aiohttp.ClientSession, state: dict[str, Any]) -> None:
    map_md_json = (
        '{"device_user_dictionary":[],'
        '"device_registration_data":{"software_version":"1"},'
        '"app_identifier":{"app_version":"2.2.443692","bundle_id":"com.amazon.echo"}}'
    )

    retail_url = state.get("retailUrl") or FALLBACK_DEFAULTS["retailUrl"]

    session.cookie_jar.update_cookies(
        {
            "map-md": base64.b64encode(map_md_json.encode()).decode(),
            "frc": state["frc"],
        },
        response_url=URL(retail_url),
    )


def cookie_header_for_url(session: aiohttp.ClientSession, url: str) -> str:
    cookies = session.cookie_jar.filter_cookies(URL(url))
    return "; ".join(f"{name}={morsel.value}" for name, morsel in cookies.items())


def amazon_cookie_tos(
    session: aiohttp.ClientSession,
    state: dict[str, Any],
) -> list[dict[str, str]]:
    retail_url = state.get("retailUrl") or FALLBACK_DEFAULTS["retailUrl"]

    result: list[dict[str, str]] = []

    for name, morsel in session.cookie_jar.filter_cookies(URL(retail_url)).items():
        result.append(
            {
                "Name": name,
                "Value": morsel.value,
                "Path": morsel["path"] or "/",
                "Secure": "true",
                "HttpOnly": "false",
            }
        )

    return result


def add_exchange_cookie(
    session: aiohttp.ClientSession,
    domain: str,
    item: dict[str, Any],
) -> None:
    name = item.get("Name") or item.get("name")
    value = item.get("Value") or item.get("value")

    if not name or value is None:
        return

    cookie_domain = item.get("Domain") or item.get("domain") or domain or "amazon.de"
    cookie_path = item.get("Path") or item.get("path") or "/"

    simple = SimpleCookie()
    simple[str(name)] = str(value)

    morsel = simple[str(name)]
    morsel["domain"] = str(cookie_domain)
    morsel["path"] = str(cookie_path)

    secure = item.get("Secure") or item.get("secure")
    if str(secure).lower() in {"true", "1", "yes"}:
        morsel["secure"] = True

    response_url = URL("https://" + str(cookie_domain).lstrip("."))
    session.cookie_jar.update_cookies(simple, response_url=response_url)


async def proxy_session(app: web.Application) -> aiohttp.ClientSession:
    session = app.get("alexa_openhab_login_session")

    if session is None or session.closed:
        session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
        app["alexa_openhab_login_session"] = session

    return session


async def reset_proxy_session(app: web.Application) -> aiohttp.ClientSession:
    old = app.get("alexa_openhab_login_session")

    if old is not None and not old.closed:
        await old.close()

    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
    app["alexa_openhab_login_session"] = session

    return session


async def start(request: web.Request) -> web.StreamResponse:
    alexa_host = safe_host(request.query.get("host", "alexa.amazon.de"))

    session = await reset_proxy_session(request.app)
    state = new_login_state(alexa_host)

    seed_login_cookies(session, state)

    login_url = URL(build_login_url(state))
    local_path = "/auth/alexa-openhab/FORWARD" + login_url.path

    if login_url.query_string:
        local_path += "?" + login_url.query_string

    raise web.HTTPFound(external_url(request, local_path))


async def register_app(
    session: aiohttp.ClientSession,
    state: dict[str, Any],
    access_token: str,
) -> dict[str, Any]:
    payload = {
        "requested_extensions": ["device_info", "customer_info"],
        "cookies": {
            "website_cookies": amazon_cookie_tos(session, state),
            "domain": "." + state.get("retailDomain", "amazon.de"),
        },
        "registration_data": {
            "domain": "Device",
            "app_version": APP_VERSION,
            "device_type": DEVICE_TYPE,
            "device_name": "%FIRST_NAME%'s%DUPE_STRATEGY_1ST%Alexa Device Management",
            "os_version": DI_OS_VERSION,
            "device_serial": state["serial"],
            "device_model": "iPhone",
            "app_name": "Alexa Device Management",
            "software_version": "1",
        },
        "auth_data": {
            "access_token": access_token,
        },
        "user_context_map": {
            "frc": state["frc"],
        },
        "requested_token_type": ["bearer", "mac_dms", "website_cookies"],
    }

    async with session.post(
        "https://api.amazon.com/auth/register",
        json=payload,
        headers={"x-amzn-identity-auth-domain": "api.amazon.com"},
        allow_redirects=False,
    ) as resp:
        text = await resp.text()

        if resp.status != 200:
            raise RuntimeError(
                f"App-Registrierung fehlgeschlagen ({resp.status}): {text[:200]}"
            )

        body = json.loads(text)

    success = body.get("response", {}).get("success") or body.get("success") or {}
    bearer = (success.get("tokens") or {}).get("bearer") or {}

    refresh_token = bearer.get("refresh_token") or bearer.get("refreshToken")

    if not refresh_token:
        raise RuntimeError("Kein Refresh-Token aus App-Registrierung erhalten.")

    state["refreshToken"] = refresh_token

    await exchange_for_web_cookies(session, state)
    await detect_endpoints(session, state)

    website_api_url = state.get("websiteApiUrl") or FALLBACK_DEFAULTS["websiteApiUrl"]

    cookie = cookie_header_for_url(session, website_api_url)
    csrf = csrf_from_cookie_header(cookie)

    if not cookie or not csrf:
        raise RuntimeError("Alexa-Web-Cookie oder CSRF konnte nicht ermittelt werden.")

    host = safe_host(URL(website_api_url).host or "alexa.amazon.de")

    session_data = {
        "host": host,
        "cookie": cookie,
        "csrf": csrf,
        "refreshToken": refresh_token,
        "retailDomain": state.get("retailDomain"),
        "retailUrl": state.get("retailUrl"),
        "websiteApiUrl": website_api_url,
        "createdAt": int(time.time()),
        "loginMode": "openhab_style_app_registration",
    }

    write_json(SESSION_PATH, session_data)
    write_json(LOGIN_STATE_PATH, state)

    return session_data


async def exchange_for_web_cookies(
    session: aiohttp.ClientSession,
    state: dict[str, Any],
) -> None:
    retail_domain = state.get("retailDomain") or "amazon.de"
    retail_url = state.get("retailUrl") or FALLBACK_DEFAULTS["retailUrl"]

    cookies_json = json.dumps(
        {"cookies": {f".{retail_domain}": []}},
        separators=(",", ":"),
    )

    form = {
        "di.os.name": "iOS",
        "app_version": APP_VERSION,
        "domain": "." + retail_domain,
        "source_token": state["refreshToken"],
        "requested_token_type": "auth_cookies",
        "source_token_type": "refresh_token",
        "di.hw.version": "iPhone",
        "di.sdk.version": DI_SDK_VERSION,
        "cookies": base64.b64encode(cookies_json.encode()).decode(),
        "app_name": "Amazon Alexa",
        "di.os.version": DI_OS_VERSION,
    }

    async with session.post(
        retail_url.rstrip("/") + "/ap/exchangetoken",
        data=form,
        headers={"Cookie": ""},
        allow_redirects=False,
    ) as resp:
        text = await resp.text()

        if resp.status != 200:
            raise RuntimeError(
                f"Cookie-Austausch fehlgeschlagen ({resp.status}): {text[:200]}"
            )

        body = json.loads(text)

    cookies = body.get("response", {}).get("tokens", {}).get("cookies") or {}

    for domain, items in cookies.items():
        if not isinstance(items, list):
            continue

        for item in items:
            if isinstance(item, dict):
                add_exchange_cookie(session, str(domain), item)


async def detect_endpoints(
    session: aiohttp.ClientSession,
    state: dict[str, Any],
) -> None:
    candidates = [
        state.get("websiteApiUrl") or FALLBACK_DEFAULTS["websiteApiUrl"],
        "https://alexa.amazon.de",
        "https://alexa.amazon.com",
    ]

    for base_url in candidates:
        try:
            async with session.get(
                base_url.rstrip("/") + "/api/endpoints",
                headers={"Accept": "application/json"},
                allow_redirects=False,
            ) as resp:
                if resp.status != 200:
                    continue

                data = await resp.json()

                if data.get("retailDomain"):
                    state["retailDomain"] = (
                        safe_host(data["retailDomain"])
                        or state.get("retailDomain")
                    )

                if data.get("retailUrl"):
                    state["retailUrl"] = str(data["retailUrl"]).rstrip("/")

                if data.get("websiteApiUrl"):
                    state["websiteApiUrl"] = str(data["websiteApiUrl"]).rstrip("/")

                return

        except Exception:
            _LOGGER.debug("Endpoint detection failed for %s", base_url, exc_info=True)


def rewrite_html(
    request: web.Request,
    text: str,
    state: dict[str, Any],
) -> str:
    retail_domain = state.get("retailDomain") or "amazon.de"
    retail_url = state.get("retailUrl") or f"https://www.{retail_domain}"

    local = external_url(request, "/auth/alexa-openhab/FORWARD/")

    replacements = {
        'action="/': f'action="{local}',
        'action="&#x2F;': f'action="{local}',
        retail_url.rstrip("/") + "/": local,
        retail_url.replace("https://", "http://").rstrip("/") + "/": local,
        f"https://www.{retail_domain}/": local,
        f"https://www.{retail_domain}:443/": local,
        f"https:&#x2F;&#x2F;www.{retail_domain}&#x2F;": local,
        f"https:&#x2F;&#x2F;www.{retail_domain}:443&#x2F;": local,
        f"http://www.{retail_domain}/": local,
        f"http:&#x2F;&#x2F;www.{retail_domain}&#x2F;": local,
    }

    result = text

    for src, dst in replacements.items():
        result = result.replace(src, dst)

    return result


def result_page(success: bool, message: str) -> web.Response:
    icon = "✅" if success else "❌"
    title = "Alexa-Login erfolgreich" if success else "Alexa-Login fehlgeschlagen"

    body = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8" />
  <title>{html.escape(title)}</title>
</head>
<body style="font-family:system-ui;padding:32px">
  <h1>{icon} {html.escape(title)}</h1>
  <p>{html.escape(message)}</p>
  <script>
    if (window.opener) {{
      window.opener.postMessage(
        {{ type: 'oauth_callback', success: {str(success).lower()} }},
        window.location.origin
      );
    }}
  </script>
</body>
</html>"""

    return web.Response(text=body, content_type="text/html")


def extract_access_token(location: str) -> str:
    parsed = urllib.parse.urlparse(location)

    params = urllib.parse.parse_qs(parsed.query)
    token = params.get("openid.oa2.access_token", [None])[0]

    if token:
        return token

    fragment_params = urllib.parse.parse_qs(parsed.fragment)
    return fragment_params.get("openid.oa2.access_token", [""])[0] or ""


async def handle_redirect(
    request: web.Request,
    session: aiohttp.ClientSession,
    location: str,
    state: dict[str, Any],
) -> web.StreamResponse:
    retail_url = state.get("retailUrl") or FALLBACK_DEFAULTS["retailUrl"]
    retail_domain = state.get("retailDomain") or "amazon.de"

    if "/ap/maplanding" in location:
        access_token = extract_access_token(location)

        if not access_token:
            return result_page(False, "Access-Token konnte nicht gelesen werden.")

        try:
            data = await register_app(session, state, access_token)
            return result_page(
                True,
                f"Session gespeichert für {data.get('host', 'Alexa')}.",
            )
        except RuntimeError as exc:
            return result_page(False, str(exc))

    if location.startswith(retail_url.rstrip("/") + "/"):
        relative = location[len(retail_url.rstrip("/") + "/") :]
        raise web.HTTPFound(
            external_url(request, "/auth/alexa-openhab/FORWARD/" + relative)
        )

    retail_www = f"https://www.{retail_domain}/"

    if location.startswith(retail_www):
        relative = location[len(retail_www) :]
        raise web.HTTPFound(
            external_url(request, "/auth/alexa-openhab/FORWARD/" + relative)
        )

    if location.startswith("/"):
        raise web.HTTPFound(
            external_url(request, "/auth/alexa-openhab/FORWARD" + location)
        )

    raise web.HTTPFound(location)


async def proxy(request: web.Request) -> web.StreamResponse:
    tail = request.match_info.get("tail", "")

    if tail in {"", "start"}:
        return await start(request)

    state = read_json(LOGIN_STATE_PATH)

    if not state:
        return result_page(False, "Login-Status fehlt. Bitte Login erneut starten.")

    retail_url = state.get("retailUrl") or FALLBACK_DEFAULTS["retailUrl"]
    website_api_url = state.get("websiteApiUrl") or FALLBACK_DEFAULTS["websiteApiUrl"]

    if tail.startswith("FORWARD/"):
        target = retail_url.rstrip("/") + "/" + tail[len("FORWARD/") :]
    elif tail.startswith("PROXY/"):
        target = website_api_url.rstrip("/") + "/" + tail[len("PROXY/") :]
    else:
        return web.Response(text="Ungültiger Proxy-Pfad", status=400)

    if request.query_string:
        target += "?" + request.query_string

    session = await proxy_session(request.app)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
            "AppleWebKit/605.1.15 Mobile/15E148"
        ),
        "Accept": request.headers.get(
            "Accept",
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        ),
        "Accept-Language": request.headers.get(
            "Accept-Language",
            "de-DE,de;q=0.9,en;q=0.8",
        ),
    }

    body = None

    if request.method in {"POST", "PUT", "PATCH"}:
        body = await request.read()

        if request.headers.get("Content-Type"):
            headers["Content-Type"] = request.headers["Content-Type"]

    async with session.request(
        request.method,
        target,
        data=body,
        headers=headers,
        allow_redirects=False,
    ) as resp:
        content = await resp.read()
        location = resp.headers.get("Location")
        content_type = resp.headers.get("Content-Type", "text/html")
        status = resp.status

    if status in {301, 302, 303, 307, 308} and location:
        return await handle_redirect(request, session, location, state)

    if "text/html" in content_type:
        text = content.decode(errors="replace")

        return web.Response(
            text=rewrite_html(request, text, state),
            content_type="text/html",
            charset="utf-8",
            status=status,
        )

    return web.Response(
        body=content,
        status=status,
        content_type=content_type.split(";")[0] or "application/octet-stream",
    )


async def cleanup(app: web.Application) -> None:
    session = app.get("alexa_openhab_login_session")

    if session is not None and not session.closed:
        await session.close()


def setup_routes(app: web.Application) -> None:
    app.router.add_route("*", "/auth/alexa-openhab/{tail:.*}", proxy)
    app.on_cleanup.append(cleanup)
