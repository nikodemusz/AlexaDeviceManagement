"""Persistent configuration storage for the HA -> Alexa designer."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import tempfile
import threading
import time
from copy import deepcopy
from typing import Any

import yaml


class ConfigStore:
    """Thread-safe JSON store with atomic writes and YAML migration."""

    SCHEMA_VERSION = 2

    def __init__(self, path: pathlib.Path, legacy_path: pathlib.Path, alexa_yaml_path: pathlib.Path) -> None:
        self.path = path
        self.legacy_path = legacy_path
        self.alexa_yaml_path = alexa_yaml_path
        self.backup_dir = path.parent / "backups"
        self._lock = threading.RLock()

    @staticmethod
    def default() -> dict[str, Any]:
        return {
            "schema_version": ConfigStore.SCHEMA_VERSION,
            "locale": "de-DE",
            "entities": {},
            "ui": {"collapsed_devices": [], "collapsed_areas": []},
            "updated_at": None,
        }

    def load(self) -> dict[str, Any]:
        with self._lock:
            for candidate in (self.path, self.legacy_path):
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                    normalized = self._normalize(data)
                    if candidate != self.path:
                        self.save(normalized, create_backup=False)
                    return normalized
                except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError):
                    continue

            imported = self._import_yaml()
            self.save(imported, create_backup=False)
            return imported

    def save(self, data: dict[str, Any], *, create_backup: bool = True) -> dict[str, Any]:
        with self._lock:
            normalized = self._normalize(deepcopy(data))
            normalized["updated_at"] = int(time.time())
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.backup_dir.mkdir(parents=True, exist_ok=True)

            if create_backup and self.path.exists():
                backup = self.backup_dir / f"config-{int(time.time())}.json"
                shutil.copy2(self.path, backup)

            fd, tmp_name = tempfile.mkstemp(prefix="config-", suffix=".tmp", dir=str(self.path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(normalized, handle, ensure_ascii=False, indent=2, sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_name, self.path)
                dir_fd = os.open(self.path.parent, os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
            return normalized

    def status(self) -> dict[str, Any]:
        writable = os.access(self.path.parent if self.path.parent.exists() else self.path.parent.parent, os.W_OK)
        return {
            "path": str(self.path),
            "exists": self.path.exists(),
            "directory_exists": self.path.parent.exists(),
            "writable": writable,
            "updated_at": int(self.path.stat().st_mtime) if self.path.exists() else None,
        }

    def _normalize(self, data: Any) -> dict[str, Any]:
        result = self.default()
        if isinstance(data, dict):
            result["locale"] = str(data.get("locale") or "de-DE")
            result["entities"] = data.get("entities") if isinstance(data.get("entities"), dict) else {}
            result["ui"] = data.get("ui") if isinstance(data.get("ui"), dict) else result["ui"]
            result["updated_at"] = data.get("updated_at")
        result["schema_version"] = self.SCHEMA_VERSION
        return result

    def _import_yaml(self) -> dict[str, Any]:
        state = self.default()
        try:
            document = yaml.safe_load(self.alexa_yaml_path.read_text(encoding="utf-8")) or {}
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
