"""Offline contracts across the real Lambda and authenticated gateway handlers.

Only the HTTP transport, config read, and HA backend are replaced. No sockets,
live config, Amazon session, or physical device is used.
"""
from __future__ import annotations

import asyncio
import copy
import importlib
import importlib.util
import io
import json
import pathlib
import sys
import unittest
import urllib.error
import urllib.parse
from contextlib import ExitStack, redirect_stdout
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from jsonschema import validate

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rootfs/opt/alexa_device_management/web"))
gateway = importlib.import_module("native_skill_gateway")
spec = importlib.util.spec_from_file_location("contract_lambda", ROOT / "native_skill/lambda_function.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)

OAUTH = "offline-linked-user"
MACHINE = "offline-gateway-secret-" + "x" * 32
STAMP = "2026-10-12T08:00:00Z"
UPDATED = "2026-10-12T08:01:00Z"


def fixture_config():
    def device(name, category, *bindings, **extra):
        return {"name": name, "display_category": category, "capabilities": list(bindings), **extra}
    def bind(interface, entity, **extra):
        return {"interface": "Alexa." + interface, "entity_id": entity, **extra}
    return {"schema_version": 6, "enabled": True, "locale": "de-DE", "devices": {
        "desk": device("Test Schreibtischlicht", "LIGHT",
                       bind("PowerController", "light.test_desk"),
                       bind("BrightnessController", "light.test_desk")),
        "socket": device("Test Steckdose", "SWITCH", bind("PowerController", "switch.test_socket")),
        "toggle": device("Test Freigabe", "SWITCH",
                         bind("ToggleController", "input_boolean.test_toggle", instance="permission")),
        "blind": device("Test Rollladen", "INTERIOR_BLIND",
                        bind("RangeController", "cover.test_blind", instance="cover.position",
                             unit="Alexa.Unit.Percent", minimum=0, maximum=100, read_only=False),
                        bind("PlaybackController", "cover.test_blind", supported_operations=["Stop"])),
        "heating": device("Test Heizung", "THERMOSTAT",
                          bind("ThermostatController", "climate.test_heating", supported_modes=["HEAT", "OFF"]),
                          bind("TemperatureSensor", "climate.test_heating")),
        "cistern": device("Test Zisterne", "OTHER",
                          bind("RangeController", "sensor.test_litres", instance="litres",
                               unit="Alexa.Unit.Liters", minimum=0, maximum=10000, read_only=True),
                          bind("RangeController", "sensor.test_percent", instance="percent",
                               unit="Alexa.Unit.Percent", minimum=0, maximum=100, read_only=True)),
        "door": device("Test Türkontakt", "CONTACT_SENSOR", bind("ContactSensor", "binary_sensor.test_door")),
        "motion": device("Test Bewegung", "MOTION_SENSOR", bind("MotionSensor", "binary_sensor.test_motion")),
        "temperature": device("Test Temperatur", "TEMPERATURE_SENSOR",
                              bind("TemperatureSensor", "sensor.test_temperature")),
        "disabled": device("Test Deaktiviert", "SWITCH", bind("PowerController", "switch.test_disabled"), enabled=False),
    }}


def fixture_states():
    def state(value, **attributes):
        return {"state": value, "attributes": attributes, "last_updated": STAMP}
    return {"light.test_desk": state("off", brightness=0), "switch.test_socket": state("off"),
            "input_boolean.test_toggle": state("off"), "cover.test_blind": state("open", current_position=40),
            "climate.test_heating": state("heat", temperature=21, current_temperature=20.5),
            "sensor.test_litres": state("2500"), "sensor.test_percent": state("50"),
            "binary_sensor.test_door": state("on"), "binary_sensor.test_motion": state("off"),
            "sensor.test_temperature": state("18.25")}


def directive(namespace="Alexa.Discovery", name="Discover", endpoint=None, payload=None, instance=None):
    header = {"namespace": namespace, "name": name, "payloadVersion": "3", "messageId": "offline-request"}
    body = {"header": header, "payload": payload or {}}
    if endpoint is None:
        body["payload"]["scope"] = {"type": "BearerToken", "token": OAUTH}
    else:
        header["correlationToken"] = "offline-correlation"
        body["endpoint"] = {"endpointId": endpoint, "scope": {"type": "BearerToken", "token": OAUTH}}
    if instance:
        header["instance"] = instance
    return {"directive": body}


class NativeDeviceContractTests(unittest.TestCase):
    def setUp(self):
        self.config = fixture_config()
        self.states = fixture_states()
        self.requests, self.services, self.state_reads = [], [], []
        self.authorized = True
        self.apply_services = True
        self.ha_failure = None
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target, name, value in ((adapter, "GATEWAY_URL", "https://offline.invalid"),
                                    (adapter, "GATEWAY_TOKEN", MACHINE)):
            self.stack.enter_context(patch.object(target, name, value))
        self.stack.enter_context(patch.object(gateway, "secret", return_value=MACHINE))
        self.stack.enter_context(patch.object(gateway.NativeSkillConfigStore, "load", side_effect=lambda: copy.deepcopy(self.config)))
        self.stack.enter_context(patch.object(gateway, "ha_request", new=AsyncMock(side_effect=self.ha_request)))
        self.stack.enter_context(patch.object(gateway, "linked_token_request", new=AsyncMock(side_effect=self.authorize)))
        # Any accidental live HA request fails instead of opening a network socket.
        self.stack.enter_context(patch.object(gateway.aiohttp, "ClientSession", side_effect=AssertionError("Live HTTP prohibited")))
        self.stack.enter_context(patch.object(adapter.urllib.request, "urlopen", side_effect=self.urlopen))
        self.app = gateway.create_app()

    async def authorize(self, token, endpoint, data=None):
        if not self.authorized or token != OAUTH:
            raise web.HTTPUnauthorized()
        self.assertEqual(endpoint, "/")
        self.assertIsNone(data)
        return {"message": "offline HA"}

    async def ha_request(self, method, endpoint, payload=None, token=None):
        self.assertEqual(token, OAUTH)
        if self.ha_failure is not None:
            raise self.ha_failure
        if method == "GET" and endpoint.startswith("/states/"):
            entity = endpoint.removeprefix("/states/")
            self.state_reads.append(entity)
            if entity not in self.states:
                raise web.HTTPNotFound()
            return copy.deepcopy(self.states[entity])
        self.assertEqual(method, "POST")
        self.services.append((endpoint, copy.deepcopy(payload)))
        entity = payload["entity_id"]
        state = self.states[entity]
        if not self.apply_services:
            return []
        if endpoint in ("/services/light/turn_on", "/services/switch/turn_on", "/services/input_boolean/turn_on"):
            state["state"] = "on"
            if "brightness_pct" in payload:
                state["attributes"]["brightness"] = round(payload["brightness_pct"] * 255 / 100)
        elif endpoint in ("/services/light/turn_off", "/services/switch/turn_off", "/services/input_boolean/turn_off"):
            state["state"] = "off"
            if entity.startswith("light."):
                state["attributes"]["brightness"] = 0
        elif endpoint == "/services/cover/set_cover_position":
            state["attributes"]["current_position"] = payload["position"]
        elif endpoint == "/services/cover/stop_cover":
            pass
        elif endpoint == "/services/climate/set_temperature":
            state["attributes"]["temperature"] = payload["temperature"]
        elif endpoint == "/services/climate/set_hvac_mode":
            state["state"] = payload["hvac_mode"]
        else:
            self.fail("Unexpected HA service: " + endpoint)
        state["last_updated"] = UPDATED
        return []

    def urlopen(self, request, timeout):
        url = urllib.parse.urlsplit(request.full_url)
        self.assertEqual((url.scheme, url.netloc), ("https", "offline.invalid"))
        self.assertEqual(timeout, 8)
        path = url.path
        body = json.loads(request.data) if request.data else None
        self.requests.append((path, request.get_method(), copy.deepcopy(body)))
        req = make_mocked_request(request.get_method(), path, headers=dict(request.header_items()), app=self.app)
        req.json = AsyncMock(return_value=body)
        async def dispatch():
            match = await self.app.router.resolve(req)
            return await gateway.authentication(req, match.handler)
        try:
            result = asyncio.run(dispatch())
        except web.HTTPException as exc:
            error = urllib.error.HTTPError(request.full_url, exc.status, "Offline gateway rejection", {}, io.BytesIO())
            error.close()
            raise error from exc
        return io.BytesIO(result.body)

    def invoke(self, request):
        with redirect_stdout(io.StringIO()):
            result = adapter.lambda_handler(copy.deepcopy(request), None)
        json.dumps(result, allow_nan=False)
        self.assertNotIn(OAUTH, json.dumps(result))
        self.assertNotIn(MACHINE, json.dumps(result))
        return result

    def discover(self):
        return self.invoke(directive())["event"]["payload"]["endpoints"]

    @staticmethod
    def properties(result):
        return {(p["namespace"], p["name"], p.get("instance")): p["value"] for p in result["context"]["properties"]}

    def assert_envelope(self, result, name, endpoint):
        header = result["event"]["header"]
        self.assertEqual((header["namespace"], header["name"], header["payloadVersion"]), ("Alexa", name, "3"))
        self.assertEqual(header["correlationToken"], "offline-correlation")
        self.assertEqual(result["event"]["endpoint"]["endpointId"], endpoint)
        self.assertTrue(header["messageId"])

    def assert_contract(self, result, endpoint):
        entry = next(e for e in self.discover() if e["endpointId"] == endpoint)
        supported = {(c["interface"], p["name"], c.get("instance"))
                     for c in entry["capabilities"] for p in c.get("properties", {}).get("supported", [])}
        properties = result["context"]["properties"]
        self.assertEqual(set(self.properties(result)), supported)
        self.assertEqual(len(properties), len(supported))
        self.assertEqual(self.properties(result)[("Alexa.EndpointHealth", "connectivity", None)], {"value": "OK"})
        for prop in properties:
            self.assertGreaterEqual(prop["uncertaintyInMilliseconds"], 0)
            self.assertTrue(prop["timeOfSample"].endswith("Z"))

    def control(self, endpoint, interface, action, payload, service, expected_payload, prop, expected, instance=None):
        request = directive(interface, action, endpoint, payload, instance)
        result = self.invoke(request)
        self.assert_envelope(result, "Response", endpoint)
        self.assertEqual(self.services, [(service, expected_payload)])
        self.assertEqual(self.properties(result)[prop], expected)
        self.assertEqual([path for path, _, _ in self.requests],
                         ["/v1/authorize", "/v1/config", "/v1/control", "/v1/state"])
        self.assert_contract(result, endpoint)
        self.assertTrue(all(p["timeOfSample"] == UPDATED for p in result["context"]["properties"]
                            if p["namespace"] != "Alexa.EndpointHealth"))
        readback = self.invoke(directive("Alexa", "ReportState", endpoint))
        self.assert_envelope(readback, "StateReport", endpoint)
        self.assertEqual(self.properties(readback), self.properties(result))
        self.assertEqual(self.services, [(service, expected_payload)])

    def test_fixture_validates_against_schema_and_config_store(self):
        validate(self.config, json.loads((ROOT / "schemas/native-skill.schema.json").read_text()))
        gateway.NativeSkillConfigStore.validate(self.config)

    def test_discovery_has_stable_unique_ids_and_one_cistern_with_two_values(self):
        entries = self.discover()
        expected = {"native:" + e for e in ("desk", "socket", "toggle", "blind", "heating", "cistern", "door", "motion", "temperature")}
        self.assertEqual({e["endpointId"] for e in entries}, expected)
        self.assertEqual(len(entries), len(expected))
        self.assertEqual(len({e["friendlyName"] for e in entries}), len(expected))
        self.assertTrue(all(e["manufacturerName"] == "Alexa Device Management" for e in entries))
        tank = next(e for e in entries if e["endpointId"] == "native:cistern")
        ranges = [c for c in tank["capabilities"] if c["interface"] == "Alexa.RangeController"]
        self.assertEqual({(c["instance"], c["configuration"]["unitOfMeasure"]) for c in ranges},
                         {("litres", "Alexa.Unit.Liters"), ("percent", "Alexa.Unit.Percent")})
        self.assertTrue(all(c["properties"]["nonControllable"] for c in ranges))
        self.config["devices"]["desk"]["name"] = "Umbenanntes Testlicht"
        self.assertEqual({e["endpointId"] for e in self.discover()}, expected)
        self.assertNotIn("/v1/legacy", [p for p, _, _ in self.requests])

    def test_disabled_global_config_exports_nothing(self):
        self.config["enabled"] = False
        self.assertEqual(self.discover(), [])

    def test_every_discovered_endpoint_has_matching_status_properties(self):
        for entry in self.discover():
            with self.subTest(endpoint=entry["endpointId"]):
                result = self.invoke(directive("Alexa", "ReportState", entry["endpointId"]))
                self.assert_envelope(result, "StateReport", entry["endpointId"])
                self.assert_contract(result, entry["endpointId"])
                self.assertTrue(all(p["timeOfSample"] == STAMP for p in result["context"]["properties"]
                                    if p["namespace"] != "Alexa.EndpointHealth"))
        self.assertEqual(self.services, [])

    def test_cistern_status_keeps_litres_and_percent_separate(self):
        result = self.invoke(directive("Alexa", "ReportState", "native:cistern"))
        self.assertEqual(self.properties(result), {("Alexa.RangeController", "rangeValue", "litres"): 2500.0,
            ("Alexa.RangeController", "rangeValue", "percent"): 50.0,
            ("Alexa.EndpointHealth", "connectivity", None): {"value": "OK"}})
        self.assertEqual(self.state_reads, ["sensor.test_litres", "sensor.test_percent"])

    def test_shared_entity_is_read_once_per_status_request(self):
        self.invoke(directive("Alexa", "ReportState", "native:desk"))
        self.assertEqual(self.state_reads, ["light.test_desk"])
        self.state_reads.clear()
        self.invoke(directive("Alexa", "ReportState", "native:heating"))
        self.assertEqual(self.state_reads, ["climate.test_heating"])

    def test_sensor_and_thermostat_status_values_match_ha(self):
        expected = {
            "native:door": {("Alexa.ContactSensor", "detectionState", None): "DETECTED"},
            "native:motion": {("Alexa.MotionSensor", "detectionState", None): "NOT_DETECTED"},
            "native:temperature": {("Alexa.TemperatureSensor", "temperature", None): {"value": 18.25, "scale": "CELSIUS"}},
            "native:heating": {
                ("Alexa.ThermostatController", "targetSetpoint", None): {"value": 21, "scale": "CELSIUS"},
                ("Alexa.ThermostatController", "thermostatMode", None): "HEAT",
                ("Alexa.TemperatureSensor", "temperature", None): {"value": 20.5, "scale": "CELSIUS"}},
        }
        for endpoint, values in expected.items():
            with self.subTest(endpoint=endpoint):
                values = {**values, ("Alexa.EndpointHealth", "connectivity", None): {"value": "OK"}}
                self.assertEqual(self.properties(self.invoke(directive("Alexa", "ReportState", endpoint))), values)
        self.assertEqual(self.services, [])

    def test_light_power_control_and_status(self):
        self.control("native:desk", "Alexa.PowerController", "TurnOn", {}, "/services/light/turn_on",
                     {"entity_id": "light.test_desk"}, ("Alexa.PowerController", "powerState", None), "ON")

    def test_light_turn_off_and_status(self):
        self.states["light.test_desk"]["state"] = "on"
        self.control("native:desk", "Alexa.PowerController", "TurnOff", {}, "/services/light/turn_off",
                     {"entity_id": "light.test_desk"}, ("Alexa.PowerController", "powerState", None), "OFF")

    def test_switch_control_and_status(self):
        self.control("native:socket", "Alexa.PowerController", "TurnOn", {}, "/services/switch/turn_on",
                     {"entity_id": "switch.test_socket"}, ("Alexa.PowerController", "powerState", None), "ON")

    def test_brightness_control_converts_ha_255_scale_to_alexa_percent(self):
        self.control("native:desk", "Alexa.BrightnessController", "SetBrightness", {"brightness": 42},
                     "/services/light/turn_on", {"entity_id": "light.test_desk", "brightness_pct": 42},
                     ("Alexa.BrightnessController", "brightness", None), 42)

    def test_toggle_uses_instance_and_correct_entity(self):
        self.control("native:toggle", "Alexa.ToggleController", "TurnOn", {}, "/services/input_boolean/turn_on",
                     {"entity_id": "input_boolean.test_toggle"}, ("Alexa.ToggleController", "toggleState", "permission"),
                     "ON", "permission")

    def test_cover_absolute_position_and_status(self):
        self.control("native:blind", "Alexa.RangeController", "SetRangeValue", {"rangeValue": 64},
                     "/services/cover/set_cover_position", {"entity_id": "cover.test_blind", "position": 64},
                     ("Alexa.RangeController", "rangeValue", "cover.position"), 64, "cover.position")

    def test_cover_relative_position_uses_current_ha_position(self):
        self.control("native:blind", "Alexa.RangeController", "AdjustRangeValue", {"rangeValueDelta": -12},
                     "/services/cover/set_cover_position", {"entity_id": "cover.test_blind", "position": 28},
                     ("Alexa.RangeController", "rangeValue", "cover.position"), 28, "cover.position")

    def test_cover_stop_preserves_position_and_reports_health(self):
        self.control("native:blind", "Alexa.PlaybackController", "Stop", {}, "/services/cover/stop_cover",
                     {"entity_id": "cover.test_blind"}, ("Alexa.RangeController", "rangeValue", "cover.position"), 40)

    def test_thermostat_absolute_target_keeps_actual_temperature_separate(self):
        self.control("native:heating", "Alexa.ThermostatController", "SetTargetTemperature",
                     {"targetSetpoint": {"value": 23.5, "scale": "CELSIUS"}}, "/services/climate/set_temperature",
                     {"entity_id": "climate.test_heating", "temperature": 23.5},
                     ("Alexa.ThermostatController", "targetSetpoint", None), {"value": 23.5, "scale": "CELSIUS"})
        self.assertEqual(self.states["climate.test_heating"]["attributes"]["current_temperature"], 20.5)

    def test_thermostat_relative_target_uses_current_setpoint(self):
        self.control("native:heating", "Alexa.ThermostatController", "AdjustTargetTemperature",
                     {"targetSetpointDelta": {"value": 1.5, "scale": "CELSIUS"}}, "/services/climate/set_temperature",
                     {"entity_id": "climate.test_heating", "temperature": 22.5},
                     ("Alexa.ThermostatController", "targetSetpoint", None), {"value": 22.5, "scale": "CELSIUS"})

    def test_thermostat_mode_control_and_discovery(self):
        heating = next(e for e in self.discover() if e["endpointId"] == "native:heating")
        cap = next(c for c in heating["capabilities"] if c["interface"] == "Alexa.ThermostatController")
        self.assertEqual(cap["configuration"]["supportedModes"], ["HEAT", "OFF"])
        self.requests.clear()
        self.control("native:heating", "Alexa.ThermostatController", "SetThermostatMode", {"thermostatMode": {"value": "OFF"}},
                     "/services/climate/set_hvac_mode", {"entity_id": "climate.test_heating", "hvac_mode": "off"},
                     ("Alexa.ThermostatController", "thermostatMode", None), "OFF")

    def test_control_response_uses_readback_not_requested_state(self):
        self.apply_services = False
        result = self.invoke(directive("Alexa.PowerController", "TurnOn", "native:desk"))
        self.assertEqual(self.properties(result)[("Alexa.PowerController", "powerState", None)], "OFF")
        self.assertEqual(self.properties(result), self.properties(self.invoke(directive("Alexa", "ReportState", "native:desk"))))

    def test_v5_unknown_and_disabled_endpoints_never_control_ha(self):
        for endpoint in ("light#test_desk", "native:missing", "native:disabled"):
            for namespace, action in (("Alexa", "ReportState"), ("Alexa.PowerController", "TurnOn")):
                with self.subTest(endpoint=endpoint, action=action):
                    result = self.invoke(directive(namespace, action, endpoint))
                    self.assert_envelope(result, "ErrorResponse", endpoint)
                    self.assertEqual(result["event"]["payload"]["type"], "NO_SUCH_ENDPOINT")
        self.assertEqual(self.services, [])
        self.assertEqual(self.state_reads, [])
        self.assertNotIn("/v1/legacy", [p for p, _, _ in self.requests])

    def test_unavailable_missing_and_invalid_sensor_states_are_unreachable(self):
        for state in ("unknown", "unavailable", "nan", "inf", None):
            with self.subTest(state=state):
                if state is None:
                    self.states.pop("sensor.test_litres")
                else:
                    self.states["sensor.test_litres"]["state"] = state
                result = self.invoke(directive("Alexa", "ReportState", "native:cistern"))
                self.assertEqual(result["event"]["payload"]["type"], "ENDPOINT_UNREACHABLE")
                self.assertNotIn("context", result)

    def test_invalid_controls_and_read_only_sensors_never_call_services(self):
        requests = [directive("Alexa.BrightnessController", "SetBrightness", "native:desk", {"brightness": 101}),
                    directive("Alexa.RangeController", "SetRangeValue", "native:blind", {"rangeValue": 101}, "cover.position"),
                    directive("Alexa.RangeController", "AdjustRangeValue", "native:blind", {"rangeValueDelta": -90}, "cover.position"),
                    directive("Alexa.RangeController", "SetRangeValue", "native:cistern", {"rangeValue": 1}, "litres"),
                    directive("Alexa.ToggleController", "TurnOn", "native:toggle", instance="wrong-instance"),
                    directive("Alexa.ThermostatController", "SetTargetTemperature", "native:heating",
                              {"targetSetpoint": {"value": 75, "scale": "FAHRENHEIT"}})]
        for request in requests:
            with self.subTest(header=request["directive"]["header"]):
                result = self.invoke(request)
                self.assertEqual(result["event"]["payload"]["type"], "INVALID_DIRECTIVE")
        self.assertEqual(self.services, [])

    def test_gateway_and_user_authorization_fail_closed(self):
        for authorization in ("machine", "user", "missing-user"):
            with self.subTest(authorization=authorization):
                request = directive("Alexa.PowerController", "TurnOn", "native:desk")
                with patch.object(adapter, "GATEWAY_TOKEN", MACHINE if authorization != "machine" else "wrong-" + "x" * 32):
                    self.authorized = authorization != "user"
                    if authorization == "missing-user":
                        request["directive"]["endpoint"].pop("scope")
                    result = self.invoke(request)
                    self.assertEqual(result["event"]["payload"]["type"], "INVALID_AUTHORIZATION_CREDENTIAL")
        self.assertEqual(self.services, [])

    def test_disabled_gateway_and_backend_failure_never_claim_success(self):
        for failure in ("disabled", "ha-unreachable"):
            with self.subTest(failure=failure):
                self.config["enabled"] = failure != "disabled"
                self.ha_failure = web.HTTPServiceUnavailable() if failure == "ha-unreachable" else None
                for namespace, action in (("Alexa", "ReportState"), ("Alexa.PowerController", "TurnOn")):
                    result = self.invoke(directive(namespace, action, "native:desk"))
                    self.assertEqual(result["event"]["header"]["name"], "ErrorResponse")
                    expected = "NO_SUCH_ENDPOINT" if failure == "disabled" else "BRIDGE_UNREACHABLE"
                    self.assertEqual(result["event"]["payload"]["type"], expected)
                    self.assertNotIn("context", result)
        self.assertEqual(self.services, [])

    def test_unavailable_readback_after_control_cannot_report_healthy_success(self):
        self.apply_services = False
        self.states["light.test_desk"]["state"] = "unavailable"
        result = self.invoke(directive("Alexa.PowerController", "TurnOn", "native:desk"))
        self.assertEqual(self.services, [("/services/light/turn_on", {"entity_id": "light.test_desk"})])
        self.assertEqual(result["event"]["payload"]["type"], "ENDPOINT_UNREACHABLE")
        self.assertNotIn("context", result)

    def test_console_examples_are_executable_against_offline_fixture(self):
        examples = json.loads((ROOT / "native_skill/test_events.json").read_text())
        for label, request in examples.items():
            with self.subTest(example=label):
                request = copy.deepcopy(request)
                body = request["directive"]
                scope = body.get("endpoint", {}).get("scope") or body["payload"]["scope"]
                self.assertEqual(scope["token"], "REPLACE_WITH_HA_OAUTH_ACCESS_TOKEN")
                scope["token"] = OAUTH
                result = self.invoke(request)
                self.assertNotEqual(result["event"]["header"]["name"], "ErrorResponse")


if __name__ == "__main__":
    unittest.main()
