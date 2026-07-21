from __future__ import annotations

import pathlib
import sys
import unittest
from unittest.mock import Mock

WEB_DIR = pathlib.Path(__file__).resolve().parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB_DIR))

import alexa_login_rewrite_fix


class AlexaLoginRewriteFixTests(unittest.TestCase):
    def test_absolute_url_is_rewritten_without_group_error(self) -> None:
        request = Mock()
        request.headers = {
            "X-Ingress-Path": "/api/hassio_ingress/test",
            "X-Forwarded-Host": "homeassistant.local",
            "X-Forwarded-Proto": "https",
        }

        result = alexa_login_rewrite_fix.rewrite_html(
            request,
            '<a href="https://www.amazon.com/ap/signin?x=1">Login</a>',
        )

        self.assertIn(
            "/api/hassio_ingress/test/auth/alexa-app/proxy/www.amazon.com/ap/signin?x=1",
            result,
        )
        self.assertNotIn('href="https://www.amazon.com/ap/signin', result)

    def test_http_scheme_is_preserved_for_proxy_parsing(self) -> None:
        request = Mock()
        request.headers = {"X-Ingress-Path": "/ingress"}

        result = alexa_login_rewrite_fix.rewrite_html(
            request,
            '<img src="http://m.media-amazon.com/image.png">',
        )

        self.assertIn("/ingress/auth/alexa-app/proxy/m.media-amazon.com/image.png", result)


if __name__ == "__main__":
    unittest.main()
