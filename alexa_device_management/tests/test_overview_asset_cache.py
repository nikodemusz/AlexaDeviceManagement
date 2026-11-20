"""A new editor must never keep using a previous release's asset URLs."""
import pathlib
import sys
import unittest
from unittest.mock import Mock, patch

WEB = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB))
import device_overview


class OverviewAssetCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_asset_urls_follow_content_changes_and_html_is_not_cached(self):
        request = Mock(headers={"X-Ingress-Path": "/api/hassio_ingress/example"})
        before = await device_overview.page(request)
        self.assertEqual(before.headers["Cache-Control"], "no-store")
        self.assertNotIn("{{OVERVIEW_ASSET_VERSION}}", before.text)
        self.assertIn('/api/hassio_ingress/example/static/device_overview.js?v=', before.text)
        self.assertEqual(before.text, (await device_overview.page(request)).text)
        original = pathlib.Path.read_bytes
        def changed(path):
            content = original(path)
            return content + b"/* updated */" if path.name == "device_overview.js" else content
        with patch.object(pathlib.Path, "read_bytes", changed):
            after = await device_overview.page(request)
        self.assertNotEqual(before.text, after.text)

