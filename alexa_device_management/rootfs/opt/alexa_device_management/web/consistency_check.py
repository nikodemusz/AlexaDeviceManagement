"""Consistency and permission checks for the Home Assistant Alexa export."""

from __future__ import annotations

import json
import os
import pathlib
import time
from collections import Counter
from typing import Any

import yaml
from aiohttp import web

import ha_export

STATUS_PATH = pathlib.Path("/data/alexa_device_management/consistency_status.json")
CONFIGURATION_YAML_PATH = pathlib.Path("/config/configuration.yaml")


def _finding(code: str, severity: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, **details}


def _enabled_entities(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entities = config.get("entities", {}) if isinstance(config, dict) else {}
    if not isinstance(entities, dict):
        return {}
    return {
        str(entity_id): settings
        for entity_id, settings in entities.items()
        if isinstance(settings, dict) and settings.get("enabled")
    }


def _deployed_entities(document: Any) -> set[str]:
    try:
        include = document["alexa"]["smart_home"]["filter"]["include_entities"]
    except (KeyError, TypeError):
        return set()
    return {str(item) for item in include} if isinstance(include, list) else set()


def _packages_enabled(document: Any) -> bool:
    if not isinstance(document, dict):
        return False
    homeassistant = document.get("homeassistant")
    if not isinstance(homeassistant, dict):
        return False
    packages = homeassistant.get("packages")
    if isinstance(packages, str):
        return "packages" in packages
    if isinstance(packages, dict):
        return True
    return any(str(key).startswith("packages") for key in homeassistant)


def analyse(
    config: dict[str, Any],
    inventory: dict[str, Any],
    deployed_document: Any,
    *,
    target_exists: bool,
    target_writable: bool,
    packages_enabled: bool,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    enabled = _enabled_entities(config)
    inventory_entities = {
        entity.get("entity_id"): entity
        for device in inventory.get("devices", [])
        for entity in device.get("entities", [])
        if entity.get("entity_id")
    }

    missing = sorted(set(enabled) - set(inventory_entities))
    for entity_id in missing:
        findings.append(_finding(
            "entity_missing", "error",
            f"Die konfigurierte Entität {entity_id} existiert nicht mehr in Home Assistant.",
            entity_id=entity_id,
            repair="Aus der Alexa-Konfiguration entfernen oder die Entität in Home Assistant wiederherstellen.",
        ))

    names = {
        entity_id: str(settings.get("name") or "").strip()
        for entity_id, settings in enabled.items()
    }
    for entity_id, name in names.items():
        if not name:
            findings.append(_finding(
                "empty_name", "warning",
                f"Für {entity_id} ist kein eigener Alexa-Name gesetzt.",
                entity_id=entity_id,
                repair="Einen eindeutigen, gut sprechbaren Alexa-Namen vergeben.",
            ))

    counts = Counter(name.casefold() for name in names.values() if name)
    for normalized, count in sorted(counts.items()):
        if count < 2:
            continue
        duplicates = sorted(entity_id for entity_id, name in names.items() if name.casefold() == normalized)
        findings.append(_finding(
            "duplicate_name", "error",
            f"Der Alexa-Name „{names[duplicates[0]]}“ wird {count}-mal verwendet.",
            entities=duplicates,
            repair="Für jede Entität einen eindeutigen Alexa-Namen vergeben.",
        ))

    deployed = _deployed_entities(deployed_document)
    configured = set(enabled)
    only_config = sorted(configured - deployed)
    only_deployed = sorted(deployed - configured)
    if only_config:
        findings.append(_finding(
            "not_deployed", "warning",
            f"{len(only_config)} konfigurierte Entität(en) sind noch nicht in alexa.yaml ausgerollt.",
            entities=only_config,
            repair="Konfiguration ausrollen.",
        ))
    if only_deployed:
        findings.append(_finding(
            "stale_deployment", "warning",
            f"{len(only_deployed)} Entität(en) stehen noch in alexa.yaml, sind aber nicht mehr aktiviert.",
            entities=only_deployed,
            repair="Konfiguration erneut ausrollen.",
        ))

    if not target_exists:
        findings.append(_finding(
            "yaml_missing", "warning", "Die Datei /config/packages/alexa.yaml existiert noch nicht.",
            repair="Die Konfiguration erstmals ausrollen.",
        ))
    if not target_writable:
        findings.append(_finding(
            "yaml_not_writable", "error", "Das Verzeichnis /config/packages ist nicht beschreibbar.",
            repair="Add-on-Mapping und Dateiberechtigungen prüfen.",
        ))
    if not packages_enabled:
        findings.append(_finding(
            "packages_not_enabled", "error",
            "In configuration.yaml wurde keine Home-Assistant-Paketeinbindung erkannt.",
            repair="Unter homeassistant: eine packages-Einbindung für /config/packages konfigurieren.",
        ))

    severities = Counter(item["severity"] for item in findings)
    return {
        "ok": severities["error"] == 0,
        "checked_at": int(time.time()),
        "selected_count": len(enabled),
        "inventory_count": len(inventory_entities),
        "deployed_count": len(deployed),
        "errors": severities["error"],
        "warnings": severities["warning"],
        "findings": findings,
    }


def _write_status(result: dict[str, Any]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATUS_PATH)


async def run_check(request: web.Request) -> web.Response:
    try:
        inventory = await ha_export._inventory()
        config = ha_export.CONFIG_STORE.load()
        try:
            deployed_document = yaml.safe_load(ha_export.ALEXA_YAML_PATH.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            deployed_document = {}
        try:
            configuration_document = yaml.safe_load(CONFIGURATION_YAML_PATH.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            configuration_document = {}
        parent = ha_export.ALEXA_YAML_PATH.parent
        writable_base = parent if parent.exists() else parent.parent
        result = analyse(
            config,
            inventory,
            deployed_document,
            target_exists=ha_export.ALEXA_YAML_PATH.exists(),
            target_writable=os.access(writable_base, os.W_OK),
            packages_enabled=_packages_enabled(configuration_document),
        )
        _write_status(result)
        return web.json_response(result, status=200 if result["ok"] else 422)
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def status(request: web.Request) -> web.Response:
    try:
        return web.json_response(json.loads(STATUS_PATH.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return web.json_response({"ok": None, "checked_at": None, "findings": []})


def register_routes(app: web.Application) -> None:
    app.router.add_post("/api/ha-export/consistency-check", run_check)
    app.router.add_get("/api/ha-export/consistency-status", status)
