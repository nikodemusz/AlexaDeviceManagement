"""Local-only UI API for opt-in native v6 migration.

No Alexa deletion, v5 YAML mutation, or bulk activation.
"""
from __future__ import annotations

import copy
from aiohttp import web

from native_migration import prepare
from native_skill_config import NativeSkillConfigStore
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
        })
    return {"global_enabled": native["enabled"], "rows": rows,
            "preview": preview, "native_count": len(native["devices"]),
            "legacy_count": sum(bool(d.get("enabled")) for d in legacy.get("entities", {}).values()
                                if isinstance(d, dict))}


def create_routes(store):
    async def page(request):
        from ha_export import STATIC_DIR
        markup = (STATIC_DIR / "native_migration.html").read_text(encoding="utf-8")
        ingress = request.headers.get("X-Ingress-Path", "").rstrip("/")
        return web.Response(text=markup.replace("{{INGRESS_PATH}}", ingress), content_type="text/html")

    async def status(request):
        return web.json_response(summary(store.load(), NATIVE_STORE.load()))

    async def import_drafts(request):
        # Deliberate action; only add disabled drafts. Existing YAML stays as-is.
        current = NATIVE_STORE.load()
        proposed, report = prepare(store.load(), current)
        if report["added"]:
            NATIVE_STORE.save(proposed)
        return web.json_response({"ok": True, "report": report, "data": summary(store.load(), NATIVE_STORE.load())})

    async def activate(request):
        body = await request.json()
        key, enabled = body.get("id"), body.get("enabled")
        if not isinstance(key, str) or type(enabled) is not bool:
            raise web.HTTPBadRequest(text="id and boolean enabled required")
        config = NATIVE_STORE.load()
        device = config["devices"].get(key)
        if device is None or not device.get("replaces_legacy_endpoint"):
            raise web.HTTPBadRequest(text="Unknown migration draft")
        if enabled and not config["enabled"]:
            raise web.HTTPConflict(text="Enable native skill globally in native config.yaml first")
        # Existing mapping is validated by NativeSkillConfigStore.
        proposed = copy.deepcopy(config)
        proposed["devices"][key]["enabled"] = enabled
        NATIVE_STORE.save(proposed)
        return web.json_response({"ok": True, "data": summary(store.load(), proposed)})

    return page, status, import_drafts, activate


def register_routes(app, legacy_store):
    page, status, import_drafts, activate = create_routes(legacy_store)
    app.router.add_get("/migration", page)
    app.router.add_get("/api/native-migration", status)
    app.router.add_post("/api/native-migration/import", import_drafts)
    app.router.add_post("/api/native-migration/activate", activate)
