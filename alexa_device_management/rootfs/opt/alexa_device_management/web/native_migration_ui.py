"""Local-only UI API for opt-in native v6 migration.

No Alexa deletion, v5 YAML mutation, or bulk activation.
"""
from __future__ import annotations

import copy
import hashlib
import yaml
from aiohttp import web

from native_migration import prepare
from native_skill_config import NativeSkillConfigStore, NativeSkillConfigError
from device_model import DeviceModelError

NATIVE_STORE = NativeSkillConfigStore()


def summary(legacy, native):
    candidate_config, preview = prepare(legacy, native)
    rows = []
    for key, device in sorted(candidate_config["devices"].items()):
        if key in native["devices"]:
            device = native["devices"][key]
        replacement = device.get("replaces_legacy_endpoint")
        if not replacement and not key.startswith("ha:"):
            continue
        rows.append({
            "id": key, "name": device["name"],
            "entity_id": key[3:] if key.startswith("ha:") else None,
            "legacy_id": replacement,
            "enabled": device.get("enabled", True),
            "capabilities": [cap["interface"] for cap in device["capabilities"]],
            "status": ("native_active" if device.get("enabled", True)
                       else "draft") if key in native["devices"] else "candidate",
            "can_activate": bool(native["enabled"] and key in native["devices"]
                                 and not device.get("enabled", True)),
            "blocked_reason": ("Native v6 ist global deaktiviert."
                               if key in native["devices"] and not device.get("enabled", True)
                               and not native["enabled"] else None),
        })
    for entity_id in preview["unsupported"]:
        settings = legacy.get("entities", {}).get(entity_id, {})
        rows.append({
            "id": "unsupported:" + entity_id,
            "name": str(settings.get("name") or entity_id),
            "entity_id": entity_id,
            "legacy_id": entity_id.replace(".", "#", 1),
            "enabled": False,
            "capabilities": [],
            "status": "unsupported",
            "can_activate": False,
            "blocked_reason": "Dieser Gerätetyp kann noch nicht automatisch nach v6 migriert werden.",
        })
    rows.sort(key=lambda row: (row["name"].casefold(), row["id"]))
    return {"global_enabled": native["enabled"], "rows": rows,
            "preview": preview, "native_count": len(native["devices"]),
            "legacy_count": sum(bool(d.get("enabled")) for d in legacy.get("entities", {}).values()
                                if isinstance(d, dict))}


def config_revision(value):
    """Optimistic lock against overwriting a concurrent edit."""
    import json
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def config_payload(value):
    return {"yaml": yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
            "revision": config_revision(value),
            "global_enabled": value["enabled"],
            "devices_count": len(value["devices"])}


def create_routes(store):
    async def page(request):
        from ha_export import STATIC_DIR
        markup = (STATIC_DIR / "native_migration.html").read_text(encoding="utf-8")
        ingress = request.headers.get("X-Ingress-Path", "").rstrip("/")
        return web.Response(text=markup.replace("{{INGRESS_PATH}}", ingress), content_type="text/html")

    async def status(request):
        return web.json_response(summary(store.load(), NATIVE_STORE.load()))

    async def read_config(request):
        return web.json_response(config_payload(NATIVE_STORE.load()))

    async def validate_config(request):
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("yaml"), str):
            raise web.HTTPBadRequest(text="YAML text required")
        try:
            parsed = yaml.safe_load(body["yaml"])
            normalized = NATIVE_STORE.validate(parsed)
        except (yaml.YAMLError, NativeSkillConfigError, DeviceModelError, TypeError, ValueError) as exc:
            return web.json_response({"valid": False, "error": str(exc)}, status=400)
        return web.json_response({"valid": True, "devices_count": len(normalized["devices"]),
                                  "global_enabled": normalized["enabled"]})

    async def save_config(request):
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("yaml"), str):
            raise web.HTTPBadRequest(text="YAML text required")
        current = NATIVE_STORE.load()
        if body.get("revision") != config_revision(current):
            return web.json_response({"error": "Native configuration changed; reload before saving"}, status=409)
        try:
            proposed = NATIVE_STORE.validate(yaml.safe_load(body["yaml"]))
        except (yaml.YAMLError, NativeSkillConfigError, DeviceModelError, TypeError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        NATIVE_STORE.save(proposed)
        return web.json_response({"ok": True, "config": config_payload(NATIVE_STORE.load()),
                                  "data": summary(store.load(), NATIVE_STORE.load())})

    async def set_global(request):
        body = await request.json()
        enabled = body.get("enabled") if isinstance(body, dict) else None
        if type(enabled) is not bool:
            raise web.HTTPBadRequest(text="Boolean enabled required")
        current = NATIVE_STORE.load()
        if body.get("revision") != config_revision(current):
            return web.json_response({"error": "Configuration changed; reload first"}, status=409)
        updated = copy.deepcopy(current)
        updated["enabled"] = enabled
        NATIVE_STORE.save(updated)
        return web.json_response({"ok": True, "config": config_payload(NATIVE_STORE.load()),
                                  "data": summary(store.load(), NATIVE_STORE.load())})

    async def import_drafts(request):
        # Deliberate action; only add disabled drafts. Existing YAML stays as-is.
        body = await request.json()
        current = NATIVE_STORE.load()
        if not isinstance(body, dict) or body.get("revision") != config_revision(current):
            return web.json_response({"error": "Configuration changed; reload first"}, status=409)
        proposed, report = prepare(store.load(), current)
        if report["added"]:
            NATIVE_STORE.save(proposed)
        saved = NATIVE_STORE.load()
        return web.json_response({"ok": True, "report": report,
                                  "config": config_payload(saved),
                                  "data": summary(store.load(), saved)})

    async def activate(request):
        body = await request.json()
        key, enabled = body.get("id"), body.get("enabled")
        if not isinstance(key, str) or type(enabled) is not bool:
            raise web.HTTPBadRequest(text="id and boolean enabled required")
        config = NATIVE_STORE.load()
        if body.get("revision") != config_revision(config):
            return web.json_response({"error": "Configuration changed; reload first"}, status=409)
        device = config["devices"].get(key)
        if device is None or not device.get("replaces_legacy_endpoint"):
            raise web.HTTPBadRequest(text="Unknown migration draft")
        if enabled and not config["enabled"]:
            raise web.HTTPConflict(text="Enable native skill globally in native config.yaml first")
        # Existing mapping is validated by NativeSkillConfigStore.
        proposed = copy.deepcopy(config)
        proposed["devices"][key]["enabled"] = enabled
        NATIVE_STORE.save(proposed)
        saved = NATIVE_STORE.load()
        return web.json_response({"ok": True, "config": config_payload(saved),
                                  "data": summary(store.load(), saved)})

    async def bulk_activate(request):
        body = await request.json()
        if not isinstance(body, dict) or type(body.get("enabled")) is not bool:
            raise web.HTTPBadRequest(text="enabled boolean required")
        ids = body.get("ids")
        if not isinstance(ids, list) or not ids or len(ids) > 50 or any(
                not isinstance(item, str) for item in ids) or len(set(ids)) != len(ids):
            raise web.HTTPBadRequest(text="Select 1–50 unique migration device IDs")
        current = NATIVE_STORE.load()
        if body.get("revision") != config_revision(current):
            return web.json_response({"error": "Configuration changed; reload first"}, status=409)
        if body["enabled"] and not current["enabled"]:
            raise web.HTTPConflict(text="Native v6 is globally disabled")
        for key in ids:
            device = current["devices"].get(key)
            if not device or not device.get("replaces_legacy_endpoint") or not device.get("capabilities"):
                raise web.HTTPBadRequest(text="Selection includes an invalid migration device")
        proposed = copy.deepcopy(current)
        for key in ids:
            proposed["devices"][key]["enabled"] = body["enabled"]
        # Validate whole batch before atomic write; never partially activate.
        NATIVE_STORE.validate(proposed)
        NATIVE_STORE.save(proposed)
        saved = NATIVE_STORE.load()
        return web.json_response({"ok": True, "changed": len(ids),
                                  "config": config_payload(saved),
                                  "data": summary(store.load(), saved)})

    return page, status, import_drafts, activate, read_config, validate_config, save_config, set_global, bulk_activate


def register_routes(app, legacy_store):
    page, status, import_drafts, activate, read_config, validate_config, save_config, set_global, bulk_activate = create_routes(legacy_store)
    app.router.add_get("/migration", page)
    app.router.add_get("/api/native-migration/config", read_config)
    app.router.add_post("/api/native-migration/config/validate", validate_config)
    app.router.add_post("/api/native-migration/config/save", save_config)
    app.router.add_post("/api/native-migration/global", set_global)
    app.router.add_get("/api/native-migration", status)
    app.router.add_post("/api/native-migration/import", import_drafts)
    app.router.add_post("/api/native-migration/activate", activate)
    app.router.add_post("/api/native-migration/bulk", bulk_activate)

