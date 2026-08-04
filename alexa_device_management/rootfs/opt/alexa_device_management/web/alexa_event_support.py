"""Official Alexa endpoint lifecycle synchronization through Home Assistant."""

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
from yaml_generator import load_yaml_with_secrets

STATUS_PATH = pathlib.Path("/data/alexa_device_management/event_sync_status.json")
COMPONENT_SOURCE = pathlib.Path(
    "/opt/alexa_device_management/ha_component/alexa_device_management_sync"
)
COMPONENT_TARGET = pathlib.Path(
    "/config/custom_components/alexa_device_management_sync"
)
HA_API_BASE_URL = "http://supervisor/core/api"
SERVICE_DOMAIN = "alexa_device_management_sync"
SERVICE_NAME = "sync"


def _atomic_write_bytes(path: pathlib.Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{path.name}-", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _read_status() -> dict[str, Any]:
    try:
        value = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def _write_status(data: dict[str, Any]) -> dict[str, Any]:
    current = _read_status()
    current.update(data)
    current["schema_version"] = 1
    _atomic_write_bytes(
        STATUS_PATH,
        json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True).encode(
            "utf-8"
        ),
    )
    return current


def _event_settings(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("event_gateway") if isinstance(config, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    return {
        "enabled": bool(raw.get("enabled", False)),
        "endpoint": str(
            raw.get("endpoint") or "https://api.eu.amazonalexa.com/v3/events"
        ).strip(),
        "client_id_secret": str(
            raw.get("client_id_secret") or "alexa_skill_client_id"
        ).strip(),
        "client_secret_secret": str(
            raw.get("client_secret_secret") or "alexa_skill_client_secret"
        ).strip(),
        "fallback_web_cleanup": bool(raw.get("fallback_web_cleanup", True)),
    }


def _enabled_entities(config: dict[str, Any]) -> set[str]:
    entities = config.get("entities") if isinstance(config, dict) else {}
    if not isinstance(entities, dict):
        return set()
    return {
        str(entity_id)
        for entity_id, settings in entities.items()
        if isinstance(settings, dict) and settings.get("enabled")
    }


def _entity_config(config: dict[str, Any], entity_ids: set[str]) -> dict[str, Any]:
    raw_entities = config.get("entities") if isinstance(config, dict) else {}
    raw_entities = raw_entities if isinstance(raw_entities, dict) else {}
    result: dict[str, Any] = {}
    for entity_id in sorted(entity_ids):
        raw = raw_entities.get(entity_id)
        if not isinstance(raw, dict):
            continue
        current: dict[str, str] = {}
        name = str(raw.get("name") or "").strip()
        description = str(raw.get("description") or "").strip()
        category = str(raw.get("display_category") or "").strip().upper()
        if name:
            current["name"] = name
        if description:
            current["description"] = description
        if category:
            current["display_categories"] = category
        if current:
            result[entity_id] = current
    return result


def _entities_from_yaml(path: pathlib.Path) -> set[str]:
    try:
        document = load_yaml_with_secrets(path.read_text(encoding="utf-8")) or {}
        values = (
            document.get("alexa", {})
            .get("smart_home", {})
            .get("filter", {})
            .get("include_entities", [])
        )
        return {str(value) for value in values or []}
    except (OSError, AttributeError, TypeError):
        return set()


def deployment_plan(
    previously_deployed: set[str],
    current_entities: set[str],
    event_enabled: bool,
) -> dict[str, set[str]]:
    """Build a lifecycle plan from the last deployed snapshot, not autosave state."""
    removed = set(previously_deployed) - set(current_entities)
    return {
        "removed": removed,
        "add_or_update": set(current_entities) if event_enabled else set(),
        "delete": removed if event_enabled else set(),
    }


def _component_files() -> list[pathlib.Path]:
    if not COMPONENT_SOURCE.exists():
        return []
    return sorted(path for path in COMPONENT_SOURCE.rglob("*") if path.is_file())


def deploy_component() -> dict[str, Any]:
    """Install the bundled Home Assistant helper integration atomically per file."""
    files = _component_files()
    if not files:
        raise FileNotFoundError(f"Event sync component source missing: {COMPONENT_SOURCE}")

    changed: list[str] = []
    for source in files:
        relative = source.relative_to(COMPONENT_SOURCE)
        target = COMPONENT_TARGET / relative
        content = source.read_bytes()
        try:
            existing = target.read_bytes()
        except OSError:
            existing = None
        if existing != content:
            _atomic_write_bytes(target, content)
            changed.append(str(relative))

    return {
        "installed": True,
        "path": str(COMPONENT_TARGET),
        "changed_files": changed,
        "restart_required": bool(changed),
    }


def _empty_cleanup(removed_entities: set[str]) -> dict[str, Any]:
    return {
        "requested_entities": sorted(removed_entities),
        "deleted_removed": [],
        "deleted_duplicates": [],
        "not_found": [],
        "failed": [],
        "warnings": [],
    }


def _json_payload(response: web.Response) -> dict[str, Any]:
    try:
        value = json.loads((response.body or b"{}").decode("utf-8"))
        return value if isinstance(value, dict) else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def snapshot(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or ha_export._load_state()
    settings = _event_settings(config)
    status = _read_status()
    pending_add = list(status.get("pending_add_or_update") or [])
    pending_delete = list(status.get("pending_delete") or [])
    return {
        "enabled": settings["enabled"],
        "endpoint": settings["endpoint"],
        "component_installed": (COMPONENT_TARGET / "manifest.json").exists(),
        "pending": bool(pending_add or pending_delete),
        "pending_add_or_update": pending_add,
        "pending_delete": pending_delete,
        "last_attempt_at": status.get("last_attempt_at"),
        "last_success_at": status.get("last_success_at"),
        "last_error": status.get("last_error"),
        "last_response": status.get("last_response"),
        "fallback_web_cleanup": settings["fallback_web_cleanup"],
        "deployed_entities": list(status.get("deployed_entities") or []),
    }


async def _ha_request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: int = 45,
) -> tuple[int, Any]:
    headers = ha_export._headers()
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.request(
            method,
            f"{HA_API_BASE_URL}{path}",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as response:
            text = await response.text()
            try:
                body = await response.json(content_type=None)
            except Exception:
                body = text
            return response.status, body


async def _service_available() -> bool:
    try:
        status, body = await _ha_request("GET", "/services", timeout=15)
    except Exception:
        return False
    if status != 200 or not isinstance(body, list):
        return False
    for domain in body:
        if not isinstance(domain, dict) or domain.get("domain") != SERVICE_DOMAIN:
            continue
        services = domain.get("services")
        if isinstance(services, dict):
            return SERVICE_NAME in services
    return False


async def _call_sync_service(payload: dict[str, Any]) -> tuple[int, Any]:
    return await _ha_request(
        "POST",
        f"/services/{SERVICE_DOMAIN}/{SERVICE_NAME}?return_response",
        payload=payload,
        timeout=60,
    )


def _service_response(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {"ok": False, "error": str(body or "Empty Home Assistant response")}
    response = body.get("service_response")
    if isinstance(response, dict):
        return response
    return body


