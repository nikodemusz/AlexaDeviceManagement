import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

WEB = Path(__file__).parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB))

import alexa_endpoint_inventory as inventory


FULL_QUERY = "query full"
MINIMAL_QUERY = "query minimal"


def endpoint(identifier, name):
    return {
        "endpointId": f"amzn1.alexa.endpoint.{identifier}",
        "friendlyName": name,
        "legacyIdentifiers": {
            "chrsIdentifier": {"entityId": identifier},
        },
    }


def make_server(*, active_devices, graph_endpoints):
    async def original_fetch(_data):
        return list(active_devices), []

    async def original_delete(_target, _data):
        raise AssertionError("original delete should not be used for GraphQL endpoints")

    async def alexa_graphql(_query, _variables, _data):
        return 200, {"data": {"endpoints": {"items": list(graph_endpoints)}}}

    return SimpleNamespace(
        ENDPOINTS_QUERY_FULL=FULL_QUERY,
        ENDPOINTS_QUERY_MINIMAL=MINIMAL_QUERY,
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

    async def gql_find_mutations(_pattern, _data):
        return [{"name": "deleteSmartHomeEndpoint"}]

    async def gql_execute_mutation(_field, _values, _require, _data):
        state["deleted"] = True
        return True, {"status": 200}

    server.alexa_graphql = alexa_graphql
    server.graphql_find_endpoint = graphql_find_endpoint
    server.gql_find_mutations = gql_find_mutations
    server.gql_execute_mutation = gql_execute_mutation
    inventory.install(server)

    asyncio.run(server._delete_target({"source": "graphql", "serial": "orphan-uuid"}, {}))

    assert state["deleted"] is True


def test_graphql_delete_rejects_unverified_noop():
    target_endpoint = endpoint("orphan-uuid", "Alte Lampe")
    server = make_server(active_devices=[], graph_endpoints=[target_endpoint])

    async def graphql_find_endpoint(_serial, _data):
        return target_endpoint, {}

    async def gql_find_mutations(_pattern, _data):
        return [{"name": "deleteSmartHomeEndpoint"}]

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
