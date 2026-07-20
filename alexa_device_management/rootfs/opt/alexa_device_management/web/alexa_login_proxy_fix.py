"""Runtime fixes for the Amazon Alexa login proxy."""

from __future__ import annotations

from urllib.parse import urljoin

from aiohttp import web
from yarl import URL

import oh_style_login


def _result_page(request: web.Request, success: bool, message: str) -> web.Response:
    title = "Alexa login successful" if success else "Alexa login failed"
    icon = "✅" if success else "❌"
    app_url = oh_style_login.external_url(request, "/")
    import html
    body = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title></head>"
        "<body style='font-family:system-ui;padding:32px'>"
        f"<h1>{icon} {html.escape(title)}</h1>"
        f"<p>{html.escape(message)}</p>"
        f"<p><a href='{html.escape(app_url, quote=True)}'>Back to app</a></p>"
        "</body></html>"
    )
    return web.Response(text=body, content_type="text/html")


async def _proxy(request: web.Request) -> web.StreamResponse:
    tail = request.match_info.get("tail", "")
    if tail in {"", "start"}:
        return await oh_style_login.start(request)

    state = oh_style_login.read_json(oh_style_login.STATE_PATH)
    if not state:
        return _result_page(request, False, "Login state missing. Start login again.")
    if not tail.startswith("proxy/"):
        return web.Response(text="Invalid auth path", status=400)

    forward = tail[len("proxy/"):]
    host, sep, path = forward.partition("/")
    if not sep or not oh_style_login.re.fullmatch(r"[a-z0-9.-]+", host):
        return web.Response(text="Invalid proxy target", status=400)

    target = "https://" + host + "/" + path
    if request.query_string:
        target += "?" + request.query_string

    session = await oh_style_login.proxy_session(request.app)
    target_url = URL(target)
    headers = {
        "User-Agent": f"AmazonWebView/Amazon Alexa/{oh_style_login.API_VERSION}/iOS/{oh_style_login.DI_OS_VERSION}/iPhone",
        "Accept": request.headers.get("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        "Accept-Language": request.headers.get("Accept-Language", "de-DE,de;q=0.9,en;q=0.8"),
        # Amazon must receive an Amazon URL here, never the Home Assistant ingress URL.
        "Referer": str(target_url.with_query(None)),
    }
    if request.headers.get("Origin"):
        headers["Origin"] = f"{target_url.scheme}://{target_url.host}"

    body = None
    if request.method in {"POST", "PUT", "PATCH"}:
        body = await request.read()
        content_type = request.headers.get("Content-Type")
        if content_type:
            headers["Content-Type"] = content_type

    async with session.request(
        request.method,
        target,
        data=body,
        headers=headers,
        allow_redirects=False,
    ) as response:
        content = await response.read()
        location = response.headers.get("Location")
        content_type = response.headers.get("Content-Type", "text/html")
        status = response.status

    if status in {301, 302, 303, 307, 308} and location:
        # Amazon increasingly returns relative redirects. Resolve them against the
        # actual request URL instead of incorrectly falling back to www.amazon.com.
        resolved = urljoin(target, location)
        if "/ap/maplanding" in resolved:
            token = oh_style_login.extract_access_token(resolved)
            if not token:
                return _result_page(request, False, "Access token not found in maplanding redirect")
            try:
                data = await oh_style_login.register_app(session, state, token)
                return _result_page(request, True, f"Session stored for {data.get('host', 'Alexa')}")
            except Exception as exc:
                return _result_page(request, False, str(exc))
        raise web.HTTPFound(oh_style_login.proxied_url(request, resolved))

    if "text/html" in content_type:
        text = content.decode(errors="replace")
        return web.Response(
            text=oh_style_login.rewrite_html(request, text, host),
            content_type="text/html",
            charset="utf-8",
            status=status,
        )
    return web.Response(
        body=content,
        status=status,
        content_type=content_type.split(";", 1)[0] or "application/octet-stream",
    )


def install() -> None:
    oh_style_login.proxy = _proxy
