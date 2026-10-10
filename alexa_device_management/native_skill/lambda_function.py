"""Alexa Smart Home v3 Lambda adapter. Devices are fetched live from HA YAML.

Required environment: GATEWAY_URL, GATEWAY_TOKEN.
Account linking stays with Home Assistant OAuth for *both* v5 and v6.
Legacy v5 delegates to HA /api/alexa/smart_home; native v6 reads YAML via gateway.
"""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

GATEWAY_URL = os.environ.get("GATEWAY_URL", "").rstrip("/")
GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "")
NATIVE_PREFIX = "native:"
INTERFACE_ACTIONS = {"Alexa.PowerController", "Alexa.BrightnessController",
                     "Alexa.RangeController", "Alexa.ToggleController",
                     "Alexa.PlaybackController", "Alexa.ThermostatController"}


def request_json(url, method="GET", payload=None, bearer=None):
    headers = {"Accept": "application/json"}
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.load(response)


def gateway(path, method="GET", payload=None):
    if not GATEWAY_URL.startswith("https://") or len(GATEWAY_TOKEN) < 32:
        raise ValueError("Missing secure gateway configuration")
    return request_json(GATEWAY_URL + path, method, payload, GATEWAY_TOKEN)


def token_for(event):
    directive = event["directive"]
    hdr = directive.get("header", {})
    if (hdr.get("namespace"), hdr.get("name")) == ("Alexa.Authorization", "AcceptGrant"):
        return directive.get("payload", {}).get("grantee", {}).get("token")
    return (directive.get("payload", {}).get("scope", {}).get("token")
            or directive.get("endpoint", {}).get("scope", {}).get("token"))


def verify_account(event):
    token = token_for(event)
    if not token:
        raise PermissionError("Missing linked Home Assistant user token")
    gateway("/v1/authorize", "POST", {"token": token})
    return token


def legacy_request(event, token):
    return gateway("/v1/legacy", "POST", {"token": token, "event": event})



def migrated_legacy_ids(config):
    """Only actively enabled native devices can replace a v5 Discovery entry."""
    replacements = set()
    for device in config.get("devices", {}).values():
        if not device.get("enabled", True) or not device.get("capabilities"):
            continue
        old_id = device.get("replaces_legacy_endpoint")
        if isinstance(old_id, str) and old_id:
            replacements.add(old_id)
    return replacements


def header(namespace, name, message_id, correlation=None):
    value = {"namespace": namespace, "name": name, "payloadVersion": "3", "messageId": message_id}
    if correlation:
        value["correlationToken"] = correlation
    return value


def response(event, namespace, name, payload=None, endpoint=None, properties=None):
    directive = event["directive"]
    result = {"event": {"header": header(namespace, name, directive["header"].get("messageId", "response") + "-response",
                                            directive["header"].get("correlationToken")),
                        "payload": payload or {}}}
    if endpoint:
        result["event"]["endpoint"] = {"endpointId": endpoint}
    if properties is not None:
        result["context"] = {"properties": properties}
    return result


def error(event, kind="INTERNAL_ERROR", message="Unable to process request", endpoint=None):
    return response(event, "Alexa", "ErrorResponse", {"type": kind, "message": message}, endpoint)


def capability_config(binding):
    name = binding["interface"]
    if name == "Alexa.PlaybackController":
        return {"type": "AlexaInterface", "interface": name, "version": "3",
                "supportedOperations": binding.get("supported_operations", ["Stop"])}
    if name == "Alexa.ThermostatController":
        return {"type": "AlexaInterface", "interface": name, "version": "3",
                "properties": {"supported": [{"name": "targetSetpoint"}, {"name": "thermostatMode"}],
                               "proactivelyReported": False, "retrievable": True},
                "configuration": {"supportsScheduling": False}}
    capability = {"type": "AlexaInterface", "interface": name, "version": "3",
                  "properties": {"supported": [], "proactivelyReported": False, "retrievable": True}}
    prop = {"Alexa.PowerController": "powerState", "Alexa.BrightnessController": "brightness",
            "Alexa.RangeController": "rangeValue", "Alexa.ToggleController": "toggleState",
            "Alexa.ContactSensor": "detectionState", "Alexa.MotionSensor": "detectionState",
            "Alexa.TemperatureSensor": "temperature"}[name]
    capability["properties"]["supported"] = [{"name": prop}]
    if name in ("Alexa.RangeController", "Alexa.ToggleController"):
        capability["instance"] = binding["instance"]
        label = binding.get("capability_names") or [binding["instance"]]
        capability["capabilityResources"] = {"friendlyNames": [
            {"@type": "text", "value": {"text": text, "locale": "de-DE"}} for text in label]}
    if name == "Alexa.RangeController":
        capability["configuration"] = {"supportedRange": {"minimumValue": binding.get("minimum", 0),
                                                           "maximumValue": binding.get("maximum", 10000),
                                                           "precision": binding.get("precision", 1)},
                                        "unitOfMeasure": binding["unit"]}
    if binding.get("read_only", True) and name == "Alexa.RangeController":
        capability["properties"]["nonControllable"] = True
    return capability


def discovery(event, config):
    endpoints = []
    for endpoint_id, device in sorted(config["devices"].items()):
        if not device.get("enabled", True) or not device["capabilities"]:
            continue
        capabilities = [{"type": "AlexaInterface", "interface": "Alexa", "version": "3"}]
        capabilities.extend(capability_config(binding) for binding in device["capabilities"])
        capabilities.append({"type": "AlexaInterface", "interface": "Alexa.EndpointHealth", "version": "3.1",
                             "properties": {"supported": [{"name": "connectivity"}],
                                            "proactivelyReported": False, "retrievable": True}})
        endpoints.append({"endpointId": NATIVE_PREFIX + endpoint_id, "manufacturerName": "Alexa Device Management",
                          "friendlyName": device["name"],
                          "description": device.get("description") or device["name"],
                          "displayCategories": [device.get("display_category", "OTHER")],
                          "capabilities": capabilities})
    return response(event, "Alexa.Discovery", "Discover.Response", {"endpoints": endpoints})


class EndpointUnavailable(ValueError):
    """No trustworthy state is available for a bound HA entity."""


def available_state(binding, states):
    state = states.get(binding["entity_id"])
    if not isinstance(state, dict) or state.get("state") in (None, "unknown", "unavailable"):
        raise EndpointUnavailable("Bound HA entity is unavailable")
    return state


def numeric_state(value):
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise EndpointUnavailable("Numeric device state missing") from exc
    if not math.isfinite(number):
        raise EndpointUnavailable("Non-finite device state")
    return number


def sample_time(state):
    for key in ("last_updated", "last_changed"):
        value = state.get(key)
        if isinstance(value, str):
            try:
                moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if moment.tzinfo is not None:
                    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            except ValueError:
                pass
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def state_for(binding, states):
    state = available_state(binding, states)
    value = state["state"]
    interface = binding["interface"]
    if interface in ("Alexa.PowerController", "Alexa.ToggleController"):
        if value not in ("on", "off"):
            raise EndpointUnavailable("Switch state is unavailable")
        mapped = "ON" if value == "on" else "OFF"
        prop = "powerState" if interface == "Alexa.PowerController" else "toggleState"
    elif interface == "Alexa.BrightnessController":
        prop = "brightness"
        value = state.get("attributes", {}).get("brightness")
        if value is None and state["state"] == "off":
            value = 0
        if value is None:
            raise EndpointUnavailable("Brightness missing")
        number = numeric_state(value)
        if not 0 <= number <= 255:
            raise EndpointUnavailable("Brightness outside HA range")
        mapped = round(100 * number / 255)
    elif interface in ("Alexa.ContactSensor", "Alexa.MotionSensor"):
        if value not in ("on", "off"):
            raise EndpointUnavailable("Sensor state unavailable")
        prop, mapped = "detectionState", "DETECTED" if value == "on" else "NOT_DETECTED"
    elif interface == "Alexa.TemperatureSensor":
        prop = "temperature"
        if binding["entity_id"].startswith("climate."):
            value = state.get("attributes", {}).get("current_temperature")
        mapped = {"value": numeric_state(value), "scale": "CELSIUS"}
    elif interface == "Alexa.RangeController":
        if binding["entity_id"].startswith("cover."):
            value = state.get("attributes", {}).get("current_position")
            if value is None:
                raise EndpointUnavailable("Cover position unavailable")
        prop, mapped = "rangeValue", numeric_state(value)
    else:
        raise ValueError("Unsupported controller")
    data = {"namespace": interface, "name": prop, "value": mapped,
            "timeOfSample": sample_time(state),
            "uncertaintyInMilliseconds": 1000}
    if binding.get("instance"):
        data["instance"] = binding["instance"]
    return data


def thermostat_properties(binding, states):
    state = available_state(binding, states)
    attributes = state.get("attributes", {})
    target = numeric_state(attributes.get("temperature"))
    mode = str(state.get("state") or "").lower()
    modes = {"heat": "HEAT", "cool": "COOL", "auto": "AUTO", "heat_cool": "AUTO",
             "off": "OFF", "eco": "ECO"}
    if mode not in modes:
        raise EndpointUnavailable("Thermostat mode unavailable")
    stamp = sample_time(state)
    return [
        {"namespace": "Alexa.ThermostatController", "name": "targetSetpoint",
         "value": {"value": target, "scale": "CELSIUS"},
         "timeOfSample": stamp, "uncertaintyInMilliseconds": 1000},
        {"namespace": "Alexa.ThermostatController", "name": "thermostatMode",
         "value": modes[mode], "timeOfSample": stamp, "uncertaintyInMilliseconds": 1000},
    ]


def state_properties(bindings, states):
    """Return every retrievable property plus the discovered endpoint health."""
    for binding in bindings:
        available_state(binding, states)
    properties = []
    for binding in bindings:
        if binding["interface"] == "Alexa.PlaybackController":
            continue
        if binding["interface"] == "Alexa.ThermostatController":
            properties.extend(thermostat_properties(binding, states))
        else:
            properties.append(state_for(binding, states))
    properties.append({"namespace": "Alexa.EndpointHealth", "name": "connectivity",
                       "value": {"value": "OK"},
                       "timeOfSample": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                       "uncertaintyInMilliseconds": 0})
    return properties


def lambda_handler(event, context):
    directive = event.get("directive", {})
    hdr = directive.get("header", {})
    namespace, name = hdr.get("namespace"), hdr.get("name")
    external_id = directive.get("endpoint", {}).get("endpointId", "")
    native = isinstance(external_id, str) and external_id.startswith(NATIVE_PREFIX)
    endpoint_id = external_id[len(NATIVE_PREFIX):] if native else external_id
    try:
        token = verify_account(event)

        # A single Alexa skill exposes both backends. The existing endpoint IDs
        # are never rewritten; only native endpoints receive an explicit prefix.
        if namespace == "Alexa.Discovery" and name == "Discover":
            legacy = legacy_request(event, token)
            if legacy.get("event", {}).get("header", {}).get("name") != "Discover.Response":
                return legacy
            config = gateway("/v1/config")
            native_result = discovery(event, config)
            endpoints = legacy["event"]["payload"]["endpoints"]
            native_endpoints = native_result["event"]["payload"]["endpoints"]
            known = {e["endpointId"] for e in endpoints}
            if any(e["endpointId"] in known for e in native_endpoints):
                raise ValueError("Endpoint ID collision between native and legacy")
            # A user-enabled migration draft replaces exactly its designated
            # legacy endpoint in Discovery. Legacy exports remain untouched,
            # so disabling the draft immediately restores v5 on next Discover.
            replacement_ids = migrated_legacy_ids(config)
            if replacement_ids:
                endpoints[:] = [e for e in endpoints if e["endpointId"] not in replacement_ids]
            # HA sends ChangeReport/AddOrUpdateReport directly to Amazon with
            # its original capabilities. Filtering only synchronous messages
            # would make Discovery and proactive reports contradict each other.
            endpoints.extend(native_endpoints)
            return legacy

        # All non-discovery requests for legacy endpoints, including AcceptGrant,
        # are forwarded unchanged to the existing HA Alexa integration.
        if not native:
            return legacy_request(event, token)

        config = gateway("/v1/config")
        device = config["devices"].get(endpoint_id)
        if not device or not device.get("enabled", True):
            return error(event, "NO_SUCH_ENDPOINT", "Unknown endpoint", external_id)
        bindings = device["capabilities"]
        if namespace == "Alexa" and name == "ReportState":
            states = gateway("/v1/state", "POST", {"endpoint_id": endpoint_id, "token": token})["states"]
            values = state_properties(bindings, states)
            return response(event, "Alexa", "StateReport", endpoint=external_id, properties=values)
        if namespace in INTERFACE_ACTIONS and name in (
                "TurnOn", "TurnOff", "SetBrightness", "SetRangeValue",
                "AdjustRangeValue", "Stop", "SetTargetTemperature",
                "AdjustTargetTemperature", "SetThermostatMode"):
            matching = [b for b in bindings if b["interface"] == namespace
                        and b.get("instance") == hdr.get("instance")]
            if len(matching) != 1:
                return error(event, "INVALID_DIRECTIVE", "Capability missing", external_id)
            binding = matching[0]
            if binding.get("read_only", namespace == "Alexa.RangeController"):
                return error(event, "INVALID_DIRECTIVE", "Read-only capability", external_id)
            action_payload = directive.get("payload", {})
            if name == "SetBrightness":
                value = action_payload.get("brightness")
            elif name == "SetRangeValue":
                value = action_payload.get("rangeValue")
            elif name == "AdjustRangeValue":
                value = action_payload.get("rangeValueDelta")
            elif name == "SetTargetTemperature":
                value = action_payload.get("targetSetpoint")
            elif name == "AdjustTargetTemperature":
                value = action_payload.get("targetSetpointDelta")
            elif name == "SetThermostatMode":
                value = action_payload.get("thermostatMode")
            else:
                value = None
            gateway("/v1/control", "POST", {"endpoint_id": endpoint_id, "interface": namespace,
                                           "instance": binding.get("instance"), "action": name, "value": value, "token": token})
            states = gateway("/v1/state", "POST", {"endpoint_id": endpoint_id, "token": token})["states"]
            return response(event, "Alexa", "Response", endpoint=external_id,
                            properties=state_properties(bindings, states))
        return error(event, "INVALID_DIRECTIVE", "Unsupported directive", external_id)
    except PermissionError:
        return error(event, "INVALID_AUTHORIZATION_CREDENTIAL", "Account not linked", external_id or None)
    except EndpointUnavailable:
        return error(event, "ENDPOINT_UNREACHABLE", "Device state unavailable", external_id or None)
    except urllib.error.HTTPError as exc:
        # Do not include the response body: it may contain account data.
        kind = {401: "INVALID_AUTHORIZATION_CREDENTIAL", 403: "INVALID_DIRECTIVE",
                404: "ENDPOINT_UNREACHABLE", 400: "INVALID_DIRECTIVE",
                503: "BRIDGE_UNREACHABLE", 504: "BRIDGE_UNREACHABLE"}.get(exc.code, "INTERNAL_ERROR")
        print(f"Alexa gateway request failed: HTTP {exc.code}")
        return error(event, kind, endpoint=external_id or None)
    except (ValueError, KeyError, TypeError, urllib.error.URLError) as exc:
        # Never log Alexa's directive: it contains the linked user's access token.
        print(f"Alexa request failed: {type(exc).__name__}")
        return error(event, endpoint=external_id or None)
