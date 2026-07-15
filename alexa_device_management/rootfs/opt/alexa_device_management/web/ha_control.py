"""Home Assistant configuration validation, deployment and restart helpers."""

from __future__ import annotations

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


def _write_deploy_status(data: dict[str, Any]) -> None:
    import json

    try:
        _atomic_write_bytes(
            DEPLOY_STATUS_PATH,
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
        )
    except OSError:
        pass


def _read_deploy_status() -> dict[str, Any]:
    import json

    try:
        return json.loads(DEPLOY_STATUS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


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
    success = 200 <= status < 300
    return {
        "ok": success,
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

    _write_deploy_status({
        "state": "running",
        "started_at": started_at,
        "finished_at": None,
        "rolled_back": False,
    })

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
                "ok": False,
                "saved": False,
                "deployed": False,
                "rolled_back": True,
                "check": check,
                "backup": deployment.backup,
                "error": "Home-Assistant-Konfigurationsprüfung fehlgeschlagen; die bisherige Datei wurde wiederhergestellt.",
            }
            _write_deploy_status({
                "state": "failed",
                "started_at": started_at,
                "finished_at": int(time.time()),
                "rolled_back": True,
                "check": check,
                "backup": deployment.backup,
                "error": result["error"],
            })
            return web.json_response(result, status=422)

        result = {
            "ok": True,
            "saved": True,
            "deployed": True,
            "rolled_back": False,
            "path": deployment.path,
            "backup": deployment.backup,
            "yaml": deployment.yaml_text,
            "selected": deployment.selected_count,
            "check": check,
            "restart_required": True,
        }
        _write_deploy_status({
            "state": "success",
            "started_at": started_at,
            "finished_at": int(time.time()),
            "rolled_back": False,
            "path": deployment.path,
            "backup": deployment.backup,
            "selected": deployment.selected_count,
            "check": check,
        })
        return web.json_response(result)
    except GeneratorValidationError as exc:
        _write_deploy_status({
            "state": "failed",
            "started_at": started_at,
            "finished_at": int(time.time()),
            "rolled_back": False,
            "error": str(exc),
        })
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
        _write_deploy_status({
            "state": "failed",
            "started_at": started_at,
            "finished_at": int(time.time()),
            "rolled_back": True,
            "error": str(exc),
        })
        return web.json_response({"ok": False, "rolled_back": True, "error": str(exc)}, status=500)


async def deploy_status(request: web.Request) -> web.Response:
    return web.json_response(_read_deploy_status())


async def check_config_endpoint(request: web.Request) -> web.Response:
    try:
        result = await check_config()
        return web.json_response(result, status=200 if result["ok"] else 422)
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def restart(request: web.Request) -> web.Response:
    try:
        status, body = await _supervisor_post("/core/restart", timeout=30)
        if not 200 <= status < 300:
            return web.json_response(
                {"ok": False, "status": status, "error": _result_message(body), "response": body},
                status=502,
            )
        return web.json_response(
            {
                "ok": True,
                "status": status,
                "message": _result_message(body),
                "note": "Home Assistant wird neu gestartet; die Oberfläche ist vorübergehend nicht erreichbar.",
            }
        )
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


def install() -> None:
    ha_export.save = checked_deploy


def register_routes(app: web.Application) -> None:
    app.router.add_post("/api/ha-export/check-config", check_config_endpoint)
    app.router.add_get("/api/ha-export/deploy-status", deploy_status)
    app.router.add_post("/api/ha-export/deploy", checked_deploy)
    app.router.add_post("/api/ha-export/restart", restart)
