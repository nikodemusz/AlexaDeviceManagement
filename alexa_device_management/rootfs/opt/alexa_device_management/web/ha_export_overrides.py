"""Compatibility shim retained for older server entry points.

State loading and YAML migration are now handled by config_store.ConfigStore.
"""

from __future__ import annotations


def install() -> None:
    """No-op: kept to avoid breaking existing imports during the v2 migration."""
    return None
