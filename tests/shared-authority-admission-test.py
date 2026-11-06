#!/usr/bin/env python3
"""Copied wrapper/skill fixtures with real Git worktrees; isolated execution only."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
REFUSAL = "orchestrator: UNVERIFIED - shared authority root required\n"
UNSET = object()


class SharedAuthorityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="shared-authority-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.main = self.root / "primary checkout"
        self.main.mkdir()
        (self.main / "bin").mkdir()
        shutil.copy2(SOURCE / "bin/orchestrator-state.sh", self.main / "bin")
        skill = Path(".agents/skills/workspace-orchestrator")
        shutil.copytree(SOURCE / skill, self.main / skill,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        # Allowlisted environment: neither fixture Git nor skill subprocesses
        # inherit host Git identity, state overrides, Python paths or config.
        self.env = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
                    "HOME": str(self.root), "TMPDIR": str(self.root),
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0"}
        self.assertNotIn("WORKSPACE_ORCHESTRATOR_ROOT", self.env)
        self.assertNotIn("ORCHESTRATOR_STATE_DIR", self.env)
        self.assertNotIn("ORCHESTRATOR_TEST_MODE", self.env)
        self.git(self.main, "init", "-b", "fixture-main")
        self.git(self.main, "add", "-f", "bin/orchestrator-state.sh",
                 str(skill / "run.sh"), str(skill / "bin"))
        self.git(self.main, "commit", "-m", "fixture")
        self.linked = self.root / "linked checkout"
        self.git(self.main, "worktree", "add", "-b", "fixture-linked", str(self.linked))
        self.assertTrue((self.linked / ".git").is_file())

    def run_command(self, command, env=None):
        return subprocess.run(command, cwd=self.root, env=self.env if env is None else env,
                              capture_output=True, text=True, check=False, timeout=15)

    def git(self, checkout, *args):
        result = self.run_command([
            "git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
            "-c", "core.fsmonitor=false", "-C", str(checkout), *args,
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def invoke(self, checkout, *args, authority=UNSET, extra_env=None, expected=0):
        env = dict(self.env)
        if authority is not UNSET:
            env["WORKSPACE_ORCHESTRATOR_ROOT"] = str(authority)
        env.update(extra_env or {})
        result = self.run_command([str(checkout / "bin/orchestrator-state.sh"), *args], env)
        self.assertEqual(result.returncode, expected, (args, result.stdout, result.stderr))
        if expected == 3:
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, REFUSAL)
        return result

    def assert_no_authority(self):
        self.assertEqual(list(self.root.rglob(".orchestrator")), [])

    def test_implicit_linked_refuses_before_dispatch_even_reads_and_test_override(self):
        for args in (("list",), ("show", "missing"), ("reconcile",), (),
                     ("create", "probe", "--scope", "fixture", "--kind", "monitor"),
                     ("claim", "probe", "--owner", "fixture"), ("list", "--help")):
            with self.subTest(args=args):
                self.invoke(self.linked, *args, expected=3)
                self.assert_no_authority()
        state_override = self.root / "override"
        self.invoke(self.linked, "list", expected=3,
                    extra_env={"ORCHESTRATOR_TEST_MODE": "1",
                               "ORCHESTRATOR_STATE_DIR": str(state_override)})
        self.assertFalse(state_override.exists())
        # A broken dispatcher would fail differently if admission ran it.
        (self.linked / ".agents/skills/workspace-orchestrator/run.sh").unlink()
        self.invoke(self.linked, "list", expected=3)
        self.invoke(self.linked, "--help", authority="")
        self.assert_no_authority()

    def test_primary_default_and_explicit_share_one_scope_with_linked_checkout(self):
        self.assertEqual(json.loads(self.invoke(self.main, "list").stdout), [])
        first = self.invoke(self.main, "create", "first", "--scope", "fixture:shared",
                            "--kind", "monitor")
        self.assertEqual(json.loads(first.stdout)["state"], "Ready")
        shown = self.invoke(self.linked, "show", "first", authority=self.main)
        self.assertEqual(json.loads(shown.stdout)["task_id"], "first")
        self.invoke(self.linked, "create", "second", "--scope", "fixture:shared",
                    "--kind", "monitor", authority=self.main, expected=4)
        listed = self.invoke(self.main, "list", authority=self.main)
        self.assertEqual([task["task_id"] for task in json.loads(listed.stdout)], ["first"])
        self.assertFalse((self.linked / ".orchestrator").exists())
        self.assertFalse((self.main / ".orchestrator/tasks/second").exists())
        self.assertEqual(len(list((self.main / ".orchestrator/scopes").glob("*.lock"))), 1)

    def test_archive_default_remains_supported_without_inherited_authority(self):
        archive = self.root / "archive"
        shutil.copytree(self.main, archive, ignore=shutil.ignore_patterns(".git"))
        self.assertFalse((archive / ".git").exists())
        # invoke passes our allowlisted env, never the validator's exported root.
        self.assertEqual(json.loads(self.invoke(archive, "list").stdout), [])
        self.assertTrue((archive / ".orchestrator/tasks").is_dir())
        self.assertFalse((self.main / ".orchestrator").exists())
        self.invoke(archive, "list", authority=self.main, expected=3)
        self.invoke(archive, "list", authority=archive, expected=3)

    def test_explicit_root_must_be_existing_absolute_physical_primary(self):
        alias = self.root / "alias"
        alias.symlink_to(self.main, target_is_directory=True)
        missing = self.root / "missing"
        ordinary = self.root / "not-git"
        ordinary.mkdir()
        roots = ("", "relative", "/", missing, ordinary, alias, str(alias / "bin/.."),
                 str(self.main) + "/", str(self.main) + "/.",
                 str(self.main) + "/bin/..", str(self.main) + "//", self.linked)
        for authority in roots:
            with self.subTest(authority=authority):
                self.invoke(self.linked, "list", authority=authority, expected=3)
                self.assert_no_authority()
        self.assertFalse(missing.exists())
        # A second valid primary repository is still the wrong authority.
        unrelated = self.root / "unrelated"
        unrelated.mkdir()
        self.git(unrelated, "init", "-b", "unrelated")
        for checkout in (self.main, self.linked):
            self.invoke(checkout, "list", authority=unrelated, expected=3)
        self.assert_no_authority()

    def test_git_metadata_identity_ignores_inherited_redirects_and_execution_config(self):
        sentinel = self.root / "executed"
        hook = self.root / "unsafe-monitor"
        hook.write_text(f"#!/bin/sh\ntouch '{sentinel}'\nexit 1\n", encoding="utf-8")
        hook.chmod(0o700)
        self.git(self.main, "config", "core.fsmonitor", str(hook))
        self.git(self.main, "config", "core.hooksPath", str(self.root))
        poisoned = {"GIT_DIR": str(self.root / "absent.git"),
                    "GIT_WORK_TREE": str(self.root / "absent"),
                    "GIT_COMMON_DIR": str(self.root / "absent-common"),
                    "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor",
                    "GIT_CONFIG_VALUE_0": str(hook), "GIT_CONFIG_GLOBAL": str(hook)}
        self.invoke(self.linked, "list", authority=self.main, extra_env=poisoned)
        self.assertFalse(sentinel.exists())
        self.assertFalse((self.linked / ".orchestrator").exists())
        unrelated = self.root / "unrelated"
        unrelated.mkdir()
        self.git(unrelated, "init", "-b", "unrelated")
        self.invoke(self.linked, "list", authority=unrelated, expected=3,
                    extra_env={"GIT_DIR": str(self.main / ".git"),
                               "GIT_WORK_TREE": str(self.main),
                               "GIT_COMMON_DIR": str(self.main / ".git")})
        self.assertFalse((unrelated / ".orchestrator").exists())
        # Malformed source metadata cannot accidentally discover a parent repo.
        (self.linked / ".git").write_text("gitdir: /nonexistent-fixture-gitdir\n", encoding="utf-8")
        self.invoke(self.linked, "list", authority=self.main, expected=3)

    def test_direct_skill_retains_explicit_non_git_consumer_behavior(self):
        consumer = self.root / "standalone-consumer"
        consumer.mkdir()
        env = dict(self.env, WORKSPACE_ORCHESTRATOR_ROOT=str(consumer))
        result = self.run_command([
            str(self.main / ".agents/skills/workspace-orchestrator/run.sh"), "state", "list",
        ], env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((consumer / ".orchestrator/tasks").is_dir())
        self.assertFalse((self.main / ".orchestrator").exists())


if __name__ == "__main__":
    unittest.main()
