"""Exercise the real Make syntax prerequisites in disposable Git repositories.

Run only in an independently isolated workspace sandbox. Behavioral/static
recipes are replaced with sentinels; the syntax recipes and dependency graph
come from the repository Makefile. No network or GitHub writes are required.
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

if not sys.flags.isolated or not sys.dont_write_bytecode:
    raise SystemExit("Run this sandbox test with python3 -I -B")

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("check", "check-rest", "test", "test-foreground", "test-rest")


class SyntaxFirstTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="syntax-first-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # Standalone repositories must not inherit a caller's Git worktree/index
        # or recursive make jobserver, flags, overrides, or injected makefiles.
        self.env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(self.root),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        sentinels = textwrap.dedent("""\
            test-foreground:
            \t@set -e; mkdir behavioral-active; trap 'rmdir behavioral-active' EXIT; printf '%s\\n' foreground-start >> events; sleep 0.05; printf '%s\\n' foreground-end >> events
            test-rest:
            \t@set -e; mkdir behavioral-active; trap 'rmdir behavioral-active' EXIT; printf '%s\\n' rest-start >> events; sleep 0.05; printf '%s\\n' rest-end >> events
            check-static:
            \t@printf '%s\\n' static >> events
            """)
        # Appending overrides preserves prerequisites and also reaches recursive
        # check-static invocations without inherited MAKEFILES or other flags.
        self.write("Makefile", (ROOT / "Makefile").read_text(encoding="utf-8")
                   + "\n" + sentinels)
        self.write("scripts/review-workspace-preflight.sh", "#!/bin/sh\nexit 99\n")
        self.write("valid.py", "raise RuntimeError('syntax checks must not execute Python')\n")
        self.write("valid.json", '{"valid": true}\n')
        self.write(".gitignore", "ignored/\n")
        self.write("ignored/broken.py", "def broken(:\n")
        self.write("ignored/broken.sh", "if then\n")
        self.write("ignored/broken.json", '{"broken":\n')
        self.run_command(["git", "init", "--quiet"])
        self.run_command(["git", "add", "."])

    def write(self, name, contents):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    def run_command(self, command, *, check=True):
        return subprocess.run(
            command, cwd=self.root, env=self.env, check=check,
            capture_output=True, text=True, timeout=30,
        )

    def make(self, target, parallel):
        (self.root / "events").unlink(missing_ok=True)
        return self.run_command([
            "make", "--no-print-directory",
            *(["-j4"] if parallel else []), target,
        ], check=False)

    def events(self):
        path = self.root / "events"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def assert_blocked(self, target, parallel, diagnostic):
        result = self.make(target, parallel)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(diagnostic, result.stderr)
        self.assertEqual(self.events(), [], result.stdout + result.stderr)
        self.assertFalse((self.root / "behavioral-active").exists())

    def test_invalid_syntax_blocks_every_entrypoint(self):
        cases = (
            ("broken.py", "def broken(:\n", "SyntaxError"),
            # Parsing alone accepts this; the existing compile check rejects it.
            ("broken.py", "return 1\n", "SyntaxError"),
            ("broken.sh", "if then\n", "syntax error"),
            ("broken.json", '{"broken":\n', "JSONDecodeError"),
            (".agents/skills/example/tests/fixtures/sample/gh", "if then\n", "syntax error"),
        )
        for name, contents, diagnostic in cases:
            for tracked in (False, True):
                self.write(name, contents)
                if tracked:
                    self.run_command(["git", "add", "--", name])
                try:
                    for parallel in (False, True):
                        for target in (*TARGETS, "check-syntax"):
                            with self.subTest(file=name, contents=contents, tracked=tracked,
                                              parallel=parallel, target=target):
                                self.assert_blocked(target, parallel, diagnostic)
                finally:
                    if tracked:
                        self.run_command(["git", "rm", "--cached", "--force", "--", name])
                    (self.root / name).unlink()

    def test_posix_preflight_syntax_blocks_tests(self):
        self.write("scripts/review-workspace-preflight.sh", "#!/bin/sh\nif then\n")
        for parallel in (False, True):
            for target in TARGETS:
                with self.subTest(parallel=parallel, target=target):
                    result = self.make(target, parallel)
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("sh -n scripts/review-workspace-preflight.sh", result.stdout)
                    self.assertIn("review-workspace-preflight.sh", result.stderr)
                    self.assertEqual(self.events(), [])

    def test_valid_syntax_runs_selected_tests_once_then_static(self):
        foreground = ["foreground-start", "foreground-end"]
        rest = ["rest-start", "rest-end"]
        expected = {
            "check": foreground + rest + ["static"],
            "check-rest": rest + ["static"],
            "test": foreground + rest,
            "test-foreground": foreground,
            "test-rest": rest,
            "check-syntax": [],
        }
        for parallel in (False, True):
            for target, events in expected.items():
                with self.subTest(parallel=parallel, target=target):
                    result = self.make(target, parallel)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(self.events(), events)
                    self.assertEqual(result.stdout.count("python syntax: PASS"), 1)
                    self.assertEqual(result.stdout.count("json syntax: PASS"), 1)
                    self.assertFalse((self.root / "behavioral-active").exists())
                    self.assertEqual(list(self.root.rglob("__pycache__")), [])

    def test_next_invocation_rechecks_changed_files(self):
        result = self.make("test", True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.write("valid.py", "def broken(:\n")
        self.assert_blocked("test", True, "SyntaxError")


if __name__ == "__main__":
    unittest.main()
