"""Extended app entry point with Home Assistant Alexa export manager."""

from __future__ import annotations

from aiohttp import web

import ha_control
import ha_export
import ha_export_overrides
import server_clean

APP_VERSION = "1.5.1"


@web.middleware
async def navigation_middleware(request: web.Request, handler):
    """Inject navigation and page-specific assets into rendered HTML pages."""
    response = await handler(request)
    if not isinstance(response, web.Response) or response.content_type != "text/html":
        return response

    text = response.text or ""
    ingress_path = request.headers.get("X-Ingress-Path", "").rstrip("/")

    if request.path == "/":
        marker = '<a class="btn btn-secondary" href="' + ingress_path + '/debug" title="Debug-Konsole">🛠 Debug</a>'
        link = '<a class="btn btn-primary" href="' + ingress_path + '/ha-export" title="Home-Assistant-Geräte für Alexa konfigurieren">HA → Alexa</a>'
        if marker in text and link not in text:
            response.text = text.replace(marker, link + marker)

    if request.path == "/ha-export":
        stylesheet = (
            '<link rel="stylesheet" href="'
            + ingress_path
            + '/static/ha_export_mobile.css?v='
            + APP_VERSION
            + '">'
        )
        if "ha_export_mobile.css" not in text:
            response.text = text.replace("</head>", stylesheet + "</head>")

    return response


def create_app() -> web.Application:
    server_clean.APP_VERSION = APP_VERSION
    ha_export_overrides.install()
    ha_control.install()
    app = server_clean.create_app()
    app.middlewares.append(navigation_middleware)
    ha_export.register_routes(app)
    ha_control.register_routes(app)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8099)
