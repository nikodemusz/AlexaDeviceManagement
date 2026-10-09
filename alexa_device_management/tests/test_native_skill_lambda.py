"""Regression tests: one Lambda, two separate Alexa backends."""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest
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
        self.assertEqual(len(endpoints[1]["capabilities"]), 3)

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
