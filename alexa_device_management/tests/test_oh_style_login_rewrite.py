from __future__ import annotations

import pathlib
import sys
import unittest
from unittest.mock import Mock

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


if __name__ == "__main__":
    unittest.main()
