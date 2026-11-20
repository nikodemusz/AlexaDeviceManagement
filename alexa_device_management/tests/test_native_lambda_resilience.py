import copy
import io
import json
import unittest
import urllib.error
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "native_skill/lambda_function.py"
spec = importlib.util.spec_from_file_location("resilience_lambda", MODULE_PATH)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class LambdaTests(unittest.TestCase):
    def setUp(self):
        self.event = {"directive": {
            "header": {"namespace": "Alexa.BrightnessController", "name": "AdjustBrightness",
                       "messageId": "test", "correlationToken": "correlation"},
            "endpoint": {"endpointId": "native:lamp", "scope": {"token": "secret-user-token"}},
            "payload": {"brightnessDelta": 10}}}
        self.config = {"devices": {"lamp": {"name": "Lamp", "capabilities": [
            {"interface": "Alexa.BrightnessController", "entity_id": "light.test", "read_only": False}]}}}
        self.states = {"states": {"light.test": {"state": "on", "attributes": {"brightness": 128}}}}
        self.calls = []

    def gateway(self, path, method="GET", payload=None):
        self.calls.append((path, method, copy.deepcopy(payload)))
        return {"/v1/authorize": {}, "/v1/config": self.config,
                "/v1/state": self.states, "/v1/control": {},
                "/v1/legacy": {"event": {"header": {"name": "AcceptGrant.Response"}, "payload": {}}}}[path]

    def invoke(self):
        with patch.object(app, "gateway", side_effect=self.gateway), redirect_stdout(io.StringIO()):
            return app.lambda_handler(self.event, None)

    def test_relative_brightness_uses_existing_gateway_action(self):
        result = self.invoke()
        control = next(p for path, _, p in self.calls if path == "/v1/control")
        self.assertEqual((control["action"], control["value"]), ("SetBrightness", 60))
        self.assertEqual(result["event"]["header"]["name"], "Response")
        self.assertEqual(result["event"]["header"]["correlationToken"], "correlation")
        self.assertEqual(self.calls[0][0], "/v1/authorize")

    def test_relative_brightness_clamps_limits(self):
        for delta, expected in [(100, 100), (-100, 0)]:
            with self.subTest(delta=delta):
                self.calls.clear()
                self.event["directive"]["payload"]["brightnessDelta"] = delta
                self.invoke()
                self.assertEqual(next(p["value"] for path, _, p in self.calls if path == "/v1/control"), expected)

    def test_invalid_brightness_deltas_do_not_control_devices(self):
        for delta in [None, True, "10", float("nan"), float("inf"), 101, -101]:
            with self.subTest(delta=delta):
                self.calls.clear()
                self.event["directive"]["payload"]["brightnessDelta"] = delta
                self.assertEqual(self.invoke()["event"]["payload"]["type"], "INVALID_VALUE")
                self.assertFalse(any(path == "/v1/control" for path, _, _ in self.calls))

    def test_unavailable_brightness_does_not_control_device(self):
        self.states["states"]["light.test"]["state"] = "unavailable"
        self.assertEqual(self.invoke()["event"]["payload"]["type"], "ENDPOINT_UNREACHABLE")
        self.assertFalse(any(path == "/v1/control" for path, _, _ in self.calls))

    def test_set_brightness_is_unchanged(self):
        self.event["directive"]["header"]["name"] = "SetBrightness"
        self.event["directive"]["payload"] = {"brightness": 25}
        self.assertEqual(self.invoke()["event"]["header"]["name"], "Response")
        self.assertEqual([p["value"] for path, _, p in self.calls if path == "/v1/control"], [25])
        self.assertEqual(sum(path == "/v1/state" for path, _, _ in self.calls), 1)

    def test_report_state(self):
        self.event["directive"]["header"].update(namespace="Alexa", name="ReportState")
        self.assertEqual(self.invoke()["event"]["header"]["name"], "StateReport")

    def test_discovery(self):
        self.event["directive"]["header"].update(namespace="Alexa.Discovery", name="Discover")
        result = self.invoke()
        self.assertEqual(result["event"]["payload"]["endpoints"][0]["endpointId"], "native:lamp")

    def test_accept_grant(self):
        self.event["directive"]["header"].update(namespace="Alexa.Authorization", name="AcceptGrant")
        self.event["directive"].pop("endpoint")
        self.event["directive"]["payload"] = {"grantee": {"token": "secret-user-token"}}
        self.assertEqual(self.invoke()["event"]["header"]["name"], "AcceptGrant.Response")
        self.assertEqual(self.calls[-1][0], "/v1/legacy")

    def test_network_failures_return_bridge_unreachable(self):
        failures = [TimeoutError("secret-error-body"), ConnectionResetError(), urllib.error.URLError("secret-error-body")]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), patch.object(app, "gateway", side_effect=failure):
                log = io.StringIO()
                with redirect_stdout(log):
                    result = app.lambda_handler(self.event, None)
                self.assertEqual(result["event"]["payload"]["type"], "BRIDGE_UNREACHABLE")
                self.assertNotIn("secret", log.getvalue())
                self.assertIsNone(app.REQUEST_DEADLINE.get())

    def test_http_error_mapping(self):
        for code, expected in [(401, "INVALID_AUTHORIZATION_CREDENTIAL"), (502, "BRIDGE_UNREACHABLE"),
                               (503, "BRIDGE_UNREACHABLE"), (504, "BRIDGE_UNREACHABLE")]:
            with self.subTest(code=code), patch.object(app, "gateway", side_effect=urllib.error.HTTPError("https://example.test", code, "secret", {}, None)), redirect_stdout(io.StringIO()):
                self.assertEqual(app.lambda_handler(self.event, None)["event"]["payload"]["type"], expected)

    def test_deadline_shrinks_between_requests(self):
        token = app.REQUEST_DEADLINE.set(107)
        try:
            with patch.object(app.time, "monotonic", side_effect=[100, 105, 107]):
                self.assertEqual(app.request_timeout(), 3)
                self.assertEqual(app.request_timeout(), 1.75)
                with self.assertRaises(TimeoutError):
                    app.request_timeout()
        finally:
            app.REQUEST_DEADLINE.reset(token)

    def test_lambda_remaining_time_caps_deadline(self):
        context = Mock()
        context.get_remaining_time_in_millis.return_value = 2000
        def check(event, ctx):
            self.assertEqual(app.REQUEST_DEADLINE.get(), 101.5)
            return {"event": {"header": {"name": "Response"}, "payload": {}}}
        with patch.object(app.time, "monotonic", return_value=100), patch.object(app, "handle_directive", side_effect=check), redirect_stdout(io.StringIO()):
            app.lambda_handler(self.event, context)
        self.assertIsNone(app.REQUEST_DEADLINE.get())

    def test_http_client_receives_budget_timeout(self):
        token = app.REQUEST_DEADLINE.set(107)
        try:
            with patch.object(app.time, "monotonic", return_value=105), patch.object(app.urllib.request, "urlopen") as client:
                client.return_value.__enter__.return_value = io.StringIO('{"ok": true}')
                self.assertEqual(app.request_json("https://example.test"), {"ok": True})
                self.assertEqual(client.call_args.kwargs["timeout"], 1.75)
        finally:
            app.REQUEST_DEADLINE.reset(token)

    def test_read_only_binding_is_preserved(self):
        self.config["devices"]["lamp"]["capabilities"][0]["read_only"] = True
        self.assertEqual(self.invoke()["event"]["payload"]["type"], "INVALID_DIRECTIVE")
        self.assertFalse(any(path == "/v1/control" for path, _, _ in self.calls))

    def test_missing_user_token_still_denied(self):
        self.event["directive"]["endpoint"].pop("scope")
        self.assertEqual(self.invoke()["event"]["payload"]["type"], "INVALID_AUTHORIZATION_CREDENTIAL")
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
