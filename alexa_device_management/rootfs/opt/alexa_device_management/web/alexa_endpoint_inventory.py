"""Supplement the Alexa device list with GraphQL-only endpoints.

Amazon keeps inactive or orphaned smart-home endpoints in the modern Nexus
GraphQL registry even after they disappear from ``behaviors/entities``.  The
legacy device page only queried Echo devices and active behavior entities, so
those stale entries could still be visible in the Alexa app but not manageable
here.

This module is installed as a small runtime extension around ``server_clean``.
It adds GraphQL-only endpoints to the cached inventory and provides deletion
with GraphQL-based verification.  Existing Echo and active smart-home handling
remains untouched.
"""

from __future__ import annotations

import re
from typing import Any

_ENDPOINT_PREFIX = "amzn1.alexa.endpoint."
_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
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
}


def _canonical_identifiers(value: Any) -> set[str]:
    """Return comparable lowercase identifiers for one Alexa ID value."""
    text = str(value or "").strip()
    if not text:
        return set()

    lowered = text.lower()
    result = {lowered}
    if lowered.startswith(_ENDPOINT_PREFIX):
        result.add(lowered[len(_ENDPOINT_PREFIX):])

    uuid_match = _UUID_PATTERN.search(lowered)
    if uuid_match:
        result.add(uuid_match.group(0))
    return result


def _collect_identifiers(value: Any) -> set[str]:
    """Collect known identifier fields from nested Alexa payloads."""
    result: set[str] = set()

    def walk(current: Any) -> None:
        if isinstance(current, dict):
            for key, child in current.items():
                normalized_key = str(key).replace("_", "").lower()
                if normalized_key in _ID_KEYS and not isinstance(child, (dict, list)):
                    result.update(_canonical_identifiers(child))
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(current, list):
            for child in current:
                walk(child)

    walk(value)
    return result


def _device_identifiers(device: dict[str, Any]) -> set[str]:
    values = {
        *(_canonical_identifiers(device.get("serial"))),
        *(_canonical_identifiers(device.get("appliance_id"))),
    }
    values.update(_collect_identifiers(device.get("raw") or {}))
    return values


def _endpoint_identifiers(endpoint: dict[str, Any]) -> set[str]:
    return _collect_identifiers(endpoint)


def _endpoint_serial(endpoint: dict[str, Any]) -> str:
    legacy = endpoint.get("legacyIdentifiers")
    if not isinstance(legacy, dict):
        legacy = {}
    chrs = legacy.get("chrsIdentifier")
    if not isinstance(chrs, dict):
        chrs = {}

    entity_id = str(chrs.get("entityId") or "").strip()
    if entity_id:
        return entity_id

    endpoint_id = str(endpoint.get("endpointId") or "").strip()
    if endpoint_id.lower().startswith(_ENDPOINT_PREFIX):
        return endpoint_id[len(_ENDPOINT_PREFIX):]
    return endpoint_id


def _normalize_orphaned_endpoint(endpoint: dict[str, Any]) -> dict[str, Any] | None:
    serial = _endpoint_serial(endpoint)
    if not serial:
        return None

    name = str(endpoint.get("friendlyName") or serial or "Inaktives Alexa-Gerät")
    raw = dict(endpoint)
    raw["alexaDeviceManagementState"] = "orphaned"
    return {
        "name": name,
        "serial": serial,
        # Keep appliance_id identical to serial so server_clean takes its v3
        # GraphQL path instead of attempting a legacy Phoenix DELETE directly.
        "appliance_id": serial,
        "type": "INACTIVE_ENDPOINT",
        "family": "Alexa Endpoint Registry",
        "skill": "Inaktiv / verwaist",
        "online": False,
        "firmware": "",
        "capabilities": [],
        "room": "",
        "source": "graphql",
        "lifecycle": "orphaned",
        "raw": raw,
    }


async def _fetch_graphql_endpoints(
    server: Any, data: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Read all smart-home endpoints from the Nexus GraphQL registry."""
    failures: list[str] = []
    queries = (
        ("full", server.ENDPOINTS_QUERY_FULL),
        ("minimal", server.ENDPOINTS_QUERY_MINIMAL),
    )
    for label, query in queries:
        try:
            status, payload = await server.alexa_graphql(query, None, data)
        except Exception as exc:
            failures.append(f"{label}: {exc}")
            continue

        if not isinstance(payload, dict):
            failures.append(f"{label}: ungültige Antwort")
            continue

        errors = payload.get("errors")
        items = (((payload.get("data") or {}).get("endpoints") or {}).get("items"))
        if status == 200 and isinstance(items, list) and not errors:
            return [item for item in items if isinstance(item, dict)], []

        detail = f"HTTP {status}"
        if errors:
            detail += f" {str(errors)[:180]}"
        elif "raw" in payload:
            detail += f" {str(payload['raw'])[:180]}"
        failures.append(f"{label}: {detail}")

    warning = "Alexa-Endpunkte (GraphQL): " + " | ".join(failures or ["keine gültige Antwort"])
    return [], [warning]


async def _endpoint_exists(server: Any, serial: str, data: dict[str, Any]) -> bool | None:
    """Return endpoint presence, or None when verification could not run."""
    endpoints, errors = await _fetch_graphql_endpoints(server, data)
    if errors:
        return None
    target_ids = _canonical_identifiers(serial)
    return any(target_ids & _endpoint_identifiers(endpoint) for endpoint in endpoints)


async def _delete_graphql_endpoint(server: Any, serial: str, data: dict[str, Any]) -> None:
    """Delete one GraphQL-only endpoint and verify it left the registry."""
    endpoint, lookup_debug = await server.graphql_find_endpoint(serial, data)
    if not endpoint:
        exists = await _endpoint_exists(server, serial, data)
        if exists is False:
            return
        raise RuntimeError(
            f"GraphQL-Endpunkt {serial!r} konnte nicht aufgelöst werden: {lookup_debug}"
        )

    endpoint_id = str(endpoint.get("endpointId") or serial)
    delete_fields = await server.gql_find_mutations(
        r"(delete|forget|remove|unlink|deregister)", data
    )
    delete_fields = [
        field
        for field in delete_fields
        if re.search(
            r"endpoint|appliance|device|entity|smarthome",
            str(field.get("name") or ""),
            re.IGNORECASE,
        )
    ][:8]

    attempts: list[str] = []
    for field in delete_fields:
        field_name = str(field.get("name") or "unknown")
        for identifier in dict.fromkeys((endpoint_id, serial)):
            accepted, info = await server.gql_execute_mutation(
                field, {"id": identifier}, ("id",), data
            )
            attempts.append(f"{field_name}[{identifier[:48]}]: {str(info)[:220]}")
            if not accepted:
                continue

            exists = await _endpoint_exists(server, serial, data)
            if exists is False:
                return
            if exists is None:
                raise RuntimeError(
                    "GraphQL-Löschung wurde angenommen, konnte aber nicht verifiziert werden."
                )

    if not delete_fields:
        raise RuntimeError("Keine passende GraphQL-Löschmutation im Alexa-Schema gefunden.")
    raise RuntimeError(
        "Alexa hat den inaktiven Endpunkt nach den Löschversuchen weiterhin geliefert. "
        + " | ".join(attempts[-8:])
    )


def install(server: Any) -> None:
    """Install GraphQL inventory and delete extensions into ``server_clean``."""
    if getattr(server, "_GRAPHQL_ENDPOINT_INVENTORY_INSTALLED", False):
        return

    original_fetch = server._fetch_devices_from_alexa
    original_delete = server._delete_target

    async def fetch_devices(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        devices, errors = await original_fetch(data)
        endpoints, endpoint_errors = await _fetch_graphql_endpoints(server, data)

        known_ids: set[str] = set()
        for device in devices:
            known_ids.update(_device_identifiers(device))

        for endpoint in endpoints:
            identifiers = _endpoint_identifiers(endpoint)
            if not identifiers or identifiers & known_ids:
                continue
            device = _normalize_orphaned_endpoint(endpoint)
            if not device:
                continue
            devices.append(device)
            known_ids.update(identifiers)

        devices.sort(key=lambda item: str(item.get("name") or "").lower())
        return devices, [*errors, *endpoint_errors]

    async def delete_target(target: dict[str, Any], data: dict[str, Any]) -> None:
        if str(target.get("source") or "") == "graphql":
            serial = str(target.get("serial") or "").strip()
            if not serial:
                raise RuntimeError("Missing serial")
            await _delete_graphql_endpoint(server, serial, data)
            return
        await original_delete(target, data)

    server._fetch_devices_from_alexa = fetch_devices
    server._delete_target = delete_target
    server._GRAPHQL_ENDPOINT_INVENTORY_INSTALLED = True
