"""Safe entrypoint for the Alexa Web discovery patched server.

This keeps the add-on startable even if the generated patched source contains
small merge/typing artifacts. The current known artifact is a stray ``f`` after
``return web.json_response(...)`` in ``server_patched.py``.
"""

from __future__ import annotations

import pathlib
import runpy

PATCHED_SERVER = pathlib.Path(__file__).with_name("server_patched.py")


def main() -> None:
    source = PATCHED_SERVER.read_text()
    fixed_source = source.replace("    )f\n\n\nasync def handle_alexa_web_session_get", "    )\n\n\nasync def handle_alexa_web_session_get", 1)

    globals_dict = {
        "__name__": "__main__",
        "__file__": str(PATCHED_SERVER),
        "__package__": None,
        "__cached__": None,
    }
    exec(compile(fixed_source, str(PATCHED_SERVER), "exec"), globals_dict)


if __name__ == "__main__":
    main()
