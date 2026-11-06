"""Offline release invariants and actual inline title-validator fixtures.

Execute only in an independently isolated workspace sandbox. Workflow assertions
are literal/static checks, not a YAML interpreter or a GitHub/Release Please run.
No third-party dependencies, network, Git operations or release writes.
"""

import io
import json
import os
import re
import sys
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

if not sys.flags.isolated or not sys.dont_write_bytecode:
    raise SystemExit("Run this sandbox test with python3 -I -B")

ROOT = Path(__file__).resolve().parents[1]
RELEASE = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
TITLE = (ROOT / ".github/workflows/pr-title.yml").read_text(encoding="utf-8")


class ReleaseConfigTests(unittest.TestCase):
    def test_single_simple_package_and_explicit_bumps(self):
        config = json.loads((ROOT / "release-please-config.json").read_text())
        self.assertEqual(set(config), {"$schema", "packages"})
        self.assertEqual(set(config["packages"]), {"."})
        self.assertEqual(config["packages"]["."], {
            "release-type": "simple",
            "initial-version": "0.1.0",
            "version-file": "version.txt",
            "changelog-path": "CHANGELOG.md",
            "include-component-in-tag": False,
            "include-v-in-tag": True,
            "bump-minor-pre-major": True,
            "bump-patch-for-minor-pre-major": False,
        })
        self.assertNotIn('"release-as"', json.dumps(config))

    def test_bootstrap_or_consistent_recorded_release(self):
        # Remain valid when the first bot PR replaces the bootstrap sentinel.
        manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())
        raw_version = (ROOT / "version.txt").read_text()
        version = raw_version.strip()
        self.assertEqual(raw_version, version + "\n")
        self.assertRegex(version, r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
        if manifest == {}:
            self.assertEqual(version, "0.0.0", "unreleased bootstrap only")
        else:
            self.assertEqual(manifest, {".": version})
            self.assertGreaterEqual(tuple(map(int, version.split("."))), (0, 1, 0))
            changelog = (ROOT / "CHANGELOG.md").read_text()
            self.assertRegex(changelog, rf"(?m)^## .*\b{re.escape(version)}\b")

    def test_release_workflow_literal_safety_contract(self):
        self.assertIn("on:\n  push:\n    branches: [main]\n  workflow_dispatch:\n", RELEASE)
        self.assertIn("\npermissions: {}\n", RELEASE)
        self.assertIn("  group: release-please-main\n  cancel-in-progress: false\n", RELEASE)
        self.assertIn(
            "    if: ${{ github.ref == 'refs/heads/main' && "
            "vars.RELEASE_PLEASE_ENABLED == 'true' }}\n", RELEASE)
        self.assertIn("    permissions:\n      contents: write\n      pull-requests: write\n", RELEASE)
        self.assertEqual(RELEASE.count("permissions:"), 2)
        self.assertEqual(RELEASE.count("uses:"), 1)
        self.assertIn(
            "uses: googleapis/release-please-action@"
            "45996ed1f6d02564a971a2fa1b5860e934307cf7 # v5.0.0\n", RELEASE)
        self.assertIn("          token: ${{ secrets.GITHUB_TOKEN }}\n", RELEASE)
        self.assertIn("          target-branch: main\n", RELEASE)
        self.assertIn("          config-file: release-please-config.json\n", RELEASE)
        self.assertIn("          manifest-file: .release-please-manifest.json\n", RELEASE)
        self.assertEqual(RELEASE.count("secrets."), 1)
        for forbidden in ("run:", "checkout@", "pull_request_target:", "id-token:", "packages:"):
            self.assertNotIn(forbidden, RELEASE)

    def test_title_workflow_literal_metadata_only_contract(self):
        self.assertIn("on:\n  pull_request:\n", TITLE)
        self.assertIn("types: [opened, edited, synchronize, reopened, ready_for_review]", TITLE)
        self.assertIn("\npermissions: {}\n", TITLE)
        self.assertEqual(TITLE.count("permissions:"), 1)
        self.assertIn("shell: python3 -I -B {0}\n", TITLE)
        self.assertEqual(TITLE.count("        run: |\n"), 1)
        self.assertNotIn("${{", TITLE.split("        run: |\n", 1)[1])
        for forbidden in ("uses:", "checkout", "secrets.", "pull_request_target:"):
            # Comments may describe the absence of checkout; executable lines may not.
            executable = "\n".join(line for line in TITLE.splitlines()
                                   if not line.lstrip().startswith("#"))
            self.assertNotIn(forbidden, executable)


class TitleValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The workflow deliberately ends in one inline Python block. No custom
        # YAML parser: fail if this bounded extraction shape changes.
        prefix, body = TITLE.split("        run: |\n")
        if not prefix or not all(not line.strip() or line.startswith("          ")
                                 for line in body.splitlines()):
            raise AssertionError("expected one final, indented Python run block")
        cls.validator = compile(textwrap.dedent(body), "pr-title.yml:inline", "exec")

    def validate(self, title):
        output = io.StringIO()
        payload = json.dumps({"pull_request": {"title": title}})
        with patch.dict(os.environ, {"GITHUB_EVENT_PATH": "/synthetic/event.json"}, clear=True), \
                patch.object(Path, "read_text", return_value=payload) as read_event, \
                redirect_stdout(output):
            exec(self.validator, {"__name__": "__main__"})
        read_event.assert_called_once_with(encoding="utf-8")
        self.assertEqual(output.getvalue(), "Conventional PR title: PASS\n")

    def test_accepted_types_scopes_breaking_and_bot(self):
        for kind in ("feat", "fix", "docs", "style", "refactor", "perf", "test",
                     "build", "ci", "chore", "revert"):
            with self.subTest(kind=kind):
                self.validate(f"{kind}: describe change")
        for title in ("feat!: change state format", "fix(state/v2)!: reject old evidence",
                      "docs(cli.config): describe flags", "chore(main): release 0.1.0",
                      "fix: preserve Unicode café"):
            with self.subTest(title=title):
                self.validate(title)

    def test_rejected_syntax_and_control_characters(self):
        for title in ("", "add a feature", "Feat: change", "unknown: change",
                      "fix:no space", "fix: ", "fix:  leading space", "fix: trailing ",
                      "fix(): empty scope", "fix(two words): bad scope",
                      "fix!!: duplicate marker", "fix: line\nbreak", "fix: tab\there",
                      "fix: carriage\rreturn", "fix: nul\x00", "fix: escape\x1b", None, 42):
            with self.subTest(title=title), self.assertRaises(SystemExit):
                self.validate(title)

    def test_shell_and_workflow_payloads_are_only_title_data(self):
        # These are valid descriptions, not instructions; validator never echoes
        # them into logs or executes them. Patch process entry points to detect use.
        with patch("os.system", side_effect=AssertionError("shell execution")), \
                patch("subprocess.Popen", side_effect=AssertionError("child process")):
            for title in ("fix: $(touch /not-a-command)", "docs: `id` ; exit 1",
                          "fix: ${{ secrets.DO_NOT_EXPAND }}",
                          "docs: ::error::not a workflow command"):
                with self.subTest(title=title):
                    self.validate(title)


if __name__ == "__main__":
    unittest.main()
