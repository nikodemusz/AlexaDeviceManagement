"""Exercise the actual HA service handler using HA/auth/session test doubles."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

import voluptuous as vol

ROOT = Path(__file__).parents[1] / "rootfs/opt/alexa_device_management/ha_component/alexa_device_management_sync"


class FakeBase:
    def __init__(self, hass):
        pass
    async def async_initialize(self):
        pass


class FakeAuth:
    def __init__(self, *args):
        self.invalidated = False
    async def async_get_access_token(self):
        return "dummy-lwa-refreshed" if self.invalidated else "dummy-lwa"
    def async_invalidate_access_token(self):
        self.invalidated = True


def module(name, **attrs):
    value = types.ModuleType(name)
    value.__dict__.update(attrs)
    return value


def load_component():
    modules = {
        "homeassistant": module("homeassistant"),
        "homeassistant.components": module("homeassistant.components"),
        "homeassistant.components.alexa": module("homeassistant.components.alexa"),
        "homeassistant.components.alexa.auth": module("auth", Auth=FakeAuth),
        "homeassistant.components.alexa.config": module("config", AbstractConfig=FakeBase),
        "homeassistant.components.alexa.state_report": module("state_report", async_send_delete_message=AsyncMock()),
        "homeassistant.const": module("const", CONF_CLIENT_ID="client_id", CONF_CLIENT_SECRET="client_secret"),
        "homeassistant.core": module("core", HomeAssistant=object, ServiceCall=object, ServiceResponse=dict,
                                     SupportsResponse=types.SimpleNamespace(ONLY="only"), callback=lambda f:f),
        "homeassistant.helpers": module("helpers"),
        "homeassistant.helpers.config_validation": module("cv", string=vol.Coerce(str), entity_id=vol.Coerce(str),
                                                          ensure_list=lambda v: v if isinstance(v, list) else [v]),
        "homeassistant.helpers.typing": module("typing", ConfigType=dict),
        "homeassistant.helpers.aiohttp_client": module("client", async_get_clientsession=lambda hass: hass.session),
    }
    spec = importlib.util.spec_from_file_location("test_ha_native_sync", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    value = importlib.util.module_from_spec(spec)
    modules["test_ha_native_sync"] = value
    for name, item in modules.items():
        item.__name__ = name
        parent, _, child = name.rpartition(".")
        if parent in modules:
            setattr(modules[parent], child, item)
            modules[parent].__path__ = []
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(value)
    return value


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.component = load_component()
        self.hass = Mock()
        response = Mock(status=202)
        response.text = AsyncMock(return_value='{"private_marker":"must_not_be_returned"}')
        self.hass.session.post = AsyncMock(return_value=response)
        await self.component.async_setup(self.hass, {self.component.DOMAIN: {
            "endpoint": "https://api.eu.amazonalexa.com/v3/events", "locale": "de-DE",
            "client_id": "dummy-id", "client_secret": "dummy-secret"}})
        self.handler = self.hass.services.async_register.call_args.args[2]

    async def call(self, data):
        call = Mock()
        call.data = self.component.SERVICE_SCHEMA(data)
        return await self.handler(call)

    async def test_all_162_native_endpoints_are_sent_in_four_authenticated_reports(self):
        native = [{"endpointId": f"native:{i}", "capabilities": []} for i in range(162)]
        result = await self.call({"native_endpoints": native})
        self.assertTrue(result["ok"])
        self.assertEqual(result["add_or_update_count"], 162)
        self.assertEqual(self.hass.session.post.await_count, 4)
        all_ids = []
        for args in self.hass.session.post.call_args_list:
            self.assertEqual(args.kwargs["headers"]["Authorization"], "Bearer dummy-lwa")
            report = json.loads(args.kwargs["data"])
            self.assertEqual(report["event"]["header"]["name"], "AddOrUpdateReport")
            self.assertEqual(report["event"]["payload"]["scope"]["token"], "dummy-lwa")
            all_ids.extend(p["endpointId"] for p in report["event"]["payload"]["endpoints"])
        self.assertEqual(set(all_ids), {f"native:{i}" for i in range(162)})
        self.assertNotIn("must_not_be_returned", json.dumps(result))
        self.assertNotIn("dummy-lwa", json.dumps(result))

    async def test_legacy_additions_are_rejected_without_sending_anything(self):
        result = await self.call({"add_or_update": ["light.old"]})
        self.assertFalse(result["ok"])
        self.hass.session.post.assert_not_awaited()

    async def test_http_rejection_is_not_reported_as_success(self):
        self.hass.session.post.return_value.status = 401
        result = await self.call({"native_endpoints": [{"endpointId": "native:desk"}]})
        self.assertFalse(result["ok"])
        self.assertEqual(result["native_reports"][0]["status"], 401)

    async def test_invalid_cached_token_is_refreshed_once_without_relinking(self):
        rejected = Mock(status=401)
        rejected.text = AsyncMock(return_value="private-body")
        accepted = Mock(status=202)
        accepted.text = AsyncMock(return_value="")
        self.hass.session.post.side_effect = [rejected, accepted]
        result = await self.call({"native_endpoints": [{"endpointId": "native:desk"}]})
        self.assertTrue(result["ok"])
        args = self.hass.session.post.call_args_list[-1]
        self.assertEqual(args.kwargs["headers"]["Authorization"], "Bearer dummy-lwa-refreshed")
        self.assertEqual(json.loads(args.kwargs["data"])["event"]["payload"]["scope"]["token"], "dummy-lwa-refreshed")
        self.assertNotIn("private-body", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
