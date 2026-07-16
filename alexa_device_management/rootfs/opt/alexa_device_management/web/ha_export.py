"""Home Assistant to Alexa configuration manager."""

from __future__ import annotations

import os
import pathlib
import re
from typing import Any

import aiohttp
from aiohttp import web

from config_store import ConfigStore
from yaml_generator import AlexaYamlGenerator, GeneratorValidationError

BASE_DIR = pathlib.Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = pathlib.Path("/data/alexa_device_management")
EXPORT_STATE_PATH = pathlib.Path("/data/ha_alexa_export.json")
CONFIG_PATH = DATA_DIR / "config.json"
ALEXA_YAML_PATH = pathlib.Path("/config/packages/alexa.yaml")
HA_HTTP_URL = os.environ.get("HA_HTTP_URL", "http://supervisor/core/api")
HA_WS_URL = os.environ.get("HA_WS_URL", "ws://supervisor/core/websocket")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
CONFIG_STORE = ConfigStore(CONFIG_PATH, EXPORT_STATE_PATH, ALEXA_YAML_PATH)
YAML_GENERATOR = AlexaYamlGenerator(ALEXA_YAML_PATH)

DISPLAY_CATEGORIES = [
    "LIGHT", "SWITCH", "SMARTPLUG", "THERMOSTAT", "TEMPERATURE_SENSOR",
    "CONTACT_SENSOR", "MOTION_SENSOR", "DOOR", "WINDOW", "GARAGE_DOOR",
    "INTERIOR_BLIND", "EXTERIOR_BLIND", "CAMERA", "LOCK", "SCENE_TRIGGER",
    "OTHER",
]

CATEGORY_BY_DOMAIN = {
    "light": "LIGHT", "switch": "SWITCH", "climate": "THERMOSTAT",
    "cover": "INTERIOR_BLIND", "lock": "LOCK", "camera": "CAMERA",
    "scene": "SCENE_TRIGGER", "script": "SCENE_TRIGGER",
}


def _headers() -> dict[str, str]:
    if not SUPERVISOR_TOKEN:
        raise RuntimeError("SUPERVISOR_TOKEN is missing; enable homeassistant_api for the app")
    return {"Authorization": f"Bearer {SUPERVISOR_TOKEN}", "Content-Type": "application/json"}


async def _ws_commands(commands: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    async with aiohttp.ClientSession(headers=_headers()) as session:
        async with session.ws_connect(HA_WS_URL, heartbeat=30) as ws:
            first = await ws.receive_json()
            if first.get("type") == "auth_required":
                await ws.send_json({"type": "auth", "access_token": SUPERVISOR_TOKEN})
                auth = await ws.receive_json()
                if auth.get("type") != "auth_ok":
                    raise RuntimeError(f"Home Assistant WebSocket authentication failed: {auth}")
            elif first.get("type") != "auth_ok":
                raise RuntimeError(f"Unexpected Home Assistant WebSocket response: {first}")

            pending: dict[int, str] = {}
            for idx, (name, command) in enumerate(commands, start=1):
                pending[idx] = name
                await ws.send_json({"id": idx, **command})

            while pending:
                message = await ws.receive_json()
                message_id = message.get("id")
                if message_id not in pending:
                    continue
                name = pending.pop(message_id)
                if not message.get("success"):
                    raise RuntimeError(f"HA command {name} failed: {message.get('error')}")
                result[name] = message.get("result", [])
    return result


async def _inventory() -> dict[str, Any]:
    registries = await _ws_commands([
        ("devices", {"type": "config/device_registry/list"}),
        ("entities", {"type": "config/entity_registry/list"}),
        ("areas", {"type": "config/area_registry/list"}),
        ("floors", {"type": "config/floor_registry/list"}),
        ("labels", {"type": "config/label_registry/list"}),
    ])

    async with aiohttp.ClientSession(headers=_headers()) as session:
        async with session.get(f"{HA_HTTP_URL}/states", timeout=20) as response:
            response.raise_for_status()
            states = await response.json()

    states_by_id = {state.get("entity_id"): state for state in states}
    areas = {area["area_id"]: area for area in registries["areas"]}
    floors = {floor["floor_id"]: floor for floor in registries.get("floors", [])}
    devices = {device["id"]: device for device in registries["devices"]}

    grouped: dict[str, dict[str, Any]] = {}
    for entity in registries["entities"]:
        entity_id = entity.get("entity_id", "")
        if not entity_id or entity.get("disabled_by") is not None:
            continue
        domain = entity_id.split(".", 1)[0]
        state = states_by_id.get(entity_id, {})
        attributes = state.get("attributes", {})
        device = devices.get(entity.get("device_id"), {})
        area_id = entity.get("area_id") or device.get("area_id")
        area = areas.get(area_id, {})
        floor = floors.get(area.get("floor_id"), {})
        device_id = entity.get("device_id") or f"entity:{entity_id}"
        group = grouped.setdefault(device_id, {
            "device_id": device_id,
            "name": device.get("name_by_user") or device.get("name") or attributes.get("friendly_name") or entity_id,
            "manufacturer": device.get("manufacturer"),
            "model": device.get("model"),
            "area_id": area_id,
            "area_name": area.get("name"),
            "floor_name": floor.get("name"),
            "entities": [],
        })
        group["entities"].append({
            "entity_id": entity_id,
            "domain": domain,
            "name": entity.get("name") or attributes.get("friendly_name") or entity.get("original_name") or entity_id,
            "original_name": entity.get("original_name"),
            "platform": entity.get("platform"),
            "device_class": attributes.get("device_class") or entity.get("device_class"),
            "state": state.get("state"),
            "category_suggestion": CATEGORY_BY_DOMAIN.get(domain, "OTHER"),
            "supported_features": attributes.get("supported_features", 0),
        })

    device_list = sorted(grouped.values(), key=lambda item: ((item.get("area_name") or ""), item.get("name") or ""))
    for device in device_list:
        device["entities"].sort(key=lambda item: item["entity_id"])
    return {
        "devices": device_list,
        "areas": sorted(registries["areas"], key=lambda item: item.get("name", "")),
        "display_categories": DISPLAY_CATEGORIES,
    }


def _load_state() -> dict[str, Any]:
    return CONFIG_STORE.load()


def _save_state(data: dict[str, Any]) -> dict[str, Any]:
    return CONFIG_STORE.save(data)


def _dump_yaml(data: dict[str, Any]) -> str:
    return YAML_GENERATOR.generate(data).yaml_text


def _suggest_name(entity: dict[str, Any], device: dict[str, Any]) -> str:
    raw = str(entity.get("name") or device.get("name") or entity.get("entity_id") or "Gerät")
    raw = re.sub(r"\b(node|channel|kanal|switch|sensor|device|entity)\b", "", raw, flags=re.I)
    raw = re.sub(r"\b\d{3,}\b", "", raw)
    raw = re.sub(r"[_-]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip(" -_")
    area = str(device.get("area_name") or "").strip()
    if area and area.lower() not in raw.lower():
        raw = f"{raw} {area}".strip()
    floor = str(device.get("floor_name") or "").strip()
    if floor and floor.lower() not in raw.lower():
        raw = f"{raw} {floor}".strip()
    return raw or entity.get("entity_id", "Gerät")


async def page(request: web.Request) -> web.Response:
    text = (STATIC_DIR / "ha_export.html").read_text(encoding="utf-8")
    ingress_path = request.headers.get("X-Ingress-Path", "").rstrip("/")
    return web.Response(text=text.replace("{{INGRESS_PATH}}", ingress_path), content_type="text/html")


async def inventory(request: web.Request) -> web.Response:
    try:
        data = await _inventory()
        data["configuration"] = _load_state()
        data["storage"] = CONFIG_STORE.status()
        return web.json_response(data)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


async def configuration(request: web.Request) -> web.Response:
    state = _load_state()
    generated = YAML_GENERATOR.generate(state)
    try:
        existing = ALEXA_YAML_PATH.read_text(encoding="utf-8")
    except OSError:
        existing = None
    return web.json_response({
        "configuration": state,
        "yaml": generated.yaml_text,
        "selected": generated.selected_count,
        "existing_yaml": existing,
        "storage": CONFIG_STORE.status(),
    })


async def autosave(request: web.Request) -> web.Response:
    try:
        saved = _save_state(await request.json())
        return web.json_response({"ok": True, "configuration": saved, "storage": CONFIG_STORE.status()})
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc), "storage": CONFIG_STORE.status()}, status=500)


async def preview(request: web.Request) -> web.Response:
    try:
        generated = YAML_GENERATOR.generate(await request.json())
        return web.json_response({"yaml": generated.yaml_text, "selected": generated.selected_count})
    except GeneratorValidationError as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def suggest_names(request: web.Request) -> web.Response:
    payload = await request.json()
    suggestions: dict[str, str] = {}
    for device in payload.get("devices", []):
        for entity in device.get("entities", []):
            suggestions[entity["entity_id"]] = _suggest_name(entity, device)
    return web.json_response({"suggestions": suggestions, "source": "local_rules"})


async def save(request: web.Request) -> web.Response:
    try:
        requested = await request.json()
        saved = _save_state(requested)
        deployed = YAML_GENERATOR.deploy(saved)
        return web.json_response({
            "ok": True,
            "configuration": saved,
            "storage": CONFIG_STORE.status(),
            "path": deployed.path,
            "backup": deployed.backup,
            "yaml": deployed.yaml_text,
            "selected": deployed.selected_count,
            "restart_required": True,
        })
    except GeneratorValidationError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    except OSError as exc:
        return web.json_response({"ok": False, "error": f"YAML deployment failed: {exc}"}, status=500)


def register_routes(app: web.Application) -> None:
    app.router.add_get("/ha-export", page)
    app.router.add_get("/api/ha-export/inventory", inventory)
    app.router.add_get("/api/ha-export/config", configuration)
    app.router.add_post("/api/ha-export/autosave", autosave)
    app.router.add_post("/api/ha-export/preview", preview)
    app.router.add_post("/api/ha-export/suggest-names", suggest_names)
    app.router.add_post("/api/ha-export/save", save)
