"""Safe entrypoint for the Alexa Web discovery patched server.

This keeps the add-on startable even if generated patched sources contain
small merge/typing artifacts.
"""

from __future__ import annotations

import pathlib
import sys
import types

BASE_DIR = pathlib.Path(__file__).resolve().parent
PATCHED_SERVER = BASE_DIR / "server_patched.py"
ALEXA_OPENHAB_LOGIN = BASE_DIR / "alexa_openhab_login.py"


def _fix_server_source(source: str) -> str:
    return source.replace(
        "    )f\n\n\nasync def handle_alexa_web_session_get",
        "    )\n\n\nasync def handle_alexa_web_session_get",
        1,
    )


def _fix_alexa_openhab_login_source(source: str) -> str:
    if source.startswith("Local-only login proxy:\n"):
        source = '"""' + source

    old_start = '''async def start(request: web.Request) -> web.StreamResponse:
    alexa_host = safe_host(request.query.get("host", "alexa.amazon.de"))

    session = await reset_proxy_session(request.app)
    state = new_login_state(alexa_host)

    seed_login_cookies(session, state)

    login_url = URL(build_login_url(state))
    local_path = "/auth/alexa-openhab/FORWARD" + login_url.path

    if login_url.query_string:
        local_path += "?" + login_url.query_string

    raise web.HTTPFound(external_url(request, local_path))
'''

    new_start = '''async def start(request: web.Request) -> web.StreamResponse:
    alexa_host = safe_host(request.query.get("host", "alexa.amazon.de"))

    session = await reset_proxy_session(request.app)
    state = new_login_state(alexa_host)

    seed_login_cookies(session, state)

    # Keep Amazon's OpenID query string percent-encoded. yarl.URL.query_string
    # returns a decoded representation, which can break nested URL parameters
    # such as openid.return_to and lead to an Amazon 404 page.
    login_url = build_login_url(state)
    parsed_login_url = urllib.parse.urlsplit(login_url)
    local_path = "/auth/alexa-openhab/FORWARD" + parsed_login_url.path

    if parsed_login_url.query:
        local_path += "?" + parsed_login_url.query

    raise web.HTTPFound(external_url(request, local_path))
'''

    source = source.replace(old_start, new_start, 1)

    old_query_forward_raw = '''    # request.query_string may contain a decoded representation of nested URL
    # parameters. Use request.raw_path to forward Amazon OpenID parameters
    # exactly as the browser sent them to the local ingress proxy.
    raw_query = ""

    if "?" in request.raw_path:
        raw_query = request.raw_path.split("?", 1)[1]

    if raw_query:
        target += "?" + raw_query
'''

    old_query_forward_plain = '''    if request.query_string:
        target += "?" + request.query_string
'''

    new_query_forward = '''    # Home Assistant ingress and aiohttp may expose nested URL parameters in a
    # decoded form. Re-encode all OpenID parameters before forwarding them to
    # Amazon, otherwise Amazon receives values such as
    # openid.return_to=https://www.amazon.de/ap/maplanding and responds with
    # its generic 404 page.
    query_items = []

    for name in request.query:
        for value in request.query.getall(name):
            query_items.append((name, value))

    if query_items:
        target += "?" + urllib.parse.urlencode(query_items, doseq=True)
'''

    if old_query_forward_raw in source:
        return source.replace(old_query_forward_raw, new_query_forward, 1)

    return source.replace(old_query_forward_plain, new_query_forward, 1)


def _load_fixed_module(module_name: str, path: pathlib.Path, source: str) -> types.ModuleType:
    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__cached__ = None
    sys.modules[module_name] = module
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def main() -> None:
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))

    alexa_source = _fix_alexa_openhab_login_source(ALEXA_OPENHAB_LOGIN.read_text())
    _load_fixed_module("alexa_openhab_login", ALEXA_OPENHAB_LOGIN, alexa_source)

    server_source = _fix_server_source(PATCHED_SERVER.read_text())
    globals_dict = {
        "__name__": "__main__",
        "__file__": str(PATCHED_SERVER),
        "__package__": None,
        "__cached__": None,
    }
    exec(compile(server_source, str(PATCHED_SERVER), "exec"), globals_dict)


if __name__ == "__main__":
    main()
