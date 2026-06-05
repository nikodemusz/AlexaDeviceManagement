"""Patched entrypoint for Alexa Device Management.

Adds read-only discovery through the Alexa web endpoints used by the Alexa web app.
This is intentionally separated from server.py for the first iteration so the
existing OAuth flow stays untouched and easy to compare.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import aiohttp
from aiohttp import web

import server as base

_LOGGER = logging.getLogger(__name__)

_DEFAULT_ALEXA_HOST_BY_REGION: dict[str, str] = {
    "eu": "alexa.amazon.de",
    "na": "alexa.amazon.com",
    "fe": "alexa.amazon.co.jp",
}

_SECRET_FIELDS = {"alexa_cookie", "alexa_csrf", "client_secret", "refresh_token"}


def _safe_host(value: str) -> str:
    """Allow only normal host names, no scheme/path/header injection."""
    host = (value or "").strip().lower()
    host = host.removeprefix("https://").removeprefix("http://").split("/")[0]
    if not re.fullmatch(r"[a-z0-9.-]+", host):
        return ""
    return host


def _get_alexa_web_options() -> tuple[str, str, str]:
    """Return Alexa web host, cookie and csrf from add-on options."""
    options = base.load_options()
    region = options.get("amazon_region", "eu")
    host = _safe_host(options.get("alexa_host", ""))
    if not host:
        host = _DEFAULT_ALEXA_HOST_BY_REGION.get(region, "alexa.amazon.de")

    cookie = str(options.get("alexa_cookie", "") or "").strip()
    csrf = str(options.get("alexa_csrf", "") or "").strip()

    if cookie and not csrf:
        match = re.search(r"(?:^|;\s*)csrf=([^;]+)", cookie)
        if match:
            csrf = match.group(1)

    return host, cookie, csrf


def _redact_options(options: dict[str, Any]) -> dict[str, Any]:
    """Return option metadata without exposing secrets."""
    return {key: ("***" if key in _SECRET_FIELDS and value else value) for key, value in options.items()}


def _normalize_capabilities(raw: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("capabilities", "supportedOperations", "actions", "interfaces"):
        current = raw.get(key)
        if isinstance(current, list):
            for item in current:
                if isinstance(item, str) and item:
                    values.append(item)
                elif isinstance(item, dict):
                    name = item.get("interface") or item.get("name") or item.get("type")
                    if isinstance(name, str) and name:
                        values.append(name)
    return sorted(set(values))


def _normalize_echo_device(raw: dict[str, Any]) -> dict[str, Any]:
    serial = str(raw.get("serialNumber") or raw.get("deviceSerialNumber") or "")
    name = (
        raw.get("accountName")
        or raw.get("deviceAccountName")
        or raw.get("deviceTypeFriendlyName")
        or serial
        or "Unbekanntes Gerät"
    )
    return {
        "id": serial or str(raw.get("deviceType") or name),
        "name": str(name),
        "type": str(raw.get("deviceType") or "ECHO_DEVICE"),
        "family": str(raw.get("deviceFamily") or "ECHO"),
        "online": bool(raw.get("online", raw.get("isOnline", False))),
        "serial": serial,
        "firmware": str(raw.get("softwareVersion") or ""),
        "capabilities": _normalize_capabilities(raw),
        "room": "",
        "source": "alexa_web_devices_v2",
        "raw": raw,
    }


def _extract_smart_home_items(payload: Any) -> list[dict[str, Any]]:
    """Extract smart-home entities from several known Alexa web shapes."""
    items: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for entry in value:
                walk(entry)
            return
        if not isinstance(value, dict):
            return

        entity_id = (
            value.get("entityId")
            or value.get("applianceId")
            or value.get("id")
            or value.get("legacyAppliance", {}).get("applianceId")
        )
        name = (
            value.get("friendlyName")
            or value.get("name")
            or value.get("displayName")
            or value.get("applianceName")
        )
        if entity_id and name:
            items.append(value)
            return

        for key in ("entities", "appliances", "devices", "items", "nodes", "payload"):
            if key in value:
                walk(value[key])

    walk(payload)
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        key = str(
            item.get("entityId")
            or item.get("applianceId")
            or item.get("id")
            or item.get("legacyAppliance", {}).get("applianceId")
        )
        deduped[key] = item
    return list(deduped.values())


def _normalize_smart_home_device(raw: dict[str, Any]) -> dict[str, Any]:
    legacy = raw.get("legacyAppliance") if isinstance(raw.get("legacyAppliance"), dict) else {}
    details = raw.get("additionalApplianceDetails") if isinstance(raw.get("additionalApplianceDetails"), dict) else {}
    device_id = (
        raw.get("entityId")
        or raw.get("applianceId")
        or raw.get("id")
        or legacy.get("applianceId")
        or ""
    )
    name = (
        raw.get("friendlyName")
        or raw.get("name")
        or raw.get("displayName")
        or raw.get("applianceName")
        or legacy.get("friendlyName")
        or device_id
        or "Unbekanntes Gerät"
    )
    device_type = (
        raw.get("entityType")
        or raw.get("applianceType")
        or raw.get("displayCategories", [None])[0]
        if isinstance(raw.get("displayCategories"), list) and raw.get("displayCategories")
        else None
    ) or raw.get("deviceType") or legacy.get("applianceType") or "SMART_HOME"
    provider = (
        raw.get("providerName")
        or raw.get("manufacturerName")
        or raw.get("skillName")
        or legacy.get("manufacturerName")
        or details.get("manufacturer")
        or "SMART_HOME"
    )
    room = (
        raw.get("roomName")
        or raw.get("location")
        or raw.get("groupName")
        or details.get("roomName")
        or ""
    )
    return {
        "id": str(device_id),
        "name": str(name),
        "type": str(device_type),
        "family": str(provider),
        "online": bool(raw.get("isReachable", raw.get("reachable", raw.get("online", False)))),
        "serial": str(raw.get("serialNumber") or raw.get("applianceId") or device_id),
        "firmware": str(raw.get("softwareVersion") or raw.get("version") or ""),
        "capabilities": _normalize_capabilities(raw),
        "room": str(room),
        "source": "alexa_web_smart_home",
        "raw": raw,
    }


async def _get_json(session: aiohttp.ClientSession, host: str, path: str, headers: dict[str, str]) -> Any:
    url = f"https://{host}{path}"
    async with session.get(url, headers=headers) as resp:
        text = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"{path} failed ({resp.status}): {text[:300]}")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{path} did not return JSON: {text[:120]}") from exc


async def fetch_alexa_web_devices(
    session: aiohttp.ClientSession,
    host: str,
    cookie: str,
    csrf: str,
) -> list[dict[str, Any]]:
    """Fetch Alexa devices via the inofficial Alexa web endpoints, read-only."""
    if not cookie or not csrf:
        raise RuntimeError("Alexa Web Cookie oder CSRF Token fehlt.")

    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Cookie": cookie,
        "csrf": csrf,
        "Referer": f"https://{host}/spa/index.html",
        "Origin": f"https://{host}",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
    }

    devices_by_key: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    try:
        payload = await _get_json(session, host, "/api/devices-v2/device?cached=false", headers)
        for raw in payload.get("devices", []) if isinstance(payload, dict) else []:
            if isinstance(raw, dict):
                device = _normalize_echo_device(raw)
                devices_by_key[f"echo:{device['id']}"] = device
    except RuntimeError as exc:
        errors.append(str(exc))

    try:
        payload = await _get_json(
            session,
            host,
            "/api/behaviors/entities?skillId=amzn1.ask.1p.smarthome",
            headers,
        )
        for raw in _extract_smart_home_items(payload):
            device = _normalize_smart_home_device(raw)
            devices_by_key[f"smart_home:{device['id']}"] = device
    except RuntimeError as exc:
        errors.append(str(exc))

    if devices_by_key:
        return sorted(devices_by_key.values(), key=lambda item: item.get("name", "").lower())
    if errors:
        raise RuntimeError("; ".join(errors))
    return []


async def handle_api_devices(request: web.Request) -> web.Response:
    """Return device list as JSON, preferring Alexa Web discovery when configured."""
    host, cookie, csrf = _get_alexa_web_options()
    if cookie and csrf:
        try:
            devices = await fetch_alexa_web_devices(request.app["http_session"], host, cookie, csrf)
            return web.json_response({"devices": devices, "source": "alexa_web"})
        except RuntimeError as exc:
            _LOGGER.error("Failed to fetch devices from Alexa Web API: %s", exc)
            return web.json_response({
                "devices": base.get_demo_devices(),
                "api_error": str(exc),
                "source": "demo",
            })

    return await base.handle_api_devices(request)


async def handle_api_config_status(request: web.Request) -> web.Response:
    """Return config status including Alexa Web credentials."""
    response = await base.handle_api_config_status(request)
    try:
        data = json.loads(response.text)
    except (TypeError, json.JSONDecodeError):
        return response
    host, cookie, csrf = _get_alexa_web_options()
    data["alexa_web_configured"] = bool(cookie and csrf)
    data["alexa_host"] = host
    data["configured"] = bool(data.get("configured") or data["alexa_web_configured"])
    return web.json_response(data)


async def handle_api_app_info(request: web.Request) -> web.Response:
    """Return app metadata and include Alexa Web auth source information."""
    response = await base.handle_api_app_info(request)
    try:
        data = json.loads(response.text)
    except (TypeError, json.JSONDecodeError):
        return response
    host, cookie, csrf = _get_alexa_web_options()
    if cookie and csrf:
        data["configured"] = True
        data["authenticated"] = True
        data["token_source"] = "alexa_web_cookie"
        data["auth_message"] = f"Alexa-Web-Zugangsdaten vorhanden ({host})."
    return web.json_response(data)


# Patch route handlers before create_app() registers them.
base.handle_api_devices = handle_api_devices
base.handle_api_config_status = handle_api_config_status
base.handle_api_app_info = handle_api_app_info


if __name__ == "__main__":
    port = int(os.environ.get("INGRESS_PORT", "8099"))
    _LOGGER.info("Starting Alexa Device Management patched web server on port %d", port)
    web.run_app(base.create_app(), host="0.0.0.0", port=port)
