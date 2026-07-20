"""Manage Alexa smart-home groups and synchronize Home Assistant areas."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Iterable
from urllib.parse import quote

from aiohttp import web


_GROUP_MEMBER_KEYS = (
    "applianceIds",
    "applianceKeys",
    "associatedApplianceIds",
    "associatedApplianceKeys",
    "members",
)
_ID_KEYS = {
    "id",
    "entityid",
    "endpointid",
    "applianceid",
    "appliancekey",
    "serial",
    "serialnumber",
    "deviceserialnumber",
    "groupid",
}
_COOKIE_SUFFIXES = ("acbmx", "acbus", "acbde", "acbuk", "acbjp", "acbin")


class AlexaGroupError(RuntimeError):
    """Raised when Alexa group data cannot be read or changed safely."""


def _parse_nested(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in ("{", "["):
        try:
            return _parse_nested(json.loads(value))
        except (json.JSONDecodeError, RecursionError):
            return value
    if isinstance(value, dict):
        return {key: _parse_nested(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_parse_nested(child) for child in value]
    return value


def _canonical(value: Any) -> set[str]:
    text = str(value or "").strip().lower()
    if not text:
        return set()
    values = {text}
    prefix = "amzn1.alexa.endpoint."
    if text.startswith(prefix):
        values.add(text[len(prefix):])
    return values


def _collect_identifiers(value: Any) -> set[str]:
    result: set[str] = set()

    def walk(current: Any) -> None:
        if isinstance(current, dict):
            for key, child in current.items():
                normalized = str(key).replace("_", "").lower()
                if normalized in _ID_KEYS and not isinstance(child, (dict, list)):
                    result.update(_canonical(child))
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(current, list):
            for child in current:
                walk(child)
        elif isinstance(current, (str, int)):
            result.update(_canonical(current))

    walk(value)
    return result


def _member_values(group: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key in _GROUP_MEMBER_KEYS:
        value = group.get(key)
        if value is None:
            continue
        if not isinstance(value, list):
            value = [value]
        for entry in value:
            if isinstance(entry, (str, int)):
                text = str(entry).strip()
                if text:
                    result.append(text)
                continue
            if isinstance(entry, dict):
                for candidate in (
                    entry.get("applianceId"),
                    entry.get("applianceKey"),
                    entry.get("entityId"),
                    entry.get("endpointId"),
                    entry.get("id"),
                ):
                    text = str(candidate or "").strip()
                    if text:
                        result.append(text)
                        break
        if result:
            break
    return list(dict.fromkeys(result))


def extract_groups(payload: Any) -> list[dict[str, Any]]:
    """Extract Alexa SPACE/group objects from nested Phoenix payloads."""
    parsed = _parse_nested(payload)
    groups: dict[str, dict[str, Any]] = {}

    def walk(current: Any) -> None:
        if isinstance(current, dict):
            member_key = next((key for key in _GROUP_MEMBER_KEYS if key in current), None)
            name = str(
                current.get("groupName")
                or current.get("name")
                or current.get("friendlyName")
                or ""
            ).strip()
            group_id = str(
                current.get("groupId")
                or current.get("id")
                or current.get("uuid")
                or ""
            ).strip()
            group_type = str(current.get("type") or current.get("groupType") or "").strip()
            if member_key and name and group_id:
                members = _member_values(current)
                groups[group_id] = {
                    "id": group_id,
                    "name": name,
                    "type": group_type or "SPACE",
                    "member_ids": members,
                    "raw": current,
                }
            for child in current.values():
                if isinstance(child, (dict, list, str)):
                    walk(child)
        elif isinstance(current, list):
            for child in current:
                walk(child)
        elif isinstance(current, str) and current[:1] in ("{", "["):
            nested = _parse_nested(current)
            if nested is not current:
                walk(nested)

    walk(parsed)
    return sorted(groups.values(), key=lambda item: item["name"].casefold())


def _enrich_cookie_aliases(data: dict[str, Any]) -> dict[str, Any]:
    result = dict(data)
    cookie = str(result.get("cookie") or "")
    cookies: dict[str, str] = {}
    for part in cookie.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name:
            cookies[name] = value
    additions: list[str] = []
    for suffix in _COOKIE_SUFFIXES:
        if not cookies.get("at-main") and cookies.get(f"at-{suffix}"):
            additions.append(f"at-main={cookies[f'at-{suffix}']}")
            cookies["at-main"] = cookies[f"at-{suffix}"]
        if not cookies.get("ubid-main") and cookies.get(f"ubid-{suffix}"):
            additions.append(f"ubid-main={cookies[f'ubid-{suffix}']}")
            cookies["ubid-main"] = cookies[f"ubid-{suffix}"]
    if additions:
        result["cookie"] = cookie.rstrip("; ") + "; " + "; ".join(additions)
    return result


async def _load_groups(server: Any, data: dict[str, Any]) -> list[dict[str, Any]]:
    status, body = await server.alexa_raw_get("/api/phoenix", data)
    if status != 200:
        raise AlexaGroupError(f"Alexa-Gruppen konnten nicht geladen werden (HTTP {status}): {body[:200]}")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise AlexaGroupError("Alexa hat ungültige Phoenix-Daten geliefert.") from exc
    return extract_groups(payload)


def _device_identifiers(device: dict[str, Any]) -> set[str]:
    return _collect_identifiers({
        "serial": device.get("serial"),
        "applianceId": device.get("appliance_id"),
        "raw": device.get("raw") or {},
    })


def _preferred_device_id(device: dict[str, Any]) -> str:
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    legacy = raw.get("legacyAppliance") if isinstance(raw.get("legacyAppliance"), dict) else {}
    for value in (
        device.get("appliance_id"),
        legacy.get("applianceId"),
        raw.get("applianceId"),
        raw.get("entityId"),
        raw.get("id"),
        device.get("serial"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _device_entity_id(device: dict[str, Any]) -> str:
    manufacturer = str(device.get("manufacturer") or "").strip()
    if "." in manufacturer and " " not in manufacturer:
        return manufacturer
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    description = str(raw.get("description") or "").strip()
    if " via " in description:
        candidate = description.partition(" via ")[0].strip()
        if "." in candidate:
            return candidate
    return ""


def _group_member_identifiers(group: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for member in group.get("member_ids", []):
        values.update(_canonical(member))
    return values


def _find_group(groups: Iterable[dict[str, Any]], name: str) -> dict[str, Any] | None:
    target = name.strip().casefold()
    return next((group for group in groups if str(group.get("name") or "").strip().casefold() == target), None)


async def _write_group(
    server: Any,
    data: dict[str, Any],
    group: dict[str, Any] | None,
    name: str,
    member_ids: list[str],
) -> None:
    write_data = _enrich_cookie_aliases(data)
    payload: dict[str, Any] = {"name": name, "applianceIds": member_ids}
    if group is None:
        payload["type"] = "SPACE"
        status, body = await server.alexa_raw_post(
            "/api/phoenix/group", json.dumps(payload).encode(), write_data
        )
    else:
        status, body = await server.alexa_raw_put(
            f"/api/phoenix/group/{quote(str(group['id']), safe='')}",
            json.dumps(payload).encode(),
            write_data,
        )
    if status not in (200, 201, 202, 204):
        action = "erstellt" if group is None else "aktualisiert"
        raise AlexaGroupError(
            f"Alexa-Gruppe „{name}“ konnte nicht {action} werden (HTTP {status}): {body[:250]}"
        )


async def _ensure_assignment(
    server: Any,
    data: dict[str, Any],
    groups: list[dict[str, Any]],
    device: dict[str, Any],
    group_name: str,
    *,
    create_missing: bool,
    remove_from_other_groups: bool,
) -> tuple[list[dict[str, Any]], bool]:
    device_id = _preferred_device_id(device)
    if not device_id:
        raise AlexaGroupError(f"Für „{device.get('name') or 'Gerät'}“ fehlt eine Alexa-Geräte-ID.")
    device_ids = _device_identifiers(device) | _canonical(device_id)
    target = _find_group(groups, group_name)
    if target is None and not create_missing:
        raise AlexaGroupError(f"Alexa-Gruppe „{group_name}“ existiert nicht.")

    changed = False
    current_members = list(target.get("member_ids", [])) if target else []
    current_identifiers = _group_member_identifiers(target) if target else set()
    if not (device_ids & current_identifiers):
        await _write_group(server, data, target, group_name, [*current_members, device_id])
        changed = True

    groups = await _load_groups(server, data)
    target = _find_group(groups, group_name)
    if target is None:
        raise AlexaGroupError(f"Alexa-Gruppe „{group_name}“ wurde nach dem Schreiben nicht gefunden.")
    if not (device_ids & _group_member_identifiers(target)):
        raise AlexaGroupError(
            f"Alexa hat die Zuordnung von „{device.get('name') or device_id}“ zu „{group_name}“ nicht bestätigt."
        )

    if remove_from_other_groups:
        for group in list(groups):
            if group.get("id") == target.get("id"):
                continue
            if str(group.get("type") or "SPACE").upper() not in ("SPACE", "GROUP"):
                continue
            if not (device_ids & _group_member_identifiers(group)):
                continue
            remaining = [
                member for member in group.get("member_ids", [])
                if not (_canonical(member) & device_ids)
            ]
            await _write_group(server, data, group, str(group["name"]), remaining)
            changed = True
        groups = await _load_groups(server, data)
        target = _find_group(groups, group_name)
        if target is None or not (device_ids & _group_member_identifiers(target)):
            raise AlexaGroupError(
                f"Alexa hat die Zielgruppe „{group_name}“ nach der Bereinigung nicht bestätigt."
            )

    return groups, changed


async def _inventory(server: Any) -> list[dict[str, Any]]:
    cache = await server.refresh_devices_cache()
    devices = cache.get("devices", []) if isinstance(cache, dict) else []
    return [device for device in devices if str(device.get("source") or "") != "echo"]


def _public_inventory(groups: list[dict[str, Any]], devices: list[dict[str, Any]]) -> dict[str, Any]:
    device_by_identifier: dict[str, dict[str, Any]] = {}
    for device in devices:
        for identifier in _device_identifiers(device):
            device_by_identifier.setdefault(identifier, device)

    public_groups: list[dict[str, Any]] = []
    for group in groups:
        members: list[dict[str, str]] = []
        for member_id in group.get("member_ids", []):
            device = next(
                (device_by_identifier.get(identifier) for identifier in _canonical(member_id) if identifier in device_by_identifier),
                None,
            )
            members.append({
                "id": member_id,
                "name": str((device or {}).get("name") or member_id),
            })
        public_groups.append({
            "id": group["id"],
            "name": group["name"],
            "type": group.get("type") or "SPACE",
            "member_ids": list(group.get("member_ids", [])),
            "members": members,
        })

    public_devices = [{
        "id": _preferred_device_id(device),
        "serial": str(device.get("serial") or ""),
        "name": str(device.get("name") or ""),
        "room": str(device.get("room") or ""),
        "entity_id": _device_entity_id(device),
        "source": str(device.get("source") or ""),
    } for device in devices if _preferred_device_id(device)]
    public_devices.sort(key=lambda item: item["name"].casefold())
    return {"groups": public_groups, "devices": public_devices}


async def list_groups(request: web.Request) -> web.Response:
    server = request.app["alexa_group_server"]
    if not server.is_configured():
        raise web.HTTPUnauthorized(text="Alexa-Web-Session fehlt.")
    data = server.session_data()
    try:
        groups = await _load_groups(server, data)
        devices = await _inventory(server)
        return web.json_response({"ok": True, **_public_inventory(groups, devices)})
    except AlexaGroupError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=502)


async def assign_group(request: web.Request) -> web.Response:
    server = request.app["alexa_group_server"]
    if not server.is_configured():
        raise web.HTTPUnauthorized(text="Alexa-Web-Session fehlt.")
    try:
        body = await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(text="Ungültige JSON-Daten.") from exc

    device_id = str(body.get("device_id") or "").strip()
    group_name = str(body.get("group_name") or "").strip()
    if not device_id or not group_name:
        raise web.HTTPBadRequest(text="device_id und group_name sind erforderlich.")

    data = server.session_data()
    try:
        devices = await _inventory(server)
        wanted = _canonical(device_id)
        device = next((item for item in devices if wanted & _device_identifiers(item)), None)
        if device is None:
            raise AlexaGroupError(f"Alexa-Gerät {device_id!r} wurde nicht gefunden.")
        groups = await _load_groups(server, data)
        groups, changed = await _ensure_assignment(
            server,
            data,
            groups,
            device,
            group_name,
            create_missing=bool(body.get("create_missing", True)),
            remove_from_other_groups=bool(body.get("remove_from_other_groups", False)),
        )
        await server.refresh_devices_cache()
        devices = await _inventory(server)
        return web.json_response({
            "ok": True,
            "changed": changed,
            "group": group_name,
            "device": str(device.get("name") or device_id),
            **_public_inventory(groups, devices),
        })
    except AlexaGroupError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=502)


async def sync_ha_groups(request: web.Request) -> web.Response:
    server = request.app["alexa_group_server"]
    store = request.app["alexa_group_config_store"]
    if not server.is_configured():
        raise web.HTTPUnauthorized(text="Alexa-Web-Session fehlt.")
    try:
        body = await request.json()
    except Exception:
        body = {}

    config = body.get("configuration") if isinstance(body.get("configuration"), dict) else store.load()
    settings = config.get("group_sync") if isinstance(config.get("group_sync"), dict) else {}
    create_missing = bool(body.get("create_missing", settings.get("create_missing", True)))
    remove_from_other_groups = bool(
        body.get("remove_from_other_groups", settings.get("remove_from_other_groups", False))
    )

    desired: dict[str, str] = {}
    for entity_id, entity in (config.get("entities") or {}).items():
        if not isinstance(entity, dict) or not entity.get("enabled"):
            continue
        group_name = str(entity.get("alexa_group") or "").strip()
        if group_name:
            desired[str(entity_id)] = group_name
    if not desired:
        return web.json_response({
            "ok": False,
            "error": "Keine aktivierte HA-Entität besitzt eine Alexa-Gruppe.",
        }, status=400)

    data = server.session_data()
    results: list[dict[str, Any]] = []
    try:
        devices = await _inventory(server)
        devices_by_entity: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for device in devices:
            entity_id = _device_entity_id(device)
            if entity_id:
                devices_by_entity[entity_id].append(device)

        groups = await _load_groups(server, data)
        for entity_id, group_name in desired.items():
            candidates = devices_by_entity.get(entity_id, [])
            if len(candidates) != 1:
                results.append({
                    "entity_id": entity_id,
                    "group": group_name,
                    "ok": False,
                    "error": (
                        "Alexa-Endpunkt noch nicht gefunden. Bitte zuerst die Alexa-Gerätesuche ausführen."
                        if not candidates else "Mehrere Alexa-Endpunkte passen zu dieser Entity-ID."
                    ),
                })
                continue
            device = candidates[0]
            try:
                groups, changed = await _ensure_assignment(
                    server,
                    data,
                    groups,
                    device,
                    group_name,
                    create_missing=create_missing,
                    remove_from_other_groups=remove_from_other_groups,
                )
                results.append({
                    "entity_id": entity_id,
                    "device": str(device.get("name") or entity_id),
                    "group": group_name,
                    "ok": True,
                    "changed": changed,
                })
            except AlexaGroupError as exc:
                results.append({
                    "entity_id": entity_id,
                    "group": group_name,
                    "ok": False,
                    "error": str(exc),
                })

        await server.refresh_devices_cache()
        failed = [item for item in results if not item.get("ok")]
        changed_count = sum(1 for item in results if item.get("changed"))
        return web.json_response({
            "ok": not failed,
            "total": len(results),
            "successful": len(results) - len(failed),
            "changed": changed_count,
            "failed": len(failed),
            "results": results,
        }, status=207 if failed else 200)
    except AlexaGroupError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=502)


def register_routes(app: web.Application, server: Any, config_store: Any) -> None:
    app["alexa_group_server"] = server
    app["alexa_group_config_store"] = config_store
    app.router.add_get("/api/alexa-groups", list_groups)
    app.router.add_post("/api/alexa-groups/assign", assign_group)
    app.router.add_post("/api/ha-export/group-sync", sync_ha_groups)
