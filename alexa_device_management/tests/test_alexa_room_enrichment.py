from pathlib import Path
import sys


WEB = Path(__file__).parents[1] / "rootfs/opt/alexa_device_management/web"
sys.path.insert(0, str(WEB))

import alexa_room_enrichment as enrichment


def test_enriches_room_from_embedded_phoenix_members():
    devices = [{
        "serial": "lamp-1",
        "appliance_id": "lamp-1",
        "family": "Example",
        "source": "smart_home",
        "room": "",
        "raw": {},
    }]
    phoenix = {"payload": '{"groups":[{"groupName":"Küche","applianceIds":["lamp-1"]}]}'}

    enrichment._enrich(devices, phoenix)

    assert devices[0]["room"] == "Küche"


def test_deep_payload_does_not_raise_recursion_error():
    payload = {"serial": "deep-device"}
    for _ in range(2_000):
        payload = {"child": payload}

    assert enrichment._identifiers(payload) == {"deep-device"}


def test_group_scan_does_not_attribute_unrelated_nested_identifiers():
    phoenix = {
        "groupName": "Wohnzimmer",
        "members": [{"applianceId": "member-1"}],
        "unrelated": {"applianceId": "not-a-member"},
    }

    memberships = enrichment._collect_group_members(phoenix)

    assert memberships["member-1"] == {"Wohnzimmer"}
    assert "Wohnzimmer" not in memberships["not-a-member"]
