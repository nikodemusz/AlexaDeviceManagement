"""WebSocket API for Alexa Device Management.

Registers WebSocket commands analogous to Z-Wave JS / Zigbee2MQTT.
The frontend communicates with the backend exclusively via these commands.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, WS_PREFIX
from .manager import AlexaDeviceManager


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register all WebSocket commands."""
    websocket_api.async_register_command(hass, ws_get_connection_state)
    websocket_api.async_register_command(hass, ws_list_devices)
    websocket_api.async_register_command(hass, ws_get_device)
    websocket_api.async_register_command(hass, ws_delete_device)
    websocket_api.async_register_command(hass, ws_rename_device)
    websocket_api.async_register_command(hass, ws_refresh_devices)
    websocket_api.async_register_command(hass, ws_subscribe_events)


def _get_manager(hass: HomeAssistant) -> AlexaDeviceManager | None:
    """Get the manager instance from hass.data."""
    domain_data: dict[str, Any] = hass.data.get(DOMAIN, {})
    for entry_data in domain_data.values():
        if isinstance(entry_data, dict) and "manager" in entry_data:
            return entry_data["manager"]
    return None


# ------------------------------------------------------------------
# WebSocket command handlers
# ------------------------------------------------------------------


@websocket_api.websocket_command(
    {vol.Required("type"): f"{WS_PREFIX}/connection_state"}
)
@websocket_api.async_response
async def ws_get_connection_state(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the current connection state."""
    manager = _get_manager(hass)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "Integration not loaded")
        return
    connection.send_result(msg["id"], {"state": manager.state})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{WS_PREFIX}/list_devices"}
)
@websocket_api.async_response
async def ws_list_devices(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return all known devices."""
    manager = _get_manager(hass)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "Integration not loaded")
        return
    devices = await manager.async_list_devices()
    connection.send_result(msg["id"], {"devices": devices})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/get_device",
        vol.Required("device_id"): str,
    }
)
@websocket_api.async_response
async def ws_get_device(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return a single device."""
    manager = _get_manager(hass)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "Integration not loaded")
        return
    device = await manager.async_get_device(msg["device_id"])
    if device is None:
        connection.send_error(msg["id"], "not_found", "Device not found")
        return
    connection.send_result(msg["id"], {"device": device})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/delete_device",
        vol.Required("device_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_device(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a device."""
    manager = _get_manager(hass)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "Integration not loaded")
        return
    success = await manager.async_delete_device(msg["device_id"])
    connection.send_result(msg["id"], {"success": success})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{WS_PREFIX}/rename_device",
        vol.Required("device_id"): str,
        vol.Required("name"): str,
    }
)
@websocket_api.async_response
async def ws_rename_device(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Rename a device."""
    manager = _get_manager(hass)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "Integration not loaded")
        return
    success = await manager.async_rename_device(msg["device_id"], msg["name"])
    connection.send_result(msg["id"], {"success": success})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{WS_PREFIX}/refresh_devices"}
)
@websocket_api.async_response
async def ws_refresh_devices(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Refresh device list from Alexa API."""
    manager = _get_manager(hass)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "Integration not loaded")
        return
    devices = await manager.async_refresh_devices()
    connection.send_result(msg["id"], {"devices": devices})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{WS_PREFIX}/subscribe"}
)
@websocket_api.async_response
async def ws_subscribe_events(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to device/connection events (push updates to frontend).

    Analogous to zwave_js/subscribe_log_updates or zigbee2mqtt event subscriptions.
    """
    from .const import EVENT_CONNECTION_STATE_CHANGED, EVENT_DEVICES_UPDATED

    @callback
    def forward_event(event):
        """Forward HA bus event to WebSocket."""
        connection.send_message(
            websocket_api.event_message(msg["id"], event.data)
        )

    unsub_conn = hass.bus.async_listen(EVENT_CONNECTION_STATE_CHANGED, forward_event)
    unsub_devices = hass.bus.async_listen(EVENT_DEVICES_UPDATED, forward_event)

    @callback
    def cancel_subscription():
        unsub_conn()
        unsub_devices()

    connection.subscriptions[msg["id"]] = cancel_subscription
    connection.send_result(msg["id"])
