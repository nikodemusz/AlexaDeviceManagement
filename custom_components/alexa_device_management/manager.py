"""Placeholder manager for Alexa device operations."""

from __future__ import annotations


class AlexaDeviceManager:
    """Handles Alexa device interactions."""

    async def async_list_devices(self) -> list[dict]:
        """Return a placeholder list of devices."""
        return []

    async def async_delete_device(self, _device_id: str) -> bool:
        """Delete a device by id (placeholder)."""
        return False
