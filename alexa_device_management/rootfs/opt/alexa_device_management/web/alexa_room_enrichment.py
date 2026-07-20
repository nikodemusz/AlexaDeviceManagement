"""Enrich Alexa inventory rows with useful descriptions and room assignments."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any


_ID_KEYS = {
    "id", "entityid", "endpointid", "applianceid", "appliancekey",
    "serial", "serialnumber", "deviceserialnumber",
}
_ROOM_KEYS = ("roomName", "groupName", "locationName", "location", "room")
_DESCRIPTION_KEYS = (
    "description", "friendlyDescription", "displayDescription", "deviceDescription",
)


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


def _identifiers(value: Any) -> set[str]:
    result: set[str] = set()

    def walk(current: Any) -> None:
        if isinstance(current, dict):
            for key, child in current.items():
                normalized = str(key).replace("_", "").lower()
                if normalized in _ID_KEYS and not isinstance(child, (dict, list)):
                    text = str(child or "").strip().lower()
                    if text:
                        result.add(text)
                        if text.startswith("amzn1.alexa.endpoint."):
                            result.add(text.removeprefix("amzn1.alexa.endpoint."))
                walk(child)
        elif isinstance(current, list):
            for child in current:
                walk(child)

    walk(value)
    return result


def _first_text(value: Any, keys: tuple[str, ...]) -> str:
    if isinstance(value, dict):
        for key in keys:
            text = value.get(key)
            if not isinstance(text, (dict, list)) and str(text or "").strip():
                return str(text).strip()
        for child in value.values():
            found = _first_text(child, keys)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_text(child, keys)
            if found:
                return found
    return ""


def _collect_group_members(value: Any) -> dict[str, set[str]]:
    memberships: dict[str, set[str]] = defaultdict(set)

    def walk(current: Any) -> None:
        if isinstance(current, dict):
            room = str(
                current.get("groupName") or current.get("roomName")
                or current.get("friendlyName") or ""
            ).strip()
            group_hint = any(
                key in current
                for key in ("applianceIds", "applianceKeys", "associatedApplianceIds", "members")
            )
            if room and group_hint:
                for identifier in _identifiers(current):
                    memberships[identifier].add(room)
            for child in current.values():
                walk(child)
        elif isinstance(current, list):
            for child in current:
                walk(child)

    walk(value)
    return memberships


def _description(device: dict[str, Any]) -> str:
    raw = device.get("raw") or {}
    text = _first_text(raw, _DESCRIPTION_KEYS)
    if text:
        return text
    if device.get("source") == "smart_home":
        return str(raw.get("description") or "").strip()
    return str(device.get("family") or "").strip()


def _enrich(devices: list[dict[str, Any]], phoenix: Any) -> None:
    parsed = _parse_nested(phoenix)
    memberships = _collect_group_members(parsed)

    for device in devices:
        original_family = str(device.get("family") or "").strip()
        description = _description(device)
        device["manufacturer"] = original_family
        device["description"] = description
        # The existing table column uses `family`; expose the useful description
        # there while retaining the real manufacturer separately.
        device["family"] = description or original_family

        if str(device.get("room") or "").strip():
            continue

        raw = device.get("raw") or {}
        room = _first_text(raw, _ROOM_KEYS)
        identifiers = _identifiers({
            "serial": device.get("serial"),
            "applianceId": device.get("appliance_id"),
            "raw": raw,
        })
        if not room:
            rooms = sorted({name for identifier in identifiers for name in memberships.get(identifier, set())})
            room = ", ".join(rooms)
        device["room"] = room


def install(server: Any) -> None:
    """Wrap the Alexa inventory fetcher once."""
    if getattr(server, "_ROOM_ENRICHMENT_INSTALLED", False):
        return

    original_fetch = server._fetch_devices_from_alexa

    async def fetch_devices(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        devices, errors = await original_fetch(data)
        phoenix_payload: Any = {}
        try:
            status, body = await server.alexa_raw_get("/api/phoenix", data)
            if status == 200:
                phoenix_payload = json.loads(body)
        except Exception:
            phoenix_payload = {}
        _enrich(devices, phoenix_payload)
        return devices, errors

    server._fetch_devices_from_alexa = fetch_devices
    server._ROOM_ENRICHMENT_INSTALLED = True
