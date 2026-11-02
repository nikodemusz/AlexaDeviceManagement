"""Exercise concurrent gateway requests against a real local HA HTTP stub."""
import asyncio
import json
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

WEB = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB))
import native_skill_gateway as gateway


class GatewayBurstTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config_path = pathlib.Path(self.temp.name) / "native.yaml"
        self.config = {"schema_version": 6, "enabled": True, "locale": "de-DE", "devices": {
            "lamp": {"name": "Lamp", "capabilities": [
                {"interface": "Alexa.PowerController", "entity_id": "light.test"}]}}}
        self.write_config(self.config)
        self.active = self.maximum = 0
        self.tokens = []
        self.connections = set()
        self.cookies = []

        async def ha(request):
            token = request.headers.get("Authorization")
            self.tokens.append(token)
            self.connections.add(request.transport)
            self.cookies.append(dict(request.cookies))
            if token == "Bearer expired":
                raise web.HTTPUnauthorized()
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            try:
                await asyncio.sleep(0.002)
                value = {"entity_id": "light.test", "state": "on"} if "/states/" in request.path else {"message": "API running"}
                response = web.json_response(value)
                response.set_cookie("ha-user", token)
                return response
            finally:
                self.active -= 1

        ha_app = web.Application()
        ha_app.router.add_route("*", "/{path:.*}", ha)
        self.ha_server = TestServer(ha_app)
        await self.ha_server.start_server()
        self.patches = [
            patch.object(gateway.NativeSkillConfigStore, "DEFAULT_PATH", self.config_path),
            patch.object(gateway, "secret", return_value="machine-secret-" * 4),
            patch.object(gateway, "HA_USER_URL", str(self.ha_server.make_url("/api"))),
        ]
        for item in self.patches:
            item.start()
        self.app = gateway.create_app()
        self.client = TestClient(TestServer(self.app), headers={"Authorization": "Bearer " + "machine-secret-" * 4})
        await self.client.start_server()

    def write_config(self, value):
        temporary = self.config_path.with_suffix(".new")
        temporary.write_text(json.dumps(value), encoding="utf-8")
        temporary.replace(self.config_path)

    async def asyncTearDown(self):
        resources = self.app[gateway.RESOURCES]
        session = resources.session
        await self.client.close()
        if session is not None:
            self.assertTrue(session.closed)
        await self.ha_server.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    async def test_94_simultaneous_status_flows_share_config_and_connection_pool(self):
        # Exercise production scheduling, without unittest's per-task debug
        # stack tracing dominating the short HTTP timeout during a large burst.
        loop = asyncio.get_running_loop()
        debug = loop.get_debug()
        loop.set_debug(False)
        self.addCleanup(loop.set_debug, debug)
        original_load = gateway.NativeSkillConfigStore.load
        loads = []

        def load(store):
            loads.append(threading.get_ident())
            return original_load(store)

        async def flow(index):
            token = "alice" if index % 2 else "bob"
            for path, data in [("/v1/authorize", {"token": token}),
                               ("/v1/state", {"token": token, "endpoint_id": "lamp"})]:
                async with self.client.post(path, json=data) as response:
                    self.assertEqual(response.status, 200, await response.text())
            async with self.client.get("/v1/config") as response:
                self.assertEqual(response.status, 200)
                self.assertEqual((await response.json())["devices"]["lamp"]["name"], "Lamp")

        with patch.object(gateway.NativeSkillConfigStore, "load", new=load):
            await asyncio.wait_for(asyncio.gather(*(flow(i) for i in range(94))), timeout=15)
        self.assertEqual(len(loads), 1)
        self.assertNotEqual(loads[0], threading.get_ident())
        self.assertGreater(self.maximum, 1)
        self.assertLessEqual(self.maximum, 32)
        self.assertLessEqual(len(self.connections), 32)
        self.assertEqual(self.tokens.count("Bearer alice"), 94)
        self.assertEqual(self.tokens.count("Bearer bob"), 94)
        self.assertTrue(all(not cookies for cookies in self.cookies))

    async def test_config_updates_disable_invalid_and_missing_files_are_not_stale(self):
        self.assertEqual((await self.client.get("/v1/config")).status, 200)
        self.config["enabled"] = False
        self.write_config(self.config)
        response = await self.client.get("/v1/config")
        self.assertEqual((await response.json())["devices"], {})
        self.assertEqual((await self.client.post("/v1/state", json={"endpoint_id": "lamp", "token": "alice"})).status, 503)
        self.config_path.write_text("invalid: [", encoding="utf-8")
        self.assertEqual((await self.client.get("/v1/config")).status, 503)
        self.config_path.unlink()
        response = await self.client.get("/v1/config")
        self.assertFalse((await response.json())["enabled"])
        self.config["enabled"] = True
        self.write_config(self.config)
        self.assertTrue((await (await self.client.get("/v1/config")).json())["enabled"])

    async def test_reused_session_does_not_cache_user_authorization(self):
        for token, status in [("alice", 200), ("expired", 401), ("bob", 200), ("expired", 401)]:
            response = await self.client.post("/v1/authorize", json={"token": token})
            self.assertEqual(response.status, status)
        self.assertEqual(self.tokens, ["Bearer alice", "Bearer expired", "Bearer bob", "Bearer expired"])

    async def test_bad_machine_token_never_reaches_ha(self):
        response = await self.client.post("/v1/authorize", json={"token": "alice"}, headers={"Authorization": "Bearer wrong"})
        self.assertEqual(response.status, 401)
        self.assertEqual(self.tokens, [])

    async def test_slow_config_read_does_not_block_authorization(self):
        entered = threading.Event()
        release = threading.Event()
        original_load = gateway.NativeSkillConfigStore.load

        def load(store):
            entered.set()
            if not release.wait(5):
                raise AssertionError("event loop could not serve authorization")
            return original_load(store)

        with patch.object(gateway.NativeSkillConfigStore, "load", new=load):
            pending = asyncio.create_task(self.client.get("/v1/config"))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                response = await asyncio.wait_for(self.client.post("/v1/authorize", json={"token": "alice"}), timeout=2)
                self.assertEqual(response.status, 200)
            finally:
                release.set()
                self.assertEqual((await pending).status, 200)

    async def test_network_errors_become_gateway_errors_without_exception_details(self):
        for failure, status in [(TimeoutError("secret-detail"), 504), (gateway.aiohttp.ClientConnectionError("secret-detail"), 502)]:
            with patch.object(gateway, "linked_token_request", side_effect=failure):
                response = await self.client.post("/v1/authorize", json={"token": "alice"})
                self.assertEqual(response.status, status)
                self.assertNotIn("secret-detail", await response.text())


if __name__ == "__main__":
    unittest.main()
