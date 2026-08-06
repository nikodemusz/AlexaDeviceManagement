"""Runtime safeguards for device-oriented Home Assistant Alexa exports."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from aiohttp import web


def install() -> None:
    """Enrich export requests with HA device IDs before save or generation."""
    import ha_export
    from yaml_generator import GeneratorValidationError

    async def enrich_device_ids(data: Any) -> dict[str, Any]:
        result = deepcopy(data) if isinstance(data, dict) else {}
        entities = result.get("entities") if isinstance(result.get("entities"), dict) else {}
        inventory = await ha_export._inventory()
        device_by_entity = {
            str(entity.get("entity_id")): str(device.get("device_id") or "")
            for device in inventory.get("devices", [])
            for entity in device.get("entities", [])
            if entity.get("entity_id")
        }
        for entity_id, settings in entities.items():
            if isinstance(settings, dict):
                settings["device_id"] = device_by_entity.get(
                    str(entity_id), str(settings.get("device_id") or "")
                )
        result["entities"] = entities
        return result

    async def autosave(request: web.Request) -> web.Response:
        try:
            saved = ha_export._save_state(await enrich_device_ids(await request.json()))
            return web.json_response({
                "ok": True,
                "configuration": saved,
                "storage": ha_export.CONFIG_STORE.status(),
            })
        except Exception as exc:
            return web.json_response({
                "ok": False,
                "error": str(exc),
                "storage": ha_export.CONFIG_STORE.status(),
            }, status=500)

    async def preview(request: web.Request) -> web.Response:
        try:
            generated = ha_export.YAML_GENERATOR.generate(
                await enrich_device_ids(await request.json())
            )
            return web.json_response({
                "yaml": generated.yaml_text,
                "selected": generated.selected_count,
            })
        except GeneratorValidationError as exc:
            return web.json_response({"error": str(exc)}, status=400)

    async def save(request: web.Request) -> web.Response:
        try:
            requested = await enrich_device_ids(await request.json())
            saved = ha_export._save_state(requested)
            deployed = ha_export.YAML_GENERATOR.deploy(saved)
            return web.json_response({
                "ok": True,
                "configuration": saved,
                "storage": ha_export.CONFIG_STORE.status(),
                "path": deployed.path,
                "backup": deployed.backup,
                "yaml": deployed.yaml_text,
                "selected": deployed.selected_count,
                "restart_required": True,
            })
        except GeneratorValidationError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except OSError as exc:
            return web.json_response({
                "ok": False,
                "error": f"YAML deployment failed: {exc}",
            }, status=500)

    ha_export.enrich_device_ids = enrich_device_ids
    ha_export.autosave = autosave
    ha_export.preview = preview
    ha_export.save = save
