import asyncio
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from aiohttp import web


WEB = Path(__file__).parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB))

import server_clean


def test_unhandled_request_logs_route_context_and_redacts_credentials():
    request = SimpleNamespace(method="GET", path="/api/device-overview", remote="172.30.32.1")

    async def handler(_request):
        raise RuntimeError(os.environ["TEST_ERROR_DETAIL"])

    with patch.dict(os.environ, {"TEST_ERROR_DETAIL": "Authorization: Bearer do-not-log https://example.test/path?token=do-not-log"}), \
            patch.object(server_clean._LOGGER, "error") as log_error:
        with pytest.raises(RuntimeError):
            asyncio.run(server_clean.request_error_logging_middleware(request, handler))

    message = log_error.call_args.args[0] % log_error.call_args.args[1:]
    assert "GET /api/device-overview from 172.30.32.1" in message
    assert "RuntimeError" in message
    assert "do-not-log" not in " ".join(str(value) for value in log_error.call_args.args)
    assert "test_request_error_logging.py" in " ".join(str(value) for value in log_error.call_args.args)


def test_expected_http_errors_are_not_logged_as_unhandled():
    request = SimpleNamespace(method="GET", path="/missing", remote="172.30.32.1")

    async def handler(_request):
        raise web.HTTPNotFound()

    with patch.object(server_clean._LOGGER, "error") as log_error:
        with pytest.raises(web.HTTPNotFound):
            asyncio.run(server_clean.request_error_logging_middleware(request, handler))

    log_error.assert_not_called()
