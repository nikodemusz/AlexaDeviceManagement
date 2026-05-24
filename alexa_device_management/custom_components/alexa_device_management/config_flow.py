"""Config flow for Alexa Device Management."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, TITLE


class AlexaDeviceManagementConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Alexa Device Management."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step – collect Amazon credentials."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            return self.async_create_entry(title=TITLE, data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required("amazon_region", default="eu"): vol.In(
                    {"eu": "Europe", "na": "North America", "fe": "Far East"}
                ),
                vol.Required("client_id"): str,
                vol.Required("client_secret"): str,
                vol.Required("refresh_token"): str,
            }
        )

        return self.async_show_form(step_id="user", data_schema=data_schema)
