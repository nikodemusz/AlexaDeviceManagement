"""Compatibility and import helpers for the HA Alexa export manager."""

from __future__ import annotations

import json
from typing import Any

import yaml

import ha_export


def load_state_with_yaml_import() -> dict[str, Any]:
    """Load saved UI state, or import an existing packages/alexa.yaml once."""
    try:
        return json.loads(ha_export.EXPORT_STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        pass

    state: dict[str, Any] = {"locale": "de-DE", "entities": {}}
    try:
        document = yaml.safe_load(ha_export.ALEXA_YAML_PATH.read_text(encoding="utf-8")) or {}
        smart_home = document.get("alexa", {}).get("smart_home", {})
        state["locale"] = smart_home.get("locale", "de-DE")
        entity_config = smart_home.get("entity_config", {}) or {}
        include_entities = smart_home.get("filter", {}).get("include_entities", []) or []
        for entity_id in include_entities:
            current = entity_config.get(entity_id, {}) or {}
            state["entities"][entity_id] = {
                "enabled": True,
                "name": current.get("name", ""),
                "description": current.get("description", ""),
                "display_category": current.get("display_categories", ""),
            }
    except (OSError, yaml.YAMLError, AttributeError, TypeError):
        pass
    return state


def install() -> None:
    ha_export._load_state = load_state_with_yaml_import
