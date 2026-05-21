"""Alexa Device Management integration.

Architecture follows the Z-Wave JS / Zigbee2MQTT pattern:
- A manager maintains the connection to the Alexa API
- WebSocket commands expose the manager to the frontend
- A custom panel provides a full device-management UI
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .manager import AlexaDeviceManager
from .panel import async_register_panel
from .websocket_api import async_register_websocket_commands


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Set up integration from YAML (not used)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Alexa Device Management from a config entry."""
    # Serve static frontend assets
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                f"/api/{DOMAIN}/static",
                hass.config.path("custom_components", DOMAIN, "www"),
                False,
            )
        ]
    )

    # Create and connect the device manager
    manager = AlexaDeviceManager(hass, entry.entry_id)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"manager": manager}

    await manager.async_connect()

    # Register WebSocket commands (idempotent, only registers once)
    async_register_websocket_commands(hass)

    # Register the sidebar panel
    await async_register_panel(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_data = hass.data[DOMAIN].pop(entry.entry_id, None)
    if entry_data and "manager" in entry_data:
        await entry_data["manager"].async_disconnect()
    return True
