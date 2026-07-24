"""Extended app entry point with Home Assistant Alexa export manager."""

from __future__ import annotations
from aiohttp import web

import alexa_cache_service
import alexa_endpoint_inventory
import alexa_group_manager
import alexa_login_ingress_fix
import alexa_room_enrichment
import consistency_check
import discovery_preview
import ha_control
import ha_export
import ha_export_overrides
import server_clean

APP_VERSION = "2.11.22-rc1"


@web.middleware
async def navigation_middleware(request: web.Request, handler):
    """Inject navigation and page-specific assets into rendered HTML pages."""
    response = await handler(request)
    if not isinstance(response, web.Response) or response.content_type != "text/html":
        return response

    text = response.text or ""
    ingress_path = request.headers.get("X-Ingress-Path", "").rstrip("/")

    if request.path == "/":
        text = text.replace(ingress_path + "/auth/login", ingress_path + "/alexa-login")
        text = text.replace("<code>/auth/login</code>", "<code>/alexa-login</code>")

        marker = '<a class="btn btn-secondary" href="' + ingress_path + '/debug" title="Debug-Konsole">🛠 Debug</a>'
        link = '<a class="btn btn-primary" href="' + ingress_path + '/ha-export" title="Home-Assistant-Geräte für Alexa konfigurieren">HA → Alexa</a>'
        if marker in text and link not in text:
            text = text.replace(marker, link + marker)

        endpoint_stylesheet = (
            '<link rel="stylesheet" href="' + ingress_path
            + '/static/alexa_endpoint_inventory.css?v=' + APP_VERSION + '">'
        )
        endpoint_script = (
            '<script>document.documentElement.dataset.ingressPath=' + repr(ingress_path) + ';</script>'
            + '<script src="' + ingress_path
            + '/static/alexa_endpoint_inventory.js?v=' + APP_VERSION + '"></script>'
            + '<script src="' + ingress_path
            + '/static/device_table_labels.js?v=' + APP_VERSION + '"></script>'
            + '<script src="' + ingress_path
            + '/static/alexa_group_manager.js?v=' + APP_VERSION + '"></script>'
        )
        if "alexa_endpoint_inventory.css" not in text:
            text = text.replace("</head>", endpoint_stylesheet + "</head>")
        if "alexa_endpoint_inventory.js" not in text:
            text = text.replace("</body>", endpoint_script + "</body>")
        response.text = text

    if request.path == "/ha-export":
        text = response.text or text
        stylesheet = (
            '<link rel="stylesheet" href="' + ingress_path
            + '/static/ha_export_mobile.css?v=' + APP_VERSION + '">'
            + '<link rel="stylesheet" href="' + ingress_path
            + '/static/ha_export_performance.css?v=' + APP_VERSION + '">'
        )
        scripts = (
            '<script>document.documentElement.dataset.ingressPath=' + repr(ingress_path)
            + ';</script><script src="' + ingress_path + '/static/ha_export_autosave.js?v=' + APP_VERSION
            + '"></script><script src="' + ingress_path + '/static/ha_export_bulk.js?v=' + APP_VERSION
            + '"></script><script src="' + ingress_path + '/static/ha_export_discovery.js?v=' + APP_VERSION
            + '"></script><script src="' + ingress_path + '/static/ha_export_consistency.js?v=' + APP_VERSION
            + '"></script><script src="' + ingress_path + '/static/ha_export_lifecycle.js?v=' + APP_VERSION
            + '"></script><script src="' + ingress_path + '/static/ha_export_performance.js?v=' + APP_VERSION
            + '"></script><script src="' + ingress_path + '/static/ha_export_deploy_fix.js?v=' + APP_VERSION
            + '"></script><script src="' + ingress_path + '/static/alexa_group_manager.js?v=' + APP_VERSION
            + '"></script>'
        )
        text = text.replace("let inventory=", "window.inventory=")
        text = text.replace("let config=", "window.config=")
        text = text.replace("function setStatus(", "window.setStatus=function setStatus(")
        if "ha_export_mobile.css" not in text:
            text = text.replace("</head>", stylesheet + "</head>")
        if "ha_export_autosave.js" not in text:
            text = text.replace("</body>", scripts + "</body>")
        response.text = text

    return response


def create_app() -> web.Application:
    server_clean.APP_VERSION = APP_VERSION
    alexa_login_ingress_fix.install()
    alexa_endpoint_inventory.install(server_clean)
    alexa_room_enrichment.install(server_clean)
    alexa_cache_service.install(server_clean)
    ha_export_overrides.install()
    ha_control.install()
    app = server_clean.create_app()
    app.middlewares.append(navigation_middleware)
    alexa_cache_service.register_routes(app, server_clean)
    alexa_group_manager.register_routes(app, server_clean, ha_export.CONFIG_STORE)
    ha_export.register_routes(app)
    ha_control.register_routes(app)
    discovery_preview.register_routes(app)
    consistency_check.register_routes(app)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8099)
