"""The event renderer uses synthetic tokens and never executes device actions."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

MODULE = pathlib.Path(__file__).resolve().parents[1] / "native_skill/render_test_events.py"
spec = importlib.util.spec_from_file_location("render_test_events", MODULE)
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)
TOKEN = "synthetic-renderer-token"


class RenderEventTests(unittest.TestCase):
    def call(self, args, env):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = renderer.main(args)
        self.assertNotIn(TOKEN, stdout.getvalue() + stderr.getvalue())
        return status, stdout.getvalue(), stderr.getvalue()

    def test_every_template_is_one_complete_placeholder_event(self):
        templates = renderer.load_templates()
        self.assertEqual(len(templates), 15)
        for name, event in templates.items():
            with self.subTest(name=name):
                self.assertEqual(set(event), {"directive"})
                body = event["directive"]
                scope = body.get("endpoint", {}).get("scope") or body["payload"]["scope"]
                self.assertEqual(scope["token"], renderer.PLACEHOLDER)

    def test_one_environment_variable_renders_all_files_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / "events"
            status, stdout, _ = self.call(["--output-dir", str(output)], {renderer.DEFAULT_TOKEN_ENV: TOKEN})
            self.assertEqual(status, 0)
            self.assertIn("15", stdout)
            files = list(output.glob("*.json"))
            self.assertEqual(len(files), 15)
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            for path in files:
                body = json.loads(path.read_text())["directive"]
                scope = body.get("endpoint", {}).get("scope") or body["payload"]["scope"]
                self.assertEqual(scope["token"], TOKEN)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(all(renderer.PLACEHOLDER in json.dumps(e) for e in renderer.load_templates().values()))

    def test_custom_variable_and_single_event_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            status, _, _ = self.call(["--output-dir", directory, "--token-env", "TEST_ACCESS_TOKEN", "--event", "discovery"],
                                     {"TEST_ACCESS_TOKEN": TOKEN})
            self.assertEqual(status, 0)
            self.assertEqual([p.name for p in pathlib.Path(directory).iterdir()], ["discovery.json"])

    def test_token_rotation_regenerates_existing_files_only_when_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            args = ["--output-dir", directory, "--event", "discovery"]
            self.assertEqual(self.call(args, {renderer.DEFAULT_TOKEN_ENV: TOKEN})[0], 0)
            original = (pathlib.Path(directory) / "discovery.json").read_bytes()
            self.assertEqual(self.call(args, {renderer.DEFAULT_TOKEN_ENV: "rotated-synthetic-token"})[0], 2)
            self.assertEqual((pathlib.Path(directory) / "discovery.json").read_bytes(), original)
            self.assertEqual(self.call(args + ["--overwrite"], {renderer.DEFAULT_TOKEN_ENV: "rotated-synthetic-token"})[0], 0)
            body = json.loads((pathlib.Path(directory) / "discovery.json").read_text())["directive"]
            self.assertEqual(body["payload"]["scope"]["token"], "rotated-synthetic-token")
            self.assertEqual((pathlib.Path(directory) / "discovery.json").stat().st_mode & 0o777, 0o600)

    def test_endpoint_mapping_changes_all_matching_events_without_mutating_templates(self):
        templates = renderer.load_templates()
        before = json.dumps(templates, sort_keys=True)
        events = renderer.render_events(templates, TOKEN, {"native:desk": "native:test_living_room"})
        for name in ("light_status", "light_turn_on", "light_turn_off", "light_brightness"):
            self.assertEqual(events[name]["directive"]["endpoint"]["endpointId"], "native:test_living_room")
        self.assertEqual(json.dumps(templates, sort_keys=True), before)

    def test_missing_token_invalid_event_and_invalid_mapping_create_no_files(self):
        cases = [([], {}), ([], {renderer.DEFAULT_TOKEN_ENV: ""}),
                 (["--event", "unknown"], {renderer.DEFAULT_TOKEN_ENV: TOKEN}),
                 (["--endpoint", "unknown=native:test"], {renderer.DEFAULT_TOKEN_ENV: TOKEN}),
                 (["--endpoint", "desk=light#test"], {renderer.DEFAULT_TOKEN_ENV: TOKEN}),
                 (["--endpoint", "desk=native:test", "--endpoint", "desk=native:other"], {renderer.DEFAULT_TOKEN_ENV: TOKEN})]
        for args, env in cases:
            with self.subTest(args=args), tempfile.TemporaryDirectory() as directory:
                output = pathlib.Path(directory) / "events"
                self.assertEqual(self.call(["--output-dir", str(output), *args], env)[0], 2)
                self.assertFalse(output.exists())

    def test_source_repository_output_is_rejected(self):
        output = MODULE.parent / "private-rendered-test-events"
        self.assertEqual(self.call(["--output-dir", str(output)], {renderer.DEFAULT_TOKEN_ENV: TOKEN})[0], 2)
        self.assertFalse(output.exists())

    def test_symlink_target_is_rejected_without_changing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            original = root / "original.txt"
            original.write_text("leave unchanged")
            output = root / "events"
            output.mkdir()
            (output / "discovery.json").symlink_to(original)
            self.assertEqual(self.call(["--output-dir", str(output), "--overwrite"], {renderer.DEFAULT_TOKEN_ENV: TOKEN})[0], 2)
            self.assertEqual(original.read_text(), "leave unchanged")
            self.assertEqual(len(list(output.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
