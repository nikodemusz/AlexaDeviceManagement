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
        owners = [key for key, device in proposed["devices"].items()
                  if any(cap["entity_id"] == entity_id for cap in device.get("capabilities", []))]
        entity = actual.get(entity_id)
        brightness_added = False
        if owners and entity and settings.get("enabled", old.get("enabled", False)):
            for owner in owners:
                brightness_added = _ensure_brightness_capability(
                    proposed["devices"][owner], entity_id, entity
                ) or brightness_added
        if not changes and not brightness_added:
            continue
        if not owners:
            if not settings.get("enabled"):
                continue
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
            _ensure_brightness_capability(draft, entity_id, entity)
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
        raise ValueError("Alle ausgewählten Entitäten müssen zum selben Home-Assistant-Gerät gehören.")
    names = names if isinstance(names, dict) else {}
    selected_settings = {}
    for entity_id in selected:
        selected_settings[entity_id] = {"enabled": True}
        member_name = str(names.get(entity_id) or "").strip()
        if member_name:
            selected_settings[entity_id]["name"] = member_name
    # First materialize newly selected entities and apply their member labels.
    # Then rebuild only this physical HA device's selected capabilities. This
    # also removes unchecked members from an old combined endpoint instead of
    # silently leaving them exported.
    proposed = apply_entities(native, selected_settings, inventory)
    physical_entities = {entity.get("entity_id") for entity in ha_device.get("entities", [])
                         if isinstance(entity, dict) and isinstance(entity.get("entity_id"), str)}
    capabilities_by_entity = {entity_id: [] for entity_id in selected}
    member_templates = {}
    group_key = "ha:group:" + hashlib.sha256(device_id.encode("utf-8")).hexdigest()[:16]
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
        if len(powers) > 1:
            unsupported = [cap["entity_id"] for cap in powers
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
        for entity_id, capabilities in capabilities_by_entity.items():
            label = str(names.get(entity_id) or entity_id)
            for capability in capabilities:
                capability.setdefault("capability_names", [label])
                capability["enabled"] = True
        combined = [cap for values in capabilities_by_entity.values() for cap in values]
        aliases = list(dict.fromkeys(str(names.get(eid) or eid) for eid in selected))
        description = (old_group or {}).get("description", "")
        category = ((old_group or {}).get("display_category")
                    or member_templates[selected[0]].get("display_category", "OTHER"))
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
            if existing:
                capabilities = [*existing.get("capabilities", []), *capabilities]
            proposed["devices"][key] = {
                **template,
                "name": name,
                "capabilities": capabilities,
                "enabled": True,
            }
            for field in ("ha_device_id", "group_mode", "members"):
                proposed["devices"][key].pop(field, None)
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
        inventory = await ha_export._inventory() if any(
            v.get("enabled") and not entity_settings(current).get(key, {}).get("enabled")
            for key, v in entities.items() if isinstance(v, dict)) else {"devices": []}
        proposed = apply_entities(current, entities, inventory)
        if "native_enabled" in body:
            if type(body["native_enabled"]) is not bool:
                raise ValueError("Native enabled muss boolesch sein.")
            proposed["enabled"] = body["native_enabled"]
        proposed["locale"] = str(body.get("locale") or current["locale"])
        STORE.validate(proposed)
    except (ValueError, TypeError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    # No await between revision check, final recheck and atomic native save.
    if revision(STORE.load()) != body["native_revision"]:
        return web.json_response({"error": "v6-Konfiguration wurde zwischenzeitlich geändert."}, status=409)
    STORE.save(proposed)
    preferences = ha_export.CONFIG_STORE.load()
    # Preserve historical entity data; only UI/connection preferences go into JSON.
    for key in ("ui", "event_gateway", "group_sync"):
        if isinstance(body.get(key), dict):
            preferences[key] = copy.deepcopy(body[key])
    preferences["legacy_export_enabled"] = False
    preferences = ha_export.CONFIG_STORE.save(preferences)
    trigger = request.app.get("native_reconcile_trigger")
    queued = callable(trigger)
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
        )
    except (ValueError, TypeError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    if revision(STORE.load()) != body["native_revision"]:
        return web.json_response({"error": "v6-Konfiguration wurde zwischenzeitlich geändert."}, status=409)
    STORE.save(proposed)
    trigger = request.app.get("native_reconcile_trigger")
    queued = callable(trigger)
    if queued:
        trigger(force=True)
    return web.json_response({"ok": True, "reconciliation_queued": queued,
                              "configuration": configuration(proposed, ha_export.CONFIG_STORE.load())})


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
    STORE.save(proposed)
    trigger = request.app.get("native_reconcile_trigger")
    queued = callable(trigger)
    if queued:
        trigger(force=True)
    return web.json_response({"ok": True, "reconciliation_queued": queued,
                              "configuration": configuration(proposed, ha_export.CONFIG_STORE.load())})


def register_routes(app):
    app.router.add_get("/api/native-export/config", read_config)
    app.router.add_post("/api/native-export/yaml", save_yaml)
    app.router.add_post("/api/native-export/group", configure_group)
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
