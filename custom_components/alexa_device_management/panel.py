"""Panel registration for Alexa Device Management."""

from __future__ import annotations

from homeassistant.components import panel_custom

from .const import DOMAIN, PANEL_ICON, PANEL_NAME, PANEL_URL_PATH


async def async_register_panel(hass) -> None:
    """Register the custom panel."""
    panel_custom.async_register_panel(
        hass=hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_NAME,
        module_url=f"/api/{DOMAIN}/static/alexa-device-management.js",
        sidebar_title="Alexa Devices",
        sidebar_icon=PANEL_ICON,
        require_admin=True,
        config={},
    )
