"""Regression tests: one Lambda, two separate Alexa backends."""
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

    def test_discovery_combines_one_native_endpoint_with_legacy(self):
        config = {"devices": {"zisterne": {"name": "Zisterne", "display_category": "OTHER",
                                          "capabilities": [
            {"interface": "Alexa.RangeController", "instance": "litres",
             "entity_id": "sensor.zisterne_liter", "unit": "Volume.Liters"},
            {"interface": "Alexa.RangeController", "instance": "percent",
             "entity_id": "sensor.zisterne_prozent", "unit": "Percent"},
        ]}}}
        def gateway(path, method="GET", payload=None):
            if path == "/v1/legacy":
                return legacy_discovery()
            if path == "/v1/config":
                return config
            raise AssertionError(path)
        with patch.object(mod, "verify_account", return_value="test-oauth"), patch.object(mod, "gateway", side_effect=gateway):
            result = mod.lambda_handler(event(), None)
        endpoints = result["event"]["payload"]["endpoints"]
        self.assertEqual([e["endpointId"] for e in endpoints], ["legacy-light", "native:zisterne"])
        self.assertEqual(len(endpoints[1]["capabilities"]), 4)

    def test_disabled_native_skill_does_not_interrupt_old_discovery(self):
        with patch.object(mod, "verify_account", return_value="test-oauth"), patch.object(
            mod, "gateway", side_effect=lambda path, method="GET", payload=None:
            legacy_discovery() if path == "/v1/legacy" else {"devices": {}}):
            result = mod.lambda_handler(event(), None)
        self.assertEqual(len(result["event"]["payload"]["endpoints"]), 1)

    def test_legacy_device_directives_are_unmodified(self):
        request = event("Alexa", "ReportState", "legacy-light")
        result = {"event": {"header": {"name": "StateReport"}, "payload": {}}}
        def gw(path, method="GET", payload=None):
            self.assertEqual(path, "/v1/legacy")
            self.assertEqual(payload["event"], request)
            return result
        with patch.object(mod, "verify_account", return_value="test-oauth"), patch.object(mod, "gateway", side_effect=gw):
            self.assertIs(mod.lambda_handler(request, None), result)

    def test_legacy_discovery_preserves_capabilities_used_by_ha_proactive_reports(self):
        import copy
        endpoints = [
            {"endpointId": "cover#blind", "displayCategories": ["INTERIOR_BLIND"],
             "capabilities": [{"interface": name} for name in (
                 "Alexa.PowerController", "Alexa.RangeController",
                 "Alexa.PlaybackController", "Alexa.EndpointHealth")]},
            {"endpointId": "switch#desk", "displayCategories": ["SWITCH"],
             "capabilities": [{"interface": "Alexa.PowerController"},
                              {"interface": "Alexa.ContactSensor"}]},
            {"endpointId": "binary_sensor#door", "displayCategories": ["CONTACT_SENSOR"],
             "capabilities": [{"interface": "Alexa.ContactSensor"}]},
        ]
        original = copy.deepcopy(endpoints)
        legacy = legacy_discovery()
        legacy["event"]["payload"]["endpoints"] = endpoints
        def gw(path, method="GET", payload=None):
            if path == "/v1/legacy":
                return legacy
            if path == "/v1/config":
                return {"devices": {}}
            raise AssertionError(path)
        with patch.object(mod, "verify_account", return_value="test-oauth"), patch.object(mod, "gateway", side_effect=gw):
            result = mod.lambda_handler(event(), None)
        self.assertEqual(result["event"]["payload"]["endpoints"], original)

    def test_legacy_state_report_and_control_properties_are_not_filtered(self):
        for eid in ("cover#blind", "switch#desk", "binary_sensor#door"):
            for namespace, name in (("Alexa", "ReportState"), ("Alexa.PowerController", "TurnOn")):
                result = {"context": {"properties": [
                    {"namespace": "Alexa.PowerController", "name": "powerState", "value": "ON"},
                    {"namespace": "Alexa.ContactSensor", "name": "detectionState", "value": "DETECTED"},
                    {"namespace": "Alexa.RangeController", "name": "rangeValue", "value": 50},
                    {"namespace": "Alexa.EndpointHealth", "name": "connectivity", "value": {"value": "OK"}}]}}
                original = __import__("copy").deepcopy(result)
                with patch.object(mod, "verify_account", return_value="test-oauth"), patch.object(mod, "gateway", return_value=result):
                    actual = mod.lambda_handler(event(namespace, name, eid), None)
                self.assertEqual(actual, original)

    def test_cover_discovery_has_position_and_stop_without_power_switch(self):
        bindings = [
            {"interface": "Alexa.RangeController", "instance": "cover.position",
             "entity_id": "cover.blind", "unit": "Alexa.Unit.Percent",
             "read_only": False, "minimum": 0, "maximum": 100},
            {"interface": "Alexa.PlaybackController", "entity_id": "cover.blind",
             "supported_operations": ["Stop"]},
        ]
        result = mod.discovery(event(), {"devices": {
            "blind": {"name": "Rollladen", "display_category": "INTERIOR_BLIND",
                      "capabilities": bindings}}})
        caps = result["event"]["payload"]["endpoints"][0]["capabilities"]
        self.assertEqual([cap["interface"] for cap in caps],
                         ["Alexa", "Alexa.RangeController", "Alexa.PlaybackController", "Alexa.EndpointHealth"])
        self.assertNotIn("nonControllable", caps[1]["properties"])
        self.assertEqual(caps[2]["supportedOperations"], ["Stop"])

    def test_cover_reports_position_from_attributes_not_on_state(self):
        b = {"interface": "Alexa.RangeController", "instance": "cover.position",
             "entity_id": "cover.blind", "unit": "Alexa.Unit.Percent",
             "read_only": False}
        value = mod.state_for(b, {"cover.blind": {
            "state": "open", "attributes": {"current_position": 37}}})
        self.assertEqual(value["value"], 37)

    def test_cover_stop_is_forwarded_with_health_property(self):
        req = event("Alexa.PlaybackController", "Stop", "native:blind")
        req["directive"]["header"]["instance"] = None
        config = {"devices": {"blind": {"name": "Blind", "capabilities": [
            {"interface": "Alexa.PlaybackController", "entity_id": "cover.blind"}]}}}
        calls = []
        def gw(path, method="GET", payload=None):
            calls.append((path, payload))
            if path == "/v1/config":
                return config
            if path == "/v1/control":
                return {"ok": True}
            if path == "/v1/state":
                return {"states": {"cover.blind": {"state": "open"}}}
            raise AssertionError(path)
        with patch.object(mod, "verify_account", return_value="test-oauth"), patch.object(mod, "gateway", side_effect=gw):
            result = mod.lambda_handler(req, None)
        self.assertEqual(result["event"]["header"]["name"], "Response")
        self.assertEqual(result["context"]["properties"][0]["namespace"], "Alexa.EndpointHealth")
        self.assertEqual(calls[-2][1]["action"], "Stop")

    def test_native_state_uses_correct_binding_and_linked_token(self):
        request = event("Alexa", "ReportState", "native:zisterne")
        config = {"devices": {"zisterne": {"name": "Zisterne", "capabilities": [
            {"interface": "Alexa.RangeController", "instance": "litres",
             "entity_id": "sensor.zisterne_liter", "unit": "Volume.Liters"}]}}}
        def gw(path, method="GET", payload=None):
            if path == "/v1/config":
                return config
            self.assertEqual((path, method), ("/v1/state", "POST"))
            self.assertEqual(payload["token"], "test-oauth")
            return {"states": {"sensor.zisterne_liter": {"state": "1599"}}}
        with patch.object(mod, "verify_account", return_value="test-oauth"), patch.object(mod, "gateway", side_effect=gw):
            result = mod.lambda_handler(request, None)
        self.assertEqual(result["context"]["properties"][0]["value"], 1599.0)
        self.assertEqual(result["event"]["endpoint"]["endpointId"], "native:zisterne")


if __name__ == "__main__":
    unittest.main()
