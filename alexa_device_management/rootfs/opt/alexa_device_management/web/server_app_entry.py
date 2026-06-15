"""Entrypoint with Alexa App route names and host-aware forwarding."""

from __future__ import annotations

import pathlib
import re
import sys
import types
import urllib.parse

BASE_DIR = pathlib.Path(__file__).resolve().parent
PATCHED_SERVER = BASE_DIR / "server_patched.py"
ALEXA_LOGIN_SOURCE = BASE_DIR / "alexa_openhab_login.py"


def _load_module(module_name: str, path: pathlib.Path, source: str) -> types.ModuleType:
    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__cached__ = None
    sys.modules[module_name] = module
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def _replace_start(source: str) -> str:
    replacement = '''async def start(request: web.Request) -> web.StreamResponse:
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

    pattern = (
        r"async def start\(request: web\.Request\) -> web\.StreamResponse:\n"
        r".*?\n\nasync def register_app"
    )
    patched, count = re.subn(
        pattern,
        replacement + "\n\nasync def register_app",
        source,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError("Could not patch Alexa app login start()")
    return patched


def _replace_setup_routes(source: str) -> str:
    replacement = '''def setup_routes(app: web.Application) -> None:
    route_key = "/auth/alexa-app/{tail:.*}"
    existing = {
        getattr(resource, "canonical", None)
        for resource in app.router.resources()
    }

    if route_key not in existing:
        app.router.add_route("*", route_key, proxy)

    if cleanup not in app.on_cleanup:
        app.on_cleanup.append(cleanup)
'''

    pattern = (
        r"def setup_routes\(app: web\.Application\) -> None:\n"
        r"(?:    .*\n)+"
    )
    patched, count = re.subn(pattern, replacement, source, count=1)
    if count != 1:
        raise RuntimeError("Could not patch Alexa app login setup_routes()")
    return patched


def _replace_proxy_target(source: str) -> str:
    old_target = '''    if tail.startswith("FORWARD/"):
        target = retail_url.rstrip("/") + "/" + tail[len("FORWARD/") :]
    elif tail.startswith("PROXY/"):
        target = website_api_url.rstrip("/") + "/" + tail[len("PROXY/") :]
    else:
        return web.Response(text="Ungültiger Proxy-Pfad", status=400)
'''

    new_target = '''    if tail.startswith("FORWARD/"):
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
'''

    if old_target in source:
        return source.replace(old_target, new_target, 1)
    return source


def _patch_login_source(source: str) -> str:
    import server_patched_entry as legacy_entry

    source = legacy_entry._fix_alexa_openhab_login_source(source)
    source = _replace_start(source)
    source = _replace_proxy_target(source)
    source = source.replace("/auth/alexa-openhab", "/auth/alexa-app")
    source = _replace_setup_routes(source)
    return source


def _force_amazon_com_openid_namespace(login_url: str) -> str:
    parsed = urllib.parse.urlsplit(login_url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    query["openid.ns.oa2"] = ["http://www.amazon.com/ap/ext/oauth/2"]
    fixed_query = urllib.parse.urlencode(query, doseq=True)
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, fixed_query, parsed.fragment)
    )


def _install_login_url_builder(module: types.ModuleType) -> None:
    import server_patched_entry as legacy_entry

    legacy_entry._install_login_url_builder(module)
    original_builder = module.build_login_url

    def build_login_url(state):
        return _force_amazon_com_openid_namespace(original_builder(state))

    module.build_login_url = build_login_url


def _patch_server_source(source: str) -> str:
    """Make /auth/login a browser navigation endpoint, not a JSON preflight."""
    new_handler = '''async def handle_alexa_web_login(request: web.Request) -> web.Response:
    host, _, _ = _get_alexa_web_options()

    auth_url = _external_url(
        request,
        "/auth/alexa-app/start?host="
        + urllib.parse.quote(host or "alexa.amazon.de"),
    )

    raise web.HTTPFound(auth_url)


async def handle_alexa_web_session_get'''

    pattern = (
        r"async def handle_alexa_web_login\(request: web\.Request\) -> web\.Response:\n"
        r".*?\n\nasync def handle_alexa_web_session_get"
    )
    patched, count = re.subn(pattern, new_handler, source, count=1, flags=re.S)

    if count != 1:
        raise RuntimeError("Could not patch handle_alexa_web_login redirect handler")
    return patched


def main() -> None:
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))

    import server_patched_entry as legacy_entry

    login_source = _patch_login_source(ALEXA_LOGIN_SOURCE.read_text())
    login_module = _load_module("alexa_app_login", ALEXA_LOGIN_SOURCE, login_source)
    sys.modules["alexa_openhab_login"] = login_module
    _install_login_url_builder(login_module)

    server_source = legacy_entry._fix_server_source(PATCHED_SERVER.read_text())
    server_source = server_source.replace("alexa_openhab_login", "alexa_app_login")
    server_source = _patch_server_source(server_source)

    globals_dict = {
        "__name__": "__main__",
        "__file__": str(PATCHED_SERVER),
        "__package__": None,
        "__cached__": None,
    }
    exec(compile(server_source, str(PATCHED_SERVER), "exec"), globals_dict)


if __name__ == "__main__":
    main()
