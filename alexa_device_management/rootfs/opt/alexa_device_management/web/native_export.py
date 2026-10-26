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
            interface = capability.get("interface")
            # A combined relay uses ToggleController on the wire. In the
            # editor it remains the same user-facing "switch" function.
            editor_interface = ("Alexa.PowerController" if interface == "Alexa.ToggleController"
                                and str(capability.get("instance", "")).startswith("power_")
                                else interface)
            name = (capability_names[0] if device.get("group_mode") == "combined" and capability_names
                    else device.get("name", key))
            settings = result.setdefault(entity_id, {
                "enabled": False, "name": name,
                "description": device.get("description", ""),
                "display_category": device.get("display_category", "OTHER"),
                "display_category_mode": device.get("display_category_mode", "standard"),
                "alexa_group": device.get("alexa_group", ""),
                "native_endpoint_ids": [],
                # No stored mode means this device has not been configured in
                # the grouping editor yet. Keep that distinct from an
                # explicit choice to export separate Alexa endpoints.
                "group_mode": device.get("group_mode", ""),
                "logical_device_name": device.get("name", key),
                "capability_mode": "standard",
                "capabilities": [],
            })
            settings["enabled"] |= bool(device.get("enabled", True) and capability.get("enabled", True))
            if capability.get("capability_mode") == "custom":
                settings["capability_mode"] = "custom"
            if capability.get("enabled", True) and editor_interface not in settings["capabilities"]:
                settings["capabilities"].append(editor_interface)
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


def _ensure_brightness_capability(device, entity_id, entity):
    """Add brightness control only when Home Assistant reports a dimmable light."""
    if not entity_id.startswith("light.") or not isinstance(entity, dict):
        return False
    modes = entity.get("supported_color_modes") or []
    try:
        dimmable = bool(set(modes) - {"onoff", "unknown"})
    except TypeError:
        dimmable = False
    if not dimmable:
        return False
    capabilities = device.setdefault("capabilities", [])
    if any(cap.get("interface") == "Alexa.BrightnessController"
           and cap.get("entity_id") == entity_id for cap in capabilities):
        return False
    capabilities.append({"interface": "Alexa.BrightnessController", "entity_id": entity_id})
    return True


def _switch_display_category(entity):
    """Infer whether a relay is presented as a light, outlet, or generic switch."""
    if entity.get("device_class") == "outlet":
        return "SMARTPLUG"
    text = " ".join(str(entity.get(key) or "") for key in
                     ("entity_id", "name", "original_name", "_device_name")).casefold()
    if any(word in text for word in ("steckdose", "stecker", "smart plug", "socket", "outlet", "plug")):
        return "SMARTPLUG"
    if any(word in text for word in ("lampe", "licht", "light", "beleuchtung", "bulb")):
        return "LIGHT"
    # A simple relay used for a heating valve still has on/off semantics. A
    # real setpoint and measured temperature require a climate entity.
    return "SWITCH"


def _display_category(entity_id, entity, requested, mode="standard"):
    if mode == "custom" and requested and str(requested).upper() != "OTHER":
        return str(requested).upper()
    domain = entity_id.split(".", 1)[0]
    if domain == "switch":
        return _switch_display_category(entity)
    if domain == "cover":
        return "GARAGE_DOOR" if entity.get("device_class") == "garage" else "INTERIOR_BLIND"
    if domain == "climate":
        return "THERMOSTAT"
    if domain == "light":
        return "LIGHT"
    if domain == "binary_sensor":
        device_class = entity.get("device_class")
        if device_class in ("door", "window", "opening", "garage_door", "lock"):
            return "CONTACT_SENSOR"
        if device_class in ("motion", "occupancy", "presence"):
            return "MOTION_SENSOR"
    if domain == "sensor" and entity.get("device_class") == "temperature":
        return "TEMPERATURE_SENSOR"
    return str(entity.get("category_suggestion") or "OTHER").upper()


def _entity_capabilities(entity_id, settings, entity, *, mode="standard", selected=None):
    """Build Alexa functions from the standard profile or an explicit custom selection."""
    if mode not in ("standard", "custom"):
        raise ValueError("Funktionsprofil muss Standard oder eigene Funktionen sein.")
    values = {**settings, "enabled": True,
              "display_category": _display_category(
                  entity_id, entity, settings.get("display_category"),
                  settings.get("display_category_mode", "standard"))}
    draft = candidate(entity_id, values)
    if draft is None:
        raise ValueError(f"Für {entity_id} gibt es kein passendes Alexa-Standardprofil.")
    catalog_device = {"capabilities": copy.deepcopy(draft["capabilities"])}
    _ensure_brightness_capability(catalog_device, entity_id, entity)
    defaults = catalog_device["capabilities"]
    if entity_id.startswith("climate."):
        modes = {"heat": "HEAT", "cool": "COOL", "auto": "AUTO",
                 "heat_cool": "AUTO", "off": "OFF", "eco": "ECO"}
        supported = sorted({modes[item] for item in entity.get("hvac_modes", []) if item in modes})
        if not set(supported) & {"HEAT", "COOL"}:
            raise ValueError(f"Keine unterstützten Thermostatmodi: {entity_id}")
        defaults[0]["supported_modes"] = supported
    if mode == "standard":
        return defaults

    catalog = copy.deepcopy(defaults)
    if entity_id.startswith("cover."):
        # Stopping is an optional custom function; the standard is only the
        # position RangeController/slider requested for roller shutters.
        catalog.append({"interface": "Alexa.PlaybackController", "entity_id": entity_id,
                        "supported_operations": ["Stop"], "enabled": False})
    selected = selected if isinstance(selected, list) else [
        cap["interface"] for cap in defaults
    ]
    supported_interfaces = {cap["interface"] for cap in catalog}
    if any(not isinstance(interface, str) or interface not in supported_interfaces
           for interface in selected):
        raise ValueError(f"Nicht unterstützte eigene Alexa-Funktion für {entity_id}.")
    selected_interfaces = set(selected)
    if not selected_interfaces:
        raise ValueError(f"Mindestens eine Alexa-Funktion für {entity_id} auswählen.")
    for capability in catalog:
        capability["enabled"] = capability["interface"] in selected_interfaces
        capability["capability_mode"] = "custom"
    return catalog


def _normalize_combined_power_controllers(devices):
    """Use unique ToggleController instances for multiple combined relays."""
    for device in devices.values():
        if device.get("group_mode") != "combined":
            continue
        powers = [cap for cap in device.get("capabilities", [])
                  if cap.get("interface") == "Alexa.PowerController"]
        toggles = [cap for cap in device.get("capabilities", [])
                   if cap.get("interface") == "Alexa.ToggleController"
                   and str(cap.get("instance", "")).startswith("power_")]
        if len(powers) + len(toggles) <= 1:
            continue
        controls = powers + toggles
        unsupported = [cap["entity_id"] for cap in controls
                       if not cap["entity_id"].startswith(("switch.", "input_boolean."))]
        if unsupported:
            raise ValueError("Mehrere Alexa-Schaltfunktionen lassen sich nur bei Relais zusammenfassen. "
                             "Verwende einzelne Alexa-Geräte für: " + ", ".join(unsupported))
        for capability in powers:
            capability["interface"] = "Alexa.ToggleController"
            capability["instance"] = "power_" + hashlib.sha256(
                capability["entity_id"].encode("utf-8")).hexdigest()[:12]
            capability.setdefault("capability_names", [capability["entity_id"]])


def standard_device_group(ha_device):
    """Return the safe standard export for one physical HA device.

    The default keeps useful controls together where Alexa can address them
    unambiguously. Multiple relay switches can be represented as named toggle
    instances; repeated non-instance controllers stay separate endpoints.
    """
    device_name = str(ha_device.get("name") or ha_device.get("device_id") or "Gerät")
    entities = [entity for entity in ha_device.get("entities", [])
                if isinstance(entity, dict) and isinstance(entity.get("entity_id"), str)]
    climate_ids = [entity["entity_id"] for entity in entities
                   if entity["entity_id"].startswith("climate.")]
    selected = []
    capabilities = {}
    for entity in entities:
        entity_id = entity["entity_id"]
        domain = str(entity.get("domain") or entity_id.split(".", 1)[0])
        if entity.get("entity_category") or domain not in {
            "light", "switch", "fan", "cover", "climate", "binary_sensor", "sensor"
        }:
            continue
        if domain == "sensor" and (entity.get("device_class") != "temperature" or climate_ids):
            continue
        category = _display_category(entity_id, entity, None)
        try:
            standard = _entity_capabilities(
                entity_id, {"enabled": True, "display_category": category}, entity
            )
        except ValueError:
            continue
        if (domain == "cover"
                and int(entity.get("supported_features", 0) or 0) & 4 != 4):
            continue
        if standard:
            selected.append(entity)
            capabilities[entity_id] = standard

    if not selected:
        return {"mode": "combined", "entity_ids": [], "name": device_name,
                "reason": "unsupported", "endpoint_count": 0, "functions": []}

    interface_entities = {}
    for entity in selected:
        entity_id = entity["entity_id"]
        for capability in capabilities[entity_id]:
            interface_entities.setdefault(capability["interface"], []).append(entity)

    mode = "combined"
    reason = "standard"
    for interface, members in interface_entities.items():
        if len(members) <= 1:
            continue
        if interface == "Alexa.PowerController" and all(
            entity["entity_id"].startswith(("switch.", "input_boolean."))
            for entity in members
        ):
            reason = "relay_outputs"
        elif interface == "Alexa.RangeController" and all(
            entity["entity_id"].startswith("cover.") for entity in members
        ):
            reason = "multiple_positions"
        else:
            mode = "separate"
            reason = "separate_controls"
            break

    function_rows = [
        {"entity_id": entity["entity_id"],
         "entity_name": str(entity.get("name") or entity["entity_id"]),
         "interfaces": [capability["interface"] for capability in capabilities[entity["entity_id"]]]}
        for entity in selected
    ]
    return {
        "mode": mode,
        "entity_ids": [entity["entity_id"] for entity in selected],
        "name": device_name,
        "reason": reason,
        "endpoint_count": 1 if mode == "combined" else len(selected),
        "functions": function_rows,
    }


def _standard_group_inputs(ha_device, current):
    defaults = standard_device_group(ha_device)
    names_by_entity = entity_settings(current)
    names = {}
    profiles = {}
    raw_by_id = {entity["entity_id"]: entity for entity in ha_device.get("entities", [])
                 if isinstance(entity, dict) and isinstance(entity.get("entity_id"), str)}
    for entity_id in defaults["entity_ids"]:
        entity = raw_by_id[entity_id]
        names[entity_id] = str(names_by_entity.get(entity_id, {}).get("name")
                               or entity.get("name") or entity_id)
        category = _display_category(entity_id, entity, None)
        caps = _entity_capabilities(entity_id, {"enabled": True, "display_category": category}, entity)
        profiles[entity_id] = {
            "mode": "standard",
            "capabilities": [cap["interface"] for cap in caps],
            "display_category": category,
            "display_category_mode": "standard",
        }
    return defaults, names, profiles


def apply_entities(native, requested, inventory):
    """Change existing logical devices in place; create only explicitly selected ones."""
    proposed = copy.deepcopy(native)
    baseline = entity_settings(native)
    actual = {entity["entity_id"]: {**entity, "_device_name": device.get("name", "")}
              for device in inventory.get("devices", []) for entity in device.get("entities", [])}
    for entity_id, settings in requested.items():
        if not isinstance(settings, dict) or type(settings.get("enabled", False)) is not bool:
            raise ValueError("Entitätsauswahl muss ein boolescher Wert sein.")
        old = baseline.get(entity_id, {})
        fields = ("enabled", "name", "description", "display_category",
                  "display_category_mode", "alexa_group")
        changes = {key: settings[key] for key in fields
                   if key in settings and settings[key] != old.get(key, False if key == "enabled" else "")}
        owners = [key for key, device in proposed["devices"].items()
                  if any(cap["entity_id"] == entity_id for cap in device.get("capabilities", []))]
        entity = actual.get(entity_id)
        brightness_added = False
        if owners and entity and settings.get("enabled", old.get("enabled", False)):
            for owner in owners:
                brightness_added = _ensure_brightness_capability(
                    proposed["devices"][owner], entity_id, entity
                ) or brightness_added
        requested_profile = settings.get("capability_mode", old.get("capability_mode", "standard"))
        requested_capabilities = settings.get("capabilities", old.get("capabilities", []))
        apply_profile = (
            settings.get("apply_capability_profile") is True
            or requested_profile != old.get("capability_mode", "standard")
            or requested_capabilities != old.get("capabilities", [])
        )
        if not changes and not brightness_added and not apply_profile:
            continue
        if not owners:
            if not settings.get("enabled"):
                continue
            if not entity:
                raise ValueError(f"HA-Entität nicht verfügbar: {entity_id}")
            category = _display_category(
                entity_id, entity, settings.get("display_category"),
                settings.get("display_category_mode", "standard"))
            draft = candidate(entity_id, {**settings, "display_category": category})
            if draft is None:
                raise ValueError(f"Gerätetyp wird von v6 noch nicht unterstützt: {entity_id}")
            mode = settings.get("capability_mode", "standard")
            selected_interfaces = settings.get("capabilities")
            needs_position = (mode == "standard" or not isinstance(selected_interfaces, list)
                              or "Alexa.RangeController" in selected_interfaces)
            if (entity_id.startswith("cover.") and needs_position
                    and int(entity.get("supported_features", 0)) & 4 != 4):
                raise ValueError(f"Positionsunterstützung fehlt: {entity_id}")
            draft["capabilities"] = _entity_capabilities(
                entity_id, {**settings, "display_category": category}, entity,
                mode=mode, selected=settings.get("capabilities"))
            key = "ha:" + entity_id
            proposed["devices"][key] = draft
            owners = [key]
        elif apply_profile:
            if not entity:
                raise ValueError(f"HA-Entität für Standardprofil nicht verfügbar: {entity_id}")
            mode = settings.get("capability_mode", "standard")
            capabilities = _entity_capabilities(
                entity_id, settings, entity, mode=mode,
                selected=settings.get("capabilities"))
            for owner in owners:
                device = proposed["devices"][owner]
                if device.get("group_mode") == "combined":
                    member_name = str(settings.get("name") or entity_id)
                    for capability in capabilities:
                        capability.setdefault("capability_names", [member_name])
                device["capabilities"] = [
                    capability for capability in device.get("capabilities", [])
                    if capability.get("entity_id") != entity_id
                ] + copy.deepcopy(capabilities)
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
            if (entity and device_changes.get("display_category_mode",
                                              device.get("display_category_mode", "standard")) != "custom"
                    and ("display_category" in device_changes or "display_category_mode" in device_changes)):
                device_changes["display_category"] = _display_category(entity_id, entity, None)
            if device.get("group_mode") == "combined" and "name" in device_changes:
                # The endpoint name belongs to the group editor. A row name is
                # the member control's accessible name (used by ToggleController).
                for capability in device.get("capabilities", []):
                    if capability["entity_id"] == entity_id:
                        capability["capability_names"] = [device_changes["name"]]
                device_changes.pop("name")
            device.update(device_changes)
    _normalize_combined_power_controllers(proposed["devices"])
    return NativeSkillConfigStore.validate(proposed)


def apply_device_group(native, device_id, entity_ids, mode, group_name, inventory, names=None,
                       profiles=None):
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
        raise ValueError("Alle ausgewählten Entitäten müssen zum selben Home-Assistant-Gerät gehören.")
    names = names if isinstance(names, dict) else {}
    profiles = profiles if isinstance(profiles, dict) else {}
    selected_settings = {}
    for entity_id in selected:
        selected_settings[entity_id] = {"enabled": True}
        member_name = str(names.get(entity_id) or "").strip()
        if member_name:
            selected_settings[entity_id]["name"] = member_name
        profile = profiles.get(entity_id)
        if profile is not None:
            if not isinstance(profile, dict):
                raise ValueError(f"Ungültiges Funktionsprofil für {entity_id}.")
            mode_value = profile.get("mode", "standard")
            interfaces = profile.get("capabilities", [])
            if mode_value not in ("standard", "custom") or not isinstance(interfaces, list):
                raise ValueError(f"Ungültiges Funktionsprofil für {entity_id}.")
            selected_settings[entity_id].update({
                "capability_mode": mode_value,
                "capabilities": interfaces,
                "apply_capability_profile": True,
            })
            category = profile.get("display_category")
            if category:
                selected_settings[entity_id]["display_category"] = category
                selected_settings[entity_id]["display_category_mode"] = profile.get(
                    "display_category_mode", "standard")
    # First materialize newly selected entities and apply their member labels.
    # Then rebuild only this physical HA device's selected capabilities. This
    # also removes unchecked members from an old combined endpoint instead of
    # silently leaving them exported.
    proposed = apply_entities(native, selected_settings, inventory)
    physical_entities = {entity.get("entity_id") for entity in ha_device.get("entities", [])
                         if isinstance(entity, dict) and isinstance(entity.get("entity_id"), str)}
    capabilities_by_entity = {entity_id: [] for entity_id in selected}
    member_templates = {}
    existing_group_key = next((key for key, device in proposed["devices"].items()
                               if device.get("group_mode") == "combined"
                               and device.get("ha_device_id") == device_id), None)
    group_key = (existing_group_key or
                 ("ha:" + selected[0] if len(selected) == 1 else
                  "ha:group:" + hashlib.sha256(device_id.encode("utf-8")).hexdigest()[:16]))
    old_group = copy.deepcopy(proposed["devices"].get(group_key))
    for endpoint_id, device in list(proposed["devices"].items()):
        keep = []
        moved = []
        for capability in device.get("capabilities", []):
            entity_id = capability["entity_id"]
            if entity_id in physical_entities:
                moved.append(copy.deepcopy(capability))
                if entity_id in capabilities_by_entity:
                    capabilities_by_entity[entity_id].append(copy.deepcopy(capability))
                member_templates.setdefault(entity_id, copy.deepcopy(device))
            else:
                keep.append(capability)
        if not moved:
            continue
        if keep:
            device["capabilities"] = keep
            device["enabled"] = any(cap.get("enabled", True) for cap in keep)
            if device.get("group_mode") == "combined":
                device["members"] = sorted({cap["entity_id"] for cap in keep})
        else:
            del proposed["devices"][endpoint_id]

    # The deterministic group key is owned by this HA device. Remove any
    # remaining members absent from today's HA inventory so stale members do
    # not survive when the user changes the group or switches back to separate.
    proposed["devices"].pop(group_key, None)

    missing = [entity_id for entity_id, caps in capabilities_by_entity.items() if not caps]
    if missing:
        raise ValueError("Keine v6-Funktionen für: " + ", ".join(missing))

    if mode == "combined":
        group_name = str(group_name or "").strip()
        if not group_name or len(group_name) > 128:
            raise ValueError("Der Alexa-Gesamtname muss 1 bis 128 Zeichen enthalten.")
        powers = [cap for values in capabilities_by_entity.values() for cap in values
                  if cap["interface"] == "Alexa.PowerController"]
        toggles = [cap for values in capabilities_by_entity.values() for cap in values
                   if cap["interface"] == "Alexa.ToggleController"
                   and str(cap.get("instance", "")).startswith("power_")]
        if len(powers) + len(toggles) > 1:
            controls = powers + toggles
            unsupported = [cap["entity_id"] for cap in controls
                           if not cap["entity_id"].startswith(("switch.", "input_boolean."))]
            if unsupported:
                raise ValueError("Mehrere PowerController können nur für Schalter als Alexa-Gesamtgerät kombiniert werden. Verwende einzelne Alexa-Geräte für: " + ", ".join(unsupported))
            for capability in powers:
                capability["interface"] = "Alexa.ToggleController"
                capability["instance"] = "power_" + hashlib.sha256(
                    capability["entity_id"].encode("utf-8")).hexdigest()[:12]
                capability["capability_names"] = [
                    str(names.get(capability["entity_id"]) or capability["entity_id"])
                ]
        positions = [cap for values in capabilities_by_entity.values() for cap in values
                     if cap["interface"] == "Alexa.RangeController"
                     and cap["entity_id"].startswith("cover.")]
        if len(positions) > 1:
            for capability in positions:
                capability["instance"] = "cover.position_" + hashlib.sha256(
                    capability["entity_id"].encode("utf-8")).hexdigest()[:12]
                capability["capability_names"] = [
                    str(names.get(capability["entity_id"]) or capability["entity_id"])
                ]
        for entity_id, capabilities in capabilities_by_entity.items():
            label = str(names.get(entity_id) or entity_id)
            for capability in capabilities:
                capability.setdefault("capability_names", [label])
                capability["enabled"] = True
        combined = [cap for values in capabilities_by_entity.values() for cap in values]
        aliases = list(dict.fromkeys(str(names.get(eid) or eid) for eid in selected))
        description = (old_group or {}).get("description", "")
        member_categories = {member_templates[entity_id].get("display_category", "OTHER")
                             for entity_id in selected}
        category = (next(iter(member_categories)) if len(member_categories) == 1
                    else "SWITCH" if all(entity_id.startswith(("switch.", "input_boolean."))
                                         for entity_id in selected)
                    else (old_group or {}).get("display_category", "OTHER"))
        proposed["devices"][group_key] = {
            "name": group_name,
            "description": description,
            "display_category": category,
            "aliases": aliases,
            "capabilities": combined,
            "enabled": True,
            "ha_device_id": device_id,
            "group_mode": "combined",
            "members": sorted(set(selected)),
        }
    else:
        for entity_id in selected:
            template = member_templates[entity_id]
            key = "ha:" + entity_id
            name = str(names.get(entity_id) or "").strip()
            if not name:
                capability_names = next((cap.get("capability_names", []) for cap in capabilities_by_entity[entity_id]
                                         if cap.get("capability_names")), [])
                name = str(capability_names[0] if capability_names else entity_id)
            existing = proposed["devices"].get(key)
            capabilities = capabilities_by_entity[entity_id]
            for capability in capabilities:
                if (capability.get("interface") == "Alexa.ToggleController"
                        and str(capability.get("instance", "")).startswith("power_")
                        and entity_id.startswith(("switch.", "input_boolean."))):
                    capability["interface"] = "Alexa.PowerController"
                    capability.pop("instance", None)
                    capability.pop("capability_names", None)
                if (capability.get("interface") == "Alexa.RangeController"
                        and entity_id.startswith("cover.")):
                    capability["instance"] = "cover.position"
                    capability["capability_names"] = ["Position"]
            if existing:
                capabilities = [*existing.get("capabilities", []), *capabilities]
            proposed["devices"][key] = {
                **template,
                "name": name,
                "capabilities": capabilities,
                "enabled": True,
                # Persist the explicit separate choice so the editor does not
                # silently suggest a combined thermostat again next time.
                "ha_device_id": device_id,
                "group_mode": "separate",
            }
            proposed["devices"][key].pop("members", None)
    try:
        return NativeSkillConfigStore.validate(proposed)
    except ValueError as exc:
        if mode == "combined":
            raise ValueError(f"Diese Funktionen können nicht gemeinsam in einem Alexa-Gerät liegen: {exc} Wähle einzelne Alexa-Geräte.") from exc
        raise


async def read_config(request):
    native = STORE.load()
    preferences = ha_export.CONFIG_STORE.load()
    return web.json_response({"configuration": configuration(native, preferences),
                              "yaml": yaml.safe_dump(native, allow_unicode=True, sort_keys=False),
                              "selected": sum(
                                  bool(d.get("enabled", True) and any(
                                      cap.get("enabled", True) for cap in d.get("capabilities", [])
                                  )) for d in native["devices"].values()
                              )})


async def inventory(request):
    data = await ha_export._inventory()
    data["configuration"] = configuration(STORE.load(), ha_export.CONFIG_STORE.load())
    return web.json_response(data)


async def autosave(request):
    body = await request.json()
    current = STORE.load()
    if not isinstance(body, dict) or body.get("export_mode") != "native":
        return web.json_response({"error": "v5-Export ist entfernt. Bitte die v6-Hauptansicht neu laden."}, status=409)
    if body.get("native_revision") != revision(current):
        return web.json_response({"error": "v6-Konfiguration wurde geändert. Ansicht neu laden."}, status=409)
    try:
        entities = body.get("entities", {})
        if not isinstance(entities, dict):
            raise ValueError("entities muss eine Zuordnung sein.")
        baseline = entity_settings(current)
        inventory = await ha_export._inventory() if any(
            isinstance(v, dict) and (
                (v.get("enabled") and not baseline.get(key, {}).get("enabled"))
                or v.get("capability_mode", "standard") != baseline.get(
                    key, {}).get("capability_mode", "standard")
                or v.get("capabilities", baseline.get(key, {}).get(
                    "capabilities", [])) != baseline.get(key, {}).get("capabilities", [])
                or v.get("display_category_mode", baseline.get(key, {}).get(
                    "display_category_mode", "standard")) != baseline.get(key, {}).get(
                        "display_category_mode", "standard")
                or v.get("display_category", baseline.get(key, {}).get(
                    "display_category", "")) != baseline.get(key, {}).get("display_category", "")
            ) for key, v in entities.items()) else {"devices": []}
        proposed = apply_entities(current, entities, inventory)
        if "native_enabled" in body:
            if type(body["native_enabled"]) is not bool:
                raise ValueError("Native enabled muss boolesch sein.")
            proposed["enabled"] = body["native_enabled"]
        proposed["locale"] = str(body.get("locale") or current["locale"])
        STORE.validate(proposed)
    except (ValueError, TypeError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    changed = revision(proposed) != body["native_revision"]
    # No await between revision check, final recheck and atomic native save.
    if revision(STORE.load()) != body["native_revision"]:
        return web.json_response({"error": "v6-Konfiguration wurde zwischenzeitlich geändert."}, status=409)
    if changed:
        STORE.save(proposed)
    preferences = ha_export.CONFIG_STORE.load()
    # Preserve historical entity data; only UI/connection preferences go into JSON.
    for key in ("ui", "event_gateway", "group_sync"):
        if isinstance(body.get(key), dict):
            preferences[key] = copy.deepcopy(body[key])
    preferences["legacy_export_enabled"] = False
    preferences = ha_export.CONFIG_STORE.save(preferences)
    trigger = request.app.get("native_reconcile_trigger")
    queued = callable(trigger) and changed
    if queued:
        trigger(force=True)
    return web.json_response({"ok": True, "reconciliation_queued": queued,
                              "configuration": configuration(proposed, preferences)})


async def configure_group(request):
    try:
        body = await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(text="Ungültige JSON-Daten.") from exc
    current = STORE.load()
    if not isinstance(body, dict) or body.get("native_revision") != revision(current):
        return web.json_response({"error": "v6-Konfiguration wurde geändert. Ansicht neu laden."}, status=409)
    try:
        inventory = await ha_export._inventory()
        proposed = apply_device_group(
            current,
            body.get("device_id"),
            body.get("entity_ids"),
            body.get("mode"),
            body.get("name"),
            inventory,
            body.get("names"),
            body.get("profiles"),
        )
    except (ValueError, TypeError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    if revision(STORE.load()) != body["native_revision"]:
        return web.json_response({"error": "v6-Konfiguration wurde zwischenzeitlich geändert."}, status=409)
    changed = revision(proposed) != body["native_revision"]
    if changed:
        STORE.save(proposed)
    trigger = request.app.get("native_reconcile_trigger")
    queued = callable(trigger) and changed
    if queued and changed:
        trigger(force=True)
    return web.json_response({"ok": True, "reconciliation_queued": queued,
                              "configuration": configuration(proposed, ha_export.CONFIG_STORE.load())})


async def auto_group(request):
    """Apply standard profiles to the requested physical HA devices in one save."""
    try:
        body = await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(text="Ungültige JSON-Daten.") from exc
    current = STORE.load()
    if not isinstance(body, dict) or body.get("native_revision") != revision(current):
        return web.json_response({"error": "v6-Konfiguration wurde geändert. Ansicht neu laden."}, status=409)
    device_ids = body.get("device_ids")
    if (not isinstance(device_ids, list) or not device_ids or len(device_ids) > 500
            or any(not isinstance(device_id, str) or not device_id.strip() for device_id in device_ids)):
        return web.json_response({"error": "Mindestens ein gültiges Home-Assistant-Gerät auswählen."}, status=400)
    inventory = await ha_export._inventory()
    available = {str(item.get("device_id") or ""): item
                 for item in inventory.get("devices", []) if isinstance(item, dict)}
    proposed = copy.deepcopy(current)
    configured = []
    skipped = []
    for device_id in dict.fromkeys(device_ids):
        ha_device = available.get(device_id)
        if not ha_device:
            skipped.append({"device_id": device_id, "reason": "Home-Assistant-Gerät nicht mehr verfügbar."})
            continue
        defaults, names, profiles = _standard_group_inputs(ha_device, proposed)
        if not defaults["entity_ids"]:
            skipped.append({"device_id": device_id, "reason": "Keine unterstützte Standardfunktion gefunden."})
            continue
        try:
            candidate = apply_device_group(
                proposed, device_id, defaults["entity_ids"], defaults["mode"],
                defaults["name"], inventory, names, profiles,
            )
            candidate = STORE.validate(candidate)
        except (ValueError, TypeError) as exc:
            skipped.append({"device_id": device_id, "reason": str(exc)})
            continue
        proposed = candidate
        configured.append({"device_id": device_id, "name": defaults["name"],
                           "endpoint_count": defaults["endpoint_count"],
                           "entity_count": len(defaults["entity_ids"]),
                           "mode": defaults["mode"]})
    changed = revision(proposed) != body["native_revision"]
    if changed:
        if revision(STORE.load()) != body["native_revision"]:
            return web.json_response({"error": "v6-Konfiguration wurde zwischenzeitlich geändert."}, status=409)
        STORE.save(proposed)
    trigger = request.app.get("native_reconcile_trigger")
    queued = callable(trigger) and changed
    if queued and changed:
        trigger(force=True)
    return web.json_response({"ok": True, "configured": configured, "skipped": skipped,
                              "reconciliation_queued": queued,
                              "configuration": configuration(proposed, ha_export.CONFIG_STORE.load())})


def normalize_active_device_groups(native, inventory):
    """Apply standard grouping to already-enabled legacy v6 endpoints.

    This runs only from the owner's explicit "send changes to Alexa" action.
    It never enables an unselected entity, and it preserves groups/capability
    profiles that were explicitly configured in the grouping editor. The one
    automatic cleanup is a temperature helper on the same physical device as
    an active climate entity: the thermostat endpoint already reports both
    values, so Alexa should not show another device for that sensor.
    """
    proposed = copy.deepcopy(native)
    changed_groups = []
    devices = [item for item in inventory.get("devices", []) if isinstance(item, dict)]

    for ha_device in devices:
        device_id = str(ha_device.get("device_id") or "")
        physical_ids = {entity.get("entity_id") for entity in ha_device.get("entities", [])
                        if isinstance(entity, dict) and isinstance(entity.get("entity_id"), str)}
        if not device_id or not physical_ids:
            continue

        owners = [device for device in proposed.get("devices", {}).values()
                  if any(capability.get("entity_id") in physical_ids
                         for capability in device.get("capabilities", []))]
        # An explicit combined/separate choice, custom profile, or custom
        # category is the user's override to the standard.
        if any(device.get("group_mode") in ("combined", "separate")
               or device.get("display_category_mode") == "custom"
               or any(capability.get("capability_mode") == "custom"
                      for capability in device.get("capabilities", []))
               or any(capability.get("enabled", True) is False
                      for capability in device.get("capabilities", []))
               for device in owners):
            continue

        active_ids = {
            capability["entity_id"]
            for device in owners
            if device.get("enabled", True)
            for capability in device.get("capabilities", [])
            if capability.get("enabled", True)
            and capability.get("entity_id") in physical_ids
        }
        if not active_ids:
            continue

        defaults, names, profiles = _standard_group_inputs(ha_device, proposed)
        selected = [entity_id for entity_id in defaults["entity_ids"] if entity_id in active_ids]
        if not selected:
            continue

        removed_ids = active_ids - set(selected)
        active_climates = {entity_id for entity_id in selected if entity_id.startswith("climate.")}
        # Only remove a deliberately redundant temperature sensor. Other
        # nonstandard active controls need explicit review in the editor.
        redundant_temperature_helpers = {
            entity.get("entity_id") for entity in ha_device.get("entities", [])
            if isinstance(entity, dict)
            and entity.get("entity_id") in removed_ids
            and entity.get("domain") in {"sensor", "number", "input_number"}
            and (
                (entity.get("domain") == "sensor"
                 and entity.get("device_class") == "temperature")
                or any(token in " ".join(str(entity.get(key) or "").casefold()
                                         for key in ("entity_id", "name", "original_name"))
                       for token in ("wunschtemperatur", "solltemperatur", "sollwert",
                                     "target temperature", "target_temperature", "setpoint"))
            )
        } if active_climates else set()
        if removed_ids != redundant_temperature_helpers:
            continue

        needs_regrouping = len(selected) > 1 or bool(removed_ids)
        if not needs_regrouping:
            continue

        # Keep a safe standard separate layout where Alexa cannot disambiguate
        # repeated controllers. The group editor can combine or customize it.
        try:
            candidate = apply_device_group(
                proposed, device_id, selected, defaults["mode"], defaults["name"],
                inventory, names, profiles,
            )
            candidate = NativeSkillConfigStore.validate(candidate)
        except (ValueError, TypeError):
            continue
        if revision(candidate) == revision(proposed):
            continue
        old_endpoint_count = len({key for key, device in proposed["devices"].items()
                                  if any(capability.get("entity_id") in active_ids
                                         for capability in device.get("capabilities", []))})
        proposed = candidate
        changed_groups.append({
            "device_id": device_id,
            "name": defaults["name"],
            "entity_count": len(selected),
            "endpoint_count": 1 if defaults["mode"] == "combined" else len(selected),
            "old_endpoint_count": old_endpoint_count,
            "removed_helpers": len(removed_ids),
            "mode": defaults["mode"],
        })

    return NativeSkillConfigStore.validate(proposed), changed_groups


async def preview(request):
    return await read_config(request)


async def save_yaml(request):
    body = await request.json()
    current = STORE.load()
    if not isinstance(body, dict) or body.get("native_revision") != revision(current):
        return web.json_response({"error": "v6-Konfiguration geändert. YAML neu laden."}, status=409)
    try:
        if not isinstance(body.get("yaml"), str):
            raise ValueError("YAML-Text fehlt.")
        proposed = STORE.validate(yaml.safe_load(body["yaml"]))
    except (ValueError, TypeError, yaml.YAMLError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    changed = revision(proposed) != body["native_revision"]
    if revision(STORE.load()) != body["native_revision"]:
        return web.json_response({"error": "v6-Konfiguration wurde zwischenzeitlich geändert."}, status=409)
    if changed:
        STORE.save(proposed)
    trigger = request.app.get("native_reconcile_trigger")
    queued = callable(trigger) and changed
    if queued:
        trigger(force=True)
    return web.json_response({"ok": True, "reconciliation_queued": queued,
                              "configuration": configuration(proposed, ha_export.CONFIG_STORE.load())})


def register_routes(app):
    app.router.add_get("/api/native-export/config", read_config)
    app.router.add_post("/api/native-export/yaml", save_yaml)
    app.router.add_post("/api/native-export/group", configure_group)
    app.router.add_post("/api/native-export/auto-group", auto_group)
    app.router.add_post("/api/native-export/setup", setup_sync_service)


async def setup_sync_service(request):
    """Apply the saved sync setting without publishing or restarting HA."""
    return await deploy(request, only_if_changed=True)


async def deploy(request, *, only_if_changed=False):
    # v6 YAML is already atomic/live. HA YAML only retains OAuth/event plumbing,
    # with an unconditional deny-all v5 filter.
    preferences = ha_export.CONFIG_STORE.load()
    enabled = support._event_settings(preferences)["enabled"]
    if only_if_changed and not enabled:
        return web.json_response({"ok": True, "configured": False, "restart_required": False,
                                  "note": "Einstellungen gespeichert. Alexa-Abgleich ist deaktiviert."})
    target = ha_export.ALEXA_YAML_PATH
    previous = target.read_bytes() if target.exists() else None
    try:
        rendered = ha_export.YAML_GENERATOR.generate(preferences)
    except ValueError:
        return web.json_response({"error": "Alexa-Abgleich ist ungültig konfiguriert. Amazon-Region und Secret-Namen prüfen."}, status=400)
    yaml_changed = previous != rendered.yaml_text.encode("utf-8")
    component = support.deploy_component() if enabled else {}
    available = await support._service_available() if only_if_changed else False
    restart_required = not only_if_changed or yaml_changed or bool(component.get("restart_required")) or not available
    written = not only_if_changed or yaml_changed
    if written:
        ha_export.YAML_GENERATOR.deploy(preferences)
    check = await ha_control.check_config() if restart_required else {"valid": True}
    if not check.get("valid"):
        if written:
            if previous is None:
                target.unlink(missing_ok=True)
            else:
                support._atomic_write_bytes(target, previous)
        return web.json_response({"error": check.get("message") or "HA-Konfiguration ungültig.", "check": check}, status=400)
    native = STORE.load()
    return web.json_response({"ok": True, "selected_count": sum(
        bool(device.get("enabled", True) and any(
            capability.get("enabled", True) for capability in device.get("capabilities", [])
        )) for device in native["devices"].values()
    ) if native["enabled"] else 0,
                              "path": str(STORE.path), "configured": True, "restart_required": restart_required,
                              "component": component, "check": check,
                              "note": ("Einstellungen gespeichert. Alexa-Abgleich ist eingerichtet. Bitte HA neu starten, um den Dienst und seine Konfiguration zu laden."
                                       if restart_required else "Einstellungen gespeichert. Alexa-Abgleich ist bereits eingerichtet und in Home Assistant verfügbar.")})


def install():
    ha_export.inventory = inventory
    ha_export.configuration = read_config
    ha_export.autosave = autosave
    ha_export.preview = preview
    ha_export.save = deploy
    ha_control.checked_deploy = deploy
