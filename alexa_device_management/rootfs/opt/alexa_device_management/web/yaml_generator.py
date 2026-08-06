"""Generate and deploy Home Assistant Alexa YAML from persisted app config."""

from __future__ import annotations

import os
import pathlib
import re
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
VALID_EVENT_ENDPOINTS = {
    "https://api.amazonalexa.com/v3/events",
    "https://api.eu.amazonalexa.com/v3/events",
    "https://api.fe.amazonalexa.com/v3/events",
}
_SECRET_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class GeneratorValidationError(ValueError):
    """Raised when persisted configuration cannot produce valid Alexa YAML."""


class SecretRef(str):
    """YAML ``!secret`` reference without storing the secret value in app state."""


class _SecretDumper(yaml.SafeDumper):
    pass


class _SecretLoader(yaml.SafeLoader):
    pass


def _represent_secret(dumper: yaml.SafeDumper, data: SecretRef) -> yaml.Node:
    return dumper.represent_scalar("!secret", str(data))


def _construct_secret(loader: yaml.SafeLoader, node: yaml.Node) -> SecretRef:
    return SecretRef(loader.construct_scalar(node))


_SecretDumper.add_representer(SecretRef, _represent_secret)
_SecretLoader.add_constructor("!secret", _construct_secret)


def load_yaml_with_secrets(text: str) -> Any:
    """Load generated YAML while retaining ``!secret`` references as strings."""
    return yaml.load(text, Loader=_SecretLoader)


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

        selected_by_device: dict[str, list[str]] = {}
        for entity_id, settings in selected.items():
            device_id = settings.get("device_id", "")
            if device_id:
                selected_by_device.setdefault(device_id, []).append(entity_id)
        duplicates = {
            device_id: entity_ids
            for device_id, entity_ids in selected_by_device.items()
            if len(entity_ids) > 1
        }
        if duplicates:
            details = "; ".join(
                f"{device_id}: {', '.join(sorted(entity_ids))}"
                for device_id, entity_ids in sorted(duplicates.items())
            )
            raise GeneratorValidationError(
                "Mehrere Alexa-Endpunkte für dasselbe Home-Assistant-Gerät sind aktiviert. "
                "Bitte genau eine Haupt-Entity auswählen: " + details
            )

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

        event_gateway = normalized["event_gateway"]
        document: dict[str, Any] = {"alexa": {"smart_home": smart_home}}
        if event_gateway["enabled"]:
            smart_home.update({
                "endpoint": event_gateway["endpoint"],
                "client_id": SecretRef(event_gateway["client_id_secret"]),
                "client_secret": SecretRef(event_gateway["client_secret_secret"]),
            })
            document["alexa_device_management_sync"] = {
                "endpoint": event_gateway["endpoint"],
                "client_id": SecretRef(event_gateway["client_id_secret"]),
                "client_secret": SecretRef(event_gateway["client_secret_secret"]),
                "locale": normalized["locale"],
            }

        yaml_text = yaml.dump(
            document,
            Dumper=_SecretDumper,
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
                "device_id": str(raw_settings.get("device_id") or "").strip(),
            }

        raw_gateway = data.get("event_gateway")
        raw_gateway = raw_gateway if isinstance(raw_gateway, dict) else {}
        event_gateway = {
            "enabled": bool(raw_gateway.get("enabled", False)),
            "endpoint": str(
                raw_gateway.get("endpoint")
                or "https://api.eu.amazonalexa.com/v3/events"
            ).strip().lower(),
            "client_id_secret": str(
                raw_gateway.get("client_id_secret") or "alexa_skill_client_id"
            ).strip(),
            "client_secret_secret": str(
                raw_gateway.get("client_secret_secret") or "alexa_skill_client_secret"
            ).strip(),
            "fallback_web_cleanup": bool(raw_gateway.get("fallback_web_cleanup", True)),
        }
        if event_gateway["enabled"]:
            if event_gateway["endpoint"] not in VALID_EVENT_ENDPOINTS:
                raise GeneratorValidationError(
                    f"Unsupported Alexa event endpoint: {event_gateway['endpoint']}"
                )
            for field in ("client_id_secret", "client_secret_secret"):
                value = event_gateway[field]
                if not value or not _SECRET_NAME_RE.fullmatch(value):
                    raise GeneratorValidationError(
                        f"Invalid Home Assistant secret name for {field}: {value!r}"
                    )

        return {
            "locale": locale,
            "entities": entities,
            "event_gateway": event_gateway,
        }

    @staticmethod
    def _validate_rendered_yaml(yaml_text: str, expected: dict[str, Any]) -> None:
        try:
            parsed = load_yaml_with_secrets(yaml_text)
        except yaml.YAMLError as exc:
            raise GeneratorValidationError(f"Generated YAML is invalid: {exc}") from exc
        if parsed != expected:
            raise GeneratorValidationError("Generated YAML changed during round-trip validation")
