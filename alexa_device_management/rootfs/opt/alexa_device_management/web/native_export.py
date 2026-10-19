"""Canonical v6 editor; archived v5 entities are never an export input."""
from __future__ import annotations

import copy
import hashlib
import json
import time

import yaml
from aiohttp import web

import alexa_event_support as support
import ha_control
import ha_export
from native_migration import candidate
from native_skill_config import NativeSkillConfigStore

STORE = NativeSkillConfigStore()


def revision(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def entity_settings(native):
    result = {}
    for key, device in native.get("devices", {}).items():
        for capability in device.get("capabilities", []):
            entity_id = capability["entity_id"]
            capability_names = capability.get("capability_names") or []
            name = (capability_names[0] if device.get("group_mode") == "combined" and capability_names
                    else device.get("name", key))
            settings = result.setdefault(entity_id, {
                "enabled": False, "name": name,
                "description": device.get("description", ""),
                "display_category": device.get("display_category", "OTHER"),
                "alexa_group": device.get("alexa_group", ""),
                "native_endpoint_ids": [],
                "group_mode": device.get("group_mode", "separate"),
                "logical_device_name": device.get("name", key),
            })
            settings["enabled"] |= bool(device.get("enabled", True) and capability.get("enabled", True))
            if device.get("group_mode") == "combined":
                settings["group_mode"] = "combined"
                settings["logical_device_name"] = device.get("name", key)
            if "native:" + key not in settings["native_endpoint_ids"]:
                settings["native_endpoint_ids"].append("native:" + key)
    return result


def configuration(native, preferences):
    return {**{key: copy.deepcopy(preferences.get(key, {}))
               for key in ("ui", "event_gateway", "group_sync")},
            "schema_version": 6, "export_mode": "native", "legacy_export_enabled": False,
            "locale": native.get("locale", "de-DE"), "native_enabled": native["enabled"],
            "native_revision": revision(native), "entities": entity_settings(native)}


def apply_entities(native, requested, inventory):
    """Change existing logical devices in place; create only explicitly selected ones."""
    proposed = copy.deepcopy(native)
    baseline = entity_settings(native)
    actual = {entity["entity_id"]: entity
              for device in inventory.get("devices", []) for entity in device.get("entities", [])}
    for entity_id, settings in requested.items():
        if not isinstance(settings, dict) or type(settings.get("enabled", False)) is not bool:
            raise ValueError("Entitätsauswahl muss ein boolescher Wert sein.")
        old = baseline.get(entity_id, {})
        fields = ("enabled", "name", "description", "display_category", "alexa_group")
        changes = {key: settings[key] for key in fields
                   if key in settings and settings[key] != old.get(key, False if key == "enabled" else "")}
        if not changes:
            continue
        owners = [key for key, device in proposed["devices"].items()
                  if any(cap["entity_id"] == entity_id for cap in device.get("capabilities", []))]
        if not owners:
            if not settings.get("enabled"):
                continue
            entity = actual.get(entity_id)
            if not entity:
                raise ValueError(f"HA-Entität nicht verfügbar: {entity_id}")
            category = settings.get("display_category") or entity.get("category_suggestion")
            if entity.get("device_class") in ("door", "window", "opening", "garage_door"):
                category = "CONTACT_SENSOR"
            elif entity.get("device_class") in ("motion", "occupancy", "presence"):
                category = "MOTION_SENSOR"
            elif entity.get("device_class") == "temperature":
                category = "TEMPERATURE_SENSOR"
            draft = candidate(entity_id, {**settings, "display_category": category})
            if draft is None:
                raise ValueError(f"Gerätetyp wird von v6 noch nicht unterstützt: {entity_id}")
            if entity_id.startswith("cover.") and int(entity.get("supported_features", 0)) & 12 != 12:
                raise ValueError(f"Positions- und Stoppunterstützung fehlen: {entity_id}")
            if entity_id.startswith("light.") and set(entity.get("supported_color_modes", [])) - {"onoff", "unknown"}:
                draft["capabilities"].append({"interface": "Alexa.BrightnessController", "entity_id": entity_id})
            if entity_id.startswith("climate."):
                modes = {"heat": "HEAT", "cool": "COOL", "auto": "AUTO", "heat_cool": "AUTO", "off": "OFF", "eco": "ECO"}
                supported = sorted({modes[m] for m in entity.get("hvac_modes", []) if m in modes})
                if not set(supported) & {"HEAT", "COOL"}:
                    raise ValueError(f"Keine unterstützten Thermostatmodi: {entity_id}")
                draft["capabilities"][0]["supported_modes"] = supported
            key = "ha:" + entity_id
            proposed["devices"][key] = draft
            owners = [key]
        for key in owners:
            device = proposed["devices"][key]
            if "enabled" in changes:
                if device.get("group_mode") == "combined":
                    for capability in device.get("capabilities", []):
                        if capability["entity_id"] == entity_id:
                            capability["enabled"] = changes["enabled"]
                    device["enabled"] = any(cap.get("enabled", True) for cap in device.get("capabilities", []))
                else:
                    # Preserve the established v6 behavior: any bound entity
                    # toggle controls its whole logical endpoint (for example,
                    # disabling either tank value disables the entire tank).
                    device["enabled"] = changes["enabled"]
            device_changes = {key: value for key, value in changes.items() if key != "enabled"}
            if device.get("group_mode") == "combined" and "name" in device_changes:
                # The endpoint name belongs to the group editor. A row name is
                # the member control's accessible name (used by ToggleController).
                for capability in device.get("capabilities", []):
                    if capability["entity_id"] == entity_id:
                        capability["capability_names"] = [device_changes["name"]]
                device_changes.pop("name")
            device.update(device_changes)
    return NativeSkillConfigStore.validate(proposed)


def apply_device_group(native, device_id, entity_ids, mode, group_name, inventory, names=None):
    """Group selected entities into one Alexa endpoint or restore one per entity."""
    if mode not in {"combined", "separate"}:
        raise ValueError("Exportform muss Gesamtgerät oder einzelne Alexa-Geräte sein.")
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("Home-Assistant-Gerät fehlt.")
    if not isinstance(entity_ids, list) or not entity_ids:
        raise ValueError("Mindestens eine Entität auswählen.")
    if any(not isinstance(entity_id, str) or not entity_id.strip() for entity_id in entity_ids):
        raise ValueError("Ungültige Entity-ID.")
    selected = list(dict.fromkeys(entity_ids))
    ha_device = next((item for item in inventory.get("devices", [])
                      if str(item.get("device_id") or "") == device_id), None)
    if not ha_device:
        raise ValueError("Home-Assistant-Gerät ist nicht mehr verfügbar.")
    available = {entity.get("entity_id") for entity in ha_device.get("entities", [])}
    if not set(selected) <= available:
        r