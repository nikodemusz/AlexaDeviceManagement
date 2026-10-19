import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

WEB = Path(__file__).parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB))

import alexa_endpoint_inventory as inventory
import server_clean


FULL_QUERY = "query full"
MINIMAL_QUERY = "query minimal"
IDENTITY_QUERY = "query identity"


def endpoint(identifier, name):
    return {
        "endpointId": f"amzn1.alexa.endpoint.{identifier}",
        "friendlyName": name,
        "legacyIdentifiers": {
            "chrsIdentifier": {"entityId": identifier},
        },
    }


def make_server(*, active_devices, graph_endpoints):
    queries = []

    async def original_fetch(_data):
        return list(active_devices), []

    async def original_delete(_target, _data):
        raise AssertionError("original delete should not be used for GraphQL endpoints")

    async def alexa_graphql(_query, _variables, _data):
        queries.append(_query)
        return 200, {"data": {"endpoints": {"items": list(graph_endpoints)}}}

    return SimpleNamespace(
        ENDPOINTS_QUERY_IDENTITY=IDENTITY_QUERY,
        ENDPOINTS_QUERY_FULL=FULL_QUERY,
        ENDPOINTS_QUERY_MINIMAL=MINIMAL_QUERY,
        queries=queries,
        _fetch_devices_from_alexa=original_fetch,
        _delete_target=original_delete,
        alexa_graphql=alexa_graphql,
    )


def test_graphql_inventory_adds_only_orphaned_endpoints():
    active = {
        "name": "Aktive Lampe",
        "serial": "active-uuid",
        "appliance_id": "active-uuid",
        "source": "smart_home",
        "raw": {"id": "active-uuid", "displayName": "Aktive Lampe"},
    }
    server = make_server(
        active_devices=[active],
        graph_endpoints=[
            endpoint("active-uuid", "Aktive Lampe"),
            endpoint("orphan-uuid", "Alte Lampe"),
        ],
    )

    inventory.install(server)
    devices, errors = asyncio.run(server._fetch_devices_from_alexa({}))

    assert errors == []
    assert [device["serial"] for device in devices] == ["active-uuid", "orphan-uuid"]
    orphan = next(device for device in devices if device["serial"] == "orphan-uuid")
    assert orphan["source"] == "graphql"
    assert orphan["online"] is False
    assert orphan["type"] == "INACTIVE_ENDPOINT"
    assert orphan["lifecycle"] == "orphaned"


def test_graphql_identity_enriches_opaque_active_inventory_entry():
    """Join Amazon's UUID card to the endpointId sent by v6 Discovery."""
    serial = "6d0bd9a9-9f50-4ee0-b299-a5d1d554c0b7"
    active = {
        "name": "Heizrelais Keller Büro",
        "serial": serial,
        "appliance_id": serial,
        "source": "smart_home",
        "family": "Alexa Device Management",
        "raw": {"id": serial},
    }
    graph = endpoint(serial, active["name"])
    graph["endpointId"] = "native:ha:switch.heizrelais_kellerbuero"
    graph["legacyAppliance"] = {
        "entityId": "native:ha:switch.heizrelais_kellerbuero",
        "manufacturerName": "Alexa Device Management",
    }
    server = make_server(active_devices=[active], graph_endpoints=[graph])

    inventory.install(server)
    devices, errors = asyncio.run(server._fetch_devices_from_alexa({}))

    assert errors == []
    assert len(devices) == 1
    assert devices[0]["serial"] == serial
    assert devices[0]["raw"]["endpointId"] == graph["endpointId"]
    assert devices[0]["raw"]["legacyIdentifiers"] == graph["legacyIdentifiers"]
    assert devices[0]["raw"]["legacyAppliance"] == graph["legacyAppliance"]


def test_native_endpoint_identity_from_legacy_appliance_is_kept_when_amazon_uuid_is_opaque():
    graph = {
        "endpointId": "amzn1.alexa.endpoint.amazon-generated-uuid",
        "friendlyName": "Heizrelais Keller Büro",
        "legacyAppliance": {
            "entityId": "native:ha:switch.heizrelais_kellerbuero",
            "manufacturerName": "Alexa Device Management",
        },
    }
    server = make_server(active_devices=[], graph_endpoints=[graph])

    inventory.install(server)
    devices, errors = asyncio.run(server._fetch_devices_from_alexa({}))

    assert errors == []
    assert len(devices) == 1
    assert devices[0]["source"] == "graphql"
    assert devices[0]["serial"] == "native:ha:switch.heizrelais_kellerbuero"
    assert devices[0]["raw"]["legacyAppliance"]["entityId"] == (
        "native:ha:switch.heizrelais_kellerbuero"
    )
    assert server.queries[0] == server.ENDPOINTS_QUERY_IDENTITY
    assert "legacyAppliance" in server_clean.ENDPOINTS_QUERY_IDENTITY
    assert "entityId" in server_clean.ENDPOINTS_QUERY_IDENTITY


def test_graphql_inventory_reports_api_failure_without_hiding_active_devices():
    active = {
        "name": "Aktive Lampe",
        "serial": "active-uuid",
        "source": "smart_home",
        "raw": {"id": "active-uuid"},
    }

    async def original_fetch(_data):
        return [active], []

    async def original_delete(_target, _data):
        return None

    async def failing_graphql(_query, _variables, _data):
        return 500, {"raw": "unavailable"}

    server = SimpleNamespace(
        ENDPOINTS_QUERY_FULL=FULL_QUERY,
        ENDPOINTS_QUERY_MINIMAL=MINIMAL_QUERY,
        _fetch_devices_from_alexa=original_fetch,
        _delete_target=original_delete,
        alexa_graphql=failing_graphql,
    )
    inventory.install(server)

    devices, errors = asyncio.run(server._fetch_devices_from_alexa({}))

    assert devices == [active]
    assert len(errors) == 1
    assert "Alexa-Endpunkte (GraphQL)" in errors[0]


def test_graphql_delete_is_verified_against_endpoint_registry():
    state = {"deleted": False}
    target_endpoint = endpoint("orphan-uuid", "Alte Lampe")

    server = make_server(active_devices=[], graph_endpoints=[])

    async def alexa_graphql(_query, _variables, _data):
        items = [] if state["deleted"] else [target_endpoint]
        return 200, {"data": {"endpoints": {"items": items}}}

    async def graphql_find_endpoint(_serial, _data):
        return target_endpoint, {"full": {"status": 200}}

    mutation_patterns = []

    async def gql_find_mutations(pattern, _data):
        mutation_patterns.append(pattern)
        assert pattern == r"^forgetEndpoint$"
        return [{"name": "forgetEndpoint"}, {"name": "deleteDeviceGroup"}]

    async def gql_execute_mutation(field, values, _require, _data):
        assert field["name"] == "forgetEndpoint"
        assert values == {"id": "amzn1.alexa.endpoint.orphan-uuid"}
        state["deleted"] = True
        return True, {"status": 200}

    server.alexa_graphql = alexa_graphql
    server.graphql_find_endpoint = graphql_find_endpoint
    server.gql_find_mutations = gql_find_mutations
    server.gql_execute_mutation = gql_execute_mutation
    inventory.install(server)

    asyncio.run(server._delete_target({"source": "graphql", "serial": "orphan-uuid"}, {}))

    assert state["deleted"] is True
    assert mutation_patterns == [r"^forgetEndpoint$"]


def test_graphql_delete_rejects_unverified_noop():
    target_endpoint = endpoint("orphan-uuid", "Alte Lampe")
    server = make_server(active_devices=[], graph_endpoints=[target_endpoint])

    async def graphql_find_endpoint(_serial, _data):
        return target_endpoint, {}

    async def gql_find_mutations(pattern, _data):
        assert pattern == r"^forgetEndpoint$"
        return [{"name": "forgetEndpoint"}]

    async def gql_execute_mutation(_field, _values, _require, _data):
        return True, {"status": 200, "body": "accepted but unchanged"}

    server.graphql_find_endpoint = graphql_find_endpoint
    server.gql_find_mutations = gql_find_mutations
    server.gql_execute_mutation = gql_execute_mutation
    inventory.install(server)

    with pytest.raises(RuntimeError, match="weiterhin geliefert"):
        asyncio.run(
            server._delete_target({"source": "graphql", "serial": "orphan-uuid"}, {})
        )
