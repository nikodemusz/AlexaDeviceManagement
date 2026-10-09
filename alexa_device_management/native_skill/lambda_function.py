"""Alexa Smart Home v3 Lambda adapter. Devices are fetched live from HA YAML.

Required environment: GATEWAY_URL, GATEWAY_TOKEN.
Account linking stays with Home Assistant OAuth for *both* v5 and v6.
Legacy v5 delegates to HA /api/alexa/smart_home; native v6 reads YAML via gateway.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

GATEWAY_URL = os.environ.get("GATEWAY_URL", "").rstrip("/")
GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "")
NATIVE_PREFIX = "native:"
INTERFACE_ACTIONS = {"Alexa.PowerController", "Alexa.BrightnessController",
                     "Alexa.RangeController", "Alexa.ToggleController"}


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
    capability = {"type": "AlexaInterface", "interface": name, "version": "3",
                  "properties": {"supported": [], "proactivelyReported": False, "retrievable": True}}
    prop = {"Alexa.PowerController": "powerState", "Alexa.BrightnessController": "brightness",
            "Alexa.RangeController": "rangeValue", "Alexa.ToggleController": "toggleState"}[name]
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
    if binding.get("read_only") or name == "Alexa.RangeController":
        capability["properties"]["nonControllable"] = True
    return capability


def discovery(event, config):
    endpoints = []
    for endpoint_id, device in sorted(config["devices"].items()):
        if not device.get("enabled", True) or not device["capabilities"]:
            continue
        capabilities = [{"type": "AlexaInterface", "interface": "Alexa", "version": "3"}]
        capabilities.extend(capability_config(binding) for binding in device["capabilities"])
        endpoints.append({"endpointId": NATIVE_PREFIX + endpoint_id, "manufacturerName": "Alexa Device Management",
                          "friendlyName": device["name"],
                          "description": device.get("description") or device["name"],
                          "displayCategories": [device.get("display_category", "OTHER")],
                          "capabilities": capabilities})
    return response(event, "Alexa.Discovery", "Discover.Response", {"endpoints": endpoints})


def state_for(binding, states):
    state = states[binding["entity_id"]]
    value = state["state"]
    interface = binding["interface"]
    if interface in ("Alexa.PowerController", "Alexa.ToggleController"):
        mapped = "ON" if value == "on" else "OFF"
        prop = "powerState" if interface == "Alexa.PowerController" else "toggleState"
    elif interface == "Alexa.BrightnessController":
        prop = "brightness"
        value = state.get("attributes", {}).get("brightness")
        if value is None:
            raise ValueError("Brightness missing")
        mapped = round(100 * float(value) / 255)
    elif interface == "Alexa.RangeController":
        prop, mapped = "rangeValue", float(value)
    else:
        raise ValueError("Unsupported controller")
    data = {"namespace": interface, "name": prop, "value": mapped,
            "timeOfSample": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "uncertaintyInMilliseconds": 1000}
    if binding.get("instance"):
        data["instance"] = binding["instance"]
    return data


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
            values = [state_for(binding, states) for binding in bindings]
            return response(event, "Alexa", "StateReport", endpoint=external_id, properties=values)
        if namespace in INTERFACE_ACTIONS and name in ("TurnOn", "TurnOff", "SetBrightness"):
            matching = [b for b in bindings if b["interface"] == namespace
                        and b.get("instance") == hdr.get("instance")]
            if len(matching) != 1:
                return error(event, "INVALID_DIRECTIVE", "Capability missing", external_id)
            binding = matching[0]
            value = directive.get("payload", {}).get("brightness")
            gateway("/v1/control", "POST", {"endpoint_id": endpoint_id, "interface": namespace,
                                           "instance": binding.get("instance"), "action": name, "value": value, "token": token})
            states = gateway("/v1/state", "POST", {"endpoint_id": endpoint_id, "token": token})["states"]
            return response(event, "Alexa", "Response", endpoint=external_id,
                            properties=[state_for(binding, states)])
        return error(event, "INVALID_DIRECTIVE", "Unsupported directive", external_id)
    except PermissionError:
        return error(event, "INVALID_AUTHORIZATION_CREDENTIAL", "Account not linked", external_id or None)
    except (ValueError, KeyError, TypeError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        # Never log Alexa's directive: it contains the linked user's access token.
        print(f"Alexa request failed: {type(exc).__name__}")
        return error(event, endpoint=external_id or None)
