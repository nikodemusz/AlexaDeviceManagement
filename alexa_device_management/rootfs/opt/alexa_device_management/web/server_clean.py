"""Clean Home Assistant OS app server for Alexa Device Management."""

from __future__ import annotations

import asyncio
import json
import pathlib
import re
import time
from typing import Any
from urllib.parse import quote

import aiohttp
from aiohttp import web

import oh_style_login

APP_VERSION = "2.11.21-rc1"
BASE_DIR = pathlib.Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
SESSION_PATH = pathlib.Path("/data/alexa_session.json")
OPTIONS_PATH = pathlib.Path("/data/options.json")
HINTS_PATH = pathlib.Path("/data/api_hints.json")
DELETE_JOB_PATH = pathlib.Path("/data/delete_job.json")
DEVICES_CACHE_PATH = pathlib.Path("/data/devices_cache.json")

# Devices cache: served instantly, refreshed in the background
DEVICES_CACHE_TTL = 60          # seconds before a background refresh is triggered
DEVICES_REFRESH_INTERVAL = 900  # periodic refresh while the add-on runs


def read_json(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def session_data() -> dict[str, Any]:
    return read_json(SESSION_PATH)


def read_hint(key: str) -> Any:
    return read_json(HINTS_PATH).get(key)


def write_hint(key: str, value: Any) -> None:
    hints = read_json(HINTS_PATH)
    hints[key] = value
    try:
        HINTS_PATH.write_text(json.dumps(hints), encoding="utf-8")
    except OSError:
        pass


def is_configured() -> bool:
    data = session_data()
    return bool(data.get("cookie") and data.get("csrf") and data.get("websiteApiUrl"))


async def index(request: web.Request) -> web.Response:
    html_path = STATIC_DIR / "index.html"
    text = html_path.read_text(encoding="utf-8")
    ingress_path = request.headers.get("X-Ingress-Path", "")
    text = text.replace("{{INGRESS_PATH}}", ingress_path.rstrip("/"))
    return web.Response(text=text, content_type="text/html")


async def app_info(request: web.Request) -> web.Response:
    data = session_data()
    configured = is_configured()
    return web.json_response(
        {
            "app_version": APP_VERSION,
            "configured": configured,
            "authenticated": configured,
            "region": data.get("retailDomain", "amazon.com"),
            "token_source": "alexa_web_session" if configured else "not_connected",
            "auth_message": "Alexa-Web-Session aktiv" if configured else "Bitte Alexa-Login starten.",
            "amazon_user": {},
        }
    )


async def config_status(request: web.Request) -> web.Response:
    data = session_data()
    configured = is_configured()
    return web.json_response(
        {
            "configured": configured,
            "region": data.get("retailDomain", "amazon.com"),
            "host": data.get("host"),
            "loginMode": data.get("loginMode"),
        }
    )


async def logout(request: web.Request) -> web.Response:
    for path in (SESSION_PATH, oh_style_login.STATE_PATH):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return web.json_response({"ok": True})


async def auth_login(request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound(oh_style_login.external_url(request, "/alexa-auth/start"))


async def auth_session(request: web.Request) -> web.Response:
    data = session_data()
    return web.json_response(
        {
            "configured": is_configured(),
            "host": data.get("host"),
            "retailDomain": data.get("retailDomain"),
            "retailUrl": data.get("retailUrl"),
            "websiteApiUrl": data.get("websiteApiUrl"),
            "createdAt": data.get("createdAt"),
            "loginMode": data.get("loginMode"),
            "hasCookie": bool(data.get("cookie")),
            "hasCsrf": bool(data.get("csrf")),
            "hasRefreshToken": bool(data.get("refreshToken")),
        }
    )


def alexa_headers(data: dict[str, Any]) -> dict[str, str]:
    base_url = data.get("websiteApiUrl", "https://alexa.amazon.com").rstrip("/")
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Referer": f"{base_url}/spa/index.html",
        "Origin": base_url,
        "Cookie": data.get("cookie", ""),
    }
    if data.get("csrf"):
        headers["csrf"] = data["csrf"]
    return headers


async def alexa_delete(path: str, data: dict[str, Any], body: bytes | None = None) -> str:
    """Returns response body on success (empty string for 204)."""
    if not is_configured():
        raise Exception("Alexa session missing")
    base = data.get("websiteApiUrl", "https://alexa.amazon.com").rstrip("/")
    headers = alexa_headers(data)
    if body is not None:
        headers["Content-Type"] = "application/json; charset=UTF-8"
    async with aiohttp.ClientSession() as session:
        async with session.delete(base + path, headers=headers, data=body, allow_redirects=False) as resp:
            resp_body = await resp.text()
            if resp.status not in (200, 204):
                raise Exception(f"HTTP {resp.status}: {resp_body[:300]}")
            return resp_body


async def alexa_raw_get(path: str, data: dict[str, Any]) -> tuple[int, str]:
    """Returns (status, body) without throwing on non-200."""
    if not is_configured():
        return 0, "Alexa session missing"
    base = data.get("websiteApiUrl", "https://alexa.amazon.com").rstrip("/")
    async with aiohttp.ClientSession() as session:
        async with session.get(base + path, headers=alexa_headers(data), allow_redirects=False) as resp:
            return resp.status, await resp.text()


async def alexa_raw_delete(path: str, data: dict[str, Any]) -> tuple[int, str]:
    """Returns (status, body) without throwing on non-2xx."""
    if not is_configured():
        return 0, "Alexa session missing"
    base = data.get("websiteApiUrl", "https://alexa.amazon.com").rstrip("/")
    async with aiohttp.ClientSession() as session:
        async with session.delete(base + path, headers=alexa_headers(data), allow_redirects=False) as resp:
            return resp.status, await resp.text()


async def alexa_raw_post(path: str, body: bytes, data: dict[str, Any]) -> tuple[int, str]:
    """POST with JSON body, cookie auth. Returns (status, body) without throwing."""
    if not is_configured():
        return 0, "Alexa session missing"
    base = data.get("websiteApiUrl", "https://alexa.amazon.com").rstrip("/")
    headers = alexa_headers(data)
    headers["Content-Type"] = "application/json; charset=UTF-8"
    async with aiohttp.ClientSession() as session:
        async with session.post(base + path, headers=headers, data=body, allow_redirects=False) as resp:
            return resp.status, await resp.text()


async def alexa_raw_put(path: str, body: bytes, data: dict[str, Any]) -> tuple[int, str]:
    """PUT with JSON body, cookie auth. Returns (status, body) without throwing."""
    if not is_configured():
        return 0, "Alexa session missing"
    base = data.get("websiteApiUrl", "https://alexa.amazon.com").rstrip("/")
    headers = alexa_headers(data)
    headers["Content-Type"] = "application/json; charset=UTF-8"
    async with aiohttp.ClientSession() as session:
        async with session.put(base + path, headers=headers, data=body, allow_redirects=False) as resp:
            return resp.status, await resp.text()


GRAPHQL_PATH = "/nexus/v1/graphql"

# Schema facts learned from live validation errors (v1.2.2 probes):
# - endpoints takes no latencyTolerance argument
# - LegacyIdentifiers has no legacyApplianceIdentifier field
# - Mutation has no deleteEndpoint field / DeleteEndpointInput type
ENDPOINTS_QUERY_FULL = """query CustomerSmartHome {
  endpoints {
    items {
      endpointId
      friendlyName
      legacyIdentifiers {
        chrsIdentifier { entityId }
      }
    }
  }
}"""

ENDPOINTS_QUERY_MINIMAL = """query CustomerSmartHome {
  endpoints {
    items {
      endpointId
      friendlyName
    }
  }
}"""


async def alexa_graphql(query: str, variables: dict[str, Any] | None, data: dict[str, Any]) -> tuple[int, Any]:
    """POST a GraphQL request to the modern /nexus/v1/graphql API."""
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    st, text = await alexa_raw_post(GRAPHQL_PATH, body, data)
    try:
        return st, json.loads(text)
    except json.JSONDecodeError:
        return st, {"raw": text[:300]}


_TYPE_REF = "kind name ofType { kind name ofType { kind name ofType { kind name } } }"

INTROSPECT_TYPE_QUERY = (
    "query Introspect($name: String!) { __type(name: $name) { name kind "
    "fields { name args { name type { " + _TYPE_REF + " } } type { " + _TYPE_REF + " } } "
    "inputFields { name type { " + _TYPE_REF + " } } } }"
)

_GQL_TYPE_CACHE: dict[str, Any] = {}
_PHOENIX_UNAVAILABLE = False


async def gql_introspect_type(type_name: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Introspect a GraphQL type; returns its fields/inputFields or None."""
    if type_name in _GQL_TYPE_CACHE:
        return _GQL_TYPE_CACHE[type_name]
    st, payload = await alexa_graphql(INTROSPECT_TYPE_QUERY, {"name": type_name}, data)
    if st != 200 or not isinstance(payload, dict) or payload.get("errors"):
        return None
    type_info = (payload.get("data") or {}).get("__type")
    if isinstance(type_info, dict):
        _GQL_TYPE_CACHE[type_name] = type_info
        return type_info
    return None


def _unwrap_type(type_ref: Any) -> dict[str, Any]:
    """Innermost named type of a TypeRef (skips NON_NULL / LIST wrappers)."""
    while isinstance(type_ref, dict) and type_ref.get("ofType") and not type_ref.get("name"):
        type_ref = type_ref["ofType"]
    return type_ref if isinstance(type_ref, dict) else {}


def _type_has_list(type_ref: Any) -> bool:
    while isinstance(type_ref, dict):
        if type_ref.get("kind") == "LIST":
            return True
        type_ref = type_ref.get("ofType")
    return False


def _render_type(type_ref: dict[str, Any]) -> str:
    kind = type_ref.get("kind")
    if kind == "NON_NULL":
        return _render_type(type_ref.get("ofType") or {}) + "!"
    if kind == "LIST":
        return "[" + _render_type(type_ref.get("ofType") or {}) + "]"
    return str(type_ref.get("name") or "String")


def _fill_value(field_name: str, type_ref: dict[str, Any], values: dict[str, str]) -> Any:
    """Pick a value for a scalar arg/input field based on its name."""
    base = _unwrap_type(type_ref)
    if base.get("kind") != "SCALAR":
        return None
    lname = field_name.lower()
    value: Any = None
    if (lname == "id" or lname.endswith("id") or lname.endswith("ids")) and "id" in values:
        value = values["id"]
    elif "name" in lname and "name" in values:
        value = values["name"]
    if value is not None and _type_has_list(type_ref):
        value = [value]
    return value


def _contains_value(container: Any, needle: str) -> bool:
    if isinstance(container, dict):
        return any(_contains_value(v, needle) for v in container.values())
    if isinstance(container, list):
        return any(_contains_value(v, needle) for v in container)
    return container == needle


async def gql_execute_mutation(
    field: dict[str, Any],
    values: dict[str, str],
    require: tuple[str, ...],
    data: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Build and execute a mutation from its introspected signature.

    Fills id-like args/input fields with values["id"] and name-like ones with
    values["name"]. Safety: refuses to execute unless every semantic in
    `require` is actually bound into the variables (prevents e.g. running a
    no-arg deleteAll-style mutation).
    """
    declarations: list[str] = []
    arg_assignments: list[str] = []
    variables: dict[str, Any] = {}

    for index, arg in enumerate(field.get("args") or []):
        type_ref = arg.get("type") or {}
        base = _unwrap_type(type_ref)
        required = type_ref.get("kind") == "NON_NULL"
        value: Any = None
        if base.get("kind") == "INPUT_OBJECT":
            input_info = await gql_introspect_type(str(base.get("name")), data)
            input_obj: dict[str, Any] = {}
            fillable = True
            for input_field in (input_info or {}).get("inputFields") or []:
                iref = input_field.get("type") or {}
                ivalue = _fill_value(str(input_field.get("name") or ""), iref, values)
                if ivalue is not None:
                    input_obj[str(input_field["name"])] = ivalue
                elif iref.get("kind") == "NON_NULL":
                    fillable = False
            if not fillable:
                if required:
                    return False, {"skipped": f"required input field of {base.get('name')} not fillable"}
                continue
            if input_obj:
                value = [input_obj] if _type_has_list(type_ref) else input_obj
        else:
            value = _fill_value(str(arg.get("name") or ""), type_ref, values)
        if value is None:
            if required:
                return False, {"skipped": f"required arg {arg.get('name')} not fillable"}
            continue
        var_name = f"v{index}"
        declarations.append(f"${var_name}: {_render_type(type_ref)}")
        arg_assignments.append(f"{arg['name']}: ${var_name}")
        variables[var_name] = value

    for semantic in require:
        if semantic in values and not _contains_value(variables, values[semantic]):
            return False, {"skipped": f"safety: {semantic} value not bound to any argument"}

    return_base = _unwrap_type(field.get("type") or {})
    selection = " { __typename }" if return_base.get("kind") in ("OBJECT", "INTERFACE", "UNION") else ""
    declaration_str = f"({', '.join(declarations)})" if declarations else ""
    assignment_str = f"({', '.join(arg_assignments)})" if arg_assignments else ""
    query = f"mutation M{declaration_str} {{ {field['name']}{assignment_str}{selection} }}"

    st, payload = await alexa_graphql(query, variables, data)
    accepted = (
        st == 200 and isinstance(payload, dict)
        and not payload.get("errors") and bool(payload.get("data"))
    )
    return accepted, {"query": query, "status": st, "response": str(payload)[:300]}


async def gql_find_mutations(pattern: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    """All Mutation fields whose name matches the regex pattern."""
    mutation_type = await gql_introspect_type("Mutation", data)
    if not mutation_type:
        return []
    return [
        field for field in mutation_type.get("fields") or []
        if re.search(pattern, str(field.get("name") or ""), re.IGNORECASE)
    ]


async def graphql_find_endpoint(uuid: str, data: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Find a smart home endpoint in the GraphQL nexus API by its v3 UUID.

    Amazon is shutting down the legacy phoenix v2 API (GET /api/phoenix now
    answers 400 for migrated accounts); the GraphQL endpoints query is the
    replacement and exposes the legacy applianceId via legacyIdentifiers.
    Returns (endpoint_record_or_None, debug_info).
    """
    debug: dict[str, Any] = {}
    arn = uuid if uuid.startswith("amzn1.alexa.endpoint.") else f"amzn1.alexa.endpoint.{uuid}"
    for label, query in (("full", ENDPOINTS_QUERY_FULL), ("minimal", ENDPOINTS_QUERY_MINIMAL)):
        st, payload = await alexa_graphql(query, None, data)
        info: dict[str, Any] = {"status": st}
        if isinstance(payload, dict):
            if payload.get("errors"):
                info["errors"] = str(payload["errors"])[:300]
            if "raw" in payload:
                info["raw"] = payload["raw"][:200]
            items = (((payload.get("data") or {}).get("endpoints") or {}).get("items")) or []
            info["item_count"] = len(items)
            for item in items:
                if not isinstance(item, dict):
                    continue
                legacy = item.get("legacyIdentifiers") or {}
                chrs_entity = ((legacy.get("chrsIdentifier") or {}).get("entityId") or "").lower()
                endpoint_id = str(item.get("endpointId") or "")
                if endpoint_id == arn or chrs_entity == uuid.lower() or endpoint_id.lower().endswith(uuid.lower()):
                    debug[label] = info
                    return item, debug
        debug[label] = info
    return None, debug


def _walk_phoenix_appliances(value: Any, found: list[dict[str, Any]]) -> None:
    """Collect appliance records from the deeply nested /api/phoenix networkDetail.

    Several layers of that payload are stringified JSON, so strings that look
    like JSON are parsed and walked as well.
    """
    if isinstance(value, dict):
        if "applianceId" in value and (
            "entityId" in value or "applianceKey" in value or "friendlyName" in value
        ):
            found.append(value)
            return
        for item in value.values():
            _walk_phoenix_appliances(item, found)
    elif isinstance(value, list):
        for item in value:
            _walk_phoenix_appliances(item, found)
    elif isinstance(value, str) and value[:1] in ("{", "["):
        try:
            _walk_phoenix_appliances(json.loads(value), found)
        except (json.JSONDecodeError, RecursionError):
            pass


async def phoenix_find_appliance(uuid: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Look up the real Phoenix appliance record for a v3 entity UUID.

    Phoenix stores skill devices under its own applianceId (e.g.
    "SKILL_<base64>_<uuid>" or "AAA_..."), not under the bare behaviors UUID.
    GET /api/phoenix returns networkDetail with all appliances including their
    entityId — the only reliable way to map UUID -> deletable applianceId.
    """
    global _PHOENIX_UNAVAILABLE
    if _PHOENIX_UNAVAILABLE:
        return None
    st, body = await alexa_raw_get("/api/phoenix", data)
    if st != 200:
        if st in (400, 403, 404, 410):
            # Legacy phoenix v2 API is shut down for this account — stop
            # probing it on every request.
            _PHOENIX_UNAVAILABLE = True
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    found: list[dict[str, Any]] = []
    _walk_phoenix_appliances(payload, found)
    uuid_lower = uuid.lower()
    for appliance in found:
        entity_id = str(appliance.get("entityId") or "").lower()
        appliance_key = str(appliance.get("applianceKey") or "").lower()
        appliance_id = str(appliance.get("applianceId") or "")
        if uuid_lower in (entity_id, appliance_key) or uuid_lower in appliance_id.lower():
            return appliance
    return None


async def _v3_entity_gone(uuid: str, data: dict[str, Any]) -> bool:
    """True when the entity no longer appears in behaviors/entities."""
    try:
        payload = await alexa_get_json(
            "/api/behaviors/entities?skillId=amzn1.ask.1p.smarthome", data
        )
        items = _extract_smart_home_items(payload)
        return not any(item.get("id") == uuid for item in items)
    except Exception:
        return False


async def _v3_entity_named(uuid: str, new_name: str, data: dict[str, Any]) -> bool:
    """True when the entity now carries new_name in behaviors/entities."""
    try:
        payload = await alexa_get_json(
            "/api/behaviors/entities?skillId=amzn1.ask.1p.smarthome", data
        )
        items = _extract_smart_home_items(payload)
        return any(
            item.get("id") == uuid
            and new_name in (item.get("displayName"), item.get("friendlyName"))
            for item in items
        )
    except Exception:
        return False


async def delete_v3_entity_cookie(uuid: str, data: dict[str, Any]) -> dict[str, Any]:
    """Try all cookie-authenticated candidates to delete a v3 smart home entity.

    Returns a probe dict: keys are "METHOD path", values {"status", "body"}.
    "_winner" is set only after verifying the device is actually gone from
    behaviors/entities (phoenix endpoints return 200 as a silent no-op).
    """
    sid = quote(uuid, safe="")
    arn_raw = f"amzn1.alexa.endpoint.{uuid}"
    arn = quote(arn_raw, safe="")
    results: dict[str, Any] = {}

    # Fast path: replay the mutation that worked last time (cached in /data)
    # instead of walking the whole candidate ladder again.
    hint = read_hint("delete_winner")
    if isinstance(hint, dict) and hint.get("mutation"):
        fields = await gql_find_mutations(rf"^{re.escape(str(hint['mutation']))}$", data)
        if fields:
            if hint.get("id_kind") == "uuid":
                id_value = uuid
            elif hint.get("id_kind") == "endpoint":
                gql_hit, _ = await graphql_find_endpoint(uuid, data)
                id_value = str((gql_hit or {}).get("endpointId") or arn_raw)
            else:
                id_value = arn_raw
            accepted, info = await gql_execute_mutation(fields[0], {"id": id_value}, ("id",), data)
            key = f"GQL {hint['mutation']} [cached winner]"
            results[key] = info
            if accepted:
                gone = await _v3_entity_gone(uuid, data)
                info["verified_deleted"] = gone
                if gone:
                    results["_winner"] = key
                    return results

    candidates: list[tuple[str, str, bytes]] = []

    # Resolve the exact endpointId via the GraphQL nexus API.
    gql_endpoint, gql_debug = await graphql_find_endpoint(uuid, data)
    results["_graphql_lookup"] = gql_debug
    endpoint_id = arn_raw
    if gql_endpoint:
        endpoint_id = str(gql_endpoint.get("endpointId") or arn_raw)
        gql_debug["endpoint"] = {
            "endpointId": endpoint_id,
            "friendlyName": gql_endpoint.get("friendlyName"),
            "legacyIdentifiers": gql_endpoint.get("legacyIdentifiers"),
        }

    # Schema-driven GraphQL mutations: introspect Mutation, pick delete-ish
    # fields, build the call from the introspected argument types. Only
    # executed when the endpoint id is actually bound into the variables.
    delete_fields = await gql_find_mutations(
        r"(delete|forget|remove|unlink|deregister)", data
    )
    delete_fields = [
        f for f in delete_fields
        if re.search(r"endpoint|appliance|device|entity|smarthome", str(f.get("name") or ""), re.IGNORECASE)
    ][:6]
    results["_graphql_delete_mutations_found"] = [str(f.get("name")) for f in delete_fields]
    for field in delete_fields:
        for id_value in dict.fromkeys([endpoint_id, uuid]):
            accepted, info = await gql_execute_mutation(
                field, {"id": id_value}, ("id",), data
            )
            results[f"GQL {field['name']} [{id_value[:40]}]"] = info
            if accepted:
                gone = await _v3_entity_gone(uuid, data)
                info["verified_deleted"] = gone
                if gone:
                    results["_winner"] = f"GQL {field['name']}"
                    write_hint("delete_winner", {
                        "mutation": str(field["name"]),
                        "id_kind": "uuid" if id_value == uuid else "endpoint",
                    })
                    return results

    # Legacy path: GET /api/phoenix networkDetail (answers 400 on accounts
    # already migrated off phoenix v2 — kept for accounts where it still works).
    phoenix_appliance = await phoenix_find_appliance(uuid, data)
    if phoenix_appliance:
        phoenix_id = str(phoenix_appliance.get("applianceId") or "")
        results["_phoenix_lookup"] = {
            "applianceId": phoenix_id,
            "entityId": phoenix_appliance.get("entityId"),
            "friendlyName": phoenix_appliance.get("friendlyName"),
        }
        if phoenix_id:
            candidates.append(("DELETE", f"/api/phoenix/appliance/{quote(phoenix_id, safe='')}", b""))
    else:
        results["_phoenix_lookup"] = "no match (GET /api/phoenix unavailable or entityId not present)"

    # Note: DELETE /api/phoenix/appliance/{uuid} and /{arn} both return 200 as no-ops
    # for pure v3 entities — excluded from candidates.
    candidates += [
        # POST to smarthome with JSON body
        ("POST", f"/api/smarthome/v1/smart-home-devices/{sid}",
         json.dumps({"entityId": uuid, "entityType": "APPLIANCE"}).encode()),
        ("POST", f"/api/smarthome/v1/smart-home-devices/{arn}",
         json.dumps({"entityId": f"amzn1.alexa.endpoint.{uuid}", "entityType": "APPLIANCE"}).encode()),
        # Phoenix smarthome appliance POST with applianceId body
        ("POST", "/api/phoenix/smarthome/appliance [arn body]",
         json.dumps({"applianceId": f"amzn1.alexa.endpoint.{uuid}"}).encode()),
        ("POST", "/api/phoenix/smarthome/appliance [uuid body]",
         json.dumps({"applianceId": uuid}).encode()),
        # behaviors/entities DELETE + POST forget (ARN and bare UUID)
        ("DELETE", f"/api/behaviors/entities/{arn}", b""),
        ("POST", f"/api/behaviors/entities/{sid}/forget", b""),
        ("POST", f"/api/behaviors/entities/{arn}/forget", b""),
    ]

    for method, path, body in candidates:
        request_path = path.split(" [", 1)[0]
        if method == "DELETE":
            st, bd = await alexa_raw_delete(request_path, data)
        else:
            st, bd = await alexa_raw_post(request_path, body, data)
        key = f"{method} {path}"
        results[key] = {"status": st, "body": bd[:120]}
        if st in (200, 202, 204):
            # Verify device is actually gone — some endpoints return 200 as no-op
            try:
                payload = await alexa_get_json(
                    "/api/behaviors/entities?skillId=amzn1.ask.1p.smarthome", data
                )
                items = _extract_smart_home_items(payload)
                device_gone = not any(item.get("id") == uuid for item in items)
            except Exception:
                device_gone = False
            results[key]["verified_deleted"] = device_gone
            if device_gone:
                results["_winner"] = key
                return results

    return results


async def rename_smart_home_cookie(
    uuid: str, appliance_id: str, new_name: str, data: dict[str, Any]
) -> dict[str, Any]:
    """Try cookie-authenticated candidates to rename a smart home entity.

    Same strategy as delete_v3_entity_cookie: probe candidates in order and
    verify against behaviors/entities after each 2xx, because several Alexa
    endpoints answer 200 as a silent no-op. Returns a probe dict; "_winner"
    is set once the new name is confirmed.
    """
    sid = quote(uuid, safe="")
    arn_raw = uuid if uuid.startswith("amzn1.alexa.endpoint.") else f"amzn1.alexa.endpoint.{uuid}"
    arn = quote(arn_raw, safe="")
    results: dict[str, Any] = {}

    # Fast path: replay the rename mutation that worked last time.
    hint = read_hint("rename_winner")
    if isinstance(hint, dict) and hint.get("mutation"):
        fields = await gql_find_mutations(rf"^{re.escape(str(hint['mutation']))}$", data)
        if fields:
            if hint.get("id_kind") == "uuid":
                id_value = uuid
            else:
                gql_hit, _ = await graphql_find_endpoint(uuid, data)
                id_value = str((gql_hit or {}).get("endpointId") or arn_raw)
            accepted, info = await gql_execute_mutation(
                fields[0], {"id": id_value, "name": new_name}, ("id", "name"), data
            )
            key = f"GQL {hint['mutation']} [cached winner]"
            results[key] = info
            if accepted:
                renamed = await _v3_entity_named(uuid, new_name, data)
                info["verified_renamed"] = renamed
                if renamed:
                    results["_winner"] = key
                    return results

    candidates: list[tuple[str, str, bytes]] = []

    # Resolve the exact endpointId via the GraphQL nexus API.
    gql_endpoint, gql_debug = await graphql_find_endpoint(uuid, data)
    results["_graphql_lookup"] = gql_debug
    endpoint_id = str((gql_endpoint or {}).get("endpointId") or "") or arn_raw
    if gql_endpoint:
        gql_debug["endpoint"] = {
            "endpointId": endpoint_id,
            "friendlyName": gql_endpoint.get("friendlyName"),
            "legacyIdentifiers": gql_endpoint.get("legacyIdentifiers"),
        }

    # Schema-driven GraphQL rename mutations: only executed when BOTH the
    # endpoint id and the new name are bound into the variables.
    rename_fields = await gql_find_mutations(
        r"rename|friendlyname|((set|update|change).*(name|endpoint|appliance))", data
    )
    rename_fields = rename_fields[:6]
    results["_graphql_rename_mutations_found"] = [str(f.get("name")) for f in rename_fields]
    for field in rename_fields:
        accepted, info = await gql_execute_mutation(
            field, {"id": endpoint_id, "name": new_name}, ("id", "name"), data
        )
        results[f"GQL {field['name']}"] = info
        if accepted:
            renamed = await _v3_entity_named(uuid, new_name, data)
            info["verified_renamed"] = renamed
            if renamed:
                results["_winner"] = f"GQL {field['name']}"
                write_hint("rename_winner", {
                    "mutation": str(field["name"]),
                    "id_kind": "endpoint",
                })
                return results

    # Legacy path: GET /api/phoenix networkDetail (400 on migrated accounts)
    phoenix_appliance = await phoenix_find_appliance(uuid, data)
    if phoenix_appliance:
        phoenix_id = str(phoenix_appliance.get("applianceId") or "")
        results["_phoenix_lookup"] = {
            "applianceId": phoenix_id,
            "friendlyName": phoenix_appliance.get("friendlyName"),
        }
        if phoenix_id:
            pid = quote(phoenix_id, safe="")
            renamed_record = dict(phoenix_appliance)
            renamed_record["friendlyName"] = new_name
            candidates += [
                ("PUT", f"/api/phoenix/appliance/{pid} [simple body]",
                 json.dumps({"applianceId": phoenix_id, "friendlyName": new_name}).encode()),
                ("PUT", f"/api/phoenix/appliance/{pid} [full record]",
                 json.dumps(renamed_record).encode()),
            ]

    candidates += [
        ("PUT", f"/api/phoenix/appliance/{arn}",
         json.dumps({"applianceId": arn_raw, "friendlyName": new_name}).encode()),
        ("PUT", f"/api/behaviors/entities/{sid}",
         json.dumps({"friendlyName": new_name, "displayName": new_name}).encode()),
        ("PUT", f"/api/behaviors/entities/{arn}",
         json.dumps({"friendlyName": new_name, "displayName": new_name}).encode()),
    ]
    if appliance_id and appliance_id not in (uuid, arn_raw):
        # v2 Phoenix device with legacy applianceId (AAA_...)
        candidates.insert(0, (
            "PUT", f"/api/phoenix/appliance/{quote(appliance_id, safe='')}",
            json.dumps({"applianceId": appliance_id, "friendlyName": new_name}).encode(),
        ))

    for method, path, body in candidates:
        request_path = path.split(" [", 1)[0]
        if method == "POST":
            st, bd = await alexa_raw_post(request_path, body, data)
        else:
            st, bd = await alexa_raw_put(request_path, body, data)
        key = f"{method} {path}"
        results[key] = {"status": st, "body": bd[:120]}
        if st in (200, 202, 204):
            try:
                payload = await alexa_get_json(
                    "/api/behaviors/entities?skillId=amzn1.ask.1p.smarthome", data
                )
                items = _extract_smart_home_items(payload)
                renamed = any(
                    item.get("id") == uuid
                    and new_name in (item.get("displayName"), item.get("friendlyName"))
                    for item in items
                )
            except Exception:
                renamed = False
            results[key]["verified_renamed"] = renamed
            if renamed:
                results["_winner"] = key
                return results

    return results


async def alexa_get_json(path: str, data: dict[str, Any]) -> Any:
    if not is_configured():
        raise web.HTTPUnauthorized(text="Alexa session missing")
    base = data.get("websiteApiUrl", "https://alexa.amazon.com").rstrip("/")
    async with aiohttp.ClientSession() as session:
        async with session.get(base + path, headers=alexa_headers(data), allow_redirects=False) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise web.HTTPBadGateway(text=f"Alexa API failed ({resp.status}): {text[:300]}")
            return json.loads(text)


def _normalize_capabilities(raw: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("capabilities", "supportedOperations", "actions", "interfaces"):
        current = raw.get(key)
        if isinstance(current, list):
            for item in current:
                if isinstance(item, str) and item:
                    values.append(item)
                elif isinstance(item, dict):
                    name = item.get("interface") or item.get("name") or item.get("type")
                    if isinstance(name, str) and name:
                        values.append(name)
    return sorted(set(values))


def _extract_smart_home_items(payload: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for entry in value:
                walk(entry)
            return
        if not isinstance(value, dict):
            return
        legacy = value.get("legacyAppliance") if isinstance(value.get("legacyAppliance"), dict) else {}
        entity_id = (
            value.get("entityId") or value.get("applianceId")
            or value.get("id") or legacy.get("applianceId")
        )
        name = (
            value.get("friendlyName") or value.get("name")
            or value.get("displayName") or value.get("applianceName")
            or legacy.get("friendlyName")
        )
        if entity_id and name:
            items.append(value)
            return
        for key in ("entities", "appliances", "devices", "items", "nodes", "payload"):
            if key in value:
                walk(value[key])

    walk(payload)
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        legacy = item.get("legacyAppliance") if isinstance(item.get("legacyAppliance"), dict) else {}
        key = str(
            item.get("entityId") or item.get("applianceId")
            or item.get("id") or legacy.get("applianceId")
        )
        deduped[key] = item
    return list(deduped.values())


def _normalize_echo_device(raw: dict[str, Any]) -> dict[str, Any]:
    serial = str(raw.get("serialNumber") or raw.get("deviceSerialNumber") or "")
    name = (
        raw.get("accountName") or raw.get("deviceAccountName")
        or raw.get("deviceTypeFriendlyName") or serial or "Unbekanntes Gerät"
    )
    return {
        "name": str(name),
        "serial": serial,
        "type": str(raw.get("deviceType") or "ECHO_DEVICE"),
        "family": str(raw.get("deviceFamily") or "ECHO"),
        "skill": "",
        "online": bool(raw.get("online", raw.get("isOnline", False))),
        "firmware": str(raw.get("softwareVersion") or ""),
        "capabilities": _normalize_capabilities(raw),
        "room": "",
        "source": "echo",
        "raw": raw,
    }


def _normalize_smart_home_device(raw: dict[str, Any]) -> dict[str, Any]:
    legacy = raw.get("legacyAppliance") if isinstance(raw.get("legacyAppliance"), dict) else {}
    details = raw.get("additionalApplianceDetails") if isinstance(raw.get("additionalApplianceDetails"), dict) else {}
    provider_data = raw.get("providerData") if isinstance(raw.get("providerData"), dict) else {}
    icon = raw.get("icon") if isinstance(raw.get("icon"), dict) else {}
    display_categories = raw.get("displayCategories")
    category = display_categories[0] if isinstance(display_categories, list) and display_categories else None

    device_id = (
        raw.get("id") or raw.get("entityId") or raw.get("applianceId")
        or legacy.get("applianceId") or ""
    )
    name = (
        raw.get("displayName") or raw.get("friendlyName") or raw.get("name")
        or raw.get("applianceName") or legacy.get("friendlyName")
        or device_id or "Unbekanntes Gerät"
    )
    device_type = (
        provider_data.get("deviceType") or icon.get("value")
        or raw.get("entityType") or raw.get("applianceType") or category
        or raw.get("deviceType") or legacy.get("applianceType") or "SMART_HOME"
    )

    # description format: "entity_id via Skill Name"
    description = str(raw.get("description") or "")
    if " via " in description:
        entity_id, _, skill = description.partition(" via ")
        skill = skill.strip()
        manufacturer = entity_id.strip()
    else:
        skill = (
            raw.get("skillName") or raw.get("providerName")
            or legacy.get("skillName") or ""
        )
        manufacturer = (
            raw.get("manufacturerName") or legacy.get("manufacturerName")
            or details.get("manufacturer") or ""
        )

    room = (
        raw.get("roomName") or raw.get("location") or raw.get("groupName")
        or details.get("roomName") or ""
    )
    online = (
        raw.get("availability") == "AVAILABLE"
        or bool(raw.get("isReachable", raw.get("reachable", raw.get("online", False))))
    )
    # Phoenix API needs the legacy applianceId, not the behaviors entityId
    appliance_id = str(legacy.get("applianceId") or raw.get("applianceId") or device_id)
    return {
        "name": str(name),
        "serial": str(device_id),
        "appliance_id": appliance_id,
        "type": str(device_type),
        "family": str(manufacturer),
        "skill": str(skill),
        "online": online,
        "firmware": str(raw.get("softwareVersion") or raw.get("version") or ""),
        "capabilities": _normalize_capabilities(raw),
        "room": str(room),
        "source": "smart_home",
        "raw": raw,
    }


async def _fetch_devices_from_alexa(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch + normalize the full device list from Alexa. Returns (devices, errors)."""
    devices_by_key: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    try:
        payload = await alexa_get_json("/api/devices-v2/device?cached=true", data)
        for raw in (payload.get("devices") if isinstance(payload, dict) else []) or []:
            if isinstance(raw, dict):
                device = _normalize_echo_device(raw)
                devices_by_key[f"echo:{device['serial']}"] = device
    except web.HTTPException as exc:
        errors.append(f"Echo-Geräte: {exc.reason}")
    except Exception as exc:
        errors.append(f"Echo-Geräte: {exc}")

    try:
        payload = await alexa_get_json("/api/behaviors/entities?skillId=amzn1.ask.1p.smarthome", data)
        for raw in _extract_smart_home_items(payload):
            device = _normalize_smart_home_device(raw)
            devices_by_key[f"smart_home:{device['serial']}"] = device
    except web.HTTPException as exc:
        errors.append(f"Smart-Home-Geräte: {exc.reason}")
    except Exception as exc:
        errors.append(f"Smart-Home-Geräte: {exc}")

    device_list = sorted(devices_by_key.values(), key=lambda d: d.get("name", "").lower())
    return device_list, errors


# ---------------------------------------------------------------------------
# Devices cache (stale-while-revalidate): the add-on keeps the device list in
# memory (+ on disk), serves it instantly and refreshes it in the background.

_DEVICES_CACHE: dict[str, Any] = {}
_DEVICES_REFRESH_LOCK = asyncio.Lock()


def _load_devices_cache() -> None:
    if _DEVICES_CACHE:
        return
    stored = read_json(DEVICES_CACHE_PATH)
    if isinstance(stored.get("devices"), list):
        _DEVICES_CACHE.update({
            "devices": stored["devices"],
            "updated_at": stored.get("updated_at", 0),
            "warnings": stored.get("warnings", []),
        })


def _persist_devices_cache() -> None:
    try:
        DEVICES_CACHE_PATH.write_text(json.dumps({
            "devices": _DEVICES_CACHE.get("devices", []),
            "updated_at": _DEVICES_CACHE.get("updated_at", 0),
            "warnings": _DEVICES_CACHE.get("warnings", []),
        }), encoding="utf-8")
    except OSError:
        pass


async def refresh_devices_cache() -> dict[str, Any]:
    """Fetch fresh devices from Alexa and update the cache. Serialized by a lock."""
    async with _DEVICES_REFRESH_LOCK:
        if not is_configured():
            return _DEVICES_CACHE
        data = session_data()
        device_list, errors = await _fetch_devices_from_alexa(data)
        # Don't overwrite a good cache with an empty list caused by a transient
        # API error (e.g. session hiccup) — keep the previous devices instead.
        if not device_list and errors and _DEVICES_CACHE.get("devices"):
            _DEVICES_CACHE["warnings"] = errors
            _DEVICES_CACHE["last_error_at"] = time.time()
            return _DEVICES_CACHE
        _DEVICES_CACHE["devices"] = device_list
        _DEVICES_CACHE["warnings"] = errors
        _DEVICES_CACHE["updated_at"] = time.time()
        _persist_devices_cache()
        return _DEVICES_CACHE


def _remove_from_cache(serials: list[str]) -> None:
    if not serials or not _DEVICES_CACHE.get("devices"):
        return
    gone = set(serials)
    _DEVICES_CACHE["devices"] = [
        d for d in _DEVICES_CACHE["devices"] if d.get("serial") not in gone
    ]
    _DEVICES_CACHE["updated_at"] = time.time()
    _persist_devices_cache()


def _rename_in_cache(serial: str, new_name: str) -> None:
    for d in _DEVICES_CACHE.get("devices", []):
        if d.get("serial") == serial:
            d["name"] = new_name
            _DEVICES_CACHE["updated_at"] = time.time()
            _persist_devices_cache()
            return


async def devices(request: web.Request) -> web.Response:
    if not is_configured():
        return web.json_response({"devices": [], "demo": False, "source": "not_connected", "warning": "Alexa-Web-Session fehlt. Bitte Alexa verbinden."})

    _load_devices_cache()
    force = request.rel_url.query.get("refresh") == "1"
    age = time.time() - _DEVICES_CACHE.get("updated_at", 0)
    has_cache = bool(_DEVICES_CACHE.get("devices")) or _DEVICES_CACHE.get("updated_at")

    if force or not has_cache:
        # No cache yet (first ever open) or explicit refresh: fetch synchronously.
        await refresh_devices_cache()
    elif age > DEVICES_CACHE_TTL and not _DEVICES_REFRESH_LOCK.locked():
        # Serve stale immediately, refresh in the background.
        asyncio.get_event_loop().create_task(refresh_devices_cache())

    result: dict[str, Any] = {
        "devices": _DEVICES_CACHE.get("devices", []),
        "demo": False,
        "source": "alexa_web",
        "cached": True,
        "updated_at": _DEVICES_CACHE.get("updated_at", 0),
    }
    if _DEVICES_CACHE.get("warnings"):
        result["warnings"] = _DEVICES_CACHE["warnings"]
    return web.json_response(result)


async def token_refresh_status(request: web.Request) -> web.Response:
    return web.json_response({"auto_refresh_active": False, "has_valid_token": is_configured(), "last_error": None})


async def _delete_target(target: dict[str, Any], data: dict[str, Any]) -> None:
    """Delete a single device; raises on failure."""
    serial = str(target.get("serial", "")).strip()
    source = str(target.get("source", "")).strip()
    if not serial:
        raise RuntimeError("Missing serial")
    if source == "echo":
        await alexa_delete(f"/api/devices-v2/device/{quote(serial, safe='')}", data)
        return
    appliance_id = str(target.get("appliance_id", "")).strip()
    if appliance_id and appliance_id != serial:
        # v2 Phoenix device — use the legacy applianceId format (AAA_...)
        await alexa_delete(f"/api/phoenix/appliance/{quote(appliance_id, safe='')}", data)
        return
    # Pure v3 entity (e.g. openHAB3/Home Assistant skill) — no legacy id.
    probe = await delete_v3_entity_cookie(serial, data)
    if "_winner" not in probe:
        raise RuntimeError(f"No delete candidate succeeded for v3 entity {serial!r}. Probe: {probe}")


async def delete_devices(request: web.Request) -> web.Response:
    if not is_configured():
        raise web.HTTPUnauthorized(text="Alexa session missing")
    data = session_data()
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON body")
    targets = body.get("devices", [])
    if not isinstance(targets, list) or not targets:
        raise web.HTTPBadRequest(text="devices list required")

    results: list[dict[str, Any]] = []
    for target in targets:
        serial = str(target.get("serial", "")).strip()
        name = str(target.get("name", "")).strip() or serial
        try:
            await _delete_target(target, data)
            _remove_from_cache([serial])
            results.append({"serial": serial, "name": name, "ok": True})
        except Exception as exc:
            results.append({"serial": serial, "name": name, "ok": False, "error": str(exc)})

    return web.json_response({"results": results})


# ---------------------------------------------------------------------------
# Server-side bulk delete job: survives page navigation — the browser only
# starts the job and polls its status.

_DELETE_JOB: dict[str, Any] = {}
_DELETE_JOB_TASK: asyncio.Task | None = None


def _persist_delete_job() -> None:
    try:
        DELETE_JOB_PATH.write_text(json.dumps(_DELETE_JOB), encoding="utf-8")
    except OSError:
        pass


async def _run_delete_job(targets: list[dict[str, Any]], data: dict[str, Any]) -> None:
    job = _DELETE_JOB
    try:
        for target in targets:
            if job.get("cancel"):
                job["aborted"] = True
                break
            serial = str(target.get("serial") or "")
            name = str(target.get("name") or serial)
            job["current"] = name
            job["current_serial"] = serial
            try:
                await _delete_target(target, data)
                job["ok"] += 1
                job["deleted"].append({"serial": serial, "name": name})
                _remove_from_cache([serial])
            except Exception as exc:
                job["failed"].append({"serial": serial, "name": name, "error": str(exc)[:500]})
            job["done"] += 1
            _persist_delete_job()
    finally:
        job["running"] = False
        job["current"] = None
        job["current_serial"] = None
        job["finished_at"] = time.time()
        _persist_delete_job()


async def delete_job_start(request: web.Request) -> web.Response:
    global _DELETE_JOB_TASK
    if not is_configured():
        raise web.HTTPUnauthorized(text="Alexa session missing")
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON body")
    targets = body.get("devices", [])
    if not isinstance(targets, list) or not targets:
        raise web.HTTPBadRequest(text="devices list required")
    if _DELETE_JOB.get("running"):
        return web.json_response({"error": "Es läuft bereits ein Löschvorgang."}, status=409)

    data = session_data()
    _DELETE_JOB.clear()
    _DELETE_JOB.update({
        "running": True,
        "cancel": False,
        "aborted": False,
        "total": len(targets),
        "done": 0,
        "ok": 0,
        "failed": [],
        "deleted": [],
        "current": None,
        "started_at": time.time(),
        "finished_at": None,
    })
    _persist_delete_job()
    _DELETE_JOB_TASK = asyncio.get_event_loop().create_task(_run_delete_job(list(targets), data))
    return web.json_response({"started": True, "total": len(targets)})


async def delete_job_status(request: web.Request) -> web.Response:
    if _DELETE_JOB:
        return web.json_response(_DELETE_JOB)
    stored = read_json(DELETE_JOB_PATH)
    if stored.get("running"):
        # Persisted as running but no in-memory job: the add-on restarted
        # mid-job — report it as interrupted, not still running.
        stored["running"] = False
        stored["interrupted"] = True
    return web.json_response(stored)


async def delete_job_cancel(request: web.Request) -> web.Response:
    if not _DELETE_JOB.get("running"):
        return web.json_response({"ok": False, "error": "Kein laufender Löschvorgang."})
    _DELETE_JOB["cancel"] = True
    return web.json_response({"ok": True})


async def rename_devices(request: web.Request) -> web.Response:
    if not is_configured():
        raise web.HTTPUnauthorized(text="Alexa session missing")
    data = session_data()
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON body")
    targets = body.get("devices", [])
    if not isinstance(targets, list) or not targets:
        raise web.HTTPBadRequest(text="devices list required")

    results: list[dict[str, Any]] = []
    for target in targets:
        serial = str(target.get("serial", "")).strip()
        source = str(target.get("source", "")).strip()
        new_name = str(target.get("new_name", "")).strip()
        old_name = str(target.get("name", "")).strip() or serial
        if not serial or not new_name:
            results.append({
                "serial": serial, "name": old_name, "ok": False,
                "error": "serial und new_name erforderlich",
            })
            continue
        try:
            if source == "echo":
                device_type = str(target.get("device_type", "")).strip()
                if not device_type:
                    raise RuntimeError("device_type fehlt für Echo-Gerät")
                payload = json.dumps({
                    "serialNumber": serial,
                    "deviceType": device_type,
                    "accountName": new_name,
                }).encode()
                st, bd = await alexa_raw_put(
                    f"/api/devices-v2/device/{quote(serial, safe='')}", payload, data
                )
                if st not in (200, 202, 204):
                    raise RuntimeError(f"HTTP {st}: {bd[:200]}")
            else:
                appliance_id = str(target.get("appliance_id", "")).strip()
                probe = await rename_smart_home_cookie(serial, appliance_id, new_name, data)
                if "_winner" not in probe:
                    raise RuntimeError(
                        "Umbenennen über die Alexa-Web-API nicht bestätigt. "
                        "Skill-verwaltete Geräte bitte in der Quelle (z.B. openHAB, "
                        f"Home Assistant) umbenennen. Probe: {probe}"
                    )
            _rename_in_cache(serial, new_name)
            results.append({"serial": serial, "name": old_name, "new_name": new_name, "ok": True})
        except Exception as exc:
            results.append({"serial": serial, "name": old_name, "ok": False, "error": str(exc)})

    return web.json_response({"results": results})


async def devices_debug(request: web.Request) -> web.Response:
    """Return raw API payloads + extracted ID fields to diagnose delete issues."""
    if not is_configured():
        raise web.HTTPUnauthorized(text="Not configured")
    data = session_data()
    result: dict[str, Any] = {}
    try:
        payload = await alexa_get_json("/api/behaviors/entities?skillId=amzn1.ask.1p.smarthome", data)
        items = _extract_smart_home_items(payload)
        result["smart_home_total"] = len(items)
        result["smart_home_id_fields"] = [
            {
                "displayName": (item.get("displayName") or item.get("friendlyName") or "")[:60],
                "id": item.get("id"),
                "entityId": item.get("entityId"),
                "applianceId": item.get("applianceId"),
                "legacy_applianceId": (item.get("legacyAppliance") or {}).get("applianceId"),
                "description": (item.get("description") or "")[:80],
            }
            for item in items[:5]
        ]
        result["smart_home_raw_sample"] = items[:3]
    except Exception as exc:
        result["smart_home_error"] = str(exc)
    return web.json_response(result)


async def delete_probe(request: web.Request) -> web.Response:
    """Diagnostic: find the right delete endpoint by probing multiple API formats."""
    if not is_configured():
        raise web.HTTPUnauthorized(text="Not configured")
    data = session_data()
    device_id = request.rel_url.query.get("id", "").strip()
    if not device_id:
        raise web.HTTPBadRequest(text="?id= required")

    sid = quote(device_id, safe='')
    result: dict[str, Any] = {"id": device_id}

    # 1. Raw device data from behaviors/entities (all fields, not just known ones)
    try:
        payload = await alexa_get_json("/api/behaviors/entities?skillId=amzn1.ask.1p.smarthome", data)
        items = _extract_smart_home_items(payload)
        raw_item = next((item for item in items if item.get("id") == device_id), None)
        if raw_item:
            legacy = raw_item.get("legacyAppliance") if isinstance(raw_item.get("legacyAppliance"), dict) else {}
            result["behaviors_raw_keys"] = list(raw_item.keys())
            result["behaviors_key_values"] = {
                k: str(v)[:120] for k, v in raw_item.items()
                if v is not None and k not in ("capabilities", "connections", "relationships", "displayCategories")
            }
            result["legacy_appliance_keys"] = list(legacy.keys()) if legacy else []
            result["legacy_key_values"] = {k: str(v)[:120] for k, v in legacy.items() if v is not None}
        else:
            result["behaviors_raw_keys"] = "device not found in behaviors/entities"
    except Exception as exc:
        result["behaviors_error"] = str(exc)

    # 1b. GraphQL nexus lookup — modern replacement for the phoenix v2 API
    try:
        gql_endpoint, gql_debug = await graphql_find_endpoint(device_id, data)
        result["graphql_lookup"] = gql_debug
        if gql_endpoint:
            result["graphql_endpoint"] = {
                "endpointId": gql_endpoint.get("endpointId"),
                "friendlyName": gql_endpoint.get("friendlyName"),
                "legacyIdentifiers": gql_endpoint.get("legacyIdentifiers"),
            }
    except Exception as exc:
        result["graphql_lookup_error"] = str(exc)

    # 1c. GraphQL schema discovery — which mutations/fields actually exist
    try:
        mutation_type = await gql_introspect_type("Mutation", data)
        if mutation_type:
            names = sorted(str(f.get("name") or "") for f in mutation_type.get("fields") or [])
            result["graphql_mutation_count"] = len(names)
            result["graphql_mutations_device_related"] = [
                n for n in names
                if re.search(r"endpoint|appliance|device|entity|smart|name", n, re.IGNORECASE)
            ][:60]
        else:
            result["graphql_mutation_introspection"] = "unavailable (introspection disabled or error)"
        for type_name, key in (("LegacyIdentifiers", "graphql_legacy_identifiers_fields"),
                               ("Endpoint", "graphql_endpoint_fields")):
            type_info = await gql_introspect_type(type_name, data)
            if type_info:
                result[key] = [str(f.get("name")) for f in (type_info.get("fields") or [])][:60]
    except Exception as exc:
        result["graphql_introspection_error"] = str(exc)

    # 1d. Phoenix networkDetail lookup — the real applianceId phoenix uses
    try:
        appliance = await phoenix_find_appliance(device_id, data)
        result["phoenix_network_lookup"] = (
            {k: str(v)[:150] for k, v in appliance.items() if not isinstance(v, (dict, list))}
            if appliance else "not found in GET /api/phoenix networkDetail"
        )
    except Exception as exc:
        result["phoenix_network_lookup_error"] = str(exc)

    # 2. GET probes on multiple URL formats — find which one phoenix recognises
    arns = [
        f"/api/phoenix/appliance/{sid}",
        f"/api/phoenix/appliance/amzn1.alexa.endpoint.{sid}",
        f"/api/smarthome/appliance/{sid}",
    ]
    result["get_probes"] = {}
    for path in arns:
        status, body = await alexa_raw_get(path, data)
        result["get_probes"][path] = {"status": status, "body": body[:200]}

    # 3. GET /api/phoenix/appliance (list all) — shows ID format phoenix actually uses
    list_status, list_body = await alexa_raw_get("/api/phoenix/appliance", data)
    result["phoenix_list_status"] = list_status
    try:
        parsed = json.loads(list_body)
        entries = parsed if isinstance(parsed, list) else parsed.get("entities", parsed.get("appliances", []))
        result["phoenix_list_sample"] = [
            {k: v for k, v in (e.items() if isinstance(e, dict) else {}) if k in ("id", "entityId", "applianceId", "friendlyName", "displayName")}
            for e in (entries[:3] if isinstance(entries, list) else [])
        ]
    except Exception:
        result["phoenix_list_body_raw"] = list_body[:300]

    # 4. GET probes on v3 candidate endpoints
    v3_candidates = [
        f"/api/phoenix/entity/{sid}",
        f"/api/smarthome/v2/entities/{sid}",
        f"/api/smarthome/v1/presentation/entities/{sid}",
        f"/api/phoenix/registration/{sid}",
        f"/api/behaviors/entities/{sid}",
        f"/api/smarthome/v1/smart-home-devices/{sid}",
        f"/api/phoenix/smarthome/appliance/{sid}",
    ]
    result["v3_get_probes"] = {}
    for path in v3_candidates:
        status, body = await alexa_raw_get(path, data)
        result["v3_get_probes"][path] = {"status": status, "body": body[:200]}

    # 5. DELETE probes (only when ?delete=1 is passed)
    if request.rel_url.query.get("delete") == "1":
        # Cookie-authenticated multi-candidate delete (works for v3 entities like openHAB3)
        cookie_variants = await delete_v3_entity_cookie(device_id, data)
        result["cookie_delete_variants"] = cookie_variants
        result["delete_ok"] = "_winner" in cookie_variants

        # Check whether device still exists in behaviors/entities after all attempts
        try:
            payload2 = await alexa_get_json("/api/behaviors/entities?skillId=amzn1.ask.1p.smarthome", data)
            items2 = _extract_smart_home_items(payload2)
            result["device_still_exists_after_delete"] = any(item.get("id") == device_id for item in items2)
            result["total_devices_after_delete"] = len(items2)
        except Exception as exc:
            result["post_delete_check_error"] = str(exc)

    return web.json_response(result)


async def debug_ui(request: web.Request) -> web.Response:
    ingress_path = request.headers.get("X-Ingress-Path", "").rstrip("/")
    endpoints = [
        ("/api/app-info",             "App-Info"),
        ("/api/config-status",        "Config-Status"),
        ("/api/auth-session",         "Session"),
        ("/api/token-refresh-status", "Token-Refresh"),
        ("/api/devices",              "Geräteliste"),
        ("/api/devices-debug",        "Geräte Rohdaten"),
    ]
    buttons = "\n".join(
        f'<button onclick="load(\'{ingress_path}{ep}\', this)">'
        f'<span class="btn-label">{label}</span>'
        f'<span class="btn-ep">{ep}</span>'
        f'</button>'
        for ep, label in endpoints
    )
    buttons += f"""
<button onclick="probeDelete('{ingress_path}', false)" style="background:#fff5f5;border-color:#e17055;">
  <span class="btn-label">🔬 Delete-Probe (GET)</span>
  <span class="btn-ep">/api/delete-probe?id=...</span>
</button>
<button onclick="probeDelete('{ingress_path}', true)" style="background:#ffe0e0;border-color:#c0392b;color:#7b241c;">
  <span class="btn-label">💥 Delete-Probe (DELETE!)</span>
  <span class="btn-ep">/api/delete-probe?id=...&amp;delete=1</span>
</button>"""
    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Debug – Alexa Device Management</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: system-ui, sans-serif; background: #f5f6fa; color: #2d3436;
           display: flex; flex-direction: column; height: 100vh; overflow: hidden; }}

    /* Top bar */
    .top-bar {{ background: #fff; border-bottom: 1px solid #e0e0e0;
                padding: 10px 14px; display: flex; align-items: center;
                justify-content: space-between; gap: 10px; flex-shrink: 0; }}
    .top-bar h2 {{ font-size: 14px; color: #636e72; white-space: nowrap; }}
    .top-bar a {{ font-size: 13px; color: #00caff; text-decoration: none; white-space: nowrap; }}

    /* Endpoint buttons */
    .ep-grid {{ display: flex; flex-wrap: wrap; gap: 8px; padding: 10px 14px;
                background: #fff; border-bottom: 1px solid #e0e0e0; flex-shrink: 0; }}
    .ep-grid button {{
      border: 1px solid #dfe6e9; border-radius: 8px; padding: 8px 12px;
      background: #f8f9fa; cursor: pointer; text-align: left; transition: background .15s;
      display: flex; flex-direction: column; gap: 2px;
    }}
    .btn-label {{ font-size: 13px; font-weight: 600; color: #2d3436; }}
    .btn-ep {{ font-size: 10px; color: #636e72; word-break: break-all; }}
    .ep-grid button:hover {{ background: #e8f4fd; border-color: #00caff; }}
    .ep-grid button.active {{ background: #e8f4fd; border-color: #00caff; }}
    .ep-grid button.active .btn-label {{ color: #0098c8; }}

    /* Action bar */
    .action-bar {{ padding: 8px 14px; background: #f8f9fa; border-bottom: 1px solid #e0e0e0;
                   display: flex; align-items: center; gap: 8px; flex-wrap: wrap; flex-shrink: 0; }}
    .action-bar code {{ font-size: 11px; color: #636e72; flex: 1; min-width: 0;
                        overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .action-bar button {{
      border: none; border-radius: 6px; padding: 6px 14px; cursor: pointer;
      font-size: 12px; font-weight: 600; white-space: nowrap;
    }}
    #btn-reload {{ background: #dfe6e9; color: #2d3436; }}
    #btn-copy   {{ background: #00caff; color: #fff; }}
    #btn-copy.copied {{ background: #27ae60; }}

    /* Output */
    #output {{ flex: 1; overflow: auto; padding: 14px; -webkit-overflow-scrolling: touch; }}
    pre {{ font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-all; }}
    .loading {{ color: #636e72; font-style: italic; }}
    .error   {{ color: #c0392b; }}
    .key  {{ color: #2980b9; }}
    .str  {{ color: #27ae60; }}
    .num  {{ color: #e67e22; }}
    .bool {{ color: #8e44ad; }}
    .null {{ color: #95a5a6; }}
  </style>
</head>
<body>
  <div class="top-bar">
    <h2>🛠 Debug-Endpunkte</h2>
    <a href="{ingress_path}/">← Zurück zur App</a>
  </div>

  <div class="ep-grid">
    {buttons}
  </div>

  <div class="action-bar">
    <code id="current-url">Endpunkt auswählen…</code>
    <button id="btn-reload" onclick="reload()">↻ Laden</button>
    <button id="btn-copy"   onclick="copyOutput()">📋 Kopieren</button>
  </div>

  <div id="output"><pre class="loading">Endpunkt oben auswählen…</pre></div>

  <script>
    let currentUrl = null;
    let rawJson = null;

    function syntaxHL(json) {{
      return JSON.stringify(json, null, 2)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/("(\\u[a-fA-F0-9]{{4}}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, m => {{
          if (/^"/.test(m)) return /:$/.test(m) ? `<span class="key">${{m}}</span>` : `<span class="str">${{m}}</span>`;
          if (/true|false/.test(m)) return `<span class="bool">${{m}}</span>`;
          if (/null/.test(m)) return `<span class="null">${{m}}</span>`;
          return `<span class="num">${{m}}</span>`;
        }});
    }}

    async function load(url, btn) {{
      currentUrl = url;
      rawJson = null;
      document.getElementById('current-url').textContent = url;
      document.querySelectorAll('.ep-grid button').forEach(b => b.classList.remove('active'));
      if (btn) btn.classList.add('active');
      const out = document.getElementById('output');
      out.innerHTML = '<pre class="loading">Lade…</pre>';
      try {{
        const resp = await fetch(url);
        const text = await resp.text();
        let json;
        try {{ json = JSON.parse(text); rawJson = text; }} catch {{ json = null; }}
        if (json !== null) {{
          out.innerHTML = '<pre>' + syntaxHL(json) + '</pre>';
        }} else {{
          rawJson = text;
          out.innerHTML = '<pre class="error">Kein JSON:\\n' + text.replace(/</g,'&lt;') + '</pre>';
        }}
      }} catch(e) {{
        out.innerHTML = '<pre class="error">Fehler: ' + e.message + '</pre>';
      }}
    }}

    function reload() {{
      const active = document.querySelector('.ep-grid button.active');
      if (currentUrl) load(currentUrl, active);
    }}

    async function probeDelete(ingressPath, withDelete) {{
      const id = prompt('Geräte-UUID aus der Geräteliste (data-serial) eingeben:');
      if (!id) return;
      const trimmed = id.trim();
      const url = ingressPath + '/api/delete-probe?id=' + encodeURIComponent(trimmed) + (withDelete ? '&delete=1' : '');
      load(url, null);
    }}

    async function copyOutput() {{
      if (!rawJson) return;
      try {{
        await navigator.clipboard.writeText(rawJson);
        const btn = document.getElementById('btn-copy');
        btn.textContent = '✓ Kopiert';
        btn.classList.add('copied');
        setTimeout(() => {{ btn.textContent = '📋 Kopieren'; btn.classList.remove('copied'); }}, 2000);
      }} catch(e) {{
        alert('Kopieren fehlgeschlagen: ' + e.message);
      }}
    }}
  </script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


async def _periodic_device_refresh() -> None:
    """Warm the cache on startup and refresh it periodically in the background."""
    _load_devices_cache()
    # Initial warm-up so the very first page open is instant.
    if is_configured():
        try:
            await refresh_devices_cache()
        except Exception:
            pass
    while True:
        try:
            await asyncio.sleep(DEVICES_REFRESH_INTERVAL)
            if is_configured() and not _DELETE_JOB.get("running"):
                await refresh_devices_cache()
        except asyncio.CancelledError:
            break
        except Exception:
            continue


async def _on_startup(app: web.Application) -> None:
    app["device_refresh_task"] = asyncio.get_event_loop().create_task(_periodic_device_refresh())


async def _on_cleanup(app: web.Application) -> None:
    task = app.get("device_refresh_task")
    if task:
        task.cancel()


def create_app() -> web.Application:
    app = web.Application()
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    app.router.add_get("/", index)
    app.router.add_get("/api/app-info", app_info)
    app.router.add_get("/api/config-status", config_status)
    app.router.add_get("/api/devices", devices)
    app.router.add_get("/api/devices-debug", devices_debug)
    app.router.add_post("/api/devices/delete", delete_devices)
    app.router.add_post("/api/devices/delete-job", delete_job_start)
    app.router.add_get("/api/devices/delete-job", delete_job_status)
    app.router.add_post("/api/devices/delete-job/cancel", delete_job_cancel)
    app.router.add_post("/api/devices/rename", rename_devices)
    app.router.add_get("/api/delete-probe", delete_probe)
    app.router.add_get("/debug", debug_ui)
    app.router.add_get("/api/token-refresh-status", token_refresh_status)
    app.router.add_get("/alexa-login", auth_login)
    app.router.add_get("/api/auth-session", auth_session)
    app.router.add_post("/api/logout", logout)
    app.router.add_static("/static/", STATIC_DIR)
    oh_style_login.setup_routes(app)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8099)
