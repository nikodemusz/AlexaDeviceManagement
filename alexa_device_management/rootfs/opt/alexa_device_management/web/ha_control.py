"""Home Assistant configuration validation, deployment and restart helpers."""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
import time
from typing import Any

import aiohttp
from aiohttp import web

import ha_export
from yaml_generator import GeneratorValidationError

SUPERVISOR_BASE_URL = "http://supervisor"
DEPLOY_STATUS_PATH = pathlib.Path("/data/alexa_device_management/deploy_status.json")
LIFECYCLE_STATUS_PATH = pathlib.Path("/data/alexa_device_management/lifecycle_status.json")


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


def _result_message(body: dict[str, Any] | str) -> str:
    if isinstance(body, dict):
        return str(body.get("message") or body.get("error") or body)
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
    """Persist browser state, deploy from ConfigStore, validate HA and roll back on failure."""
    started_at = int(time.time())
    target = ha_export.ALEXA_YAML_PATH
    previous_exists = target.exists()
    previous_bytes = target.read_bytes() if previous_exists else None
    _write_deploy_status({"state": "running", "started_at": started_at, "finished_at": None, "rolled_back": False})

    try:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if isinstance(payload, dict) and payload:
            ha_export._save_state(payload)

        persisted = ha_export._load_state()
        deployment = ha_export.YAML_GENERATOR.deploy(persisted)
        check = await check_config()
        if not check["ok"]:
            if previous_bytes is None:
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
            else:
                _atomic_write_bytes(target, previous_bytes)
            result = {
                "ok": False, "saved": False, "deployed": False, "rolled_back": True,
                "check": check, "backup": deployment.backup,
                "error": "Home-Assistant-Konfigurationsprüfung fehlgeschlagen; die bisherige Datei wurde wiederhergestellt.",
            }
            _write_deploy_status({
                "state": "failed", "started_at": started_at, "finished_at": int(time.time()),
                "rolled_back": True, "check": check, "backup": deployment.backup, "error": result["error"],
            })
            return web.json_response(result, status=422)

        finished_at = int(time.time())
        result = {
            "ok": True, "saved": True, "deployed": True, "rolled_back": False,
            "path": deployment.path, "backup": deployment.backup, "yaml": deployment.yaml_text,
            "selected": deployment.selected_count, "selected_count": deployment.selected_count,
            "check": check, "restart_required": True,
        }
        _write_deploy_status({
            "state": "success", "started_at": started_at, "finished_at": finished_at,
            "rolled_back": False, "path": deployment.path, "backup": deployment.backup,
            "selected": deployment.selected_count, "selected_count": deployment.selected_count, "check": check,
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
    try:
        requested_at = int(time.time())
        status, body = await _supervisor_post("/core/restart", timeout=30)
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
            "note": "Home Assistant wird neu gestartet. Danach muss die Alexa-Gerätesuche manuell gestartet werden.",
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
