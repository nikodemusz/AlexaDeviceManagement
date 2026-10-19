"""Regression tests: native-only Lambda with preserved account linking."""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest
import urllib.error
from unittest.mock import patch

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "native_skill/lambda_function.py"
spec = importlib.util.spec_from_file_location("native_lambda", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def event(namespace="Alexa.Discovery", name="Discover", endpoint=None):
    d = {"header": {"namespace": namespace, "name": name, "messageId": "test-1"},
         "payload": {"scope": {"type": "BearerToken", "token": "test-oauth"}}}
    if endpoint:
        d["endpoint"] = {"endpointId": endpoint}
    return {"directive": d}


def legacy_discovery():
    return {"event": {"header": {"namespace": "Alexa.Discovery", "name": "Discover.Response",
                                 "payloadVersion": "3", "messageId": "old-1"},
                      "payload": {"endpoints": [{"endpointId": "legacy-light", "friendlyName": "Alte Lampe"}]}}}


class CombinedSkillTests(unittest.TestCase):
    def test_accept_grant_authenticates_grantee_token_and_forwards_original_directive(self):
        request = event("Alexa.Authorization", "AcceptGrant")
        request["directive"]["payload"] = {
            "grant": {"type": "OAuth2.AuthorizationCode", "code": "dummy-grant"},
            "grantee": {"type": "BearerToken", "token": "dummy-ha-user"}}
        result = {"event": {"header": {"namespace": "Alexa.Authorization", "name": "AcceptGrant.Response"},
                            "payload": {}}}
        calls = []
        def gw(path, method="GET", payload=None):
            calls.append((path, payload))
            self.assertEqual(payload["token"], "dummy-ha-user")
            if path == "/v1/authorize":
                return {"authorized": True}
            self.assertEqual(path, "/v1/legacy")
            self.assertEqual(payload["event"], request)
            return result
        with patch.object(mod, "gateway", side_effect=gw):
            self.assertIs(mod.lambda_handler(request, None), result)
        self.assertEqual([p for p, _ in calls], ["/v1/authorize", "/v1/legacy"])

    def test_native_discovery_and_reports_have_all_properties_and_endpoint_health(self):
        bindings = [{"interface": "Alexa.PowerController", "entity_id": "light.desk"},
                    {"interface": "Alexa.BrightnessController", "entity_id": "light.desk"}]
        config = {"devices": {"desk": {"name": "Desk", "capabilities": bindings}}}
        states = {"light.desk": {"state": "on", "attributes": {"brightness": 128},
                                 "last_updated": "2026-10-10T08:00:00Z"}}
        caps = mod.discovery(event(), config)["event"]["payload"]["endpoints"][0]["capabilities"]
        supported = {(cap["interface"], prop["name"])
                     for cap in caps for prop in cap.get("properties", {}).get("supported", [])}
        for namespace, name in (("Alexa", "ReportState"), ("Alexa.PowerController", "TurnOn")):
            calls = []
            def gw(path, method="GET", payload=None):
                calls.append(path)
                if path == "/v1/config":
                    return config
                if path == "/v1/control":
                    return {"ok": True}
                if path == "/v1/state":
                    return {"states": states}
                raise AssertionError(path)
            request = event(namespace, name, "native:desk")
            request["directive"]["header"]["correlationToken"] = "dummy-correlation"
            with patch.object(mod, "verify_account", return_value="dummy-ha-user"), patch.object(mod, "gateway", side_effect=gw):
                result = mod.lambda_handler(request, None)
            properties = result["context"]["properties"]
            self.assertEqual({(p["namespace"], p["name"]) for p in properties}, supported)
            self.assertEqual(properties[-1]["value"], {"value": "OK"})
            self.assertEqual(properties[0]["timeOfSample"], states["light.desk"]["last_updated"])
            self.assertEqual(result["event"]["header"]["correlationToken"], "dummy-correlation")

    def test_discovery_omits_individually_disabled_group_capabilities(self):
        config = {"devices": {"relay": {"name": "Doppelrelais", "capabilities": [
            {"interface": "Alexa.ToggleController", "instance": "left", "entity_id": "switch.left"},
            {"interface": "Alexa.ToggleController", "instance": "right", "entity_id": "switch.right", "enabled": False},
        ]}}}
        capabilities = mod.discovery(event(), config)["event"]["payload"]["endpoints"][0]["capabilities"]
        toggles = [capability for capability in capabilities
                   if capability["interface"] == "Alexa.ToggleController"]
        self.assertEqual([capability["instance"] for capability in toggles], ["left"])

    def test_unavailable_entities_never_report_off_or_successful_health(self):
        binding = {"interface": "Alexa.PowerController", "entity_id": "light.desk"}
        config = {"devices": {"desk": {"name": "Desk", "capabilities": [binding]}}}
        for state in ("unknown", "unavailable", None):
            states = {} if state is None else {"light.desk": {"state": state}}
            with patch.object(mod, "verify_account", return_value="dummy-ha-user"), patch.object(
                    mod, "gateway", side_effect=lambda path, method="GET", payload=None:
                    config if path == "/v1/config" else {"states": states}):
                result = mod.lambda_handler(event("Alexa", "ReportState", "native:desk"), None)
            self.assertEqual(result["event"]["payload"]["type"], "ENDPOINT_UNREACHABLE")
            self.assertNotIn("context", result)

    def test_off_light_without_brightness_attribute_reports_zero(self):
        prop = mod.state_for({"interface": "Alexa.BrightnessController", "entity_id": "light.desk"},
                             {"light.desk": {"state": "off", "attributes": {}}})
        self.assertEqual(prop["value"], 0)

    def test_non_finite_sensor_value_cannot_be_serialized_as_valid_alexa_state(self):
        binding = {"interface": "Alexa.RangeController", "instance": "volume", "entity_id": "sensor.tank"}
        for value in ("nan", "inf", "-inf", "not-a-number"):
            with self.subTest(value=value), self.assertRaises(mod.EndpointUnavailable):
                mod.state_for(binding, {"sensor.tank": {"state": value}})

    def test_ha_timestamp_is_preserved_as_utc_instead_of_current_query_time(self):
        binding = {"interface": "Alexa.PowerController", "entity_id": "light.desk"}
        prop = mod.state_for(binding, {"light.desk": {"state": "on",
            "last_updated": "2026-10-10T10:00:00+02:00"}})
        self.assertEqual(prop["timeOfSample"], "2026-10-10T08:00:00Z")

    def test_gateway_authorization_failures_are_not_internal_errors_and_do_not_log_body(self):
        import io
        from contextlib import redirect_stdout
        for status, kind in ((401, "INVALID_AUTHORIZATION_CREDENTIAL"),
                             (404, "ENDPOINT_UNREACHABLE"), (503, "BRIDGE_UNREACHABLE")):
            failure = urllib.error.HTTPError("https://example.invalid/gateway", status, "Private marker", {},
                                             io.BytesIO(b"private-session-marker"))
            output = io.StringIO()
            with redirect_stdout(output), patch.object(mod, "gateway", side_effect=failure):
                result = mod.lambda_handler(event("Alexa", "ReportState", "native:desk"), None)
            self.assertEqual(result["event"]["payload"]["type"], kind)
            self.assertNotIn("private-session-marker", output.getvalue())
            failure.close()

    def test_discovery_returns_native_only_without_calling_legacy(self):
        config = {"devices": {"zisterne": {"name": "Zisterne",