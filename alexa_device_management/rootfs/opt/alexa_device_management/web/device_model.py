"""Device-centric Alexa configuration model (independent of HA Alexa YAML export).

Schema v6 keeps legacy 'entities' intact while adding explicit Alexa endpoints.
No Amazon requests are made here: discovery/protocol translation is a later sprint.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

ENDPOINT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
SUPPORTED_INTERFACES = frozenset({
    "Alexa.PowerController", "Alexa.BrightnessController",
    "Alexa.RangeController", "Alexa.ToggleController",
})
INSTANCE_INTERFACES = frozenset({"Alexa.RangeController", "Alexa.ToggleController"})


class DeviceModelError(ValueError):
    """Invalid device model or ambiguous Alexa capability configuration."""


def migrate_v5_entities(entities: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Conservatively migrate enabled legacy entities, one endpoint per entity.

    Automatic physical-device grouping could merge unrelated devices. Explicit
    multi-entity grouping can be configured later without changing endpoint IDs.
    The legacy entities mapping is never modified.
    """
    devices: dict[str, dict[str, Any]] = {}
    for entity_id, settings in sorted(entities.items()):
        if not isinstance(entity_id, str) or not isinstance(settings, dict):
            continue
        if not settings.get("enabled") or "." not in entity_id:
            continue
        domain = entity_id.split(".", 1)[0]
        interface = {
            "light": "Alexa.PowerController",
            "switch": "Alexa.PowerController",
        }.get(domain)
        # Do not guess a controller for sensor, cover, climate, etc.
        bindings = ([{"interface": interface, "entity_id": entity_id}]
                    if interface else [])
        devices[f"ha:{entity_id}"] = {
            "name": str(settings.get("name") or entity_id),
            "description": str(settings.get("description") or ""),
            "display_category": str(settings.get("display_category") or "OTHER"),
            "aliases": [],
            "capabilities": bindings,
            "enabled": True,
        }
    return devices


def validate_devices(devices: Any) -> dict[str, dict[str, Any]]:
    """Validate and normalize devices without dropping future-compatible fields."""
    if not isinstance(devices, dict):
        raise DeviceModelError("devices must be an object")
    result: dict[str, dict[str, Any]] = {}
    for endpoint_id, raw in devices.items():
        if not isinstance(endpoint_id, str) or not ENDPOINT_RE.fullmatch(endpoint_id):
            raise DeviceModelError(f"invalid endpoint ID: {endpoint_id!r}")
        if not isinstance(raw, dict):
            raise DeviceModelError(f"{endpoint_id}: device must be an object")
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            raise DeviceModelError(f"{endpoint_id}: name must contain 1-128 characters")
        aliases = raw.get("aliases", [])
        if not isinstance(aliases, list) or any(
            not isinstance(a, str) or not a.strip() for a in aliases
        ):
            raise DeviceModelError(f"{endpoint_id}: aliases must be non-empty strings")
        capabilities = raw.get("capabilities", [])
        if not isinstance(capabilities, list):
            raise DeviceModelError(f"{endpoint_id}: capabilities must be a list")
        seen: set[tuple[str, str]] = set()
        for cap in capabilities:
            if not isinstance(cap, dict):
                raise DeviceModelError(f"{endpoint_id}: capability must be an object")
            interface, entity_id = cap.get("interface"), cap.get("entity_id")
            if interface not in SUPPORTED_INTERFACES:
                raise DeviceModelError(f"{endpoint_id}: unsupported interface {interface!r}")
            if not isinstance(entity_id, str) or "." not in entity_id:
                raise DeviceModelError(f"{endpoint_id}: invalid entity_id {entity_id!r}")
            instance = cap.get("instance")
            if interface in INSTANCE_INTERFACES:
                if not isinstance(instance, str) or not instance.strip():
                    raise DeviceModelError(f"{endpoint_id}: {interface} requires instance")
            elif instance is not None:
                raise DeviceModelError(f"{endpoint_id}: {interface} cannot have instance")
            key = (interface, instance or "")
            if key in seen:
                raise DeviceModelError(f"{endpoint_id}: duplicate capability {key!r}")
            seen.add(key)
            if interface == "Alexa.RangeController":
                if not isinstance(cap.get("unit"), str) or not cap["unit"].strip():
                    raise DeviceModelError(f"{endpoint_id}: RangeController requires unit")
                if cap.get("read_only", True) is not True:
                    raise DeviceModelError(f"{endpoint_id}: writable ranges not implemented")
        normalized = deepcopy(raw)
        normalized.setdefault("description", "")
        normalized.setdefault("display_category", "OTHER")
        normalized["aliases"] = list(aliases)
        normalized["capabilities"] = deepcopy(capabilities)
        normalized.setdefault("enabled", True)
        result[endpoint_id] = normalized
    return result


def device_preview(devices: dict[str, Any]) -> list[dict[str, Any]]:
    """One discovery-preview record per logical Alexa endpoint."""
    valid = validate_devices(devices)
    return [
        {"endpoint_id": endpoint_id, "name": device["name"],
         "capabilities": deepcopy(device["capabilities"])}
        for endpoint_id, device in sorted(valid.items())
        if device.get("enabled", True)
    ]
