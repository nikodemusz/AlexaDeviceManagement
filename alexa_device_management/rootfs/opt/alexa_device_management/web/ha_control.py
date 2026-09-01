"""Home Assistant configuration validation, deployment and restart helpers."""

from __future__ import annotations

import json
import os
import pathlib
import re
import tempfile
import time
from typing import Any

import aiohttp
from aiohttp import web

import ha_export
import server_clean
from yaml_generator import GeneratorValidationError, load_yaml_with_secrets

SUPERVISOR_BASE_URL = "http://supervisor"
HA_API_BASE_URL = "http://supervisor/core/api"
DEPLOY_STATUS_PATH = pathlib.Path("/data/alexa_device_management/deploy_status.json")
LIFECYCLE_STATUS_PATH = pathlib.Path("/data/alexa_device_management/lifecycle_status.json")
_ENTITY_ID_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$", re.IGNORECASE)


def verify_deployed_configuration(path: pathlib.Path, config: dict[str, Any]) -> list[str]:
    """Verify entity selection and custom names from the file visible after deployment."""
    document = load_yaml_with_secrets(path.read_text(encoding="utf-8"))
    smart_home = document.get("alexa", {}).get("smart_home", {}) if isinstance(document, dict) else {}
    deployed = smart_home.get("filter", {}).get("include_entities", [])
    deployed_entities = {str(entity_id) for entity_id in deployed} if isinstance(deployed, list) else set()
    raw_entities = config.get("entities", {}) if isinstance(config, dict) else {}
    expected_entities = {
        str(entity_id) for entity_id, settings in raw_entities.items()
        if isinstance(settings, dict) and settings.get("enabled")
    }
    if deployed_entities != expected_entities:
        missing = sorted(expected_entities - deployed_entities)
        stale = sorted(deployed_entities - expected_entities)
        raise OSError(f"alexa.yaml verification failed: missing={missing}, stale={stale}")

    deployed_config = smart_home.get("entity_config", {})
    deployed_config = deployed_config if isinstance(deployed_config, dict) else {}
    wrong_names = []
    for entity_id in expected_entities:
        expected_name = str(raw_entities[entity_id].get("name") or "").strip()
        actual = deployed_config.get(entity_id, {})
        actual_name = str(actual.get("name") or "").strip() if isinstance(actual, dict) else ""
        if expected_name and actual_name != expected_name:
            wrong_names.append(entity_id)
    if wrong_names:
        raise OSError(f"alexa.yaml name verification failed: {sorted(wrong_names)}")
    return sorted(deployed_entities)


def _atomic_write_bytes(path: pathlib.Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        dir_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _write_json(path: pathlib.Path, data: dict[str, Any]) -> None:
    try:
        _atomic_write_bytes(
            path,
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
        )
    except OSError:
        pass


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def _write_deploy_status(data: dict[str, Any]) -> None:
    _write_json(DEPLOY_STATUS_PATH, data)


def _read_deploy_status() -> dict[str, Any]:
    return _read_json(DEPLOY_STATUS_PATH)


def _write_lifecycle_status(data: dict[str, Any]) -> None:
    current = _read_json(LIFECYCLE_STATUS_PATH)
    current.update(data)
    _write_json(LIFECYCLE_STATUS_PATH, current)


def _enabled_entities(config: dict[str, Any]) -> set[str]:
    entities = config.get("entities") if isinstance(config, dict) else {}
    if not isinstance(entities, dict):
        return set()
    return {
        str(entity_id)
        for entity_id, settings in entities.items()
        if isinstance(settings, dict) and settings.get("enabled")
    }


def _ha_entity_id_for_device(device: dict[str, Any]) -> str | None:
    """Extract the Home Assistant entity_id exposed in Alexa metadata."""
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    candidates: list[Any] = [
        device.get("ha_entity_id"),
        device.get("family"),
        raw.get("entityId"),
        raw.get("entity_id"),
    ]
    description = str(raw.get("description") or "").strip()
    if description:
        candidates.insert(0, description.partition(" via ")[0].strip())

    for candidate in candidates:
        value = str(candidate or "").strip()
        if _ENTITY_ID_RE.fullmatch(value):
            return value.lower()
    return None


def _cleanup_plan(
    devices: list[dict[str, Any]],
    removed_entities: set[str],
    enabled_entities: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return explicit removals and unreachable duplicates safe to delete."""
    by_entity: dict[str, list[dict[str, Any]]] = {}
    for device in devices:
        entity_id = _ha_entity_id_for_device(device)
        if entity_id:
            by_entity.setdefault(entity_id, []).append(device)

    removed_matches: list[dict[str, Any]] = []
    duplicate_matches: list[dict[str, Any]] = []
    for entity_id in sorted(removed_entities):
        removed_matches.extend(by_entity.get(entity_id.lower(), []))

    for entity_id in sorted(enabled_entities):
        matches = by_entity.get(entity_id.lower(), [])
        if len(matches) < 2:
            continue
        reachable = [item for item in matches if bool(item.get("online"))]
        if not reachable:
            continue
        duplicate_matches.extend(item for item in matches if not bool(item.get("online")))

    removed_serials = {str(item.get("serial") or "") for item in removed_matches}
    duplicate_matches = [
        item for item in duplicate_matches
        if str(item.get("serial") or "") not in removed_serials
    ]
    return removed_matches, duplicate_matches


async def _cleanup_alexa_endpoints(
    removed_entities: set[str], enabled_entities: set[str]
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "requested_entities": sorted(removed_entities),
        "deleted_removed": [],
        "deleted_duplicates": [],
        "not_found": [],
        "failed": [],
        "warnings": [],
    }
    if not removed_entities and not enabled_entities:
        return result
    if not server_clean.is_configured():
        result["warnings"].append(
            "Alexa ist nicht verbunden; deaktivierte Geräte konnten nicht aus Alexa entfernt werden."
        )
        return result

    data = server_clean.session_data()
    devices, errors = await server_clean._fetch_devices_from_alexa(data)
    result["warnings"].extend(errors)
    removed_matches, duplicate_matches = _cleanup_plan(
        devices, removed_entities, enabled_entities
    )

    found_entities = {
        entity_id
        for item in removed_matches
        if (entity_id := _ha_entity_id_for_device(item))
    }
    result["not_found"] = sorted(entity for entity in removed_entities if entity.lower() not in found_entities)

    async def delete_items(items: list[dict[str, Any]], result_key: str) -> None:
        for item in items:
            serial = str(item.get("serial") or "").strip()
            entity_id = _ha_entity_id_for_device(item)
            try:
                await server_clean._delete_target(item, data)
                if serial:
                    server_clean._remove_from_cache([serial])
                result[result_key].append({
                    "entity_id": entity_id,
                    "serial": serial,
                    "name": str(item.get("name") or serial),
                })
            except Exception as exc:
                result["failed"].append({
                    "entity_id": entity_id,
                    "serial": serial,
                    "name": str(item.get("name") or serial),
                    "error": str(exc)[:500],
                })

    await delete_items(removed_matches, "deleted_removed")
    await delete_items(duplicate_matches, "deleted_duplicates")
    return result


def lifecycle_snapshot() -> dict[str, Any]:
    lifecycle = _read_json(LIFECYCLE_STATUS_PATH)
    deploy = _read_deploy_status()
    config = ha_export.CONFIG_STORE.load()
    config_updated_at = int(config.get("updated_at") or 0)
    deployed_at = int(deploy.get("finished_at") or 0) if deploy.get("state") == "success" else 0
    restart_requested_at = int(lifecycle.get("last_restart_requested_at") or 0)
    changes_pending = bool(config_updated_at and config_updated_at > deployed_at)
    restart_required = bool(deployed_at and restart_requested_at < deployed_at)
    discovery_pending = bool(lifecycle.get("discovery_pending")) and not changes_pending
    return {
        "config_updated_at": config_updated_at or None,
        "last_deploy_at": deployed_at or None,
        "last_restart_requested_at": restart_requested_at or None,
        "changes_pending": changes_pending,
        "restart_required": restart_required,
        "discovery_pending": discovery_pending,
        "deploy_state": deploy.get("state"),
        "deployed_count": deploy.get("selected_count", deploy.get("selected")),
        "alexa_discovery": {
            "automatic_supported": False,
            "reason": "Home Assistant und die Alexa-Web-API stellen keinen stabilen, offiziell unterstützten Endpunkt zum Starten einer Alexa-Gerätesuche bereit.",
        },
    }


async def _supervisor_post(path: str, timeout: int = 120) -> tuple[int, dict[str, Any] | str]:
    headers = ha_export._headers()
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(
            f"{SUPERVISOR_BASE_URL}{path}",
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as response:
            text = await response.text()
            try:
                body: dict[str, Any] | str = await response.json(content_type=None)
            except Exception:
                body = text
            return response.status, body


async def _ha_post(path: str, timeout: int = 120) -> tuple[int, dict[str, Any] | list[Any] | str]:
    headers = ha_export._headers()
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(
            f"{HA_API_BASE_URL}{path}",
            json={},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as response:
            text = await response.text()
            try:
                body: dict[str, Any] | list[Any] | str = await response.json(content_type=None)
            except Exception:
                body = text
            return response.status, body


def _result_message(body: dict[str, Any] | list[Any] | str) -> str:
    if isinstance(body, dict):
        return str(body.get("message") or body.get("error") or body)
    if isinstance(body, list):
        return "Home-Assistant-Dienst wurde ausgeführt."
    return str(body or "Unbekannte Antwort")


async def check_config() -> dict[str, Any]:
    status, body = await _supervisor_post("/core/check", timeout=180)
    return {
        "ok": 200 <= status < 300,
        "status": status,
        "message": _result_message(body),
        "response": body,
    }


async def checked_deploy(request: web.Request) -> web.Response:
    """Persist browser state, deploy, validate HA and synchronize removals to Alexa."""
    started_at = int(time.time())
    target = ha_export.ALEXA_YAML_PATH
    previous_exists = target.exists()
    previous_bytes = target.read_bytes() if previous_exists else None
    previous_config = ha_export._load_state()
    previous_enabled = _enabled_entities(previous_config)
    _write_deploy_status({"state": "running", "started_at": started_at, "finished_at": None, "rolled_back": False})

    try:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if isinstance(payload, dict) and payload:
            ha_export._save_state(payload)

        persisted = ha_export._load_state()
        enabled_entities = _enabled_entities(persisted)
        removed_entities = previous_enabled - enabled_entities
        deployment = ha_export.YAML_GENERATOR.deploy(persisted)
        deployed_entities = verify_deployed_configuration(target, persisted)
        check = await check_config()
        if not check["ok"]:
            if previous_bytes is None:
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
            else:
                _atomic_write_bytes(target, previous_bytes)
            check_detail = str(check.get("message") or "Unbekannter Home-Assistant-Prüffehler")
            result = {
                "ok": False, "saved": False, "deployed": False, "rolled_back": True,
                "check": check, "backup": deployment.backup,
                "error": (
                    "Home-Assistant-Konfigurationsprüfung fehlgeschlagen; die bisherige Datei wurde "
                    f"wiederhergestellt. Ursache: {check_detail}"
                ),
            }
            _write_deploy_status({
                "state": "failed", "started_at": started_at, "finished_at": int(time.time()),
                "rolled_back": True, "check": check, "backup": deployment.backup, "error": result["error"],
            })
            return web.json_response(result, status=422)

        alexa_cleanup = await _cleanup_alexa_endpoints(removed_entities, enabled_entities)
        finished_at = int(time.time())
        result = {
            "ok": True, "saved": True, "deployed": True, "rolled_back": False,
            "path": deployment.path, "backup": deployment.backup, "yaml": deployment.yaml_text,
            "selected": deployment.selected_count, "selected_count": deployment.selected_count,
            "deployed_entities": deployed_entities,
            "check": check, "alexa_cleanup": alexa_cleanup, "restart_required": True,
        }
        _write_deploy_status({
            "state": "success", "started_at": started_at, "finished_at": finished_at,
            "rolled_back": False, "path": deployment.path, "backup": deployment.backup,
            "selected": deployment.selected_count, "selected_count": deployment.selected_count,
            "check": check, "alexa_cleanup": alexa_cleanup,
        })
        _write_lifecycle_status({"discovery_pending": False, "last_deploy_at": finished_at})
        return web.json_response(result)
    except GeneratorValidationError as exc:
        _write_deploy_status({"state": "failed", "started_at": started_at, "finished_at": int(time.time()), "rolled_back": False, "error": str(exc)})
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    except Exception as exc:
        if target.exists() and previous_bytes is not None:
            try:
                _atomic_write_bytes(target, previous_bytes)
            except OSError:
                pass
        elif not previous_exists:
            try:
                target.unlink()
            except FileNotFoundError:
                pass
        _write_deploy_status({"state": "failed", "started_at": started_at, "finished_at": int(time.time()), "rolled_back": True, "error": str(exc)})
        return web.json_response({"ok": False, "rolled_back": True, "error": str(exc)}, status=500)


async def deploy_status(request: web.Request) -> web.Response:
    return web.json_response(_read_deploy_status())


async def lifecycle_status(request: web.Request) -> web.Response:
    return web.json_response(lifecycle_snapshot())


async def discovery_guide(request: web.Request) -> web.Response:
    return web.json_response({
        "automatic_supported": False,
        "title": "Alexa-Gerätesuche starten",
        "reason": "Es gibt keinen stabilen, offiziell unterstützten API-Endpunkt zum automatischen Start der Alexa-Gerätesuche.",
        "steps": [
            "Home Assistant nach dem Deployment neu starten.",
            "Zur Alexa-App wechseln und Geräte öffnen.",
            "Oben rechts auf + tippen, Gerät hinzufügen wählen und Andere auswählen.",
            "Geräte suchen starten. Alternativ sagen: Alexa, suche nach meinen Geräten.",
        ],
        "voice_command": "Alexa, suche nach meinen Geräten.",
        "lifecycle": lifecycle_snapshot(),
    })


async def mark_discovery_complete(request: web.Request) -> web.Response:
    _write_lifecycle_status({"discovery_pending": False, "last_discovery_confirmed_at": int(time.time())})
    return web.json_response({"ok": True, **lifecycle_snapshot()})


async def check_config_endpoint(request: web.Request) -> web.Response:
    try:
        result = await check_config()
        return web.json_response(result, status=200 if result["ok"] else 422)
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def restart(request: web.Request) -> web.Response:
    """Restart only Home Assistant Core through its service API."""
    try:
        requested_at = int(time.time())
        status, body = await _ha_post("/services/homeassistant/restart", timeout=30)
        if not 200 <= status < 300:
            return web.json_response({"ok": False, "status": status, "error": _result_message(body), "response": body}, status=502)
        _write_lifecycle_status({
            "last_restart_requested_at": requested_at,
            "discovery_pending": True,
        })
        return web.json_response({
            "ok": True, "status": status, "message": _result_message(body),
            "restart_requested_at": requested_at,
            "discovery_pending": True,
            "note": "Nur Home Assistant Core wird neu gestartet; Host und Supervisor bleiben aktiv.",
        })
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


def install() -> None:
    ha_export.save = checked_deploy


def register_routes(app: web.Application) -> None:
    app.router.add_post("/api/ha-export/check-config", check_config_endpoint)
    app.router.add_get("/api/ha-export/deploy-status", deploy_status)
    app.router.add_post("/api/ha-export/deploy", checked_deploy)
    app.router.add_post("/api/ha-export/restart", restart)
    app.router.add_get("/api/ha-export/lifecycle-status", lifecycle_status)
    app.router.add_get("/api/ha-export/discovery-guide", discovery_guide)
    app.router.add_post("/api/ha-export/discovery-complete", mark_discovery_complete)
