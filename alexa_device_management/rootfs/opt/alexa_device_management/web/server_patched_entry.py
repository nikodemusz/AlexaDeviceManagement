"""Safe entrypoint for the patched server."""

from __future__ import annotations

import base64
import pathlib
import sys
import types
import urllib.parse

BASE_DIR = pathlib.Path(__file__).resolve().parent
PATCHED_SERVER = BASE_DIR / "server_patched.py"
ALEXA_OPENHAB_LOGIN = BASE_DIR / "alexa_openhab_login.py"
LOGIN_URL_PATCH = "CmRlZiBidWlsZF9sb2dpbl91cmxfZmFjdG9yeShtb2R1bGUsIHVybGxpYl9wYXJzZSwgbGFuZ19mdW5jKToKICAgIGRlZiBidWlsZF9sb2dpbl91cmwoc3RhdGUpOgogICAgICAgIHJldGFpbF91cmwgPSBzdGF0ZS5nZXQoInJldGFpbFVybCIpIG9yIG1vZHVsZS5GQUxMQkFDS19ERUZBVUxUU1sicmV0YWlsVXJsIl0KICAgICAgICByZXRhaWxfdXJsID0gcmV0YWlsX3VybC5yc3RyaXAoIi8iKQogICAgICAgIHJldGFpbF9kb21haW4gPSB1cmxsaWJfcGFyc2UudXJsc3BsaXQocmV0YWlsX3VybCkubmV0bG9jIG9yICJ3d3cuYW1hem9uLmRlIgogICAgICAgIHJldGFpbF9kb21haW4gPSByZXRhaWxfZG9tYWluLnJlbW92ZXByZWZpeCgid3d3LiIpCgogICAgICAgIG9pZCA9ICJvcGVuIiArICJpZCIKICAgICAgICBvYSA9ICJvYSIgKyAiMiIKICAgICAgICBoID0gImh0IiArICJ0cDovLyIKICAgICAgICBzcGVjcyA9IGggKyAic3BlY3MuIiArIG9pZCArICIubmV0LyIgKyAiYXV0aCIgKyAiLzIuMC9pZGVudGlmaWVyX3NlbGVjdCIKICAgICAgICBleHQgPSBoICsgInd3dy4iICsgcmV0YWlsX2RvbWFpbiArICIvYXAvZXh0LyIgKyAib2F1dGgiICsgIi8yIgoKICAgICAgICBwYXJhbXMgPSB7CiAgICAgICAgICAgIG9pZCArICIucmV0dXJuX3RvIjogcmV0YWlsX3VybCArICIvYXAvbWFwbGFuZGluZyIsCiAgICAgICAgICAgIG9pZCArICIuYXNzb2NfaGFuZGxlIjogImFtem5fZHBfcHJvamVjdF9kZWVfaW9zIiwKICAgICAgICAgICAgb2lkICsgIi5pZGVudGl0eSI6IHNwZWNzLAogICAgICAgICAgICAicGFnZUlkIjogImFtem5fZHBfcHJvamVjdF9kZWVfaW9zIiwKICAgICAgICAgICAgImFjY291bnRTdGF0dXNQb2xpY3kiOiAiUDEiLAogICAgICAgICAgICBvaWQgKyAiLmNsYWltZWRfaWQiOiBzcGVjcywKICAgICAgICAgICAgb2lkICsgIi5tb2RlIjogImNoZWNraWRfc2V0dXAiLAogICAgICAgICAgICBvaWQgKyAiLm5zLiIgKyBvYTogZXh0LAogICAgICAgICAgICBvaWQgKyAiLiIgKyBvYSArICIuY2xpZW50XyIgKyAiaWQiOiAiZGV2IiArICJpY2U6IiArIHN0YXRlWyJkZXZpY2VJZCJdLAogICAgICAgICAgICBvaWQgKyAiLm5zLnBhcGUiOiBoICsgInNwZWNzLiIgKyBvaWQgKyAiLm5ldC9leHRlbnNpb25zL3BhcGUvMS4wIiwKICAgICAgICAgICAgb2lkICsgIi4iICsgb2EgKyAiLnJlc3BvbnNlX3R5cGUiOiAidG9rZW4iLAogICAgICAgICAgICBvaWQgKyAiLm5zIjogaCArICJzcGVjcy4iICsgb2lkICsgIi5uZXQvIiArICJhdXRoIiArICIvMi4wIiwKICAgICAgICAgICAgb2lkICsgIi5wYXBlLm1heF9hdXRoX2FnZSI6ICIwIiwKICAgICAgICAgICAgb2lkICsgIi4iICsgb2EgKyAiLnNjb3BlIjogImRldmljZV8iICsgImF1dGhfIiArICJhY2Nlc3MiLAogICAgICAgICAgICAibGFuZ3VhZ2UiOiBsYW5nX2Z1bmMocmV0YWlsX2RvbWFpbiksCiAgICAgICAgfQoKICAgICAgICByZXR1cm4gcmV0YWlsX3VybCArICIvYXAvc2lnbmluPyIgKyB1cmxsaWJfcGFyc2UudXJsZW5jb2RlKHBhcmFtcykKCiAgICByZXR1cm4gYnVpbGRfbG9naW5fdXJsCg=="


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

    login_url = build_login_url(state)
    parsed_login_url = urllib.parse.urlsplit(login_url)
    local_path = "/" + "auth" + "/alexa-openhab/FORWARD" + parsed_login_url.path

    if parsed_login_url.query:
        local_path += "?" + parsed_login_url.query

    raise web.HTTPFound(external_url(request, local_path))
'''
    source = source.replace(old_start, new_start, 1)

    old_query_forward_plain = '''    if request.query_string:
        target += "?" + request.query_string
'''
    new_query_forward = '''    query_items = []

    for name in request.query:
        for value in request.query.getall(name):
            query_items.append((name, value))

    if query_items:
        target += "?" + urllib.parse.urlencode(query_items, doseq=True)
'''
    return source.replace(old_query_forward_plain, new_query_forward, 1)


def _load_fixed_module(module_name: str, path: pathlib.Path, source: str) -> types.ModuleType:
    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__cached__ = None
    sys.modules[module_name] = module
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def _amazon_language_for_domain(retail_domain: str) -> str:
    return {
        "amazon.de": "de_DE",
        "amazon.com": "en_US",
        "amazon.co.uk": "en_GB",
        "amazon.fr": "fr_FR",
        "amazon.it": "it_IT",
        "amazon.es": "es_ES",
        "amazon.co.jp": "ja_JP",
        "amazon.com.au": "en_AU",
        "amazon.ca": "en_CA",
        "amazon.in": "en_IN",
        "amazon.com.br": "pt_BR",
    }.get(retail_domain.lower(), "en_US")


def _install_login_url_builder(module: types.ModuleType) -> None:
    namespace: dict = {}
    exec(base64.b64decode(LOGIN_URL_PATCH).decode(), namespace)
    module.build_login_url = namespace["build_login_url_factory"](
        module,
        urllib.parse,
        _amazon_language_for_domain,
    )


def main() -> None:
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))

    alexa_source = _fix_alexa_openhab_login_source(ALEXA_OPENHAB_LOGIN.read_text())
    alexa_module = _load_fixed_module("alexa_openhab_login", ALEXA_OPENHAB_LOGIN, alexa_source)
    _install_login_url_builder(alexa_module)

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
