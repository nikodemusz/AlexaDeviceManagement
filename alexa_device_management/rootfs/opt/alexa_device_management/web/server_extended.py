"""Extended app entry point with unified Home Assistant and Alexa management."""

from __future__ import annotations

from aiohttp import web

import alexa_cache_service
import alexa_endpoint_inventory
import alexa_group_manager
import alexa_login_ingress_fix
import alexa_room_enrichment
import device_overview
import ha_control
import ha_export
import ha_export_overrides
import native_export
import native_lifecycle
import server_clean

APP_VERSION = "3.3.0"


@web.middleware
async def navigation_middleware(request: web.Request, handler):
    """Use the unified overview as the canonical UI while keeping old URLs valid."""
    if request.path in {"/", "/ha-export", "/migration"}:
        ingress_path = request.headers.get("X-Ingress-Path", "").rstrip("/")
        raise web.HTTPFound(location=f"{ingress_path}/devices")

    response = await handler(request)
    if not isinstance(response, web.Response) or response.content_type != "text/html":
        return response

    text = response.text or ""
    ingress_path = request.headers.get("X-Ingress-Path", "").rstrip("/")
    text = text.replace(ingress_path + "/auth/login", ingress_path + "/alexa-login")
    text = text.replace("<code>/auth/login</code>", "<code>/alexa-login</code>")
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
    native_export.install()

    app = server_clean.create_app()
    app["native_primary"] = True
    app.middlewares.append(navigation_middleware)

    alexa_cache_service.register_routes(app, server_clean)
    alexa_group_manager.register_routes(app, server_clean, ha_export.CONFIG_STORE)
    device_overview.register_routes(app, server_clean, ha_export.CONFIG_STORE)
    ha_export.register_routes(app)
    native_lifecycle.install(app, server_clean)
    native_export.register_routes(app)
    ha_control.register_routes(app)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8099)
