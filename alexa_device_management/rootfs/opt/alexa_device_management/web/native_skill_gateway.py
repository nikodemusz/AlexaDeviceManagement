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
# User OAuth tokens must be validated by Home Assistant Core directly, NOT
# through the Supervisor proxy (which requires a Supervisor-specific token).
HA_USER_URL = os.environ.get("HA_USER_HTTP_URL", "http://homeassistant:8123/api").rstrip("/")


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
    config = NativeSkillConfigStore().load()
    return web.json_response({"schema_version": config["schema_version"],
                              "export_mode": "native", "runtime_version": "3.1.0",
                              "locale": config["locale"], "enabled": config["enabled"],
                              "devices": config["devices"] if config["enabled"] else {}})


def lookup_binding(config: dict, endpoint_id: str, interface: str, instance: str | None):
    device = config["devices"].get(endpoint_id)
    if not device or not device.get("enabled", True):
        raise web.HTTPNotFound(text="Unknown endpoint")
    for binding in device["capabilities"]:
        if (binding.get("enabled", True)
                and binding["interface"] == interface
                and binding.get("instance") == instance):
            return binding
    raise web.HTTPNotFound(text="Unknown capability")


async def ha_request(method: str, endpoint: str, payload=None, token: str | None = None):
    if token is None or not isinstance(token, str) or not token:
        raise web.HTTPUnauthorized(text="User token required")
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.request(method, HA_USER_URL + endpoint, json=payload,
                                   timeout=aiohttp.ClientTimeout(total=10)) as result:
            if result.status in (401, 403):
                raise web.HTTPUnauthorized(text="Home Assistant authorization rejected")
            if result.status == 404:
                raise web.HTTPNotFound(text="HA entity/service not found")
            if result.status >= 400:
                raise web.HTTPBadGateway(text=f"HA response {result.status}")
            if result.status == 204:
                return {}
            return await result.json()


async def state_route(request: web.Request) -> web.Response:
    data = await request.json()
    config = active_config()
    endpoint_id = data.get("endpoint_id", "")
    token = data.get("token")
    device = config["devices"].get(endpoint_id)
    if not device or not device.get("enabled", True):
        raise web.HTTPNotFound(text="Unknown endpoint")
    entities = sorted({cap["entity_id"] for cap in device["capabilities"]
                       if cap.get("enabled", True)})
    states = {}
    for entity in entities:
        states[entity] = await ha_request("GET", "/states/" + entity, token=token)
    return web.json_response({"endpoint_id": endpoint_id, "states": states})


async def control_route(request: web.Request) -> web.Response:
    config = active_config()
    data = await request.json()
    interface = data.get("interface")
    instance = data.get("instance")
    binding = lookup_binding(config, data.get("endpoint_id", ""), interface, instance)
    if binding.get("read_only", False):
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
    elif domain == "cover" and interface == "Alexa.PlaybackController" and action == "Stop":
        service, value = "stop_cover", None
    elif domain == "cover" and interface == "Alexa.RangeController" and action in ("SetRangeValue", "AdjustRangeValue"):
        value = data.get("value")
        if type(value) not in (int, float) or not -100 <= value <= 100:
            raise web.HTTPBadRequest(text="Invalid cover position")
        if action == "AdjustRangeValue":
            state = await ha_request("GET", "/states/" + entity, token=data.get("token"))
            position = state.get("attributes", {}).get("current_position")
            if type(position) not in (int, float):
                raise web.HTTPBadRequest(text="Cover position unavailable")
            value += position
        if not 0 <= value <= 100:
            raise web.HTTPBadRequest(text="Cover position outside 0..100")
        service = "set_cover_position"
    elif domain == "climate" and interface == "Alexa.ThermostatController":
        value = data.get("value")
        if action in ("SetTargetTemperature", "AdjustTargetTemperature"):
            if not isinstance(value, dict) or value.get("scale") != "CELSIUS":
                raise web.HTTPBadRequest(text="Celsius setpoint required")
            number = value.get("value")
            if type(number) not in (int, float) or not -40 <= number <= 50:
                raise web.HTTPBadRequest(text="Invalid thermostat setpoint")
            if action == "AdjustTargetTemperature":
                current = await ha_request("GET", "/states/" + entity, token=data.get("token"))
                base = current.get("attributes", {}).get("temperature")
                if type(base) not in (int, float):
                    raise web.HTTPBadRequest(text="Thermostat setpoint unavailable")
                number += base
            service, value = "set_temperature", {"temperature": number}
        elif action == "SetThermostatMode":
            mode = {"HEAT": "heat", "COOL": "cool", "AUTO": "auto",
                    "OFF": "off", "ECO": "eco"}.get(value)
            if mode is None:
                raise web.HTTPBadRequest(text="Unsupported thermostat mode")
            service, value = "set_hvac_mode", {"hvac_mode": mode}
        else:
            raise web.HTTPBadRequest(text="Unsupported thermostat action")
    else:
        raise web.HTTPBadRequest(text="Unsupported action/domain")
    payload = {"entity_id": entity}
    if value is not None:
        if domain == "climate":
            payload.update(value)
        elif domain == "cover":
   