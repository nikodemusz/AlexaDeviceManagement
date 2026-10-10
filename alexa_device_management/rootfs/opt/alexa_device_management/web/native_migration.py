"""Conservative, opt-in migration of v5 exported entities to native v6 drafts.

Never writes or disables legacy Home Assistant exports. Drafts are disabled
until each capability has been tested and explicitly enabled by the owner.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from native_skill_config import NativeSkillConfigStore

LEGACY_JSON = Path("/data/alexa_device_management/config.json")


def candidate(entity_id, settings):
    if not isinstance(settings, dict) or not settings.get("enabled"):
        return None
    if not isinstance(entity_id, str) or "." not in entity_id:
        return None
    domain, _ = entity_id.split(".", 1)
    if domain not in ("light", "switch", "fan", "input_boolean"):
        return None
    # HA-v5 endpoint IDs are domain#object_id, independent of the friendly name.
    legacy_endpoint_id = entity_id.replace(".", "#", 1)
    bindings = [{"interface": "Alexa.PowerController", "entity_id": entity_id}]
    return {
        "name": str(settings.get("name") or entity_id),
        "description": str(settings.get("description") or ""),
        "display_category": ("LIGHT" if domain == "light" else "SWITCH"),
        "enabled": False,
        "replaces_legacy_endpoint": legacy_endpoint_id,
        "capabilities": bindings,
    }


def prepare(legacy, native):
    """Add safe drafts, report unsupported entities, do not mutate inputs."""
    import copy
    updated = copy.deepcopy(native)
    result = {"added": [], "existing": [], "unsupported": []}
    entries = legacy.get("entities", {})
    if not isinstance(entries, dict):
        raise ValueError("Legacy entities must be a mapping")
    for entity_id, settings in sorted(entries.items()):
        if not isinstance(settings, dict) or not settings.get("enabled"):
            continue
        draft = candidate(entity_id, settings)
        if draft is None:
            result["unsupported"].append(entity_id)
            continue
        key = "ha:" + entity_id
        if key in updated["devices"]:
            result["existing"].append(entity_id)
            continue
        # Never create an overlapping replacement of an already staged device.
        replacement = draft["replaces_legacy_endpoint"]
        if any(d.get("replaces_legacy_endpoint") == replacement
               for d in updated["devices"].values()):
            result["existing"].append(entity_id)
            continue
        updated["devices"][key] = draft
        result["added"].append(entity_id)
    return updated, result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Stage v5 exports as disabled v6 draft devices")
    parser.add_argument("--legacy", type=Path, default=LEGACY_JSON)
    parser.add_argument("--native", type=Path, default=NativeSkillConfigStore.DEFAULT_PATH)
    parser.add_argument("--apply", action="store_true", help="Write drafts to native YAML (default: preview)")
    args = parser.parse_args(argv)
    legacy = json.loads(args.legacy.read_text(encoding="utf-8"))
    store = NativeSkillConfigStore(args.native)
    updated, report = prepare(legacy, store.load())
    store.validate(updated)
    if args.apply and report["added"]:
        store.save(updated)
    print(json.dumps({"mode": "apply" if args.apply else "preview", **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
