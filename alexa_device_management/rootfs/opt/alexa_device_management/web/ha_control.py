"""Home Assistant configuration validation and restart helpers."""

from __future__ import annotations

import pathlib
import shutil
import time
from typing import Any

import aiohttp
import yaml
from aiohttp import web

import ha_export

SUPERVISOR_BASE_URL = "http://supervisor"


async def _supervisor_post(path: str, timeout: int = 120) -> tuple[int, dict[str, Any] | str]:
    """Call a Supervisor API action using the app's Supervisor token."""
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
    """Run Home Assistant's full configuration check through Supervisor."""
    status, body = await _supervisor_post("/core/check", timeout=180)
    success = 200 <= status < 300
    return {
        "ok": success,
        "status": status,
        "message": _result_message(body),
        "response": body,
    }


async def checked_save(request: web.Request) -> web.Response:
    """Write proposed YAML, validate the complete HA config, and roll back on error."""
    try:
        data = await request.json()
        yaml_text = ha_export._dump_yaml(data)
        yaml.safe_load(yaml_text)

        target = ha_export.ALEXA_YAML_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        previous_exists = target.exists()
        previous_bytes = target.read_bytes() if previous_exists else None
        backup: pathlib.Path | None = None

        if previous_exists:
            backup = target.with_name(f"alexa.yaml.backup-{int(time.time())}")
            shutil.copy2(target, backup)

        temporary = target.with_suffix(".yaml.tmp")
        temporary.write_text(yaml_text, encoding="utf-8")
        temporary.replace(target)

        check = await check_config()
        if not check["ok"]:
            if previous_bytes is None:
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
            else:
                rollback = target.with_suffix(".yaml.rollback")
                rollback.write_bytes(previous_bytes)
                rollback.replace(target)
            return web.json_response(
                {
                    "ok": False,
                    "saved": False,
                    "rolled_back": True,
                    "check": check,
                    "backup": str(backup) if backup else None,
                    "error": "Home-Assistant-Konfigurationsprüfung fehlgeschlagen; die bisherige Datei wurde wiederhergestellt.",
                },
                status=422,
            )

        ha_export._save_state(data)
        return web.json_response(
            {
                "ok": True,
                "saved": True,
                "path": str(target),
                "backup": str(backup) if backup else None,
                "yaml": yaml_text,
                "check": check,
                "restart_required": True,
            }
        )
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def check_config_endpoint(request: web.Request) -> web.Response:
    try:
        result = await check_config()
        return web.json_response(result, status=200 if result["ok"] else 422)
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def restart(request: web.Request) -> web.Response:
    """Restart Home Assistant Core after explicit confirmation in the UI."""
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
    """Replace the original save handler before ha_export registers its routes."""
    ha_export.save = checked_save


def register_routes(app: web.Application) -> None:
    app.router.add_post("/api/ha-export/check-config", check_config_endpoint)
    app.router.add_post("/api/ha-export/restart", restart)
