"""Manager for Alexa device operations (analogous to zwave-js Server connection)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback

from .const import (
    DOMAIN,
    EVENT_CONNECTION_STATE_CHANGED,
    EVENT_DEVICES_UPDATED,
    STATE_CONNECTED,
    STATE_CONNECTING,
    STATE_DISCONNECTED,
)

_LOGGER = logging.getLogger(__name__)


class AlexaDeviceManager:
    """Manages the connection to Amazon Alexa and device state.

    Analogous to the Z-Wave JS server connection or Zigbee2MQTT MQTT bridge:
    - Maintains connection state
    - Caches device list
    - Provides commands to query/modify devices
    - Fires HA events on state changes
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.entry_id = entry_id
        self._state: str = STATE_DISCONNECTED
        self._devices: dict[str, dict[str, Any]] = {}
        self._subscribers: list[callback] = []

    @property
    def state(self) -> str:
        """Return current connection state."""
        return self._state

    @property
    def devices(self) -> dict[str, dict[str, Any]]:
        """Return cached device dict keyed by device id."""
        return self._devices

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def async_connect(self) -> None:
        """Connect to Alexa API.

        TODO: Implement actual OAuth/token authentication to Amazon Alexa API.
        For now this simulates a successful connection with demo devices.
        """
        self._set_state(STATE_CONNECTING)
        _LOGGER.info("Connecting to Amazon Alexa API...")

        # TODO: Replace with real Alexa Smart Home / Alexa App API call
        # This would use OAuth2 tokens obtained during config flow
        self._devices = self._get_demo_devices()
        self._set_state(STATE_CONNECTED)

        self.hass.bus.async_fire(
            EVENT_DEVICES_UPDATED,
            {"entry_id": self.entry_id},
        )
        _LOGGER.info("Connected to Alexa – %d devices loaded", len(self._devices))

    async def async_disconnect(self) -> None:
        """Disconnect from Alexa API."""
        self._devices = {}
        self._set_state(STATE_DISCONNECTED)
        _LOGGER.info("Disconnected from Alexa API")

    # ------------------------------------------------------------------
    # Device commands (analogous to zwave-js node commands)
    # ------------------------------------------------------------------

    async def async_list_devices(self) -> list[dict[str, Any]]:
        """Return list of all known Alexa devices."""
        return list(self._devices.values())

    async def async_get_device(self, device_id: str) -> dict[str, Any] | None:
        """Return a single device by id."""
        return self._devices.get(device_id)

    async def async_delete_device(self, device_id: str) -> bool:
        """Remove a device.

        TODO: Call Alexa API to deregister the device.
        """
        if device_id not in self._devices:
            return False
        del self._devices[device_id]
        self.hass.bus.async_fire(
            EVENT_DEVICES_UPDATED,
            {"entry_id": self.entry_id},
        )
        return True

    async def async_rename_device(self, device_id: str, new_name: str) -> bool:
        """Rename a device.

        TODO: Call Alexa API to update device name.
        """
        if device_id not in self._devices:
            return False
        self._devices[device_id]["name"] = new_name
        self.hass.bus.async_fire(
            EVENT_DEVICES_UPDATED,
            {"entry_id": self.entry_id},
        )
        return True

    async def async_refresh_devices(self) -> list[dict[str, Any]]:
        """Re-fetch device list from Alexa API.

        TODO: Replace with real API call.
        """
        self._devices = self._get_demo_devices()
        self.hass.bus.async_fire(
            EVENT_DEVICES_UPDATED,
            {"entry_id": self.entry_id},
        )
        return list(self._devices.values())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_state(self, new_state: str) -> None:
        """Update connection state and fire event."""
        old_state = self._state
        self._state = new_state
        if old_state != new_state:
            self.hass.bus.async_fire(
                EVENT_CONNECTION_STATE_CHANGED,
                {
                    "entry_id": self.entry_id,
                    "old_state": old_state,
                    "new_state": new_state,
                },
            )

    @staticmethod
    def _get_demo_devices() -> dict[str, dict[str, Any]]:
        """Return demo devices for development.

        TODO: Remove once real Alexa API is integrated.
        """
        return {
            "echo-dot-living": {
                "id": "echo-dot-living",
                "name": "Echo Dot Wohnzimmer",
                "type": "ECHO_DOT",
                "family": "ECHO",
                "online": True,
                "serial": "G0911W079412345X",
                "firmware": "711473420",
                "capabilities": ["AUDIO_PLAYER", "MICROPHONE", "SPEAKER"],
                "room": "Wohnzimmer",
            },
            "echo-show-kitchen": {
                "id": "echo-show-kitchen",
                "name": "Echo Show Küche",
                "type": "ECHO_SHOW_5",
                "family": "ECHO",
                "online": True,
                "serial": "G0712K039487621Y",
                "firmware": "711473420",
                "capabilities": [
                    "AUDIO_PLAYER",
                    "MICROPHONE",
                    "SPEAKER",
                    "DISPLAY",
                    "CAMERA",
                ],
                "room": "Küche",
            },
            "smart-plug-office": {
                "id": "smart-plug-office",
                "name": "Smart Plug Büro",
                "type": "SMART_PLUG",
                "family": "SMART_HOME",
                "online": False,
                "serial": "SP-0048271635",
                "firmware": "1.2.3",
                "capabilities": ["POWER_SWITCH"],
                "room": "Büro",
            },
            "fire-tv-bedroom": {
                "id": "fire-tv-bedroom",
                "name": "Fire TV Schlafzimmer",
                "type": "FIRE_TV_STICK_4K",
                "family": "FIRE_TV",
                "online": True,
                "serial": "FT4K-90125634",
                "firmware": "PS7633/2108",
                "capabilities": ["AUDIO_PLAYER", "VIDEO_PLAYER", "MICROPHONE"],
                "room": "Schlafzimmer",
            },
            "echo-studio-music": {
                "id": "echo-studio-music",
                "name": "Echo Studio Musikzimmer",
                "type": "ECHO_STUDIO",
                "family": "ECHO",
                "online": True,
                "serial": "ES-77341289",
                "firmware": "711473420",
                "capabilities": ["AUDIO_PLAYER", "MICROPHONE", "SPEAKER", "DOLBY_ATMOS"],
                "room": "Musikzimmer",
            },
        }
