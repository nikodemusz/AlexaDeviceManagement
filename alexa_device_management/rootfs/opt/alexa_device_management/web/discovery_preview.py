"""Preview the Alexa discovery result before deploying Home Assistant YAML."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from aiohttp import web

import ha_export


CONTROLLABLE_DOMAINS = {
    "light", "switch", "cover", "climate", "lock", "camera",
    "scene", "script", "fan", "input_boolean", "sensor", "binary_sensor",
}


def _flatten_devices(devices: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    entities: dict[str, dict[str, Any]] = {}
    for device in devices:
        for entity in device.get("entities", []):
            entity_id = str(entity.get("entity_id") or "").strip()
            if not entity_id:
                continue
            entities[entity_id] = {
                **entity,
                "device_id": device.get("device_id"),
                "device_name": device.get("name"),
                "area_id": device.get("area_id"),
                "area_name": device.get("area_name"),
                "floor_name": device.get("floor_name"),
            }
    return entities


def build_preview(config: dict[str, Any], devices: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the endpoints Alexa would discover plus consistency warnings."""
    inventory = _flatten_devices(devices)
    configured = config.get("entities", {}) if isinstance(config, dict) else {}
    if not isinstance(configured, dict):
        configured = {}

    endpoints: list[dict[str, Any]] = []
    missing_entities: list[str] = []
    warnings: list[dict[str, Any]] = []

    for entity_id, settings in sorted(configured.items()):
        if not isinstance(settings, dict) or not settings.get("enabled"):
            continue
        source = inventory.get(entity_id)
        if source is None:
            missing_entities.append(entity_id)
            warnings.append({
                "code": "missing_entity",
                "severity": "error",
                "entity_id": entity_id,
                "message": "Die konfigurierte Entität existiert nicht mehr in Home Assistant.",
            })
            continue

        name = str(settings.get("name") or source.get("name") or entity_id).strip()
        category = str(
            settings.get("display_category")
            or source.get("category_suggestion")
            or "OTHER"
        ).strip().upper()
        domain = str(source.get("domain") or entity_id.split(".", 1)[0])

        if not name:
            warnings.append({
                "code": "empty_name",
                "severity": "error",
                "entity_id": entity_id,
                "message": "Für die Alexa-Entität fehlt ein Name.",
            })
        if len(name) > 128:
            warnings.append({
                "code": "long_name",
                "severity": "warning",
                "entity_id": entity_id,
                "message": "Der Alexa-Name ist länger als 128 Zeichen.",
            })
        if domain not in CONTROLLABLE_DOMAINS:
            warnings.append({
                "code": "unusual_domain",
                "severity": "warning",
                "entity_id": entity_id,
                "message": f"Die Domain {domain} ist für Alexa ungewöhnlich oder nicht steuerbar.",
            })

        endpoints.append({
            "entity_id": entity_id,
            "name": name,
            "category": category,
            "domain": domain,
            "area": source.get("area_name") or "Ohne Bereich",
            "floor": source.get("floor_name"),
            "device": source.get("device_name"),
            "state": source.get("state"),
        })

    names: dict[str, list[str]] = defaultdict(list)
    for endpoint in endpoints:
        names[endpoint["name"].casefold()].append(endpoint["entity_id"])
    duplicates = [
        {"name": next(e["name"] for e in endpoints if e["entity_id"] == ids[0]), "entities": ids}
        for ids in names.values() if len(ids) > 1
    ]
    for duplicate in duplicates:
        warnings.append({
            "code": "duplicate_name",
            "severity": "warning",
            "entities": duplicate["entities"],
            "message": f"Der Alexa-Name „{duplicate['name']}“ wird mehrfach verwendet.",
        })

    category_counts = dict(sorted(Counter(e["category"] for e in endpoints).items()))
    domain_counts = dict(sorted(Counter(e["domain"] for e in endpoints).items()))
    area_counts = dict(sorted(Counter(e["area"] for e in endpoints).items()))
    error_count = sum(1 for warning in warnings if warning["severity"] == "error")
    warning_count = sum(1 for warning in warnings if warning["severity"] == "warning")

    return {
        "ok": error_count == 0,
        "endpoint_count": len(endpoints),
        "endpoints": endpoints,
        "category_counts": category_counts,
        "domain_counts": domain_counts,
        "area_counts": area_counts,
        "duplicate_names": duplicates,
        "missing_entities": missing_entities,
        "warnings": warnings,
        "error_count": error_count,
        "warning_count": warning_count,
    }


async def preview_endpoint(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    config = payload.get("configuration") if isinstance(payload, dict) else None
    devices = payload.get("devices") if isinstance(payload, dict) else None
    if not isinstance(config, dict):
        config = ha_export._load_state()
    if not isinstance(devices, list):
        devices = (await ha_export._inventory()).get("devices", [])

    return web.json_response(build_preview(config, devices))


def register_routes(app: web.Application) -> None:
    app.router.add_post("/api/ha-export/discovery-preview", preview_endpoint)
