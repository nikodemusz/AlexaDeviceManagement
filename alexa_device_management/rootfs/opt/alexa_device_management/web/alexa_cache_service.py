"""Resilient Alexa device cache service.

This module upgrades the legacy in-process cache in ``server_clean`` without
changing the public device API. It moves the persisted cache into the app data
folder, writes it atomically, exposes cache diagnostics and preserves a known
good device list when Alexa refreshes fail.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import tempfile
import time
from typing import Any

from aiohttp import web

CACHE_DIR = pathlib.Path("/data/alexa_device_management")
CACHE_PATH = CACHE_DIR / "alexa_cache.json"
LEGACY_CACHE_PATH = pathlib.Path("/data/devices_cache.json")
DEFAULT_REFRESH_INTERVAL = 600
DEFAULT_STALE_AFTER = 120


def _positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value or "")
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _atomic_write(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="alexa-cache-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
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


def _migrate_legacy_cache() -> None:
    if CACHE_PATH.exists() or not LEGACY_CACHE_PATH.exists():
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(LEGACY_CACHE_PATH, CACHE_PATH)
    except OSError:
        pass


def install(server: Any) -> None:
    """Install cache persistence and diagnostics into ``server_clean``."""
    _migrate_legacy_cache()
    server.DEVICES_CACHE_PATH = CACHE_PATH
    server.DEVICES_REFRESH_INTERVAL = _positive_int(
        os.environ.get("ALEXA_CACHE_REFRESH_INTERVAL"), DEFAULT_REFRESH_INTERVAL
    )
    server.DEVICES_CACHE_TTL = _positive_int(
        os.environ.get("ALEXA_CACHE_STALE_AFTER"), DEFAULT_STALE_AFTER
    )

    original_refresh = server.refresh_devices_cache

    def persist_cache() -> None:
        payload = {
            "schema_version": 1,
            "devices": server._DEVICES_CACHE.get("devices", []),
            "updated_at": server._DEVICES_CACHE.get("updated_at", 0),
            "last_attempt_at": server._DEVICES_CACHE.get("last_attempt_at"),
            "last_success_at": server._DEVICES_CACHE.get("last_success_at"),
            "last_error_at": server._DEVICES_CACHE.get("last_error_at"),
            "warnings": server._DEVICES_CACHE.get("warnings", []),
        }
        try:
            _atomic_write(CACHE_PATH, payload)
        except OSError:
            # A cache write failure must never take down the application.
            pass

    def load_cache() -> None:
        if server._DEVICES_CACHE:
            return
        stored = server.read_json(CACHE_PATH)
        if not isinstance(stored.get("devices"), list):
            return
        server._DEVICES_CACHE.update({
            "devices": stored.get("devices", []),
            "updated_at": stored.get("updated_at", 0),
            "last_attempt_at": stored.get("last_attempt_at"),
            "last_success_at": stored.get("last_success_at") or stored.get("updated_at"),
            "last_error_at": stored.get("last_error_at"),
            "warnings": stored.get("warnings", []),
        })

    async def refresh_cache() -> dict[str, Any]:
        before = server._DEVICES_CACHE.get("updated_at", 0)
        server._DEVICES_CACHE["last_attempt_at"] = time.time()
        result = await original_refresh()
        after = server._DEVICES_CACHE.get("updated_at", 0)
        if after and after != before:
            server._DEVICES_CACHE["last_success_at"] = after
        elif server._DEVICES_CACHE.get("warnings"):
            server._DEVICES_CACHE["last_error_at"] = time.time()
        persist_cache()
        return result

    server._persist_devices_cache = persist_cache
    server._load_devices_cache = load_cache
    server.refresh_devices_cache = refresh_cache


def register_routes(app: web.Application, server: Any) -> None:
    async def cache_status(request: web.Request) -> web.Response:
        server._load_devices_cache()
        now = time.time()
        updated_at = server._DEVICES_CACHE.get("updated_at", 0) or 0
        return web.json_response({
            "path": str(CACHE_PATH),
            "exists": CACHE_PATH.exists(),
            "device_count": len(server._DEVICES_CACHE.get("devices", [])),
            "updated_at": updated_at or None,
            "age_seconds": max(0, int(now - updated_at)) if updated_at else None,
            "last_attempt_at": server._DEVICES_CACHE.get("last_attempt_at"),
            "last_success_at": server._DEVICES_CACHE.get("last_success_at"),
            "last_error_at": server._DEVICES_CACHE.get("last_error_at"),
            "warnings": server._DEVICES_CACHE.get("warnings", []),
            "refreshing": server._DEVICES_REFRESH_LOCK.locked(),
            "refresh_interval_seconds": server.DEVICES_REFRESH_INTERVAL,
            "stale_after_seconds": server.DEVICES_CACHE_TTL,
        })

    async def refresh_now(request: web.Request) -> web.Response:
        await server.refresh_devices_cache()
        return await cache_status(request)

    app.router.add_get("/api/devices/cache-status", cache_status)
    app.router.add_post("/api/devices/refresh", refresh_now)
