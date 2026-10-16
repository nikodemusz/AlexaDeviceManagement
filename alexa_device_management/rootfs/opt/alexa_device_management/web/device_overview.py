"""Unified Home Assistant and Alexa device overview."""

from __future__ import annotations

import asyncio
import json
import pathlib
import time
from copy import deepcopy
from typing import Any, Iterable

from aiohttp import web

import alexa_group_manager
import ha_export
import native_export
import native_lifecycle
from native_skill_config import NativeSkillConfigStore

STATIC_DIR = ha_export.STATIC_DIR

_UI_LISTS = {
    "device": "hidden_devices",
    "entity": "hidden_entities",
    "alexa": "hidden_alexa",
}
_SENSITIVE_DETAIL_KEYS = {"authorization", "cookie", "setcookie", "csrf", "password", "apikey", "xapikey"}

# Mirrors the established Alexa GraphQL selection used by alexapy. Unlike the
# behaviors/entities response, legacyAppliance includes connectedVia and the
# provider description. This query is only executed when the user opens one
# device's detail dialog, and the result is filtered to that device below.
_ALEXA_DEVICE_DETAILS_QUERY = """query CustomerSmartHome {
  endpoints(endpointsQueryParams: { paginationParams: { disablePagination: true } }) {
    items {
      endpointId
      legacyIdentifiers { chrsIdentifier { entityId } }
      legacyAppliance {
        applianceId applianceTypes friendlyName friendlyDescription
        manufacturerName connectedVia modelName entityId aliases capabilities
        customerDefinedDeviceType alexaDeviceIdentifierList driverIdentity
      }
    }
  }
}"""

# The overview combines two slow inventories (HA and Alexa groups). Keep those
# source snapshots on the add-on's persistent /data volume so opening the UI
# never has to wait for upstream API calls when a previous snapshot exists.
_OVERVIEW_CACHE_PATH = pathlib.Path("/data/device_overview_cache.json")
_OVERVIEW_CACHE_TTL = 60
_OVERVIEW_REFRESH_INTERVAL = 900
_OVERVIEW_RETRY_INTERVAL = 30
_OVERVIEW_SOURCE_CACHE: dict[str, Any] = {
    "ha_inventory": None,
    "ha_updated_at": 0,
    "groups": None,
    "groups_updated_at": 0,
    "alexa_configured": None,
    "warnings": [],
    "last_attempt_at": 0,
}
_OVERVIEW_CACHE_LOADED = False
_OVERVIEW_REFRESH_LOCK = asyncio.Lock()


def _load_overview_cache(server: Any) -> None:
    """Load the persisted source snapshots once, without reading credentials."""
    global _OVERVIEW_CACHE_LOADED
    if _OVERVIEW_CACHE_LOADED:
        return
    _OVERVIEW_CACHE_LOADED = True
    try:
        stored = json.loads(_OVERVIEW_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        stored = {}
    if isinstance(stored.get("ha_inventory"), dict):
        _OVERVIEW_SOURCE_CACHE["ha_inventory"] = stored["ha_inventory"]
        _OVERVIEW_SOURCE_CACHE["ha_updated_at"] = stored.get("ha_updated_at", 0)
    if isinstance(stored.get("groups"), list):
        _OVERVIEW_SOURCE_CACHE["groups"] = stored["groups"]
        _OVERVIEW_SOURCE_CACHE["groups_updated_at"] = stored.get("groups_updated_at", 0)
    _OVERVIEW_SOURCE_CACHE["alexa_configured"] = stored.get("alexa_configured")
    warnings = stored.get("warnings")
    if isinstance(warnings, list):
        _OVERVIEW_SOURCE_CACHE["warnings"] = [str(item) for item in warnings]
    _OVERVIEW_SOURCE_CACHE["last_attempt_at"] = stored.get("last_attempt_at", 0)

    # A cached group list belongs to the previous Alexa session state. Do not
    # show it after logout or assume it is valid after connecting a new account.
    if _OVERVIEW_SOURCE_CACHE["alexa_configured"] != bool(server.is_configured()):
        _OVERVIEW_SOURCE_CACHE["groups"] = None if server.is_configured() else []
        _OVERVIEW_SOURCE_CACHE["groups_updated_at"] = 0


def _persist_overview_cache() -> None:
    """Persist only inventory snapshots, never Alexa session or token data."""
    try:
        _OVERVIEW_CACHE_PATH.write_text(
            json.dumps({
                "ha_inventory": _OVERVIEW_SOURCE_CACHE["ha_inventory"],
                "ha_updated_at": _OVERVIEW_SOURCE_CACHE["ha_updated_at"],
                "groups": _OVERVIEW_SOURCE_CACHE["groups"],
                "groups_updated_at": _OVERVIEW_SOURCE_CACHE["groups_updated_at"],
                "alexa_configured": _OVERVIEW_SOURCE_CACHE["alexa_configured"],
                "warnings": _OVERVIEW_SOURCE_CACHE["warnings"],
                "last_attempt_at": _OVERVIEW_SOURCE_CACHE["last_attempt_at"],
            }),
            encoding="utf-8",
        )
    except OSError:
        # The in-memory cache still works for this process if persistence fails.
        pass


def _overview_sources_ready(server: Any) -> bool:
    return (
        isinstance(_OVERVIEW_SOURCE_CACHE.get("ha_inventory"), dict)
        and (
            not server.is_configured()
            or (
                isinstance(_OVERVIEW_SOURCE_CACHE.get("groups"), list)
                and _OVERVIEW_SOURCE_CACHE.get("alexa_configured") is True
            )
        )
    )


def _overview_sources_stale(server: Any, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    if not _overview_sources_ready(server):
        return True
    if now - float(_OVERVIEW_SOURCE_CACHE.get("ha_updated_at") or 0) > _OVERVIEW_CACHE_TTL:
        return True
    return bool(
        server.is_configured()
        and now - float(_OVERVIEW_SOURCE_CACHE.get("groups_updated_at") or 0) > _OVERVIEW_CACHE_TTL
    )


async def _refresh_overview_sources(server: Any) -> None:
    """Refresh HA inventory and Alexa groups concurrently, retaining stale data on errors."""
    async with _OVERVIEW_REFRESH_LOCK:
        now = time.time()
        _OVERVIEW_SOURCE_CACHE["last_attempt_at"] = now
        configured = bool(server.is_configured())
        _OVERVIEW_SOURCE_CACHE["alexa_configured"] = configured
        warnings: list[str] = []

        async def refresh_ha_inventory() -> None:
            try:
                inventory = await ha_export._inventory()
                if not isinstance(inventory, dict):
                    raise ValueError("invalid inventory")
            except Exception as exc:
                warnings.append(f"Home-Assistant-Inventar: {type(exc).__name__}")
                return
            _OVERVIEW_SOURCE_CACHE["ha_inventory"] = inventory
            _OVERVIEW_SOURCE_CACHE["ha_updated_at"] = time.time()

        async def refresh_groups() -> None:
            if not configured:
                _OVERVIEW_SOURCE_CACHE["groups"] = []
                _OVERVIEW_SOURCE_CACHE["groups_updated_at"] = time.time()
                return
            try:
                groups = await alexa_group_manager._load_groups(server, server.session_data())
                if not isinstance(groups, list):
                    raise ValueError("invalid groups")
            except Exception as exc:
                # AlexaGroupError contains only sanitized HTTP/error details;
                # other exception strings may contain request data.
                detail = str(exc) if isinstance(exc, alexa_group_manager.AlexaGroupError) else type(exc).__name__
                warnings.append(f"Alexa-Gruppen: {detail}")
                return
            _OVERVIEW_SOURCE_CACHE["groups"] = groups
            _OVERVIEW_SOURCE_CACHE["groups_updated_at"] = time.time()

        await asyncio.gather(refresh_ha_inventory(), refresh_groups())
        _OVERVIEW_SOURCE_CACHE["warnings"] = warnings
        _persist_overview_cache()


def _schedule_overview_refresh(app: web.Application, server: Any) -> None:
    """Start a stale-while-revalidate refresh without delaying the UI response."""
    task = app.get("overview_refresh_task")
    if task and not task.done():
        return
    now = time.time()
    # Failed refreshes leave the last good snapshot intact and stale. Back off
    # even in that case so each view poll does not launch another HTTP 299 call.
    if now - float(_OVERVIEW_SOURCE_CACHE.get("last_attempt_at") or 0) < _OVERVIEW_RETRY_INTERVAL:
        return
    if _OVERVIEW_REFRESH_LOCK.locked():
        return
    task = asyncio.create_task(_refresh_overview_sources(server))
    app["overview_refresh_task"] = task


async def _periodic_overview_refresh(app: web.Application) -> None:
    """Warm the overview cache at startup and refresh it in the background."""
    server = app["device_overview_server"]
    _load_overview_cache(server)
    while True:
        try:
            await _refresh_overview_sources(server)
            delay = (
                _OVERVIEW_REFRESH_INTERVAL
                if _overview_sources_ready(server)
                else _OVERVIEW_RETRY_INTERVAL
            )
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(_OVERVIEW_RETRY_INTERVAL)


async def _start_overview_refresh(app: web.Application) -> None:
    app["overview_periodic_task"] = asyncio.create_task(_periodic_overview_refresh(app))


async def _stop_overview_refresh(app: web.Application) -> None:
    for key in ("overview_periodic_task", "overview_refresh_task", "overview_device_refresh_task"):
        task = app.get(key)
        if task:
            task.cancel()


def _schedule_alexa_device_refresh(app: web.Application, server: Any) -> None:
    """Refresh Alexa inventory without blocking a request that can use cache."""
    task = app.get("overview_device_refresh_task")
    if task and not task.done():
        return
    now = time.time()
    if now - float(app.get("overview_device_refresh_last_attempt") or 0) < _OVERVIEW_RETRY_INTERVAL:
        return
    lock = getattr(server, "_DEVICES_REFRESH_LOCK", None)
    if lock is not None and lock.locked():
        return

    async def refresh() -> None:
        app["overview_device_refresh_last_attempt"] = time.time()
        try:
            await server.refresh_devices_cache()
        except Exception:
            # Keep serving the last known device snapshot; the periodic retry
            # and explicit refresh button remain available.
            return

    task = asyncio.create_task(refresh())
    app["overview_device_refresh_task"] = task


def _overview_refresh_in_progress(app: web.Application) -> bool:
    return _OVERVIEW_REFRESH_LOCK.locked() or any(
        task is not None and not task.done()
        for task in (
            app.get("overview_refresh_task"),
            app.get("overview_device_refresh_task"),
        )
    )


def _canonical(value: Any) -> set[str]:
    """Return comparable forms for Alexa and Home Assistant identifiers."""
    text = str(value or "").strip().lower()
    if not text:
        return set()
    values = {text}
    prefix = "amzn1.alexa.endpoint."
    if text.startswith(prefix):
        values.add(text[len(prefix):])
    if "#" in text:
        values.add(text.replace("#", ".", 1))
    if "." in text:
        values.add(text.replace(".", "#", 1))
    return values


def _collect_identifiers(value: Any) -> set[str]:
    result: set[str] = set()

    def walk(current: Any) -> None:
        if isinstance(current, dict):
            for key, child in current.items():
                normalized = str(key).replace("_", "").lower()
                if normalized in {
                    "id",
                    "entityid",
                    "endpointid",
                    "applianceid",
                    "appliancekey",
                    "serial",
                    "serialnumber",
                    "deviceserialnumber",
                } and not isinstance(child, (dict, list)):
                    result.update(_canonical(child))
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(current, list):
            for child in current:
                walk(child)

    walk(value)
    return result


def _alexa_key(device: dict[str, Any]) -> str:
    return f"{str(device.get('source') or 'unknown')}:{str(device.get('serial') or device.get('appliance_id') or '')}"


def _alexa_entity_id(device: dict[str, Any]) -> str:
    explicit = alexa_group_manager._device_entity_id(device)
    if explicit:
        return explicit.lower()

    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    for value in (
        raw.get("entityId"),
        raw.get("entity_id"),
        raw.get("endpointId"),
        device.get("serial"),
    ):
        for candidate in _canonical(value):
            if "." in candidate and " " not in candidate:
                return candidate
    return ""


def _device_identifiers(device: dict[str, Any]) -> set[str]:
    identifiers = alexa_group_manager._device_identifiers(device)
    identifiers.update(_collect_identifiers(device.get("raw") or {}))
    identifiers.update(_canonical(device.get("serial")))
    identifiers.update(_canonical(device.get("appliance_id")))
    entity_id = _alexa_entity_id(device)
    if entity_id:
        identifiers.update(_canonical(entity_id))
    return identifiers


def _group_names_for_device(
    device: dict[str, Any], groups: Iterable[dict[str, Any]]
) -> list[str]:
    identifiers = _device_identifiers(device)
    names = [
        str(group.get("name") or "").strip()
        for group in groups
        if identifiers & alexa_group_manager._group_member_identifiers(group)
    ]
    return sorted({name for name in names if name}, key=str.casefold)


def _public_alexa_device(
    device: dict[str, Any], groups: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    return {
        "key": _alexa_key(device),
        "serial": str(device.get("serial") or ""),
        "appliance_id": str(device.get("appliance_id") or ""),
        "name": str(device.get("name") or device.get("serial") or "Unbekannt"),
        "source": str(device.get("source") or ""),
        "type": str(device.get("type") or ""),
        "family": str(device.get("family") or ""),
        "skill": str(device.get("skill") or ""),
        "room": str(device.get("room") or ""),
        "online": bool(device.get("online")),
        "lifecycle": str(device.get("lifecycle") or ""),
        "entity_id": _alexa_entity_id(device),
        "groups": _group_names_for_device(device, groups),
        "device_type": str(raw.get("deviceType") or device.get("type") or ""),
    }


def _safe_device_details(value: Any) -> Any:
    """Copy one device's raw Alexa record while omitting credential fields."""
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, child in value.items():
            normalized = "".join(char for char in str(key).lower() if char.isalnum())
            if (normalized in _SENSITIVE_DETAIL_KEYS or "token" in normalized
                    or "secret" in normalized or "credential" in normalized):
                safe[str(key)] = "[redigiert]"
            else:
                safe[str(key)] = _safe_device_details(child)
        return safe
    if isinstance(value, list):
        return [_safe_device_details(child) for child in value]
    if isinstance(value, str):
        return value[:2000]
    return value


def _connected_via(details: dict[str, Any]) -> tuple[str | None, str | None]:
    """Use Alexa's connectedVia field, falling back to skill description text."""
    value = str(details.get("connectedVia") or "").strip()
    if value:
        return value, "connectedVia"
    description = str(details.get("friendlyDescription") or "").strip()
    match = re.search(r"\s+via\s+(.+)$", description, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip(), "friendlyDescription"
    return None, None


def _matching_alexa_detail(
    device: dict[str, Any], endpoints: list[Any]
) -> dict[str, Any] | None:
    """Match a fresh GraphQL endpoint to a cached list item by stable IDs."""
    expected = _device_identifiers(device)
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            continue
        legacy = endpoint.get("legacyAppliance")
        if not isinstance(legacy, dict):
            continue
        identifiers = _collect_identifiers(endpoint)
        if expected & identifiers:
            connected_via, via_source = _connected_via(legacy)
            return {
                "endpoint_id": endpoint.get("endpointId"),
                "connected_via": connected_via,
                "connected_via_source": via_source,
                "friendly_name": legacy.get("friendlyName"),
                "description": legacy.get("friendlyDescription"),
                "manufacturer": legacy.get("manufacturerName"),
                "model": legacy.get("modelName"),
                "device_types": legacy.get("applianceTypes"),
                "custom_device_type": legacy.get("customerDefinedDeviceType"),
                "aliases": legacy.get("aliases"),
                "capabilities": legacy.get("capabilities"),
                "driver": legacy.get("driverIdentity"),
                "identifiers": legacy.get("alexaDeviceIdentifierList"),
                "raw": legacy,
            }
    return None


def _entity_matches(
    entity_id: str,
    devices: list[dict[str, Any]],
    native_endpoint_ids: Iterable[str] = (),
) -> list[int]:
    expected = _canonical(entity_id)
    for endpoint_id in native_endpoint_ids:
        expected.update(_canonical(endpoint_id))
    matches: list[int] = []
    for index, device in enumerate(devices):
        if str(device.get("source") or "") == "echo":
            continue
        explicit = _alexa_entity_id(device)
        identifiers = _device_identifiers(device)
        if explicit == entity_id.lower() or expected & identifiers:
            matches.append(index)
    return matches


def _native_bindings(config: dict[str, Any]) -> dict[str, list[str]]:
    """Read only active YAML devices; transitional legacy JSON is not v6."""
    bindings: dict[str, list[str]] = {}
    if not config.get("enabled"):
        return bindings
    for endpoint_id, device in config.get("devices", {}).items():
        if not device.get("enabled", True):
            continue
        for capability in device.get("capabilities", []):
            entity_id = capability.get("entity_id")
            if entity_id:
                ids = bindings.setdefault(entity_id, [])
                external_id = "native:" + endpoint_id
                if external_id not in ids:
                    ids.append(external_id)
    return bindings


def _entity_status(enabled: bool, match_count: int) -> str:
    if match_count > 1:
        return "duplicate"
    if enabled and match_count == 1:
        return "synced"
    if enabled:
        return "pending"
    if match_count:
        return "only_alexa"
    return "not_exposed"


def _device_status(statuses: Iterable[str]) -> str:
    values = set(statuses)
    if "duplicate" in values or "only_alexa" in values:
        return "problem"
    if "pending" in values:
        return "pending"
    if "synced" in values:
        return "synced"
    return "not_exposed"


def build_overview(
    ha_inventory: dict[str, Any],
    alexa_devices: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    config: dict[str, Any],
    native_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Join HA entities and Alexa endpoints without fuzzy name matching."""
    ui = config.get("ui") if isinstance(config.get("ui"), dict) else {}
    hidden_devices = {str(value) for value in ui.get("hidden_devices", [])}
    hidden_entities = {str(value) for value in ui.get("hidden_entities", [])}
    hidden_alexa = {str(value) for value in ui.get("hidden_alexa", [])}
    entity_config = config.get("entities") if isinstance(config.get("entities"), dict) else {}
    native_primary = config.get("export_mode") == "native"
    native_bindings = _native_bindings(native_config or {})

    public_alexa = [_public_alexa_device(device, groups) for device in alexa_devices]
    native_inventory_ids = [native_lifecycle.identifiers(device) for device in alexa_devices]
    matched_indexes: set[int] = set()
    devices: list[dict[str, Any]] = []

    summary = {
        "ha_devices": 0,
        "ha_entities": 0,
        "selected": 0,
        "native_selected": 0,
        "synced": 0,
        "pending": 0,
        "only_alexa": 0,
        "duplicates": 0,
        "hidden": 0,
        "alexa_only": 0,
    }

    for ha_device in ha_inventory.get("devices", []):
        if not isinstance(ha_device, dict):
            continue
        device_id = str(ha_device.get("device_id") or "")
        public_entities: list[dict[str, Any]] = []
        statuses: list[str] = []
        for entity in ha_device.get("entities", []):
            if not isinstance(entity, dict):
                continue
            entity_id = str(entity.get("entity_id") or "")
            if not entity_id:
                continue
            settings = entity_config.get(entity_id)
            if not isinstance(settings, dict):
                settings = {}
            enabled = bool(settings.get("enabled") if native_primary else config.get("legacy_export_enabled", True) and settings.get("enabled"))
            native_ids = native_bindings.get(entity_id, [])
            match_indexes = _entity_matches(entity_id, alexa_devices, native_ids)
            matched_indexes.update(match_indexes)
            matches = [public_alexa[index] for index in match_indexes]
            native_matches = [index for index, alexa in enumerate(alexa_devices)
                              if set(native_ids) & native_inventory_ids[index]]
            status = (_entity_status(bool(native_ids), int(bool(native_matches))) if native_primary
                      else _entity_status(enabled or bool(native_ids), len(matches)))
            if native_primary and not native_ids and matches:
                status = "only_alexa"
            statuses.append(status)
            hidden = entity_id in hidden_entities or device_id in hidden_devices

            summary["ha_entities"] += 1
            summary["selected"] += int(enabled or bool(native_ids))
            summary["native_selected"] += int(bool(native_ids))
            summary["hidden"] += int(hidden)
            if status == "synced":
                summary["synced"] += 1
            elif status == "pending":
                summary["pending"] += 1
            elif status == "only_alexa":
                summary["only_alexa"] += 1
            elif status == "duplicate":
                summary["duplicates"] += 1

            public_entities.append({
                **entity,
                "export": {
                    "enabled": enabled,
                    "name": str(settings.get("name") or ""),
                    "description": str(settings.get("description") or ""),
                    "display_category": str(settings.get("display_category") or ""),
                    "alexa_group": str(settings.get("alexa_group") or ""),
                },
                "alexa": {
                    "present": bool(matches),
                    "count": len(matches),
                    "matches": matches,
                },
                "native": {"enabled": bool(native_ids), "endpoint_ids": list(native_ids)},
                "status": status,
                "hidden": hidden,
                "hidden_directly": entity_id in hidden_entities,
            })

        if not public_entities:
            continue
        hidden = device_id in hidden_devices
        devices.append({
            **{key: value for key, value in ha_device.items() if key != "entities"},
            "entities": public_entities,
            "status": _device_status(statuses),
            "hidden": hidden,
        })
        summary["ha_devices"] += 1

    alexa_only: list[dict[str, Any]] = []
    for index, public in enumerate(public_alexa):
        if index in matched_indexes:
            continue
        item = dict(public)
        item["hidden"] = item["key"] in hidden_alexa
        if item["source"] == "echo":
            item["status"] = "alexa_device"
        elif item["lifecycle"] == "orphaned":
            item["status"] = "orphaned"
        else:
            item["status"] = "unmatched"
        alexa_only.append(item)
        summary["alexa_only"] += 1
        summary["hidden"] += int(item["hidden"])

    if native_primary:
        active_ids = {endpoint for values in native_bindings.values() for endpoint in values}
        present_ids = {endpoint for endpoint in active_ids
                       if any(endpoint in ids for ids in native_inventory_ids)}
        # Count logical endpoints once, including ones with missing HA registry rows.
        summary.update(selected=len(active_ids), native_selected=len(active_ids),
                       synced=len(present_ids), pending=len(active_ids - present_ids),
                       duplicates=0, only_alexa=len(native_lifecycle.legacy_targets(alexa_devices)))

    return {
        "devices": devices,
        "alexa_only": sorted(alexa_only, key=lambda item: item["name"].casefold()),
        "areas": ha_inventory.get("areas", []),
        "display_categories": ha_inventory.get("display_categories", []),
        "groups": [
            {"id": group.get("id"), "name": group.get("name"), "type": group.get("type")}
            for group in groups
        ],
        "configuration": config,
        "summary": summary,
    }


async def page(request: web.Request) -> web.Response:
    text = (STATIC_DIR / "device_overview.html").read_text(encoding="utf-8")
    ingress_path = request.headers.get("X-Ingress-Path", "").rstrip("/")
    return web.Response(
        text=text.replace("{{INGRESS_PATH}}", ingress_path),
        content_type="text/html",
    )


async def overview(request: web.Request) -> web.Response:
    server = request.app["device_overview_server"]
    store = request.app["device_overview_store"]
    force = request.rel_url.query.get("refresh") == "1"
    warnings: list[str] = []

    try:
        _load_overview_cache(server)
        if force:
            if server.is_configured():
                await server.refresh_devices_cache()
            await _refresh_overview_sources(server)
        else:
            if _overview_sources_stale(server):
                _schedule_overview_refresh(request.app, server)
            if server.is_configured():
                server._load_devices_cache()
                device_cache = getattr(server, "_DEVICES_CACHE", {})
                cache_age = time.time() - float(device_cache.get("updated_at") or 0)
                if cache_age > _OVERVIEW_CACHE_TTL:
                    _schedule_alexa_device_refresh(request.app, server)

        ha_inventory = _OVERVIEW_SOURCE_CACHE.get("ha_inventory") or {
            "devices": [], "areas": [], "display_categories": []
        }
        config = store.load()
        native_config = {}
        try:
            native_config = NativeSkillConfigStore().load()
        except ValueError:
            # A broken optional v6 config must not take down the v5 overview.
            warnings.append("Native v6-Konfiguration konnte nicht validiert werden.")

        alexa_devices: list[dict[str, Any]] = []
        groups: list[dict[str, Any]] = _OVERVIEW_SOURCE_CACHE.get("groups") or []
        if server.is_configured():
            cache = getattr(server, "_DEVICES_CACHE", {})
            alexa_devices = list(cache.get("devices", []))
            warnings.extend(str(item) for item in cache.get("warnings", []) if item)
        warnings.extend(str(item) for item in _OVERVIEW_SOURCE_CACHE.get("warnings", []) if item)

        configuration = native_export.configuration(native_config or {"schema_version": 6, "enabled": False, "locale": "de-DE", "devices": {}}, config)
        result = build_overview(ha_inventory, alexa_devices, groups, configuration, native_config)
        lifecycle = native_lifecycle.read_status()
        for key in ("publish_error", "legacy_error"):
            if lifecycle.get(key):
                warnings.append(lifecycle[key])
        result.update({
            "ok": True,
            "alexa_connected": server.is_configured(),
            "alexa_updated_at": (
                getattr(server, "_DEVICES_CACHE", {}).get("updated_at")
                if isinstance(getattr(server, "_DEVICES_CACHE", {}), dict)
                else None
            ),
            "source_cache_loading": not (
                _overview_sources_ready(server)
                and (
                    not server.is_configured()
                    or bool(getattr(server, "_DEVICES_CACHE", {}).get("updated_at"))
                )
            ),
            "source_cache_refreshing": _overview_refresh_in_progress(request.app),
            "source_cache_updated_at": min(
                value for value in (
                    _OVERVIEW_SOURCE_CACHE.get("ha_updated_at"),
                    _OVERVIEW_SOURCE_CACHE.get("groups_updated_at") if server.is_configured() else None,
                ) if value
            ) if _OVERVIEW_SOURCE_CACHE.get("ha_updated_at") else None,
            "warnings": warnings,
            "generated_at": int(time.time()),
            "native_lifecycle": lifecycle,
        })
        return web.json_response(result)
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def alexa_device_details(request: web.Request) -> web.Response:
    """Return cached details plus a fresh Alexa GraphQL record for one device."""
    server = request.app["device_overview_server"]
    if not server.is_configured():
        raise web.HTTPUnauthorized(text="Alexa ist nicht verbunden.")
    try:
        body = await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(text="Ungültige JSON-Daten.") from exc
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="Gerätekennung fehlt.")
    key = str(body.get("key") or "").strip()
    if not key or len(key) > 512:
        raise web.HTTPBadRequest(text="Gültige Gerätekennung fehlt.")

    server._load_devices_cache()
    cache = server._DEVICES_CACHE
    device = next((item for item in cache.get("devices", [])
                   if _alexa_key(item) == key), None)
    if device is None:
        raise web.HTTPNotFound(text="Gerät ist nicht mehr im Alexa-Cache. Bitte zuerst aktualisieren.")

    result = {
        "ok": True,
        "cache_updated_at": cache.get("updated_at") or None,
        "warning_sources": sorted({str(item).split(":", 1)[0][:50]
                                    for item in cache.get("warnings", []) if str(item)}),
        "device": _safe_device_details({
            "name": device.get("name"),
            "serial": device.get("serial"),
            "appliance_id": device.get("appliance_id"),
            "type": device.get("type"),
            "family": device.get("family"),
            "skill": device.get("skill"),
            "online": device.get("online"),
            "firmware": device.get("firmware"),
            "capabilities": device.get("capabilities"),
            "room": device.get("room"),
            "source": device.get("source"),
            "raw": device.get("raw"),
        }),
        "alexa_api": {"status": "not_loaded"},
    }

    # The supported customer query returns an inventory list. Fetch on demand,
    # match stable IDs locally, and return only the selected device.
    try:
        status, payload = await server.alexa_graphql(
            _ALEXA_DEVICE_DETAILS_QUERY, None, server.session_data()
        )
        errors = payload.get("errors") if isinstance(payload, dict) else None
        endpoints = (
            (((payload.get("data") or {}).get("endpoints") or {}).get("items"))
            if isinstance(payload, dict) else None
        )
        if status == 200 and not errors and isinstance(endpoints, list):
            api_details = _matching_alexa_detail(device, endpoints)
            result["alexa_api"] = {
                "status": "matched" if api_details else "not_found",
                "fetched_at": int(time.time()),
                "device": _safe_device_details(api_details) if api_details else None,
            }
        else:
            result["alexa_api"] = {
                "status": "error",
                "http_status": status,
                "error": "Alexa hat keine gültigen erweiterten Gerätedetails geliefert.",
            }
    except Exception as exc:
        result["alexa_api"] = {
            "status": "error",
            "error": f"Alexa-Detailabfrage fehlgeschlagen ({type(exc).__name__}).",
        }
    return web.json_response(result)


async def visibility(request: web.Request) -> web.Response:
    store = request.app["device_overview_store"]
    try:
        body = await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(text="Ungültige JSON-Daten.") from exc

    kind = str(body.get("kind") or "").strip()
    list_name = _UI_LISTS.get(kind)
    if list_name is None:
        raise web.HTTPBadRequest(text="kind muss device, entity oder alexa sein.")

    raw_ids = body.get("ids")
    if not isinstance(raw_ids, list):
        raw_ids = [body.get("id")]
    ids = {str(value).strip() for value in raw_ids if str(value or "").strip()}
    if not ids:
        raise web.HTTPBadRequest(text="id oder ids ist erforderlich.")
    hidden = bool(body.get("hidden", True))

    config = deepcopy(store.load())
    ui = config.get("ui") if isinstance(config.get("ui"), dict) else {}
    current = {str(value) for value in ui.get(list_name, [])}
    if hidden:
        current.update(ids)
    else:
        current.difference_update(ids)
    ui[list_name] = sorted(current)
    config["ui"] = ui
    saved = store.save(config)
    return web.json_response({
        "ok": True,
        "kind": kind,
        "hidden": hidden,
        "ids": sorted(ids),
        "configuration": saved,
    })


def register_routes(app: web.Application, server: Any, store: Any) -> None:
    app["device_overview_server"] = server
    app["device_overview_store"] = store
    app.on_startup.append(_start_overview_refresh)
    app.on_cleanup.append(_stop_overview_refresh)
    app.router.add_get("/devices", page)
    app.router.add_get("/api/device-overview", overview)
    app.router.add_post("/api/device-overview/alexa-details", alexa_device_details)
    app.router.add_post("/api/device-overview/visibility", visibility)
