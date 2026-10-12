"""Render individual console events using one local environment variable.

This utility only writes JSON files. It never invokes Lambda, contacts HA,
refreshes OAuth, or changes production authentication.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import pathlib
import re
import sys
import tempfile

TEMPLATES = pathlib.Path(__file__).with_name("test_events")
PLACEHOLDER = "REPLACE_WITH_HA_OAUTH_ACCESS_TOKEN"
DEFAULT_TOKEN_ENV = "HA_ALEXA_OAUTH_TOKEN"


def load_templates():
    return {path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(TEMPLATES.glob("*.json"))}


def render_events(templates, token, endpoint_map=None):
    if not isinstance(token, str) or not token.strip() or token == PLACEHOLDER:
        raise ValueError("The token environment variable is missing or empty.")
    mapping = endpoint_map or {}
    known = {event.get("directive", {}).get("endpoint", {}).get("endpointId")
             for event in templates.values()} - {None}
    if set(mapping) - known:
        raise ValueError("An endpoint mapping does not match a template endpoint.")
    if any(not isinstance(value, str) or not re.fullmatch(r"native:[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value)
           for value in mapping.values()):
        raise ValueError("Replacement endpoints must be valid native: IDs.")
    rendered = copy.deepcopy(templates)
    for event in rendered.values():
        directive = event["directive"]
        endpoint = directive.get("endpoint")
        scope = endpoint["scope"] if endpoint else directive["payload"]["scope"]
        if scope.get("token") != PLACEHOLDER:
            raise ValueError("A template must contain the token placeholder.")
        scope["token"] = token
        if endpoint:
            endpoint["endpointId"] = mapping.get(endpoint["endpointId"], endpoint["endpointId"])
    return rendered


def write_events(events, output_dir, overwrite=False):
    output_dir = pathlib.Path(output_dir).resolve()
    repository = pathlib.Path(__file__).resolve().parents[2]
    if output_dir.is_relative_to(repository):
        raise ValueError("Choose an output directory outside the source repository.")
    if any(not re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in events):
        raise ValueError("Invalid event file name.")
    paths = [output_dir / (name + ".json") for name in events]
    if any(path.is_symlink() or (path.exists() and not path.is_file()) for path in paths):
        raise ValueError("Output targets must be regular files, not symbolic links.")
    if not overwrite and any(path.exists() for path in paths):
        raise ValueError("Output files already exist; use --overwrite to regenerate them.")
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, event in events.items():
        path = output_dir / (name + ".json")
        data = (json.dumps(event, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if not overwrite:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
        else:
            fd, temporary = tempfile.mkstemp(prefix=".alexa-event-", dir=output_dir)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-env", default=DEFAULT_TOKEN_ENV,
                        help="Environment variable containing the current linked HA OAuth access token")
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--event", default="all", help="One template name, or all")
    parser.add_argument("--endpoint", action="append", default=[], metavar="OLD=NEW",
                        help="Replace an endpoint in every event, e.g. desk=native:living_room")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        templates = load_templates()
        mapping = {}
        for item in args.endpoint:
            old, separator, new = item.partition("=")
            if not separator or not old or not new:
                raise ValueError("Endpoint mappings require OLD=NEW.")
            old = old if old.startswith("native:") else "native:" + old
            if old in mapping:
                raise ValueError("Specify each endpoint mapping once.")
            mapping[old] = new
        # Read once, then apply to all files; never print the token or events.
        rendered = render_events(templates, os.environ.get(args.token_env), mapping)
        if args.event != "all":
            if args.event not in rendered:
                raise ValueError("Unknown event name.")
            rendered = {args.event: rendered[args.event]}
        paths = write_events(rendered, args.output_dir, args.overwrite)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, KeyError, TypeError):
        print("Could not read templates or write output files.", file=sys.stderr)
        return 2
    print(f"Created {len(paths)} private JSON test file(s). No requests were sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
