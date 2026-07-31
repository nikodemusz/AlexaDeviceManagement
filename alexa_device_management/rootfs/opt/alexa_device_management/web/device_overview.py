"""Unified Home Assistant and Alexa device overview."""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any, Iterable

from aiohttp import web

import alexa_group_manager
import ha_export

STATIC_DIR = ha_export.STATIC_DIR

_UI_LISTS = {
    "device": "hidden_devices",
    "entity": "hidden_entities",
    "alexa": "hidden_alexa",
}


def _canonical(value: Any) -> set[str]:
    """Return comparable forms for Alexa and Home Assistant identifiers."""
    text = str(value or "").strip().lower()
    if not text:
        return set()
    values = {text}
    prefix = "amzn1.alexa.endpoint."
    if text.startswith(prefix):
        values.add(text[len(prefix):])
    if "#" in text:
        values.add(text.replace("#", ".", 1))
    if "." in text:
        values.add(text.replace(".", "#", 1))
    return values


def _collect_identifiers(value: Any) -> set[str]:
    result: set[str] = set()

    def walk(current: Any) -> None:
        if isinstance(current, dict):
            for key, child in current.items():
                normalized = str(key).replace("_", "").lower()
                if normalized in {
                    "id",
                    "entityid",
                    "endpointid",
                    "applianceid",
                    "appliancekey",
                    "serial",
                    "serialnumber",
                    "deviceserialnumber",
                } and not isinstance(child, (dict, list)):
                    result.update(_canonical(child))
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(current, list):
            for child in current:
                walk(child)

    walk(value)
    return result


def _alexa_key(device: dict[str, Any]) -> str:
    return f"{str(device.get('source') or 'unknown')}:{str(device.get('serial') or device.get('appliance_id') or '')}"


def _alexa_entity_id(device: dict[str, Any]) -> str:
    explicit = alexa_group_manager._device_entity_id(device)
    if explicit:
        return explicit.lower()

    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    for value in (
        raw.get("entityId"),
        raw.get("entity_id"),
        raw.get("endpointId"),
        device.get("serial"),
    ):
        for candidate in _canonical(value):
            if "." in candidate and " " not in candidate:
                return candidate
    return ""


def _device_identifiers(device: dict[str, Any]) -> set[str]:
    identifiers = alexa_group_manager._device_identifiers(device)
    identifiers.update(_collect_identifiers(device.get("raw") or {}))
    identifiers.update(_canonical(device.get("serial")))
    identifiers.update(_canonical(device.get("appliance_id")))
    entity_id = _alexa_entity_id(device)
    if entity_id:
        identifiers.update(_canonical(entity_id))
    return identifiers


def _group_names_for_device(
    device: dict[str, Any], groups: Iterable[dict[str, Any]]
) -> list[str]:
    identifiers = _device_identifiers(device)
    names = [
        str(group.get("name") or "").strip()
        for group in groups
        if identifiers & alexa_group_manager._group_member_identifiers(group)
    ]
    return sorted({name for name in names if name}, key=str.casefold)


def _public_alexa_device(
    device: dict[str, Any], groups: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    return {
        "key": _alexa_key(device),
        "serial": str(device.get("serial") or ""),
        "appliance_id": str(device.get("appliance_id") or ""),
        "name": str(device.get("name") or device.get("serial") or "Unbekannt"),
        "source": str(device.get("source") or ""),
        "type": str(device.get("type") or ""),
        "family": str(device.get("family") or ""),
        "skill": str(device.get("skill") or ""),
        "room": str(device.get("room") or ""),
        "online": bool(device.get("online")),
        "lifecycle": str(device.get("lifecycle") or ""),
        "entity_id": _alexa_entity_id(device),
        "groups": _group_names_for_device(device, groups),
        "device_type": str(raw.get("deviceType") or device.get("type") or ""),
    }


def _entity_matches(
    entity_id: str,
    devices: list[dict[str, Any]],
) -> list[int]:
    expected = _canonical(entity_id)
    matches: list[int] = []
    for index, device in enumerate(devices):
        if str(device.get("source") or "") == "echo":
            continue
        explicit = _alexa_entity_id(device)
        identifiers = _device_identifiers(device)
        if explicit == entity_id.lower() or expected & identifiers:
            matches.append(index)
    return matches


def _entity_status(enabled: bool, match_count: int) -> str:
    if match_count > 1:
        return "duplicate"
    if enabled and match_count == 1:
        return "synced"
    if enabled:
        return "pending"
    if match_count:
        return "only_alexa"
    return "not_exposed"


def _device_status(statuses: Iterable[str]) -> str:
    values = set(statuses)
    if "duplicate" in values or "only_alexa" in values:
        return "problem"
    if "pending" in values:
        return "pending"
    if "synced" in values:
        return "synced"
    return "not_exposed"


def build_overview(
    ha_inventory: dict[str, Any],
    alexa_devices: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Join HA entities and Alexa endpoints without fuzzy name matching."""
    ui = config.get("ui") if isinstance(config.get("ui"), dict) else {}
    hidden_devices = {str(value) for value in ui.get("hidden_devices", [])}
    hidden_entities = {str(value) for value in ui.get("hidden_entities", [])}
    hidden_alexa = {str(value) for value in ui.get("hidden_alexa", [])}
    entity_config = config.get("entities") if isinstance(config.get("entities"), dict) else {}

    public_alexa = [_public_alexa_device(device, groups) for device in alexa_devices]
    matched_indexes: set[int] = set()
    devices: list[dict[str, Any]] = []

    summary = {
        "ha_devices": 0,
        "ha_entities": 0,
        "selected": 0,
        "synced": 0,
        "pending": 0,
        "only_alexa": 0,
        "duplicates": 0,
        "hidden": 0,
        "alexa_only": 0,
    }

    for ha_device in ha_inventory.get("devices", []):
        if not isinstance(ha_device, dict):
            continue
        device_id = str(ha_device.get("device_id") or "")
        public_entities: list[dict[str, Any]] = []
        statuses: list[str] = []
        for entity in ha_device.get("entities", []):
            if not isinstance(entity, dict):
                continue
            entity_id = str(entity.get("entity_id") or "")
            if not entity_id:
                continue
            settings = entity_config.get(entity_id)
            if not isinstance(settings, dict):
                settings = {}
            enabled = bool(settings.get("enabled"))
            match_indexes = _entity_matches(entity_id, alexa_devices)
            matched_indexes.update(match_indexes)
            matches = [public_alexa[index] for index in match_indexes]
            status = _entity_status(enabled, len(matches))
            statuses.append(status)
            hidden = entity_id in hidden_entities or device_id in hidden_devices

            summary["ha_entities"] += 1
            summary["selected"] += int(enabled)
            summary["hidden"] += int(hidden)
            if status == "synced":
                summary["synced"] += 1
            elif status == "pending":
                summary["pending"] += 1
            elif status == "only_alexa":
                summary["only_alexa"] += 1
            elif status == "duplicate":
                summary["duplicates"] += 1

            public_entities.append({
                **entity,
                "export": {
                    "enabled": enabled,
                    "name": str(settings.get("name") or ""),
                    "description": str(settings.get("description") or ""),
                    "display_category": str(settings.get("display_category") or ""),
                    "alexa_group": str(settings.get("alexa_group") or ""),
                },
                "alexa": {
                    "present": bool(matches),
                    "count": len(matches),
                    "matches": matches,
                },
                "status": status,
                "hidden": hidden,
                "hidden_directly": entity_id in hidden_entities,
            })

        if not public_entities:
            continue
        hidden = device_id in hidden_devices
        devices.append({
            **{key: value for key, value in ha_device.items() if key != "entities"},
            "entities": public_entities,
            "status": _device_status(statuses),
            "hidden": hidden,
        })
        summary["ha_devices"] += 1

    alexa_only: list[dict[str, Any]] = []
    for index, public in enumerate(public_alexa):
        if index in matched_indexes:
            continue
        item = dict(public)
        item["hidden"] = item["key"] in hidden_alexa
        if item["source"] == "echo":
            item["status"] = "alexa_device"
        elif item["lifecycle"] == "orphaned" or item["source"] == "graphql":
            item["status"] = "orphaned"
        else:
            item["status"] = "unmatched"
        alexa_only.append(item)
        summary["alexa_only"] += 1
        summary["hidden"] += int(item["hidden"])

    return {
        "devices": devices,
        "alexa_only": sorted(alexa_only, key=lambda item: item["name"].casefold()),
        "areas": ha_inventory.get("areas", []),
        "display_categories": ha_inventory.get("display_categories", []),
        "groups": [
            {"id": group.get("id"), "name": group.get("name"), "type": group.get("type")}
            for group in groups
        ],
        "configuration": config,
        "summary": summary,
    }


async def page(request: web.Request) -> web.Response:
    text = (STATIC_DIR / "device_overview.html").read_text(encoding="utf-8")
    ingress_path = request.headers.get("X-Ingress-Path", "").rstrip("/")
    return web.Response(
        text=text.replace("{{INGRESS_PATH}}", ingress_path),
        content_type="text/html",
    )


async def overview(request: web.Request) -> web.Response:
    server = request.app["device_overview_server"]
    store = request.app["device_overview_store"]
    force = request.rel_url.query.get("refresh") == "1"
    warnings: list[str] = []

    try:
        ha_inventory = await ha_export._inventory()
        config = store.load()

        alexa_devices: list[dict[str, Any]] = []
        groups: list[dict[str, Any]] = []
        if server.is_configured():
            if force:
                cache = await server.refresh_devices_cache()
            else:
                server._load_devices_cache()
                cache = server._DEVICES_CACHE
                if not cache.get("updated_at"):
                    cache = await server.refresh_devices_cache()
            alexa_devices = list(cache.get("devices", []))
            warnings.extend(str(item) for item in cache.get("warnings", []) if item)
            try:
                groups = await alexa_group_manager._load_groups(
                    server, server.session_data()
                )
            except Exception as exc:
                warnings.append(f"Alexa-Gruppen: {exc}")

        result = build_overview(ha_inventory, alexa_devices, groups, config)
        result.update({
            "ok": True,
            "alexa_connected": server.is_configured(),
            "alexa_updated_at": (
                server._DEVICES_CACHE.get("updated_at")
                if hasattr(server, "_DEVICES_CACHE")
                else None
            ),
            "warnings": warnings,
            "generated_at": int(time.time()),
        })
        return web.json_response(result)
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def visibility(request: web.Request) -> web.Response:
    store = request.app["device_overview_store"]
    try:
        body = await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(text="Ungültige JSON-Daten.") from exc

    kind = str(body.get("kind") or "").strip()
    list_name = _UI_LISTS.get(kind)
    if list_name is None:
        raise web.HTTPBadRequest(text="kind muss device, entity oder alexa sein.")

    raw_ids = body.get("ids")
    if not isinstance(raw_ids, list):
        raw_ids = [body.get("id")]
    ids = {str(value).strip() for value in raw_ids if str(value or "").strip()}
    if not ids:
        raise web.HTTPBadRequest(text="id oder ids ist erforderlich.")
    hidden = bool(body.get("hidden", True))

    config = deepcopy(store.load())
    ui = config.get("ui") if isinstance(config.get("ui"), dict) else {}
    current = {str(value) for value in ui.get(list_name, [])}
    if hidden:
        current.update(ids)
    else:
        current.difference_update(ids)
    ui[list_name] = sorted(current)
    config["ui"] = ui
    saved = store.save(config)
    return web.json_response({
        "ok": True,
        "kind": kind,
        "hidden": hidden,
        "ids": sorted(ids),
        "configuration": saved,
    })


def register_routes(app: web.Application, server: Any, store: Any) -> None:
    app["device_overview_server"] = server
    app["device_overview_store"] = store
    app.router.add_get("/devices", page)
    app.router.add_get("/api/device-overview", overview)
    app.router.add_post("/api/device-overview/visibility", visibility)
