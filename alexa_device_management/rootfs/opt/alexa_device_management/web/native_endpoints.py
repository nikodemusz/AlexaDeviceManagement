"""Use the deployed Lambda's discovery serializer for native lifecycle reports."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_path = Path(__file__).with_name("native_skill_adapter.py")
if not _path.exists():
    _path = Path(__file__).resolve().parents[4] / "native_skill/lambda_function.py"
_spec = importlib.util.spec_from_file_location("native_discovery_adapter", _path)
_adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_adapter)


def endpoints(config):
    if not config.get("enabled"):
        return []
    event = {"directive": {"header": {"messageId": "native-preview"}}}
    return _adapter.discovery(event, config)["event"]["payload"]["endpoints"]
