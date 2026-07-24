from __future__ import annotations

import asyncio
import inspect
import pathlib
import sys
import unittest
from unittest.mock import Mock

import aiohttp

WEB_DIR = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB_DIR))

import oh_style_login


def _request(ingress: str = "/ingress") -> Mock:
    r = Mock()
    r.headers = {"X-Ingress-Path": ingress}
    return r


class RewriteHtmlTests(unittest.TestCase):
    def test_absolute_https_url_rewritten(self) -> None:
        result = oh_style_login.rewrite_html(
            _request(),
            '<a href="https://www.amazon.com/ap/signin?x=1">Login</a>',
        )
        self.assertIn("/alexa-auth/proxy/www.amazon.com/ap/signin?x=1", result)
        self.assertNotIn("https://www.amazon.com/ap/signin", result)

    def test_absolute_http_url_rewritten(self) -> None:
        result = oh_style_login.rewrite_html(
            _request(),
            '<img src="http://m.media-amazon.com/image.png">',
        )
        self.assertIn("/ingress/alexa-auth/proxy/m.media-amazon.com/image.png", result)
        self.assertNotIn("http://m.media-amazon.com", result)

    def test_protocol_relative_url_rewritten(self) -> None:
        result = oh_style_login.rewrite_html(
            _request(),
            '<form action="//www.amazon.com/ap/signin">',
        )
        self.assertIn("/alexa-auth/proxy/www.amazon.com/ap/signin", result)
        self.assertNotIn('action="//www.amazon.com', result)

    def test_relative_path_rewritten(self) -> None:
        result = oh_style_login.rewrite_html(
            _request(),
            '<link href="/static/css/main.css">',
        )
        self.assertIn("/ingress/alexa-auth/proxy/www.amazon.com/static/css/main.css", result)

    def test_no_double_rewrite(self) -> None:
        result = oh_style_login.rewrite_html(
            _request(),
            '<img src="http://m.media-amazon.com/image.png">',
        )
        self.assertEqual(result.count("/alexa-auth/proxy/"), 1)


class LoginUrlTests(unittest.TestCase):
    def test_login_url_always_targets_amazon_com(self) -> None:
        state = {"deviceId": "abc123"}
        url = oh_style_login.build_openhab_login_url(state)
        self.assertTrue(url.startswith("https://www.amazon.com/ap/signin?"))
        self.assertIn("openid.assoc_handle=amzn_dp_project_dee_ios&", url)
        self.assertIn("pageId=amzn_dp_project_dee_ios&", url)


class AddExchangeCookieTests(unittest.TestCase):
    def test_uses_map_key_domain_not_per_cookie_domain_field(self) -> None:
        async def run() -> str:
            session = Mock()
            session.cookie_jar = aiohttp.CookieJar(unsafe=True)
            oh_style_login.add_exchange_cookie(
                session,
                ".amazon.com",
                {"Name": "session-id", "Value": "abc123", "Domain": "some-other-host.example"},
            )
            cookies = session.cookie_jar.filter_cookies(oh_style_login.URL("https://alexa.amazon.com/"))
            return cookies["session-id"].value

        self.assertEqual(asyncio.run(run()), "abc123")


class TlsImpersonationTests(unittest.TestCase):
    def test_get_json_uses_curl_cffi_ios_impersonation(self) -> None:
        # The whole point of the TLS experiment: app-API GETs must go through
        # curl_cffi with an iOS Safari fingerprint, not aiohttp.
        self.assertEqual(oh_style_login.TLS_IMPERSONATE, "safari18_4_ios")
        import curl_cffi.requests  # noqa: F401  (dependency must be importable)
        src = inspect.getsource(oh_style_login.get_json)
        self.assertIn("CurlSession", src)
        self.assertIn("impersonate=TLS_IMPERSONATE", src)


if __name__ == "__main__":
    unittest.main()
