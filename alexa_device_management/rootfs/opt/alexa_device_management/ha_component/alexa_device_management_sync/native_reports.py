"""Native discovery reports, bounded by Amazon's payload and endpoint limits."""
from __future__ import annotations

import json
import uuid

MAX_BYTES = 256 * 1024


def discovery_report(name, items, token):
    return {"event": {"header": {"namespace": "Alexa.Discovery", "name": name,
                                 "payloadVersion": "3", "messageId": str(uuid.uuid4())},
                       "payload": {"scope": {"type": "BearerToken", "token": token},
                                   "endpoints": items}}}


def reports(endpoints, delete_ids, token):
    ids = [item.get("endpointId") for item in endpoints]
    if len(ids) > 300 or len(set(ids)) != len(ids) or any(
        not isinstance(value, str) or not value.startswith("native:") or len(value) > 256 for value in ids
    ):
        raise ValueError("Nur eindeutige native v6-Endpunkte sind für AddOrUpdateReport erlaubt (maximal 300).")
    if any(not isinstance(value, str) or not value or len(value) > 256 for value in delete_ids):
        raise ValueError("Ungültige Lösch-Endpunkt-ID.")
    if set(ids) & set(delete_ids):
        raise ValueError("Aktive v6-Endpunkte dürfen nicht gleichzeitig gelöscht werden.")
    output = []
    # Delete first so retained v5 endpoints do not consume the 300-device quota.
    operations = [("DeleteReport", [{"endpointId": value} for value in dict.fromkeys(delete_ids)]),
                  ("AddOrUpdateReport", endpoints)]
    for name, items in operations:
        batch = []
        for item in items:
            proposed = discovery_report(name, batch + [item], token)
            size = len(json.dumps(proposed, ensure_ascii=False).encode("utf-8"))
            if batch and (len(batch) == 50 or size > MAX_BYTES):
                output.append(discovery_report(name, batch, token))
                batch = []
            batch.append(item)
            if len(json.dumps(discovery_report(name, batch, token), ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
                raise ValueError("Ein v6-Endpunkt überschreitet die maximale Alexa-Reportgröße.")
        if batch:
            output.append(discovery_report(name, batch, token))
    return output
