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
_MAX_NESTED_JSON_LENGTH = 1_000_000
_MAX_WALK_NODES = 100_000


def _nested_json(value: Any) -> Any:
    """Decode a reasonably sized embedded JSON value without copying payloads."""
    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    if not stripped[:1] in ("{", "[") or len(value) > _MAX_NESTED_JSON_LENGTH:
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, RecursionError):
        return value


def _walk(value: Any):
    """Iterate over nested Alexa payloads with bounded memory and stack depth."""
    stack = [value]
    visited = 0
    while stack and visited < _MAX_WALK_NODES:
        current = _nested_json(stack.pop())
        visited += 1
        yield current
        if isinstance(current, dict):
            stack.extend(reversed(tuple(current.values())))
        elif isinstance(current, list):
            stack.extend(reversed(current))


def _identifiers(value: Any) -> set[str]:
    result: set[str] = set()
    for current in _walk(value):
        if isinstance(current, dict):
            for key, child in current.items():
                normalized = str(key).replace("_", "").lower()
                if normalized in _ID_KEYS and not isinstance(child, (dict, list)):
                    text = str(child or "").strip().lower()
                    if text:
                        result.add(text)
                        if text.startswith("amzn1.alexa.endpoint."):
                            result.add(text.removeprefix("amzn1.alexa.endpoint."))
    return result


def _first_text(value: Any, keys: tuple[str, ...]) -> str:
    for current in _walk(value):
        if not isinstance(current, dict):
            continue
        for key in keys:
            text = current.get(key)
            if not isinstance(text, (dict, list)) and str(text or "").strip():
                return str(text).strip()
    return ""


def _membership_identifiers(value: Any) -> set[str]:
    """Read both scalar member IDs and identifier fields in member objects."""
    result = _identifiers(value)
    for current in _walk(value):
        if isinstance(current, (dict, list)) or current is None:
            continue
        text = str(current).strip().lower()
        if text:
            result.add(text)
            if text.startswith("amzn1.alexa.endpoint."):
                result.add(text.removeprefix("amzn1.alexa.endpoint."))
    return result


def _collect_group_members(value: Any) -> dict[str, set[str]]:
    memberships: dict[str, set[str]] = defaultdict(set)
    for current in _walk(value):
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
                # Only inspect membership fields. Walking the entire group subtree
                # here made large Phoenix responses quadratic and could OOM the app.
                member_values = [
                    current.get(key)
                    for key in ("applianceIds", "applianceKeys", "associatedApplianceIds", "members")
                    if key in current
                ]
                for identifier in _membership_identifiers(member_values):
                    memberships[identifier].add(room)
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
    memberships = _collect_group_members(phoenix)

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
