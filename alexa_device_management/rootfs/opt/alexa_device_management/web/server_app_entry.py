"""Entrypoint with Alexa App route names and host-aware forwarding."""

from __future__ import annotations

import pathlib
import sys
import types

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


def _patch_login_source(source: str) -> str:
    import server_patched_entry as legacy_entry

    source = legacy_entry._fix_alexa_openhab_login_source(source)
    source = source.replace("/auth/alexa-openhab", "/auth/alexa-app")

    source = source.replace(
        'local_path = "/" + "auth" + "/alexa-app/FORWARD" + parsed_login_url.path',
        'local_path = "/" + "auth" + "/alexa-app/FORWARD/" + parsed_login_url.netloc + parsed_login_url.path',
        1,
    )

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

    return source.replace(old_target, new_target, 1)


def main() -> None:
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))

    import server_patched_entry as legacy_entry

    login_source = _patch_login_source(ALEXA_LOGIN_SOURCE.read_text())
    login_module = _load_module("alexa_app_login", ALEXA_LOGIN_SOURCE, login_source)
    sys.modules["alexa_openhab_login"] = login_module
    legacy_entry._install_login_url_builder(login_module)

    server_source = legacy_entry._fix_server_source(PATCHED_SERVER.read_text())
    server_source = server_source.replace("alexa_openhab_login", "alexa_app_login")

    globals_dict = {
        "__name__": "__main__",
        "__file__": str(PATCHED_SERVER),
        "__package__": None,
        "__cached__": None,
    }
    exec(compile(server_source, str(PATCHED_SERVER), "exec"), globals_dict)


if __name__ == "__main__":
    main()
