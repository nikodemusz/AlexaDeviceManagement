"""Official Alexa endpoint lifecycle synchronization through Home Assistant."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiohttp import web

import alexa_event_support as support
import ha_export

_HA_CONTROL: Any = None
_ORIGINAL_CLEANUP: Callable[[set[str], set[str]], Awaitable[dict[str, Any]]] | None = None

deployment_plan = support.deployment_plan
_entity_config = support._entity_config
_entities_from_yaml = support._entities_from_yaml


async def sync_status(request: web.Request) -> web.Response:
    result = support.snapshot()
    result["service_available"] = await support._service_available()
    return web.json_response(result)


async def sync_now(request: web.Request) -> web.Response:
    if _HA_CONTROL is None:
        return web.json_response({"ok": False, "error": "Event sync is not installed"}, status=500)

    config = ha_export._load_state()
    settings = support._event_settings(config)
    if not settings["enabled"]:
        return web.json_response({
            "ok": False,
            "error": "Der offizielle Alexa Event Gateway-Abgleich ist deaktiviert.",
            "status": support.snapshot(config),
        }, status=409)

    try:
        request_data = await request.json()
    except Exception:
        request_data = {}
    force = bool(request_data.get("force")) if isinstance(request_data, dict) else False

    current_entities = support._enabled_entities(config)
    stored = support._read_status()
    add_or_update = set(stored.get("pending_add_or_update") or [])
    delete = set(stored.get("pending_delete") or [])
    if force or not add_or_update:
        add_or_update = set(current_entities)

    if not await support._service_available():
        result = {
            "ok": False,
            "error": (
                "Der Home-Assistant-Dienst alexa_device_management_sync.sync ist noch nicht verfügbar. "
                "Home Assistant nach dem Deployment neu starten."
            ),
            "restart_required": True,
            "status": support.snapshot(config),
        }
        support._write_status({"last_attempt_at": int(time.time()), "last_error": result["error"]})
        return web.json_response(result, status=409)

    attempted_at = int(time.time())
    service_payload = {
        "add_or_update": sorted(add_or_update),
        "delete": sorted(delete),
        "entity_config": support._entity_config(config, current_entities),
    }
    try:
        http_status, body = await support._call_sync_service(service_payload)
        service_result = support._service_response(body)
    except Exception as exc:
        http_status = 0
        service_result = {"ok": False, "error": str(exc)}

    official_ok = 200 <= http_status < 300 and bool(service_result.get("ok"))
    fallback: dict[str, Any] | None = None
    remaining_delete = set(delete)

    if official_ok:
        remaining_add: set[str] = set()
        remaining_delete.clear()
        _HA_CONTROL._write_lifecycle_status({
            "discovery_pending": False,
            "last_discovery_confirmed_at": attempted_at,
        })
        last_error = None
    else:
        remaining_add = set(add_or_update)
        last_error = str(
            service_result.get("error")
            or f"Home Assistant service returned HTTP {http_status}"
        )
        if (
            settings["fallback_web_cleanup"]
            and remaining_delete
            and _ORIGINAL_CLEANUP is not None
        ):
            fallback = await _ORIGINAL_CLEANUP(remaining_delete, current_entities)
            failed_entities = {
                str(item.get("entity_id") or "")
                for item in fallback.get("failed", [])
                if isinstance(item, dict)
            }
            if not fallback.get("failed"):
                remaining_delete.clear()
            elif failed_entities:
                remaining_delete = failed_entities

    saved = support._write_status({
        "pending_add_or_update": sorted(remaining_add),
        "pending_delete": sorted(remaining_delete),
        "last_attempt_at": attempted_at,
        "last_success_at": attempted_at if official_ok else stored.get("last_success_at"),
        "last_error": last_error,
        "last_response": service_result,
        "last_fallback": fallback,
    })
    response_status = support.snapshot(config)
    response_status["service_available"] = True
    response_payload = {
        "ok": official_ok,
        "official": service_result,
        "http_status": http_status,
        "fallback": fallback,
        "status": response_status,
        "pending_add_or_update": saved.get("pending_add_or_update", []),
        "pending_delete": saved.get("pending_delete", []),
    }
    return web.json_response(response_payload, status=200 if official_ok else 502)


def install(ha_control: Any) -> None:
    """Wrap deployment/lifecycle handlers and defer cleanup to the official gateway."""
    global _HA_CONTROL, _ORIGINAL_CLEANUP
    if getattr(ha_control, "_ALEXA_EVENT_SYNC_INSTALLED", False):
        return

    _HA_CONTROL = ha_control
    original_checked_deploy = ha_control.checked_deploy
    original_cleanup = ha_control._cleanup_alexa_endpoints
    original_lifecycle_snapshot = ha_control.lifecycle_snapshot
    original_restart = ha_control.restart
    _ORIGINAL_CLEANUP = original_cleanup

    async def deferred_cleanup(
        removed_entities: set[str], enabled_entities: set[str]
    ) -> dict[str, Any]:
        return support._empty_cleanup(removed_entities)

    async def checked_deploy(request: web.Request) -> web.Response:
        stored_before = support._read_status()
        if "deployed_entities" in stored_before:
            previously_deployed = set(stored_before.get("deployed_entities") or [])
        else:
            previously_deployed = support._entities_from_yaml(ha_export.ALEXA_YAML_PATH)

        config_before = ha_export._load_state()
        settings_before = support._event_settings(config_before)
        if settings_before["enabled"]:
            component = support.deploy_component()
            if component.get("restart_required"):
                return web.json_response({
                    "ok": False,
                    "deployed": False,
                    "rolled_back": False,
                    "bootstrap_required": True,
                    "restart_required": True,
                    "component": component,
                    "error": (
                        "Die Event-Gateway-Komponente wurde installiert oder aktualisiert. "
                        "Home Assistant muss sie zuerst durch einen Neustart laden. Danach die "
                        "Konfiguration erneut ausrollen. alexa.yaml wurde noch nicht verändert."
                    ),
                }, status=409)
        else:
            component = {
                "installed": (support.COMPONENT_TARGET / "manifest.json").exists(),
                "path": str(support.COMPONENT_TARGET),
                "changed_files": [],
                "restart_required": False,
            }
        response = await original_checked_deploy(request)
        if response.status >= 300:
            return response

        payload = support._json_payload(response)
        config = ha_export._load_state()
        settings = support._event_settings(config)
        current_entities = support._enabled_entities(config)
        plan = support.deployment_plan(previously_deployed, current_entities, settings["enabled"])
        removed_entities = plan["removed"]
        now = int(time.time())

        if settings["enabled"]:
            cleanup = support._empty_cleanup(removed_entities)
            cleanup["warnings"].append(
                "Alexa-Löschungen wurden für den offiziellen DeleteReport nach dem Home-Assistant-Neustart vorgemerkt."
            )
            pending_add = sorted(plan["add_or_update"])
            pending_delete = sorted(plan["delete"])
        else:
            cleanup = await original_cleanup(removed_entities, current_entities)
            pending_add = []
            pending_delete = []

        event_status = support._write_status({
            "enabled": settings["enabled"],
            "deployed_entities": sorted(current_entities),
            "pending_add_or_update": pending_add,
            "pending_delete": pending_delete,
            "pending_since": now if pending_add or pending_delete else None,
            "last_deploy_at": now,
            "component": component,
        })

        payload["alexa_cleanup"] = cleanup
        payload["alexa_event_sync"] = {
            **support.snapshot(config),
            "component": component,
        }
        deploy_status = ha_control._read_deploy_status()
        deploy_status.update({
            "alexa_cleanup": cleanup,
            "alexa_event_sync": event_status,
        })
        ha_control._write_deploy_status(deploy_status)
        return web.json_response(payload, status=response.status)

    def lifecycle_snapshot() -> dict[str, Any]:
        result = original_lifecycle_snapshot()
        event = support.snapshot()
        result["event_sync"] = event
        result["event_sync_pending"] = bool(event["enabled"] and event["pending"])
        if result["event_sync_pending"]:
            result["discovery_pending"] = False
        return result

    async def restart(request: web.Request) -> web.Response:
        response = await original_restart(request)
        config = ha_export._load_state()
        if response.status < 300 and support._event_settings(config)["enabled"]:
            ha_control._write_lifecycle_status({"discovery_pending": False})
            payload = support._json_payload(response)
            payload["discovery_pending"] = False
            payload["event_sync_pending"] = support.snapshot(config)["pending"]
            payload["note"] = (
                "Nur Home Assistant Core wird neu gestartet. Sobald der Dienst wieder verfügbar ist, "
                "den offiziellen Alexa-Abgleich starten."
            )
            return web.json_response(payload, status=response.status)
        return response

    ha_control._cleanup_alexa_endpoints = deferred_cleanup
    ha_control.checked_deploy = checked_deploy
    ha_control.lifecycle_snapshot = lifecycle_snapshot
    ha_control.restart = restart
    ha_export.save = checked_deploy
    ha_control._ALEXA_EVENT_SYNC_INSTALLED = True


def register_routes(app: web.Application) -> None:
    app.router.add_get("/api/ha-export/event-sync/status", sync_status)
    app.router.add_post("/api/ha-export/event-sync", sync_now)
