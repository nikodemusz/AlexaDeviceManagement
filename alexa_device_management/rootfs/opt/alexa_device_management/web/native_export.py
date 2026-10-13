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
            settings = result.setdefault(entity_id, {
                "enabled": False, "name": device.get("name", key),
                "description": device.get("description", ""),
                "display_category": device.get("display_category", "OTHER"),
                "alexa_group": device.get("alexa_group", ""),
                "native_endpoint_ids": [],
            })
            settings["enabled"] |= bool(device.get("enabled", True))
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
            # An entity row edits its complete logical endpoint (e.g. both tank values).
            proposed["devices"][key].update(changes)
    return NativeSkillConfigStore.validate(proposed)


async def read_config(request):
    native = STORE.load()
    preferences = ha_export.CONFIG_STORE.load()
    return web.json_response({"configuration": configuration(native, preferences),
                              "yaml": yaml.safe_dump(native, allow_unicode=True, sort_keys=False),
                              "selected": sum(d.get("enabled", True) for d in native["devices"].values())})


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
    return web.json_response({"ok": True, "configuration": configuration(proposed, preferences)})


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
    return web.json_response({"ok": True, "configuration": configuration(proposed, ha_export.CONFIG_STORE.load())})


def register_routes(app):
    app.router.add_get("/api/native-export/config", read_config)
    app.router.add_post("/api/native-export/yaml", save_yaml)
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
        bool(device.get("enabled", True) and device.get("capabilities")) for device in native["devices"].values()
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
