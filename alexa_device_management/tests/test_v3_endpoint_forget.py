import asyncio
from pathlib import Path
import sys

import pytest

WEB = Path(__file__).parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB))

import server_clean


def test_v3_forget_uses_only_exact_registered_endpoint_id(monkeypatch):
    endpoint = {"endpointId": "amzn1.alexa.endpoint.abc-123"}
    called = {}

    async def find_endpoint(_uuid, _data):
        return endpoint, {"full": {"status": 200}}

    async def find_mutations(pattern, _data):
        called["pattern"] = pattern
        assert pattern == r"^forgetEndpoint$"
        return [{"name": "forgetEndpoint"}, {"name": "deleteDeviceGroup"}]

    async def execute_mutation(field, values, require, _data):
        called["field"] = field["name"]
        called["values"] = values
        called["require"] = require
        return True, {"status": 200}

    async def gone(_uuid, _data):
        return True

    monkeypatch.setattr(server_clean, "graphql_find_endpoint", find_endpoint)
    monkeypatch.setattr(server_clean, "gql_find_mutations", find_mutations)
    monkeypatch.setattr(server_clean, "gql_execute_mutation", execute_mutation)
    monkeypatch.setattr(server_clean, "_v3_entity_gone", gone)

    result = asyncio.run(server_clean.delete_v3_entity_cookie("abc-123", {}))

    assert result["_winner"] == "GQL forgetEndpoint"
    assert called == {
        "pattern": r"^forgetEndpoint$",
        "field": "forgetEndpoint",
        "values": {"id": "amzn1.alexa.endpoint.abc-123"},
        "require": ("id",),
    }


def test_v3_unresolved_entity_does_not_guess_graphql_delete_id(monkeypatch):
    called = {"mutations": 0}

    async def find_endpoint(_uuid, _data):
        return None, {"full": {"status": 200, "item_count": 385}}

    async def find_mutations(_pattern, _data):
        called["mutations"] += 1
        raise AssertionError("must not try a guessed GraphQL identifier")

    async def no_phoenix(_uuid, _data):
        return None

    async def raw_delete(_path, _data):
        return 404, "Resource not found"

    async def raw_post(_path, _body, _data):
        return 404, "Resource not found"

    monkeypatch.setattr(server_clean, "graphql_find_endpoint", find_endpoint)
    monkeypatch.setattr(server_clean, "gql_find_mutations", find_mutations)
    monkeypatch.setattr(server_clean, "phoenix_find_appliance", no_phoenix)
    monkeypatch.setattr(server_clean, "alexa_raw_delete", raw_delete)
    monkeypatch.setattr(server_clean, "alexa_raw_post", raw_post)

    result = asyncio.run(server_clean.delete_v3_entity_cookie("abc-123", {}))

    assert called["mutations"] == 0
    assert result["_graphql_endpoint_resolved"] is False
    assert "DeleteReport" in result["_delete_guidance"]
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(server_clean._delete_target({"serial": "abc-123"}, {}))
    assert "source skill" in str(exc.value)
    assert "Probe:" not in str(exc.value)
