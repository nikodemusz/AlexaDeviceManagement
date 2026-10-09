"""Restricted HTTPS-reverse-proxy target for an independent Alexa Smart Home skill.

Expose ONLY this separate gateway port via a TLS reverse proxy, not the app's
admin/ingress UI. A secret bearer token is required for every request.
"""
from __future__ import annotations

import hmac
import json
import os
from pathlib import Path

import aiohttp
from aiohttp import web

from native_skill_config import NativeSkillConfigStore
from device_model import DeviceModelError

OPTIONS = Path("/data/options.json")
HA_URL = os.environ.get("HA_HTTP_URL", "http://supervisor/core/api")
HA_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")


def secret() -> str:
    try:
        value = json.loads(OPTIONS.read_text(encoding="utf-8")).get("native_gateway_token", "")
    except (OSError, ValueError, TypeError):
        return ""
    return str(value).strip()


@web.middleware
async def authentication(request: web.Request, handler):
    token = secret()
    presented = request.headers.get("Authorization", "")
    if not token or len(token) < 32 or not hmac.compare_digest(presented, f"Bearer {token}"):
        raise web.HTTPUnauthorized()
    return await handler(request)


def active_config() -> dict:
    config = NativeSkillConfigStore().load()
    if not config["enabled"]:
        raise web.HTTPServiceUnavailable(text="Native skill is disabled")
    return config


async def config_route(request: web.Request) -> web.Response:
    config = active_config()
    return web.json_response({"schema_version": config["schema_version"],
                              "locale": config["locale"], "devices": config["devices"]})


def lookup_binding(config: dict, endpoint_id: str, interface: str, instance: str | None):
    device = config["devices"].get(endpoint_id)
    if not device or not device.get("enabled", True):
        raise web.HTTPNotFound(text="Unknown endpoint")
    for binding in device["capabilities"]:
        if binding["interface"] == interface and binding.get("instance") == instance:
            return binding
    raise web.HTTPNotFound(text="Unknown capability")


async def ha_request(method: str, endpoint: str, payload=None):
    if not HA_TOKEN:
        raise web.HTTPServiceUnavailable(text="HA supervisor token unavailable")
    headers = {"Authorization": f"Bearer {HA_TOKEN}"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.request(method, HA_URL + endpoint, json=payload,
                                   timeout=aiohttp.ClientTimeout(total=10)) as result:
            if result.status == 404:
                raise web.HTTPNotFound(text="HA entity/service not found")
            if result.status >= 400:
                raise web.HTTPBadGateway(text=f"HA response {result.status}")
            if result.status == 204:
                return {}
            return await result.json()


async def state_route(request: web.Request) -> web.Response:
    config = active_config()
    endpoint_id = request.query.get("endpoint_id", "")
    device = config["devices"].get(endpoint_id)
    if not device or not device.get("enabled", True):
        raise web.HTTPNotFound(text="Unknown endpoint")
    entities = sorted({cap["entity_id"] for cap in device["capabilities"]})
    states = {}
    for entity in entities:
        states[entity] = await ha_request("GET", "/states/" + entity)
    return web.json_response({"endpoint_id": endpoint_id, "states": states})


async def control_route(request: web.Request) -> web.Response:
    config = active_config()
    data = await request.json()
    interface = data.get("interface")
    instance = data.get("instance")
    binding = lookup_binding(config, data.get("endpoint_id", ""), interface, instance)
    if binding.get("read_only", False) or interface == "Alexa.RangeController":
        raise web.HTTPForbidden(text="Read-only capability")
    entity = binding["entity_id"]
    domain = entity.split(".", 1)[0]
    action = data.get("action")
    if interface == "Alexa.PowerController" and action in ("TurnOn", "TurnOff") and domain in ("light", "switch", "fan"):
        service, value = ("turn_on" if action == "TurnOn" else "turn_off"), None
    elif interface == "Alexa.BrightnessController" and action == "SetBrightness" and domain == "light":
        value = data.get("value")
        if type(value) not in (int, float) or not 0 <= value <= 100:
            raise web.HTTPBadRequest(text="Brightness must be 0..100")
        service = "turn_on"
    elif interface == "Alexa.ToggleController" and action in ("TurnOn", "TurnOff") and domain in ("switch", "input_boolean"):
        service, value = ("turn_on" if action == "TurnOn" else "turn_off"), None
    else:
        raise web.HTTPBadRequest(text="Unsupported action/domain")
    payload = {"entity_id": entity}
    if value is not None:
        payload["brightness_pct"] = value
    await ha_request("POST", f"/services/{domain}/{service}", payload)
    return web.json_response({"ok": True})


def create_app() -> web.Application:
    app = web.Application(middlewares=[authentication], client_max_size=16 * 1024)
    app.router.add_get("/v1/config", config_route)
    app.router.add_get("/v1/state", state_route)
    app.router.add_post("/v1/control", control_route)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8100)
