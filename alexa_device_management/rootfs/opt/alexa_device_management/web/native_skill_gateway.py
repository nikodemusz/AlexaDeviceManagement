"""Restricted HTTPS-reverse-proxy target for an independent Alexa Smart Home skill.

Expose ONLY this separate gateway port via a TLS reverse proxy, not the app's
admin/ingress UI. A secret bearer token is required for every request.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path

import aiohttp
from aiohttp import web

from native_skill_config import NativeSkillConfigStore, NativeSkillConfigError
from device_model import DeviceModelError

OPTIONS = Path("/data/options.json")
HA_URL = os.environ.get("HA_HTTP_URL", "http://supervisor/core/api")
# User OAuth tokens must be validated by Home Assistant Core directly, NOT
# through the Supervisor proxy (which requires a Supervisor-specific token).
HA_USER_URL = os.environ.get("HA_USER_HTTP_URL", "http://homeassistant:8123/api").rstrip("/")
HA_TIMEOUT = aiohttp.ClientTimeout(total=2.5)
CURRENT_RESOURCES = ContextVar("gateway_resources", default=None)


class GatewayResources:
    """Resources belong to one app/event loop, never to a linked user."""

    def __init__(self):
        self.config_lock = asyncio.Lock()
        self.config_signature = None
        self.config = None
        self.session = None

    def _load_config(self):
        store = NativeSkillConfigStore()

        def signature():
            try:
                stat = store.path.stat()
                return (str(store.path), stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            except FileNotFoundError:
                return (str(store.path), None)

        before = signature()
        if self.config is not None and before == self.config_signature:
            return self.config
        # A failed read must never fall back to a previously enabled config.
        self.config = None
        self.config_signature = None
        config = store.load()
        if signature() != before:
            raise NativeSkillConfigError("Configuration changed while reading; retry request")
        self.config, self.config_signature = config, before
        return config

    async def load_config(self):
        # Coalesce a burst into one YAML parse and keep disk/validation work
        # off the event loop so pending HA responses can still be processed.
        async with self.config_lock:
            return await asyncio.to_thread(self._load_config)

    def client(self):
        if self.session is None:
            self.session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=32, limit_per_host=32),
                cookie_jar=aiohttp.DummyCookieJar())
        return self.session


RESOURCES = web.AppKey("gateway_resources", GatewayResources)


async def resource_context(app):
    resources = app[RESOURCES]
    try:
        yield
    finally:
        if resources.session is not None:
            await resources.session.close()


@web.middleware
async def resources_middleware(request, handler):
    marker = CURRENT_RESOURCES.set(request.app[RESOURCES])
    try:
        return await handler(request)
    except (asyncio.TimeoutError, aiohttp.ServerTimeoutError):
        raise web.HTTPGatewayTimeout(text="Home Assistant request timed out") from None
    except aiohttp.ClientError:
        raise web.HTTPBadGateway(text="Home Assistant connection failed") from None
    except NativeSkillConfigError:
        raise web.HTTPServiceUnavailable(text="Native skill configuration unavailable") from None
    finally:
        CURRENT_RESOURCES.reset(marker)


async def request_config():
    resources = CURRENT_RESOURCES.get()
    if resources is None:
        return await asyncio.to_thread(NativeSkillConfigStore().load)
    return await resources.load_config()


async def request_active_config():
    if CURRENT_RESOURCES.get() is None:
        return active_config()
    config = await request_config()
    if not config["enabled"]:
        raise web.HTTPServiceUnavailable(text="Native skill is disabled")
    return config


@asynccontextmanager
async def ha_session(headers):
    resources = CURRENT_RESOURCES.get()
    if resources is None:
        async with aiohttp.ClientSession(headers=headers) as session:
            yield session
    else:
        yield resources.client()


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
    config = await request_config()
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
    async with ha_session(headers) as session:
        async with session.request(method, HA_USER_URL + endpoint, json=payload,
                                   headers=headers, timeout=HA_TIMEOUT) as result:
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
    config = await request_active_config()
    endpoint_id = data.get("endpoint_id", "")
    token = data.get("token")
    device = config["devices"].get(endpoint_id)
    if not device or not device.get("enabled", True):
        raise web.HTTPNotFound(text="Unknown endpoint")
    entities = sorted({cap["entity_id"] for cap in device["capabilities"]
                       if cap.get("enabled", True)})
    # A virtual Alexa device can contain many entities. Fetch them concurrently
    # so a long list does not consume Alexa's short ReportState response window.
    # A missing HA entity is represented by an omitted state; the Lambda can
    # still report the other live capabilities on this endpoint.
    semaphore = asyncio.Semaphore(16)

    async def fetch_state(entity: str):
        async with semaphore:
            try:
                return entity, await ha_request("GET", "/states/" + entity, token=token)
            except web.HTTPNotFound:
                return entity, None

    results = await asyncio.gather(*(fetch_state(entity) for entity in entities))
    states = {entity: state for entity, state in results if state is not None}
    return web.json_response({"endpoint_id": endpoint_id, "states": states})


async def control_route(request: web.Request) -> web.Response:
    config = await request_active_config()
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
            payload["position"] = round(value)
        else:
            payload["brightness_pct"] = value
    await ha_request("POST", f"/services/{domain}/{service}", payload, token=data.get("token"))
    return web.json_response({"ok": True})



async def linked_token_request(token: str, endpoint: str, data=None):
    """Make a HA request using the *linked user's* OAuth access token."""
    if not isinstance(token, str) or not token or len(token) > 8192:
        raise web.HTTPUnauthorized(text="Missing linked Home Assistant token")
    headers = {"Authorization": "Bearer " + token}
    async with ha_session(headers) as session:
        async with session.request("POST" if data is not None else "GET",
                                   HA_USER_URL + endpoint, json=data,
                                   headers=headers, timeout=HA_TIMEOUT) as result:
            if result.status in (401, 403):
                raise web.HTTPUnauthorized(text="Home Assistant authorization rejected")
            if result.status >= 400:
                raise web.HTTPBadGateway(text=f"HA rejected directive: {result.status}")
            return await result.json()


async def linked_authorize_route(request: web.Request) -> web.Response:
    data = await request.json()
    # The HA API authenticates the Alexa-linked Home Assistant user; never
    # assume the gateway's machine secret alone authorizes device control.
    await linked_token_request(data.get("token"), "/")
    return web.json_response({"authorized": True})


async def legacy_route(request: web.Request) -> web.Response:
    data = await request.json()
    event, token = data.get("event"), data.get("token")
    if not isinstance(event, dict) or not isinstance(event.get("directive"), dict):
        raise web.HTTPBadRequest(text="Invalid Alexa directive")
    header = event["directive"].get("header", {})
    if (header.get("namespace"), header.get("name")) != ("Alexa.Authorization", "AcceptGrant"):
        raise web.HTTPGone(text="v5 retired; deploy the native-only AWS Lambda adapter")
    response = await linked_token_request(token, "/alexa/smart_home", event)
    return web.json_response(response)

def create_app() -> web.Application:
    app = web.Application(middlewares=[authentication, resources_middleware], client_max_size=16 * 1024)
    app[RESOURCES] = GatewayResources()
    app.cleanup_ctx.append(resource_context)
    app.router.add_post("/v1/authorize", linked_authorize_route)
    app.router.add_post("/v1/legacy", legacy_route)
    app.router.add_get("/v1/config", config_route)
    app.router.add_post("/v1/state", state_route)
    app.router.add_post("/v1/control", control_route)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8100)
