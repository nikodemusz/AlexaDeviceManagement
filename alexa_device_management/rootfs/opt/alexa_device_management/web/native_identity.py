"""Extract the stable native Home Assistant identity from Alexa IDs."""

from __future__ import annotations

import re
from typing import Any


_NATIVE_APPLIANCE_SUFFIX = re.compile(
    r"(?:^|_)native:ha:([a-z0-9_]+\.[a-z0-9_]+)$",
    re.IGNORECASE,
)


def embedded_native_endpoint_ids(value: Any) -> set[str]:
    """Return native endpoint IDs embedded at the end of a skill appliance ID.

    Alexa gives skill endpoints an opaque ``SKILL_...`` appliance ID. For
    Alexa Device Management, the suffix contains the native endpoint ID, for
    example ``..._native:ha:switch.spiegel_bad_og``. The separate
    ``legacyAppliance.entityId`` field is an Alexa UUID and is not the HA
    entity ID, so only this explicit suffix is used as mapping evidence.
    """
    text = str(value or "").strip()
    match = _NATIVE_APPLIANCE_SUFFIX.search(text)
    if not match:
        return set()
    return {f"native:ha:{match.group(1).lower()}"}

