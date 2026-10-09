"""Standalone native Alexa skill configuration, isolated from legacy HA export.

The future skill MUST consume this YAML file, not ConfigStore's legacy JSON.
Writing is atomic and validated before changing the active file.
"""
from __future__ import annotations

import os
import pathlib
import tempfile
from copy import deepcopy
from typing import Any

import yaml

from device_model import validate_devices


class NativeSkillConfigError(ValueError):
    """Invalid native skill settings or malformed YAML."""


class NativeSkillConfigStore:
    DEFAULT_PATH = pathlib.Path("/config/alexa_device_management/native/config.yaml")

    def __init__(self, path: pathlib.Path | None = None) -> None:
        self.path = path if path is not None else self.DEFAULT_PATH

    @staticmethod
    def default() -> dict[str, Any]:
        return {"schema_version": 6, "enabled": False, "locale": "de-DE", "devices": {}}

    @classmethod
    def validate(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise NativeSkillConfigError("Native configuration must be a YAML mapping")
        if value.get("schema_version") != 6:
            raise NativeSkillConfigError("Expected schema_version: 6")
        if not isinstance(value.get("enabled"), bool):
            raise NativeSkillConfigError("enabled must be true or false")
        locale = value.get("locale")
        if not isinstance(locale, str) or not locale.strip():
            raise NativeSkillConfigError("locale must be a non-empty string")
        if "devices" not in value:
            raise NativeSkillConfigError("Missing devices mapping")
        normalized = deepcopy(value)
        normalized["devices"] = validate_devices(value["devices"])
        return normalized

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            # Read operations must not bootstrap or deploy a skill implicitly.
            return self.default()
        try:
            value = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise NativeSkillConfigError(f"Cannot read native skill configuration: {exc}") from exc
        return self.validate(value)

    def save(self, value: dict[str, Any]) -> dict[str, Any]:
        normalized = self.validate(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(normalized, allow_unicode=True, sort_keys=False)
        fd, temporary = tempfile.mkstemp(prefix=".config-", suffix=".yaml", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return normalized
