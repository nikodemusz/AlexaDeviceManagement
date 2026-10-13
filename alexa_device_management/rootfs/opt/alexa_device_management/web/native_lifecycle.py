"""Publish selected native endpoints and retire confirmed unwanted endpoints.

Inventory reads remain observational. Reconciliation runs in a separate task,
uses the app's own Alexa session, and never guesses ownership from device names.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from pathlib import Path

from aiohttp import web

import alexa_event_support as support
import ha_export
from native_endpoints import endpoints
from native_skill_config import NativeSkillConfigStore

STATUS_PATH = Path("/data/alexa_device_management/native_lifecycle.json")
_ENTITY = re.compile(r"^[a-z_]+\.[A-Za-z0-9_]+$")
_REPORT_LOCK = asyncio.Lock()
_CLEANUP_LOCK = asyncio.Lock()


def read_status():
    try:
        value = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_status(**values):
    data = {**read_status(), **values, "updated_at": int(time.time())}
    support._atomic_write_bytes(STATUS_PATH, json.dumps(data, ensure_ascii=False).encode())
    return data


def identifiers(device):
    """Collect IDs, including wrapped and nested Phoenix/GraphQL endpoint IDs."""
    result = set()
    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.replace("_", "").lower() in {
                    "id", "entityid", "endpointid", "applianceid", "serial", "serialnumber"
                } and isinstance(child, str):
                    result.add(child)
                    result.add(child.removeprefix("amzn1.alexa.endpoint."))
                elif isinstance(child, (dict, list)):
                    walk(child)
                elif isinstance(child, str) and child[:1] in ("{", "["):
                    try:
                        walk(json.loads(child))
                    except (ValueError, RecursionError):
                        pass
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(device)
    return result


def providers(device):
    """Read provider fields, never friendly names, including legacy wrappers."""
    result = set()
    fields = {"manufacturer", "manufacturername", "family", "skill", "skillname", "providername"}
    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.replace("_", "").casefold() in fields and isinstance(child, str):
                    result.add(child.strip().casefold())
                elif isinstance(child, (dict, list)):
                    walk(child)
                elif isinstance(child, str) and child[:1] in ("{", "["):
                    try:
                        walk(json.loads(child))
                    except (ValueError, RecursionError):
                        pass
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(device)
    return result


def selection_config():
    store = NativeSkillConfigStore()
    if not store.path.is_file():
        raise ValueError("Missing native selection; deletion blocked")
    return store.load()


def legacy_targets(devices):
    """Identify all HA-v5 devices, including never-selected and opaque-ID ones."""
    targets = []
    seen = set()
    for device in devices:
        if device.get("source") == "echo":
            continue
        ids = identifiers(device)
        raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
        manufacturers = providers(device)
        # Protect every native endpoint, even disabled ones or overlapping HA IDs.
        if any(value.casefold().startswith("native:") for value in ids) or "alexa device management" in manufacturers:
            continue
        legacy = raw.get("legacyAppliance") if isinstance(raw.get("legacyAppliance"), dict) else {}
        description = str(raw.get("description") or legacy.get("description") or device.get("description") or "").strip()
        via_ha = description.casefold().endswith(" via home assistant")
        if not via_ha and "home assistant" not in manufacturers:
            continue
        key = (str(device.get("source") or ""), str(device.get("appliance_id") or device.get("serial") or ""))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        endpoint_id = None
        entity = description[:-len(" via Home Assistant")] if via_ha else ""
        if _ENTITY.fullmatch(entity):
            endpoint_id = entity.replace(".", "#", 1)
        else:
            for field in ("endpointId", "entityId"):
                value = raw.get(field)
                if isinstance(value, str) and value and len(value) <= 256:
                    endpoint_id = value.removeprefix("amzn1.alexa.endpoint.")
                    break
        targets.append({"device": device, "endpoint_id": endpoint_id, "kind": "legacy"})
    return targets


def selection_targets(devices, native):
    """Keep selected IDs; remove confirmed v5 and inactive managed native IDs."""
    active = {item["endpointId"] for item in endpoints(native)}
    configured = {"native:" + key for key in native["devices"]}
    old = {id(target["device"]): target for target in legacy_targets(devices)}
    targets, seen = [], set()
    for device in devices:
        if device.get("source") == "echo":
            continue
        ids = identifiers(device)
        if ids & active:
            continue
        native_ids = {value for value in ids if value.startswith("native:")}
        managed = native_ids & configured
        if "alexa device management" in providers(device):
            managed |= native_ids
        target = old.get(id(device))
        if managed:
            target = {"device": device, "endpoint_id": sorted(managed)[0],
                      "native_ids": sorted(managed), "kind": "unselected_native"}
        if target is None:
            continue
        key = (device.get("source"), device.get("appliance_id") or device.get("serial"))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        targets.append(target)
    return targets


async def cleanup_legacy(server, native=None):
    """Delete only confirmed old endpoints and verify with fresh Amazon inventory."""
    async with _CLEANUP_LOCK:
        if not server.is_configured():
            return write_status(inventory_verified=False, legacy_verified=False, selection_verified=False,
                                legacy_error="Alexa-Sitzung fehlt; unerwünschte Geräte können nicht gelöscht werden.")
        inventory, warnings = await server._fetch_devices_from_alexa(server.session_data())
        if warnings and not inventory:
            # Do not guess from a stale cache when no fresh devices were read.
            return write_status(inventory_verified=False, legacy_verified=False, selection_verified=False,
                                legacy_error="Alexa-Bestand nicht vollständig abrufbar; Bereinigung wird wiederholt.")
        targets = legacy_targets(inventory) if native is None else selection_targets(inventory, native)
        failures = []
        removed = {"legacy": 0, "unselected_native": 0}
        semaphore = asyncio.Semaphore(4)
        async def delete_one(target):
            item = target["device"]
            try:
                async with semaphore:
                    # A user may reselect an endpoint while inventory is loading.
                    if native is not None and not selection_targets([item], selection_config()):
                        return
                    await server._delete_target(item, server.session_data())
                removed[target["kind"]] += 1
            except Exception:
                failures.append({"name": str(item.get("name") or "Altgerät"),
                                 "error": "Alexa-Löschung fehlgeschlagen; erneuter Versuch beim nächsten Abgleich."})
        await asyncio.gather(*(delete_one(target) for target in targets))
        # A successful mutation response alone is not proof of deletion.
        fresh, fresh_warnings = await server._fetch_devices_from_alexa(server.session_data())
        if not fresh_warnings:
            server._DEVICES_CACHE.update(devices=fresh, updated_at=time.time(), warnings=[])
            server._persist_devices_cache()
        if fresh_warnings:
            remaining = targets
        else:
            remaining = legacy_targets(fresh) if native is None else selection_targets(fresh, selection_config())
        legacy = [item for item in remaining if item["kind"] == "legacy"]
        inactive = [item for item in remaining if item["kind"] == "unselected_native"]
        return write_status(legacy_deleted=removed["legacy"], legacy_remaining=len(legacy),
                            unselected_native_deleted=removed["unselected_native"],
                            unselected_native_remaining=len(inactive),
                            unselected_native_ids=sorted({value for item in inactive for value in item["native_ids"]}),
                            selection_deleted=sum(removed.values()), selection_remaining=len(remaining),
                            selection_verified=not fresh_warnings and not remaining,
                            inventory_verified=not fresh_warnings,
                            legacy_failures=failures,
                            legacy_error=("Alexa-Löschungen noch nicht bestätigt." if remaining or fresh_warnings else None),
                            legacy_verified=not fresh_warnings and not legacy)


async def publish_native(force=False):
    async with _REPORT_LOCK:
        native = selection_config()
        current = endpoints(native)
        status = read_status()
        active_ids = {item["endpointId"] for item in current}
        # Disabled endpoints may predate published_ids; their IDs still belong
        # to this configuration. Observed orphan IDs require provider evidence.
        known = {"native:" + key for key in native["devices"]}
        known |= {value for value in status.get("published_ids", []) if value.startswith("native:")}
        known |= {value for value in status.get("unselected_native_ids", []) if value.startswith("native:")}
        deleted = known - active_ids
        fingerprint = hashlib.sha256(json.dumps({"endpoints": current, "delete_ids": sorted(deleted)}, sort_keys=True).encode()).hexdigest()
        if not force and status.get("published_revision") == fingerprint:
            return status
        settings = support._event_settings(ha_export.CONFIG_STORE.load())
        if not settings["enabled"]:
            return write_status(publish_error="Alexa Event Gateway ist deaktiviert; v6-Anmeldung steht aus.")
        component = support.deploy_component()
        if component["restart_required"]:
            return write_status(publish_error="v6-Abgleichsdienst aktualisiert. HA neu starten, dann erneut abgleichen.",
                                restart_required=True)
        if not await support._service_available():
            return write_status(publish_error="HA-Abgleichsdienst fehlt. Konfiguration ausrollen und HA neu starten.")
        try:
            http, body = await support._call_sync_service({
                "native_endpoints": current,
                "delete_endpoint_ids": sorted(deleted),
                "add_or_update": [], "delete": [], "entity_config": {},
            })
            result = support._service_response(body)
        except Exception:
            return write_status(publish_error="HA-/Alexa-Abgleich nicht erreichbar; Anmeldung wird wiederholt.")
        if http != 200 or not result.get("ok"):
            if http == 400:
                return write_status(publish_error="v6-Abgleichsdienst ist noch nicht geladen. HA neu starten.", restart_required=True)
            return write_status(publish_error=result.get("error") or "Alexa hat den v6-Report nicht angenommen.",
                                publish_result=result, restart_required=bool(result.get("restart_required")))
        return write_status(publish_error=None, publish_result=result,
                            published_revision=fingerprint, published_ids=sorted(active_ids),
                            published_at=int(time.time()), restart_required=False)


async def reconcile(server, force=False):
    # Cleanup and publication have independent failure handling and credentials.
    try:
        await cleanup_legacy(server, selection_config())
    except Exception:
        write_status(inventory_verified=False, selection_verified=False, legacy_verified=False,
                     legacy_error="Auswahl/Bereinigung nicht prüfbar; keine weitere Löschung, erneuter Versuch folgt.")
    try:
        # HTTP 202 does not prove presence. Re-publish missing native IDs after
        # a fresh complete inventory, even if the YAML revision is unchanged.
        status = read_status()
        if server.is_configured() and status.get("inventory_verified"):
            expected = {item["endpointId"] for item in endpoints(NativeSkillConfigStore().load())}
            observed = set().union(*(identifiers(item) for item in server._DEVICES_CACHE.get("devices", [])))
            missing = expected - observed
            write_status(native_observed=len(expected & observed), native_pending=len(missing))
            force = force or bool(missing)
        await publish_native(force)
        if server.is_configured() and not read_status().get("publish_error"):
            fresh, warnings = await server._fetch_devices_from_alexa(server.session_data())
            if not warnings:
                server._DEVICES_CACHE.update(devices=fresh, updated_at=time.time(), warnings=[])
                server._persist_devices_cache()
                expected = {item["endpointId"] for item in endpoints(NativeSkillConfigStore().load())}
                observed = set().union(*(identifiers(item) for item in fresh))
                write_status(native_observed=len(expected & observed), native_pending=len(expected - observed))
    except Exception:
        write_status(publish_error="v6-Konfiguration oder Abgleich ungültig; Veröffentlichung blockiert.")
    return read_status()


def install(app, server):
    state = {"job": None}
    def start_job(force=False):
        task = state["job"]
        if task and not task.done():
            return
        state["job"] = asyncio.create_task(reconcile(server, force))
    async def periodic():
        while True:
            start_job()
            await asyncio.sleep(600)
    async def startup(app):
        app["native_reconcile_task"] = asyncio.create_task(periodic())
    async def shutdown(app):
        task = app.get("native_reconcile_task")
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        job = state["job"]
        if job:
            job.cancel()
            try:
                await job
            except asyncio.CancelledError:
                pass
    async def status(request):
        job = state["job"]
        failed = bool(job and job.done() and not job.cancelled() and job.exception())
        return web.json_response({"ok": True, **read_status(), "running": bool(job and not job.done()),
                                 "background_error": "Alexa-Abgleich konnte nicht abgeschlossen werden." if failed else None})
    async def sync(request):
        start_job(force=True)
        return web.json_response({"ok": True, "queued": True,
                                 "message": "Ausgewählte v6-Geräte werden veröffentlicht; alte v5-Kopien und abgewählte v6-Geräte werden bereinigt."}, status=202)
    app.on_startup.append(startup)
    app.on_cleanup.append(shutdown)
    app.router.add_get("/api/native-export/lifecycle", status)
    app.router.add_post("/api/native-export/sync", sync)
