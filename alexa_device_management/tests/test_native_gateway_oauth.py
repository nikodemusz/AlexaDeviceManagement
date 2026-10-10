"""Regression tests: OAuth user requests bypass the Supervisor proxy."""
from __future__ import annotations

import asyncio
import importlib
import pathlib
import sys
import unittest
from unittest.mock import patch
from aiohttp import web

WEB = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB))
gateway = importlib.import_module("native_skill_gateway")


class FakeResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return {"message": "API running."}


class FakeSession:
    def __init__(self, headers, record):
        self.headers = headers
        self.record = record

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def request(self, method, url, **kwargs):
        self.record.append((method, url, self.headers.get("Authorization"), kwargs.get("json")))
        return FakeResponse()


class GatewayOAuthTests(unittest.TestCase):
    def test_expired_ha_user_token_is_not_masked_as_gateway_failure(self):
        for status in (401, 403):
            with self.subTest(status=status), patch.object(FakeResponse, "status", status), \
                 patch.object(gateway.aiohttp, "ClientSession",
                              side_effect=lambda **kwargs: FakeSession(kwargs["headers"], [])):
                with self.assertRaises(web.HTTPUnauthorized):
                    asyncio.run(gateway.ha_request("GET", "/states/light.example", token="expired-test-token"))

    def test_linked_authorize_uses_core_not_supervisor(self):
        calls = []
        with patch.object(gateway.aiohttp, "ClientSession",
                          side_effect=lambda **kwargs: FakeSession(kwargs["headers"], calls)):
            result = asyncio.run(gateway.linked_token_request("test-user-token", "/"))
        self.assertEqual(result, {"message": "API running."})
        self.assertEqual(calls[0][:3], ("GET", gateway.HA_USER_URL + "/", "Bearer test-user-token"))
        self.assertNotIn("supervisor/core/api", calls[0][1])

    def test_legacy_and_native_routes_use_core(self):
        calls = []
        with patch.object(gateway.aiohttp, "ClientSession",
                          side_effect=lambda **kwargs: FakeSession(kwargs["headers"], calls)):
            asyncio.run(gateway.linked_token_request("oauth", "/alexa/smart_home", {"directive": {}}))
            asyncio.run(gateway.ha_request("GET", "/states/sensor.example", token="oauth"))
        self.assertEqual(calls[0][0:3], ("POST", gateway.HA_USER_URL + "/alexa/smart_home", "Bearer oauth"))
        self.assertEqual(calls[1][0:3], ("GET", gateway.HA_USER_URL + "/states/sensor.example", "Bearer oauth"))


if __name__ == "__main__":
    unittest.main()
