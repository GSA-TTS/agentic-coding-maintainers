"""Actual core gate control-flow fixtures; run only in an isolated workspace.

Recording stubs replace analyzers and Git on a closed PATH in a synthetic repo.
The xargs recorder delegates to real xargs to exercise NUL-delimited arguments.
No quality tools, network calls or repository writes outside the fixture run.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if not sys.flags.isolated or not sys.dont_write_bytecode:
    raise SystemExit("Run this sandbox test with python3 -I -B")

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts/core-quality-check.sh"
BASH = shutil.which("bash")
XARGS = shutil.which("xargs")
if BASH is None or XARGS is None:
    raise SystemExit("sandbox must provide Bash and xargs")

# Independent expectations: do not derive coverage or flags from the gate.
PYTHON_ROOTS = [
    ".agents/skills/cross-repo-epic/bin",
    ".agents/skills/workspace-orchestrator/bin",
    ".agents/skills/federal-authority-research/bin",
    "scripts",
]
TOOLS = ["ruff", "pyright", "bandit", "git", "xargs", "shellcheck", "actionlint", "zizmor"]
SHELL_FILES = ["scripts/example file.sh", ".agents/skills/example/tests/fixtures/sample/gh",
               "scripts/line\nbreak.sh"]
WORKFLOWS = [".github/workflows/ci.yml", ".github/workflows/security check.yaml"]
PASS = "core quality checks: PASS"

STUB = r'''
import json
import os
import subprocess
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
root = Path(os.environ["FIXTURE_ROOT"])
# Drain the pipe before recording xargs, so event order is deterministic even
# when Git fails. Real xargs still handles argument splitting and exit status.
stdin = sys.stdin.buffer.read() if name == "xargs" else b""
with (root / "events.jsonl").open("a", encoding="utf-8") as log:
    log.write(json.dumps({"name": name, "args": args}) + "\n")
if name == os.environ.get("FAIL_TOOL"):
    print("synthetic failure: " + name, file=sys.stderr)
    raise SystemExit(19)
if name == "git":
    files = json.loads((root / "shell-files.json").read_text(encoding="utf-8"))
    sys.stdout.buffer.write(b"".join(path.encode() + b"\0" for path in files))
elif name == "xargs":
    result = subprocess.run([os.environ["REAL_XARGS"], *args], input=stdin, check=False)
    raise SystemExit(result.returncode)
'''


class CoreQualityCheckTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="core-quality-check-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "fixture-bin"
        self.bin.mkdir()
        for name in TOOLS:
            stub = self.bin / name
            stub.write_text(f"#!{sys.executable} -IB\n" + STUB, encoding="utf-8")
            stub.chmod(0o700)
        for path in PYTHON_ROOTS:
            (self.root / path).mkdir(parents=True, exist_ok=True)
        for path in SHELL_FILES:
            file = self.root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("#!/bin/sh\n", encoding="utf-8")
        (self.root / "shell-files.json").write_text(json.dumps(SHELL_FILES), encoding="utf-8")

    def run_gate(self, workflows=WORKFLOWS, fail_tool=""):
        for path in workflows:
            workflow = self.root / path
            workflow.parent.mkdir(parents=True, exist_ok=True)
            workflow.write_text("name: synthetic workflow\n", encoding="utf-8")
        log = self.root / "events.jsonl"
        log.unlink(missing_ok=True)
        result = subprocess.run(
            [BASH, "--noprofile", "--norc", str(GATE)], cwd=self.root,
            env={"PATH": str(self.bin), "FIXTURE_ROOT": str(self.root),
                 "REAL_XARGS": XARGS, "FAIL_TOOL": fail_tool, "LC_ALL": "C"},
            capture_output=True, text=True, timeout=30, check=False,
        )
        events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        return result, events

    def test_roots_flags_and_shell_inventory(self):
        result, events = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, PASS + "\n")
        self.assertEqual(events, [
            {"name": "ruff", "args": ["check", "--isolated", "--select", "E4,E7,E9,F,I", *PYTHON_ROOTS]},
            {"name": "pyright", "args": PYTHON_ROOTS},
            {"name": "bandit", "args": ["-q", "-ll", "-r", *PYTHON_ROOTS, "-x", "*/tests/*"]},
            {"name": "git", "args": ["ls-files", "-z", "--", "*.sh", ".agents/skills/*/tests/fixtures/*/gh"]},
            {"name": "xargs", "args": ["-0", "shellcheck"]},
            {"name": "shellcheck", "args": SHELL_FILES},
            {"name": "actionlint", "args": WORKFLOWS},
            {"name": "zizmor", "args": ["--offline", "--format", "plain", *WORKFLOWS]},
        ])

    def test_each_analyzer_failure_stops_later_steps(self):
        for tool in ("ruff", "pyright", "bandit", "shellcheck", "actionlint", "zizmor"):
            with self.subTest(tool=tool):
                result, events = self.run_gate(fail_tool=tool)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(PASS, result.stdout + result.stderr)
                self.assertIn("synthetic failure: " + tool, result.stderr)
                self.assertEqual([event["name"] for event in events], TOOLS[:TOOLS.index(tool) + 1])

    def test_pipeline_failures_stop_workflow_checks(self):
        for tool in ("git", "xargs"):
            with self.subTest(tool=tool):
                result, events = self.run_gate(fail_tool=tool)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(PASS, result.stdout + result.stderr)
                self.assertIn("synthetic failure: " + tool, result.stderr)
                names = [event["name"] for event in events]
                # Both sides of a pipeline start; xargs may run shellcheck with
                # empty input after Git fails. Neither workflow step may run.
                self.assertEqual(names[:5], TOOLS[:5])
                self.assertIn(names[5:], ([], ["shellcheck"]) if tool == "git" else ([],))

    def test_each_workflow_extension_and_unmatched_globs(self):
        for workflow in WORKFLOWS:
            with self.subTest(workflow=workflow):
                result, events = self.run_gate(workflows=[workflow, ".github/workflows/ignored.txt",
                                                          ".github/workflows/nested/ignored.yml"])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, PASS + "\n")
                self.assertEqual(events[-2:], [
                    {"name": "actionlint", "args": [workflow]},
                    {"name": "zizmor", "args": ["--offline", "--format", "plain", workflow]},
                ])
                (self.root / workflow).unlink()

    def test_no_workflows_fails_before_workflow_tools(self):
        for workflows in ([], [".github/workflows/ignored.txt", ".github/workflows/nested/ignored.yaml"]):
            with self.subTest(workflows=workflows):
                result, events = self.run_gate(workflows=workflows)
                self.assertEqual(result.returncode, 3)
                self.assertNotIn(PASS, result.stdout + result.stderr)
                self.assertIn("ERROR: no workflows found for actionlint/zizmor", result.stderr)
                self.assertEqual([event["name"] for event in events], TOOLS[:6])


if __name__ == "__main__":
    unittest.main()
