"""Generate and deploy Home Assistant Alexa YAML from persisted app config."""

from __future__ import annotations

import os
import pathlib
import tempfile
from dataclasses import dataclass
from typing import Any

import yaml

SUPPORTED_DISPLAY_CATEGORIES = {
    "LIGHT", "SWITCH", "SMARTPLUG", "THERMOSTAT", "TEMPERATURE_SENSOR",
    "CONTACT_SENSOR", "MOTION_SENSOR", "DOOR", "WINDOW", "GARAGE_DOOR",
    "INTERIOR_BLIND", "EXTERIOR_BLIND", "CAMERA", "LOCK", "SCENE_TRIGGER",
    "OTHER",
}


class GeneratorValidationError(ValueError):
    """Raised when persisted configuration cannot produce valid Alexa YAML."""


@dataclass(frozen=True)
class GenerationResult:
    document: dict[str, Any]
    yaml_text: str
    selected_count: int


@dataclass(frozen=True)
class DeploymentResult:
    path: str
    backup: str | None
    yaml_text: str
    selected_count: int


class AlexaYamlGenerator:
    """Transforms ConfigStore data into deterministic Home Assistant YAML."""

    def __init__(self, target_path: pathlib.Path, backup_limit: int = 0) -> None:
        self.target_path = target_path
        self.backup_limit = 0

    def generate(self, data: dict[str, Any]) -> GenerationResult:
        normalized = self._normalize(data)
        selected = {
            entity_id: settings
            for entity_id, settings in normalized["entities"].items()
            if settings["enabled"]
        }

        smart_home: dict[str, Any] = {
            "locale": normalized["locale"],
            "filter": {"include_entities": sorted(selected)},
        }
        entity_config: dict[str, Any] = {}
        for entity_id, settings in sorted(selected.items()):
            config: dict[str, Any] = {}
            if settings["name"]:
                config["name"] = settings["name"]
            if settings["description"]:
                config["description"] = settings["description"]
            if settings["display_category"]:
                config["display_categories"] = settings["display_category"]
            if config:
                entity_config[entity_id] = config

        if entity_config:
            smart_home["entity_config"] = entity_config

        document = {"alexa": {"smart_home": smart_home}}
        yaml_text = yaml.safe_dump(
            document,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
        self._validate_rendered_yaml(yaml_text, document)
        return GenerationResult(document, yaml_text, len(selected))

    def deploy(self, data: dict[str, Any]) -> DeploymentResult:
        generated = self.generate(data)
        if not generated.yaml_text.strip():
            raise GeneratorValidationError("Generated Alexa YAML is empty")

        self.target_path.parent.mkdir(parents=True, exist_ok=True)
        expected_bytes = generated.yaml_text.encode("utf-8")

        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{self.target_path.name}-",
            suffix=".tmp",
            dir=str(self.target_path.parent),
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(expected_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.target_path)
            dir_fd = os.open(self.target_path.parent, os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

        actual_bytes = self.target_path.read_bytes()
        if actual_bytes != expected_bytes:
            raise OSError(
                f"Alexa YAML write verification failed: expected {len(expected_bytes)} bytes, "
                f"read back {len(actual_bytes)} bytes"
            )

        print(
            f"[ha-export] wrote {len(actual_bytes)} bytes with "
            f"{generated.selected_count} entities to {self.target_path}",
            flush=True,
        )
        return DeploymentResult(
            path=str(self.target_path),
            backup=None,
            yaml_text=generated.yaml_text,
            selected_count=generated.selected_count,
        )

    def _normalize(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise GeneratorValidationError("Configuration must be a JSON object")

        locale = str(data.get("locale") or "de-DE").strip()
        if not locale:
            raise GeneratorValidationError("Locale must not be empty")

        raw_entities = data.get("entities", {})
        if not isinstance(raw_entities, dict):
            raise GeneratorValidationError("entities must be an object")

        entities: dict[str, dict[str, Any]] = {}
        for raw_entity_id, raw_settings in raw_entities.items():
            entity_id = str(raw_entity_id).strip()
            if not entity_id or "." not in entity_id:
                raise GeneratorValidationError(f"Invalid entity_id: {raw_entity_id!r}")
            if not isinstance(raw_settings, dict):
                raise GeneratorValidationError(f"Settings for {entity_id} must be an object")

            category = str(raw_settings.get("display_category") or "").strip().upper()
            if category and category not in SUPPORTED_DISPLAY_CATEGORIES:
                raise GeneratorValidationError(
                    f"Unsupported display category for {entity_id}: {category}"
                )

            entities[entity_id] = {
                "enabled": bool(raw_settings.get("enabled")),
                "name": str(raw_settings.get("name") or "").strip(),
                "description": str(raw_settings.get("description") or "").strip(),
                "display_category": category,
            }
        return {"locale": locale, "entities": entities}

    @staticmethod
    def _validate_rendered_yaml(yaml_text: str, expected: dict[str, Any]) -> None:
        try:
            parsed = yaml.safe_load(yaml_text)
        except yaml.YAMLError as exc:
            raise GeneratorValidationError(f"Generated YAML is invalid: {exc}") from exc
        if parsed != expected:
            raise GeneratorValidationError("Generated YAML changed during round-trip validation")
