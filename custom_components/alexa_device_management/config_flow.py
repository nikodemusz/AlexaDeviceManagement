"""Config flow for Alexa Device Management."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, TITLE


class AlexaDeviceManagementConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Alexa Device Management."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            return self.async_create_entry(title=TITLE, data={})

        return self.async_show_form(step_id="user", data_schema={})
