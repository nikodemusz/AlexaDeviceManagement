"""OpenHAB-style Alexa login for the Home Assistant OS app.

This module intentionally follows the current openHAB Amazon Echo Control flow
(see Connection.java's registerConnectionAsApp/exchangeToken/getLoginPage):

1. start at https://www.amazon.com/ap/signin with device_auth_access — this is
   hardcoded to amazon.com for every account, EU included; it is not a
   marketplace picker
2. intercept the /ap/maplanding access token
3. call https://api.amazon.com/auth/register (also always amazon.com)
4. exchange the refresh token for website cookies via /ap/exchangetoken,
   which is likewise always requested against amazon.com — only the
   *requested cookie domain* inside the payload changes
5. call https://alexa.amazon.com/api/users/me (always amazon.com) to learn
   the account's real marketplace, then exchange cookies for that domain and
   discover its endpoints

It does not use a user-provided LWA client_id/client_secret/refresh_token.
"""

from __future__ import annotations

import base64
import html
import json
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

SESSION_PATH = pathlib.Path("/data/alexa_session.json")
STATE_PATH = pathlib.Path("/data/alexa_login_state.json")

API_VERSION = "2.2.556530.0"
DI_OS_VERSION = "16.6"
DI_SDK_VERSION = "6.12.4"
DEVICE_TYPE = "A2IVLV5VM2W81"
DEFAULT_RETAIL_DOMAIN = "amazon.com"
DEFAULT_RETAIL_URL = "https://www.amazon.com"
DEFAULT_ALEXA_API = "https://alexa.amazon.com"
AMAZON_PROXY_HOSTS = (
    "www.amazon.com",
    "amazon.com",
    "www.amazon.de",
    "amazon.de",
    "www.amazon.co.uk",
    "www.amazon.fr",
    "www.amazon.it",
    "www.amazon.es",
    "images-na.ssl-images-amazon.com",
    "m.media-amazon.com",
    "m.media-amazon.de",
    "images-eu.ssl-images-amazon.com",
    "fls-na.amazon.com",
    "fls-eu.amazon.com",
    "completion.amazon.com",
    "completion.amazon.de",
    "unagi-na.amazon.com",
    "unagi-eu.amazon.com",
    "api.amazon.com",
    "ap.amazon.com",
)


def read_json(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_host(value: str | None) -> str:
    host = (value or "").strip().lower()
    host = host.removeprefix("https://").removeprefix("http://").split("/")[0]
    if not re.fullmatch(r"[a-z0-9.-]+", host):
        return DEFAULT_RETAIL_DOMAIN
    return host


def external_url(request: web.Request, path: str) -> str:
    ingress_path = request.headers.get("X-Ingress-Path", "")
    if not re.match(r"^[a-zA-Z0-9/_-]*$", ingress_path):
        ingress_path = ""
    host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host", "")
    proto = request.headers.get("X-Forwarded-Proto") or "https"
    if host:
        return f"{proto}://{host}{ingress_path.rstrip('/')}{path}"
    return f"{ingress_path.rstrip('/')}{path}"


def proxied_url(request: web.Request, target_url: str, default_host: str = "www.amazon.com") -> str:
    parsed = URL(target_url)
    if parsed.host:
        host = safe_host(parsed.host)
        path = parsed.raw_path or "/"
        query = parsed.raw_query_string
    else:
        host = default_host
        path = target_url if target_url.startswith("/") else "/" + target_url
        query = ""
    local = f"/alexa-auth/proxy/{host}{path}"
    if query:
        local += "?" + query
    return external_url(request, local)


def csrf_from_cookie(cookie_header: str) -> str:
    match = re.search(r"(?:^|;\s*)csrf=([^;]+)", cookie_header or "")
    return match.group(1) if match else ""


def new_state() -> dict[str, Any]:
    serial = secrets.token_hex(16)
    device_identity = f"{secrets.token_hex(16).upper()}#{DEVICE_TYPE}"
    device_id = device_identity.encode().hex()
    frc = base64.b64encode(os.urandom(313)).decode()
    state = {
        "frc": frc,
        "serial": serial,
        "deviceId": device_id,
        "deviceType": DEVICE_TYPE,
        "refreshToken": "",
        "retailDomain": DEFAULT_RETAIL_DOMAIN,
        "retailUrl": DEFAULT_RETAIL_URL,
        "websiteApiUrl": DEFAULT_ALEXA_API,
        "createdAt": int(time.time()),
    }
    write_json(STATE_PATH, state)
    return state


def build_openhab_login_url(state: dict[str, Any]) -> str:
    params = {
        "openid.return_to": DEFAULT_RETAIL_URL + "/ap/maplanding",
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
    return DEFAULT_RETAIL_URL + "/ap/signin?" + urllib.parse.urlencode(params)


async def proxy_session(app: web.Application) -> aiohttp.ClientSession:
    session = app.get("oh_alexa_session")
    if session is None or session.closed:
        session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
        app["oh_alexa_session"] = session
    return session


async def reset_proxy_session(app: web.Application) -> aiohttp.ClientSession:
    old = app.get("oh_alexa_session")
    if old is not None and not old.closed:
        await old.close()
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
    app["oh_alexa_session"] = session
    return session


def seed_login_cookies(session: aiohttp.ClientSession, state: dict[str, Any]) -> None:
    map_md_json = json.dumps({"device_user_dictionary": [], "device_registration_data": {"software_version": "1"}, "app_identifier": {"app_version": API_VERSION, "bundle_id": "com.amazon.echo"}}, separators=(",", ":"))
    session.cookie_jar.update_cookies(
        {
            "map-md": base64.b64encode(map_md_json.encode()).decode(),
            "frc": state["frc"],
        },
        response_url=URL(DEFAULT_RETAIL_URL),
    )


def cookie_header_for(session: aiohttp.ClientSession, url: str) -> str:
    cookies = session.cookie_jar.filter_cookies(URL(url))
    return "; ".join(f"{k}={m.value}" for k, m in cookies.items())


def amazon_cookies_for_register(session: aiohttp.ClientSession) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for name, morsel in session.cookie_jar.filter_cookies(URL(DEFAULT_RETAIL_URL)).items():
        result.append({"Name": name, "Value": morsel.value, "Path": morsel["path"] or "/", "Secure": "true", "HttpOnly": "false"})
    return result


def add_exchange_cookie(session: aiohttp.ClientSession, domain: str, item: dict[str, Any]) -> None:
    name = item.get("Name") or item.get("name")
    value = item.get("Value") or item.get("value")
    if not name or value is None:
        return
    cookie_domain = domain
    cookie_path = item.get("Path") or item.get("path") or "/"
    simple = SimpleCookie()
    simple[str(name)] = str(value)
    morsel = simple[str(name)]
    morsel["domain"] = str(cookie_domain)
    morsel["path"] = str(cookie_path)
    if str(item.get("Secure") or item.get("secure")).lower() in {"true", "1", "yes"}:
        morsel["secure"] = True
    session.cookie_jar.update_cookies(simple, response_url=URL("https://" + str(cookie_domain).lstrip(".")))


async def exchange_token(session: aiohttp.ClientSession, state: dict[str, Any], cookie_domain: str) -> dict[str, Any]:
    cookies_json = json.dumps({"cookies": {"." + cookie_domain: []}}, separators=(",", ":"))
    cookies_base64 = base64.b64encode(cookies_json.encode()).decode()
    form = {
        "di.os.name": "iOS",
        "app_version": API_VERSION,
        "domain": "." + state.get("retailDomain", DEFAULT_RETAIL_DOMAIN),
        "source_token": state["refreshToken"],
        "requested_token_type": "auth_cookies",
        "source_token_type": "refresh_token",
        "di.hw.version": "iPhone",
        "di.sdk.version": DI_SDK_VERSION,
        "cookies": cookies_base64,
        "app_name": "Amazon Alexa",
        "di.os.version": DI_OS_VERSION,
    }
    async with session.post(state.get("retailUrl", DEFAULT_RETAIL_URL).rstrip("/") + "/ap/exchangetoken", data=form, headers={"Cookie": ""}, allow_redirects=False) as resp:
        text = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"Token exchange failed ({resp.status}): {text[:200]}")
        body = json.loads(text)
    token_cookies = body.get("response", {}).get("tokens", {}).get("cookies", {})
    added: list[str] = []
    for domain, cookies in token_cookies.items():
        for cookie in cookies:
            name = cookie.get("Name") or cookie.get("name")
            if name:
                added.append(f"{domain}:{name}")
            add_exchange_cookie(session, domain, cookie)
    return {
        "requested_domain": cookie_domain,
        "response_len": len(text),
        "returned_domains": list(token_cookies.keys()),
        "added_cookies": added,
    }


async def outbound_ip(session: aiohttp.ClientSession) -> str:
    try:
        async with session.get("https://api.ipify.org?format=json", timeout=aiohttp.ClientTimeout(total=5)) as resp:
            body = await resp.json()
            return body.get("ip", "unknown")
    except Exception:
        return "unknown"


TLS_IMPERSONATE = "safari18_4_ios"

_DIAG_HEADER_KEYS = {
    "server", "via", "x-amzn-requestid", "x-amzn-errortype", "x-cache",
    "x-amz-cf-id", "x-amz-cf-pop", "www-authenticate", "content-type",
}


async def impersonated_request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    allow_redirects: bool = False,
) -> tuple[int, str]:
    """Make an Alexa app-API request with a real iOS TLS fingerprint.

    Amazon's CloudFront edge fingerprints the TLS ClientHello of
    alexa.amazon.com/api/* callers and rejects non-app clients (Python/
    aiohttp) with an empty-body 401 even when the auth cookies are valid.
    curl_cffi impersonates a genuine iOS Safari handshake so the stored
    session cookies are accepted. Returns (status_code, text).
    """
    from curl_cffi.requests import AsyncSession as CurlSession

    async with CurlSession(impersonate=TLS_IMPERSONATE) as cs:
        resp = await cs.request(method, url, headers=headers, data=data, allow_redirects=allow_redirects)
        return resp.status_code, resp.text


async def get_json(session: aiohttp.ClientSession, url: str) -> dict[str, Any]:
    """Fetch a JSON app-API endpoint using a real-iOS TLS fingerprint.

    Amazon's edge (CloudFront) fingerprints the TLS ClientHello of
    alexa.amazon.com/api/* callers and rejects non-app clients such as
    Python/aiohttp with an empty-body 401 even when the auth cookies are
    valid. curl_cffi impersonates a genuine iOS Safari TLS handshake, so the
    cookies we already obtained are accepted. Cookies still come from the
    aiohttp jar (populated by the login proxy + token exchange) and are
    passed explicitly, since this curl session has no jar of its own.
    """
    from curl_cffi.requests import AsyncSession as CurlSession

    cookie = cookie_header_for(session, url)
    csrf = csrf_from_cookie(cookie)
    headers = {
        "User-Agent": f"AmazonWebView/Amazon Alexa/{API_VERSION}/iOS/{DI_OS_VERSION}/iPhone",
        "Accept-Language": "en-US",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
        "Cookie": cookie,
    }
    if csrf:
        headers["csrf"] = csrf
    async with CurlSession(impersonate=TLS_IMPERSONATE) as cs:
        resp = await cs.get(url, headers=headers, allow_redirects=False)
        text = resp.text
        status = resp.status_code
        resp_headers = resp.headers
    if status != 200:
        cookie_names = [c.split("=", 1)[0].strip() for c in cookie.split(";") if c.strip()]
        diag_headers = {k: v for k, v in resp_headers.items() if k.lower() in _DIAG_HEADER_KEYS}
        ip = await outbound_ip(session)
        raise RuntimeError(
            f"GET {url} failed ({status}): {text[:200]} "
            f"[tls={TLS_IMPERSONATE}, outbound_ip={ip}, csrf={'yes' if csrf else 'no'}, "
            f"cookies={cookie_names}, headers={diag_headers}]"
        )
    return json.loads(text)


async def register_app(session: aiohttp.ClientSession, state: dict[str, Any], access_token: str) -> dict[str, Any]:
    payload = {
        "requested_extensions": ["device_info", "customer_info"],
        "cookies": {"website_cookies": amazon_cookies_for_register(session), "domain": "." + DEFAULT_RETAIL_DOMAIN},
        "registration_data": {
            "domain": "Device",
            "app_version": API_VERSION,
            "device_type": DEVICE_TYPE,
            "device_name": "%FIRST_NAME%'s%DUPE_STRATEGY_1ST%Alexa Device Management",
            "os_version": DI_OS_VERSION,
            "device_serial": state["serial"],
            "device_model": "iPhone",
            "app_name": "Amazon Alexa",
            "software_version": "1",
        },
        "auth_data": {"access_token": access_token},
        "user_context_map": {"frc": state["frc"]},
        "requested_token_type": ["bearer", "mac_dms", "website_cookies"],
    }
    async with session.post("https://api.amazon.com/auth/register", json=payload, headers={"x-amzn-identity-auth-domain": "api.amazon.com"}, allow_redirects=False) as resp:
        text = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"App registration failed ({resp.status}): {text[:200]}")
        body = json.loads(text)
    success = body.get("response", {}).get("success") or body.get("success") or {}
    bearer = (success.get("tokens") or {}).get("bearer") or {}
    refresh_token = bearer.get("refresh_token") or bearer.get("refreshToken")
    if not refresh_token:
        raise RuntimeError("No refresh token from app registration")
    state["refreshToken"] = refresh_token
    write_json(STATE_PATH, state)

    exchange_summary = await exchange_token(session, state, state.get("retailDomain", DEFAULT_RETAIL_DOMAIN))
    try:
        users_me = await get_json(session, DEFAULT_ALEXA_API + "/api/users/me?platform=ios&version=" + API_VERSION)
    except RuntimeError as exc:
        current_ip = await outbound_ip(session)
        start_ip = state.get("startIp", "unknown")
        raise RuntimeError(
            f"{exc} [start_ip={start_ip}, ip_at_failure={current_ip}, ip_changed={start_ip != current_ip}, "
            f"exchange={exchange_summary}]"
        ) from exc
    marketplace = users_me.get("marketPlaceDomainName") or state.get("retailDomain", DEFAULT_RETAIL_DOMAIN)
    marketplace = safe_host(marketplace)
    await exchange_token(session, state, marketplace)
    endpoints = await get_json(session, DEFAULT_ALEXA_API + "/api/endpoints")

    state["retailDomain"] = safe_host(endpoints.get("retailDomain") or marketplace)
    state["retailUrl"] = endpoints.get("retailUrl") or ("https://www." + state["retailDomain"])
    state["websiteApiUrl"] = endpoints.get("websiteApiUrl") or ("https://alexa." + state["retailDomain"])

    api_url = state["websiteApiUrl"]
    cookie = cookie_header_for(session, api_url)
    csrf = csrf_from_cookie(cookie)
    session_data = {
        "host": safe_host(URL(api_url).host or "alexa.amazon.com"),
        "cookie": cookie,
        "csrf": csrf,
        "refreshToken": refresh_token,
        "retailDomain": state["retailDomain"],
        "retailUrl": state["retailUrl"],
        "websiteApiUrl": api_url,
        "createdAt": int(time.time()),
        "loginMode": "openhab_style_app_registration",
    }
    write_json(SESSION_PATH, session_data)
    write_json(STATE_PATH, state)
    return session_data


def result_page(success: bool, message: str) -> web.Response:
    title = "Alexa login successful" if success else "Alexa login failed"
    icon = "✅" if success else "❌"
    body = f"""<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title></head><body style='font-family:system-ui;padding:32px'><h1>{icon} {html.escape(title)}</h1><p>{html.escape(message)}</p><p><a href='/'>Back to app</a></p></body></html>"""
    return web.Response(text=body, content_type="text/html")


def extract_access_token(location: str) -> str:
    parsed = urllib.parse.urlparse(location)
    params = urllib.parse.parse_qs(parsed.query)
    token = params.get("openid.oa2.access_token", [None])[0]
    if token:
        return token
    return urllib.parse.parse_qs(parsed.fragment).get("openid.oa2.access_token", [""])[0]


async def start(request: web.Request) -> web.StreamResponse:
    session = await reset_proxy_session(request.app)
    state = new_state()
    state["startIp"] = await outbound_ip(session)
    write_json(STATE_PATH, state)
    seed_login_cookies(session, state)
    login_url = URL(build_openhab_login_url(state))
    raise web.HTTPFound(proxied_url(request, str(login_url)))


async def handle_redirect(request: web.Request, session: aiohttp.ClientSession, location: str, state: dict[str, Any], current_host: str) -> web.StreamResponse:
    if "/ap/maplanding" in location:
        token = extract_access_token(location)
        if not token:
            return result_page(False, "Access token not found in maplanding redirect")
        try:
            data = await register_app(session, state, token)
            return result_page(True, f"Session stored for {data.get('host', 'Alexa')}")
        except Exception as exc:
            return result_page(False, str(exc))
    raise web.HTTPFound(proxied_url(request, location, current_host))


def rewrite_html(request: web.Request, text: str, current_host: str = "www.amazon.com") -> str:
    result = text

    def repl_absolute(match: re.Match[str]) -> str:
        quote, scheme, host, path = match.groups()
        return f"={quote}{proxied_url(request, scheme + '://' + host + path)}"

    result = re.sub(
        r"=([\"'])(https?)://([a-z0-9.-]+)((?:/|&#x2F;)[^\"']*)",
        repl_absolute,
        result,
        flags=re.I,
    )

    def repl_protocol_relative(match: re.Match[str]) -> str:
        quote, host, path = match.groups()
        return f"={quote}{proxied_url(request, 'https://' + host + path)}"

    result = re.sub(
        r"=([\"'])//([a-z0-9.-]+)((?:/|&#x2F;)[^\"']*)",
        repl_protocol_relative,
        result,
        flags=re.I,
    )

    local_root = external_url(request, f"/alexa-auth/proxy/{current_host}/")

    def repl_relative_path(m: re.Match[str]) -> str:
        quote, rest = m.group(1), m.group(2)
        if "/alexa-auth/proxy/" in rest:
            return m.group(0)
        return f"={quote}{local_root}{rest}"

    result = re.sub(r"=([\"'])/(?!/)([^\"']*)", repl_relative_path, result)
    result = re.sub(r"=([\"'])&#x2F;([^\"']*)", repl_relative_path, result)

    for host in AMAZON_PROXY_HOSTS:
        root = external_url(request, f"/alexa-auth/proxy/{host}/")
        result = result.replace(f"https://{host}/", root)
        result = result.replace(f"http://{host}/", root)
        result = result.replace(f"https://{host}:443/", root)
        result = result.replace(f"https:\\/\\/{host}\\/", root)
        result = result.replace(f"https:&#x2F;&#x2F;{host}&#x2F;", root)
        result = result.replace(f"https:&#x2F;&#x2F;{host}:443&#x2F;", root)

    return result


async def proxy(request: web.Request) -> web.StreamResponse:
    tail = request.match_info.get("tail", "")
    if tail in {"", "start"}:
        return await start(request)
    state = read_json(STATE_PATH)
    if not state:
        return result_page(False, "Login state missing. Start login again.")
    if not tail.startswith("proxy/"):
        return web.Response(text="Invalid auth path", status=400)
    forward = tail[len("proxy/"):]
    host, sep, path = forward.partition("/")
    if not sep or not re.fullmatch(r"[a-z0-9.-]+", host):
        return web.Response(text="Invalid proxy target", status=400)
    target = "https://" + host + "/" + path
    if request.query_string:
        target += "?" + request.query_string
    session = await proxy_session(request.app)
    headers = {
        "User-Agent": f"AmazonWebView/Amazon Alexa/{API_VERSION}/iOS/{DI_OS_VERSION}/iPhone",
        "Accept": request.headers.get("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        "Accept-Language": request.headers.get("Accept-Language", "en-US,en;q=0.8"),
        "Referer": proxied_url(request, "https://" + host + "/"),
    }
    if request.headers.get("Origin"):
        headers["Origin"] = "https://" + host
    body = None
    if request.method in {"POST", "PUT", "PATCH"}:
        body = await request.read()
        if request.headers.get("Content-Type"):
            headers["Content-Type"] = request.headers["Content-Type"]
    async with session.request(request.method, target, data=body, headers=headers, allow_redirects=False) as resp:
        content = await resp.read()
        location = resp.headers.get("Location")
        content_type = resp.headers.get("Content-Type", "text/html")
        status = resp.status
    if status in {301, 302, 303, 307, 308} and location:
        return await handle_redirect(request, session, location, state, host)
    if "text/html" in content_type:
        return web.Response(text=rewrite_html(request, content.decode(errors="replace"), host), content_type="text/html", charset="utf-8", status=status)
    return web.Response(body=content, status=status, content_type=content_type.split(";")[0] or "application/octet-stream")


async def cleanup(app: web.Application) -> None:
    session = app.get("oh_alexa_session")
    if session is not None and not session.closed:
        await session.close()


def setup_routes(app: web.Application) -> None:
    app.router.add_route("*", "/alexa-auth/{tail:.*}", proxy)
    app.on_cleanup.append(cleanup)
