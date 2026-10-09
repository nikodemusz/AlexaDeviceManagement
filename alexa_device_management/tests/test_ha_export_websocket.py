from __future__ import annotations

import asyncio
import json
import pathlib
import struct
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch

import aiohttp
from aiohttp._websocket.reader_py import WebSocketDataQueue, WebSocketReader

WEB_DIR = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB_DIR))

import ha_export


class InMemoryWebSocket:
    """Parse real WebSocket frames without opening a network connection."""

    def __init__(self, replies: dict[int, list[dict]], max_msg_size: int) -> None:
        protocol = Mock(_reading_paused=False)
        self.queue = WebSocketDataQueue(
            protocol, 2**16, loop=asyncio.get_running_loop()
        )
        self.reader = WebSocketReader(self.queue, max_msg_size, compress=False)
        self.replies = replies
        self.feed_json({"type": "auth_required"})

    def feed_json(self, message: dict) -> None:
        payload = json.dumps(message).encode("utf-8")
        if len(payload) < 126:
            header = bytes((0x81, len(payload)))
        elif len(payload) < 2**16:
            header = b"\x81\x7e" + struct.pack("!H", len(payload))
        else:
            header = b"\x81\x7f" + struct.pack("!Q", len(payload))
        self.reader.feed_data(header + payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def send_json(self, message: dict) -> None:
        if message.get("type") == "auth":
            self.feed_json({"type": "auth_ok"})
        else:
            self.feed_json({
                "id": message["id"],
                "type": "result",
                "success": True,
                "result": self.replies[message["id"]],
            })

    async def receive_json(self) -> dict:
        message = await self.queue.read()
        return json.loads(message.data)


class HomeAssistantWebSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_inventory_reply_above_four_mib_loads_with_other_registries(self):
        # Match the 4,284,956-byte entity-registry reply reported in production.
        entities = [{"entity_id": "light.example", "padding": ""}]
        envelope = {"id": 1, "type": "result", "success": True, "result": entities}
        entities[0]["padding"] = "x" * (4_284_956 - len(json.dumps(envelope)))
        self.assertEqual(len(json.dumps(envelope).encode("utf-8")), 4_284_956)
        areas = [{"area_id": "living", "name": "Wohnzimmer"}]
        session = MagicMock()
        session.__aenter__.return_value = session
        session.ws_connect.side_effect = lambda url, **options: InMemoryWebSocket(
            {1: entities, 2: areas}, options.get("max_msg_size", 4 * 1024 * 1024)
        )

        with patch.object(ha_export, "SUPERVISOR_TOKEN", "test-token"), patch.object(
            ha_export.aiohttp, "ClientSession", return_value=session
        ):
            result = await ha_export._ws_commands([
                ("entities", {"type": "config/entity_registry/list"}),
                ("areas", {"type": "config/area_registry/list"}),
            ])

        self.assertEqual(result, {"entities": entities, "areas": areas})

    async def test_default_four_mib_limit_reproduces_message_too_big(self):
        ws = InMemoryWebSocket({}, 4 * 1024 * 1024)
        await ws.receive_json()
        ws.feed_json({"padding": "x" * 4_284_956})
        with self.assertRaises(aiohttp.WebSocketError) as error:
            await ws.receive_json()
        self.assertEqual(error.exception.code, aiohttp.WSCloseCode.MESSAGE_TOO_BIG)

    async def test_inventory_receive_limit_remains_bounded(self):
        session = MagicMock()
        session.__aenter__.return_value = session
        session.ws_connect.side_effect = lambda url, **options: InMemoryWebSocket(
            {1: [{"padding": "x" * (17 * 1024 * 1024)}]},
            options.get("max_msg_size", 4 * 1024 * 1024),
        )

        with patch.object(ha_export, "SUPERVISOR_TOKEN", "test-token"), patch.object(
            ha_export.aiohttp, "ClientSession", return_value=session
        ), self.assertRaises(aiohttp.WebSocketError) as error:
            await ha_export._ws_commands([
                ("entities", {"type": "config/entity_registry/list"}),
            ])

        self.assertEqual(error.exception.code, aiohttp.WSCloseCode.MESSAGE_TOO_BIG)


if __name__ == "__main__":
    unittest.main()
