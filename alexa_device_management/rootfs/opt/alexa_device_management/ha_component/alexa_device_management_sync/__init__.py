"""Home Assistant service for official Alexa endpoint lifecycle reports."""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol

from homeassistant.components.alexa.auth import Auth
from homeassistant.components.alexa.config import AbstractConfig
from homeassistant.components.alexa.state_report import (
    async_send_add_or_update_message,
    async_send_delete_message,
)
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

DOMAIN = "alexa_device_management_sync"
SERVICE_SYNC = "sync"
CONF_ENDPOINT = "endpoint"
CONF_LOCALE = "locale"
ATTR_ADD_OR_UPDATE = "add_or_update"
ATTR_DELETE = "delete"
ATTR_ENTITY_CONFIG = "entity_config"
VALID_ENDPOINTS = {
    "https://api.amazonalexa.com/v3/events",
    "https://api.eu.amazonalexa.com/v3/events",
    "https://api.fe.amazonalexa.com/v3/events",
}

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_ENDPOINT): vol.In(VALID_ENDPOINTS),
                vol.Required(CONF_CLIENT_ID): cv.string,
                vol.Required(CONF_CLIENT_SECRET): cv.string,
                vol.Optional(CONF_LOCALE, default="de-DE"): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ADD_OR_UPDATE, default=[]): vol.All(
            cv.ensure_list, [cv.entity_id]
        ),
        vol.Optional(ATTR_DELETE, default=[]): vol.All(
            cv.ensure_list, [cv.entity_id]
        ),
        vol.Optional(ATTR_ENTITY_CONFIG, default={}): dict,
    }
)


class EventGatewayConfig(AbstractConfig):
    """Minimal Alexa config backed by Home Assistant's existing Alexa auth store."""

    def __init__(self, hass: HomeAssistant, raw: dict[str, Any]) -> None:
        super().__init__(hass)
        self._endpoint = raw[CONF_ENDPOINT]
        self._locale = raw[CONF_LOCALE]
        self._auth = Auth(hass, raw[CONF_CLIENT_ID], raw[CONF_CLIENT_SECRET])
        self._entity_config: dict[str, Any] = {}

    @property
    def supports_auth(self) -> bool:
        return True

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def locale(self) -> str:
        return self._locale

    @property
    def entity_config(self) -> dict[str, Any]:
        return self._entity_config

    def set_entity_config(self, value: dict[str, Any]) -> None:
        self._entity_config = value

    @callback
    def user_identifier(self) -> str:
        return ""

    @callback
    def async_invalidate_access_token(self) -> None:
        self._auth.async_invalidate_access_token()

    async def async_get_access_token(self) -> str | None:
        return await self._auth.async_get_access_token()

    async def async_accept_grant(self, code: str) -> str | None:
        return await self._auth.async_do_auth(code)


async def _response_details(response: Any) -> dict[str, Any]:
    text = await response.text()
    result = {
        "status": response.status,
        "accepted": response.status == 202,
        "body": text[:2000],
    }
    response.release()
    return result


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register a response-capable service used by the add-on after deployment."""
    gateway = EventGatewayConfig(hass, config[DOMAIN])
    await gateway.async_initialize()
    lock = asyncio.Lock()

    async def handle_sync(call: ServiceCall) -> ServiceResponse:
        async with lock:
            add_or_update = list(dict.fromkeys(call.data[ATTR_ADD_OR_UPDATE]))
            delete = list(dict.fromkeys(call.data[ATTR_DELETE]))
            gateway.set_entity_config(dict(call.data[ATTR_ENTITY_CONFIG]))

            try:
                token = await gateway.async_get_access_token()
                if not token:
                    return {
                        "ok": False,
                        "error": (
                            "Kein Alexa Event Gateway-Token vorhanden. In der Alexa Developer Console "
                            "Send Alexa Events aktivieren und den Skill anschließend neu verknüpfen."
                        ),
                    }

                result: dict[str, Any] = {
                    "ok": True,
                    "add_or_update_count": len(add_or_update),
                    "delete_count": len(delete),
                }
                if add_or_update:
                    response = await async_send_add_or_update_message(
                        hass, gateway, add_or_update
                    )
                    result["add_or_update"] = await _response_details(response)
                    result["ok"] = result["ok"] and result["add_or_update"]["accepted"]

                if delete:
                    response = await async_send_delete_message(hass, gateway, delete)
                    result["delete"] = await _response_details(response)
                    result["ok"] = result["ok"] and result["delete"]["accepted"]

                if not result["ok"]:
                    result["error"] = "Alexa Event Gateway hat mindestens einen Report nicht mit HTTP 202 akzeptiert."
                return result
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC,
        handle_sync,
        schema=SERVICE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    return True
