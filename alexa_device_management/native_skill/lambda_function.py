"""Native-only Alexa Smart Home v3 Lambda adapter. Devices use the v6 HA YAML.

Required environment: GATEWAY_URL, GATEWAY_TOKEN.
Account linking stays with Home Assistant OAuth. Only AcceptGrant reaches the
existing HA Alexa integration; v5 discovery and device control are retired.
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
        if not device.get("enabled", True) or not any(
            capability.get("enabled", True) for capability in device.get("capabilities", [])
        ):
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
                "configuration": {"supportsScheduling": False,
                                  "supportedModes": binding.get("supported_modes", ["HEAT"])}}
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
        bindings = [binding for binding in device["capabilities"] if binding.get("enabled", True)]
        if not device.get("enabled", True) or not bindings:
            continue
        capabilities = [{"type": "AlexaInterface", "interface": "Alexa", "version": "3"}]
        capabilities.extend(capability_config(binding) for binding in bindings)
        capabilities.append({"type": "AlexaInterface", "interface": "Alexa.EndpointHealth", "version": "3.1",
                             "properties": {"supported": [{"name": "connectivity"}],
                                            "proactivelyReported": False, "retrievable": True}})
        endpoints.append({"endpointId": NATIVE_PREFIX + endpoint_id, "manufacturerName": "Alexa Device Management",
                          "friendlyName": device["name"],
                          "description": device.get("description") or device["name"],
                          "displayCategories": [device.get("display_category", "OTHER")],
                          "capabilities": capabilities})
    if len(endpoints) > 300:
        raise ValueError("Alexa supports at most 300 active endpoints")
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
    except (ValueError, TypeError, OverflowError) as