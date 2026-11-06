#!/usr/bin/env python3
"""Actual copied state-CLI fixtures; execute only in an isolated validation guest."""

import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1]
SESSION = "a" * 32
OTHER_SESSION = "b" * 32
HEAD = "1" * 40


class CooperativeBindingTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cooperative-binding-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.skill = self.root / "skill"
        shutil.copytree(SOURCE / ".agents/skills/workspace-orchestrator/bin", self.skill,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        self.core = self.skill / "orchestrator-state.py"
        self.state = self.root / "state"
        self.env = {"PATH": os.defpath, "HOME": str(self.root), "TMPDIR": str(self.root),
                    "PYTHONDONTWRITEBYTECODE": "1", "ORCHESTRATOR_TEST_MODE": "1",
                    "ORCHESTRATOR_STATE_DIR": str(self.state)}
        spec = importlib.util.spec_from_file_location("fixture_cooperative_core", self.core)
        self.core_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.core_module)

    def invoke(self, *args, expected=0, env=None):
        result = subprocess.run([sys.executable, "-I", "-B", str(self.core), *args],
                                cwd=self.root, env=self.env if env is None else env,
                                capture_output=True, text=True, check=False, timeout=15)
        self.assertEqual(result.returncode, expected, (args, result.stdout, result.stderr))
        if expected == 0:
            return json.loads(result.stdout)
        return result

    def create(self, task="pilot", kind="implementation"):
        checkout = self.root / task
        checkout.mkdir()
        return self.invoke("create", task, "--scope", f"fixture:{task}", "--kind", kind,
                           "--worktree", str(checkout), "--base-sha", HEAD, "--head-sha", HEAD,
                           "--branch", f"task/{task}", "--repo", "example/fixture")

    def claim(self, task="pilot", session=SESSION, generation=0, revision=0, pid=None):
        return self.invoke("claim", task, "--owner", "fixture-owner", "--pid", str(os.getpid() if pid is None else pid),
                           "--session-id", session, "--expected-generation", str(generation),
                           "--expected-revision", str(revision))

    def live_child(self):
        child = subprocess.Popen([sys.executable, "-I", "-B", "-c", "import time; time.sleep(30)"],
                                 cwd=self.root, env=self.env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop_child, child)
        return child

    @staticmethod
    def stop_child(child):
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)

    @staticmethod
    def owned(record):
        return ["--expected-session-id", record["worker"]["session_id"],
                "--expected-worker-id", record["worker"]["worker_id"],
                "--expected-generation", str(record["cooperative_binding"]["generation"]),
                "--expected-revision", str(record["revision"])]

    @staticmethod
    def operator(record):
        return ["--operator-action", "--operator-reason", "fixture lifecycle decision",
                "--expected-generation", str(record["cooperative_binding"]["generation"]),
                "--expected-revision", str(record["revision"])]

    def snapshot(self):
        return {str(path.relative_to(self.state)): path.read_bytes()
                for path in self.state.rglob("*") if path.is_file()}

    def refuses_unchanged(self, *args, expected=3):
        before = self.snapshot()
        self.invoke(*args, expected=expected)
        self.assertEqual(self.snapshot(), before)

        self.assertFalse((self.state / "locks/coordinator.lock").exists())

    def persist_fixture(self, path, data):
        path.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    def task_path(self, task="pilot"):
        return self.state / "tasks" / task / "task.json"

    def test_actual_claim_record_release_reclaim_and_stale_generation(self):
        initial = self.create()
        self.assertEqual(initial["schema_version"], 2)
        claimed = self.claim()
        self.assertEqual(claimed["schema_version"], 3)
        self.assertEqual(claimed["cooperative_binding"], {"session_id": SESSION, "generation": 1})
        self.assertEqual(claimed["worker"]["session_id"], SESSION)
        implementing = self.invoke("transition", "pilot", "Implementing", *self.owned(claimed))
        lane = self.state / "implementation" / f"{implementing['leases']['implementation_lane']}.lock/owner.json"
        self.assertEqual(json.loads(lane.read_text()), implementing["worker"])
        recorded = self.invoke("record", "pilot", "validation", "fixture validation", *self.owned(implementing))
        blocked = self.invoke("transition", "pilot", "Blocked", *self.owned(recorded))
        self.assertIsNone(blocked["worker"])
        self.assertEqual(blocked["cooperative_binding"]["generation"], 1)
        self.assertEqual(list((self.state / "slots").iterdir()), [])
        self.assertEqual(list((self.state / "implementation").iterdir()), [])
        self.refuses_unchanged("transition", "pilot", "Ready")
        ready = self.invoke("transition", "pilot", "Ready", *self.operator(blocked))
        second = self.claim(session=OTHER_SESSION, generation=1, revision=ready["revision"])
        self.assertEqual(second["cooperative_binding"]["generation"], 2)
        self.assertNotEqual(second["worker"]["worker_id"], claimed["worker"]["worker_id"])
        stale = self.owned(second)
        stale[5] = "1"  # Copied old generation with otherwise current expectations.
        self.refuses_unchanged("record", "pilot", "validation", "stale", *stale, expected=4)
        self.assertEqual(self.invoke("show", "pilot"), second)
        self.assertEqual(self.invoke("list"), [second])

    def test_every_owned_mutator_requires_all_flags_before_effects(self):
        self.create()
        claimed = self.claim()
        commands = [("record", "pilot", "validation", "fixture"),
                    ("update-head", "pilot", HEAD), ("transition", "pilot", "Implementing"),
                    ("resolve-finding", "pilot", "--finding-index", "0", "--finding-sha256", "0" * 64,
                     "--head-sha", HEAD, "--disposition", "fixed", "--reviewer", "fixture-reviewer",
                     "--evidence", "fixture evidence")]
        flags = self.owned(claimed)
        for command in commands:
            for index in range(0, len(flags), 2):
                # Legacy resolve-finding already requires revision at argparse.
                expected = 2 if command[0] == "resolve-finding" and index == 6 else 3
                with self.subTest(command=command[0], missing=flags[index]):
                    self.refuses_unchanged(*command, *(flags[:index] + flags[index + 2:]), expected=expected)
            for index, value in ((1, OTHER_SESSION), (3, "f" * 32), (5, "0"), (7, "0")):
                bad = list(flags)
                bad[index] = value
                with self.subTest(command=command[0], mismatch=flags[index - 1]):
                    self.refuses_unchanged(*command, *bad, expected=4)
        self.refuses_unchanged("record", "pilot", "validation", "fixture", *self.operator(claimed), expected=4)
        self.refuses_unchanged("transition", "pilot", "Cancelled", *self.operator(claimed))

    def test_claim_opt_in_inputs_and_ready_only(self):
        self.create()
        prefix = ("claim", "pilot", "--owner", "fixture", "--pid", str(os.getpid()))
        for extra in (("--session-id", SESSION),
                      ("--session-id", SESSION, "--expected-generation", "0"),
                      ("--session-id", SESSION, "--expected-revision", "0"),
                      ("--session-id", "non ASCII é", "--expected-generation", "0", "--expected-revision", "0"),
                      ("--session-id", "x" * 129, "--expected-generation", "0", "--expected-revision", "0"),
                      ("--session-id", SESSION, "--expected-generation", "-1", "--expected-revision", "0")):
            self.refuses_unchanged(*prefix, *extra)
        self.refuses_unchanged(*prefix, "--session-id", SESSION, "--expected-generation", "1",
                              "--expected-revision", "0", expected=4)
        claimed = self.claim()
        self.refuses_unchanged(*prefix, expected=4)
        blocked = self.invoke("transition", "pilot", "Blocked", *self.owned(claimed))
        self.refuses_unchanged(*prefix, "--session-id", OTHER_SESSION, "--expected-generation", "1",
                              "--expected-revision", str(blocked["revision"]), expected=4)
        self.refuses_unchanged("transition", "pilot", "Ready", "--operator-action",
                              "--expected-generation", "1", "--expected-revision", str(blocked["revision"]))

    def test_claim_failure_rolls_back_and_generation_limit_is_bounded(self):
        self.create()
        before = self.snapshot()
        env = dict(self.env, ORCHESTRATOR_TEST_FAIL_CLAIM_WRITE="1")
        self.invoke("claim", "pilot", "--owner", "fixture", "--pid", str(os.getpid()),
                    "--session-id", SESSION, "--expected-generation", "0", "--expected-revision", "0",
                    env=env, expected=3)
        self.assertEqual(self.snapshot(), before)
        claimed = self.claim()
        blocked = self.invoke("transition", "pilot", "Blocked", *self.owned(claimed))
        ready = self.invoke("transition", "pilot", "Ready", *self.operator(blocked))
        ready["revision"] = (1 << 63) - 1
        ready["cooperative_binding"]["generation"] = (1 << 63) - 1
        self.persist_fixture(self.task_path(), ready)
        self.refuses_unchanged("claim", "pilot", "--owner", "fixture", "--pid", str(os.getpid()),
                              "--session-id", OTHER_SESSION, "--expected-generation", str((1 << 63) - 1),
                              "--expected-revision", str((1 << 63) - 1), expected=4)

    def test_malformed_binding_worker_and_all_reservation_metadata(self):
        self.create()
        claimed = self.claim()
        implementing = self.invoke("transition", "pilot", "Implementing", *self.owned(claimed))
        malformed = []
        for field, value in (("generation", True), ("generation", 0), ("generation", -1),
                             ("generation", 1 << 63), ("generation", "1"), ("generation", 1.0),
                             ("session_id", ""), ("session_id", "é"), ("session_id", "a" * 129)):
            item = copy.deepcopy(implementing)
            item["cooperative_binding"][field] = value
            malformed.append(item)
        for field, value in (("session_id", OTHER_SESSION), ("generation", True),
                             ("generation", 2), ("owner", "other-owner"), ("extra", "unsupported")):
            item = copy.deepcopy(implementing)
            item["worker"][field] = value
            malformed.append(item)
        for binding in (None, {}, {"session_id": SESSION, "generation": 1, "extra": 0}):
            item = copy.deepcopy(implementing)
            item["cooperative_binding"] = binding
            malformed.append(item)
        for item in malformed:
            self.persist_fixture(self.task_path(), item)
            self.refuses_unchanged("record", "pilot", "validation", "fixture", *self.owned(implementing))
        self.persist_fixture(self.task_path(), implementing)
        for group, index in (("slots", implementing["leases"]["global_slot"]),
                             ("implementation", implementing["leases"]["implementation_lane"]),
                             ("scopes", implementing["scope_key"])):
            path = self.state / group / f"{index}.lock/owner.json"
            original = json.loads(path.read_text())
            corrupt = dict(original)
            corrupt["owner" if group == "scopes" else "session_id"] = OTHER_SESSION
            self.persist_fixture(path, corrupt)
            self.refuses_unchanged("record", "pilot", "validation", "fixture", *self.owned(implementing))
            self.refuses_unchanged("create", "extra", "--scope", "extra", "--kind", "monitor")
            self.persist_fixture(path, original)
        for group, index in (("slots", implementing["leases"]["global_slot"]),
                             ("implementation", implementing["leases"]["implementation_lane"])):
            path = self.state / group / f"{index}.lock/owner.json"
            original = json.loads(path.read_text())
            corrupt = dict(original, generation=True)
            self.persist_fixture(path, corrupt)
            self.refuses_unchanged("record", "pilot", "validation", "fixture", *self.owned(implementing))
            self.persist_fixture(path, original)

    def test_public_and_old_readers_refuse_before_domain_operations(self):
        self.create()
        claimed = self.claim()
        with self.assertRaises(self.core_module.UnknownError):
            self.core_module.read_task(self.state, "pilot")
        with self.assertRaises(self.core_module.UnknownError):
            self.core_module.validate_record(claimed)
        with self.assertRaises(self.core_module.UnknownError):
            self.core_module.command_list(self.state)
        self.assertEqual(self.core_module.read_task(self.state, "pilot", allow_bound=True), claimed)
        # The previous core's explicit SCHEMA=2 check, applied to actual CLI state.
        def old_reader(record):
            if record["schema_version"] != 2:
                raise ValueError("task schema or revision is invalid")
            return record
        with self.assertRaises(ValueError):
            old_reader(claimed)
        before = self.snapshot()
        for controller, args in (("foreground-delivery.py", ["pilot"]),
                                 ("review-evidence.py", ["pilot"])):
            result = subprocess.run([sys.executable, "-I", "-B", str(self.skill / controller), *args],
                                    cwd=self.root, env=self.env, capture_output=True,
                                    text=True, check=False, timeout=15)
            self.assertEqual(result.returncode, 3, (controller, result.stdout, result.stderr))
            self.assertEqual(self.snapshot(), before)

    def test_verified_absent_operator_cancellation_and_lock_contention(self):
        self.create()
        child = self.live_child()
        claimed = self.claim(pid=child.pid)
        self.assertEqual(claimed["worker"]["pid"], child.pid)
        self.assertTrue(claimed["worker"]["process_start"])
        lock = self.state / "locks/coordinator.lock"
        lock.mkdir()
        before = self.snapshot()
        self.invoke("record", "pilot", "validation", "fixture", *self.owned(claimed), expected=4)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(lock.is_dir())
        lock.rmdir()
        # Reap the actual claimed child, then require real platform ps evidence.
        self.stop_child(child)
        self.assertEqual(self.core_module.process_identity(child.pid), ("absent", None))
        cancelled = self.invoke("transition", "pilot", "Cancelled", *self.operator(claimed))
        self.assertEqual(cancelled["state"], "Cancelled")
        self.assertIsNone(cancelled["worker"])
        self.assertEqual(cancelled["cooperative_binding"]["generation"], 1)
        self.assertEqual(cancelled["next_action"], "fixture lifecycle decision")

    def test_standalone_bound_monitor_refuses_before_config_poll_files_or_dispatch(self):
        self.create(kind="monitor")
        self.claim()
        config = self.root / "monitor-config.json"
        config.write_text(json.dumps({"schema_version": 1, "repositories": ["example/fixture"],
                                     "project": None}), encoding="utf-8")
        tools = self.root / "monitor-tools"
        tools.mkdir()
        marker = self.root / "forge-dispatched"
        gh = tools / "gh"
        gh.write_text(f"#!/bin/sh\n: > '{marker}'\nprintf '%s\\n' '[]'\n", encoding="utf-8")
        gh.chmod(0o700)
        env = dict(self.env, PATH=str(tools) + os.pathsep + os.defpath)
        before = self.snapshot()
        for selected_config in (config, self.root / "missing-config"):
            for flags in ([], ["--durable"], ["--loop"]):
                result = subprocess.run([sys.executable, "-I", "-B", str(self.skill / "orchestrator-monitor.py"),
                                         "--task-id", "pilot", "--config", str(selected_config), *flags],
                                        cwd=self.root, env=env, capture_output=True, text=True,
                                        check=False, timeout=15)
                self.assertEqual(result.returncode, 3, (result.stdout, result.stderr))
                self.assertIn("task schema is unsupported", result.stderr)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse((self.state / "monitor").exists())
                self.assertFalse(marker.exists())
        # A pre-existing monitor directory must also remain byte-identical.
        monitor_dir = self.state / "monitor"
        monitor_dir.mkdir(mode=0o700)
        checkpoint = monitor_dir / "checkpoint.json"
        checkpoint.write_text('{"fixture":"preserve"}\n', encoding="utf-8")
        before = self.snapshot()
        result = subprocess.run([sys.executable, "-I", "-B", str(self.skill / "orchestrator-monitor.py"),
                                 "--task-id", "pilot", "--config", str(config), "--durable"],
                                cwd=self.root, env=env, capture_output=True, text=True, check=False, timeout=15)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(marker.exists())

    def test_monitor_schema1_and_schema2_read_compatibility_and_durable_guard(self):
        self.create(kind="monitor")
        legacy = self.invoke("claim", "pilot", "--owner", "fixture", "--pid", str(os.getpid()))
        spec = importlib.util.spec_from_file_location("fixture_monitor", self.skill / "orchestrator-monitor.py")
        monitor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(monitor)
        root = self.state / "monitor"
        with mock.patch.dict(os.environ, self.env, clear=True):
            for schema in (1, 2):
                self.persist_fixture(self.task_path(), dict(legacy, schema_version=schema))
                monitor.validate_monitor_task(root, "pilot")
            for schema in (True, "2", 3, 4):
                self.persist_fixture(self.task_path(), dict(legacy, schema_version=schema))
                with self.assertRaisesRegex(ValueError, "schema is unsupported"):
                    monitor.validate_monitor_task(root, "pilot")
            with mock.patch.object(monitor, "journal_module") as journal:
                with self.assertRaisesRegex(ValueError, "schema is unsupported"):
                    monitor.durable_poll(root, {}, self.root / "missing-config", "pilot")
                journal.assert_not_called()
        self.assertFalse(root.exists())

    def test_bound_execution_observation_refuses_before_definition_config_or_runtime(self):
        self.create()
        self.claim()
        before = self.snapshot()
        # Missing definition must not mask the earlier bound-task refusal.
        command = [sys.executable, "-I", "-B", str(self.skill / "execution-observe.py"), "pilot",
                   "--operation-id", "fixture", "--definition", str(self.root / "missing-definition"),
                   "--definition-sha256", "a" * 64, "--expected-revision", "1"]
        for flags in ([], ["--reconcile-stopped"]):
            result = subprocess.run([*command, *flags], cwd=self.root, env=self.env,
                                    capture_output=True, text=True, check=False, timeout=15)
            self.assertEqual(result.returncode, 3, (result.stdout, result.stderr))
            self.assertEqual(self.snapshot(), before)
            self.assertFalse((self.state / "execution-docker-config").exists())
            self.assertFalse((self.state / "review-artifacts").exists())
        spec = importlib.util.spec_from_file_location("fixture_observer", self.skill / "execution-observe.py")
        observer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(observer)
        c = observer.dependency("review-collect")
        coordinator = observer.dependency("orchestrator-state")
        runner = observer.dependency("review-run")
        modules = {"review-collect": c, "orchestrator-state": coordinator, "review-run": runner}
        with (mock.patch.dict(os.environ, self.env, clear=True),
              mock.patch.object(sys, "argv", command[3:]),
              mock.patch.object(observer, "dependency", side_effect=modules.__getitem__),
              mock.patch.object(c, "read_bytes") as read_definition,
              mock.patch.object(runner, "binary_digest") as binary_digest,
              mock.patch.object(observer, "inspect_backend") as backend,
              mock.patch.object(observer, "capture") as capture,
              redirect_stdout(io.StringIO())):
            self.assertEqual(observer.main(), 3)
            read_definition.assert_not_called()
            binary_digest.assert_not_called()
            backend.assert_not_called()
            capture.assert_not_called()
        self.assertEqual(self.snapshot(), before)

        # Opt-in between the early read and lock-held read must still refuse
        # before runtime configuration or backend calls.
        definition = {"docker_binary": "/fixture/docker", "docker_sha256": "b" * 64}
        with (mock.patch.dict(os.environ, self.env, clear=True),
              mock.patch.object(sys, "argv", command[3:]),
              mock.patch.object(observer, "dependency", side_effect=modules.__getitem__),
              mock.patch.object(coordinator, "read_task", side_effect=[{}, coordinator.UnknownError("unsupported schema 3")]) as reads,
              mock.patch.object(c, "read_bytes", return_value=b"{}"),
              mock.patch.object(c, "decode", return_value=definition),
              mock.patch.object(observer, "digest", return_value="a" * 64),
              mock.patch.object(observer, "validate_definition"),
              mock.patch.object(runner, "binary_digest", return_value="b" * 64),
              mock.patch.object(observer, "inspect_backend") as backend,
              redirect_stdout(io.StringIO())):
            self.assertEqual(observer.main(), 3)
            self.assertEqual(reads.call_count, 2)
            backend.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.state / "execution-docker-config").exists())

    def test_bound_reconcile_preflight_preserves_earlier_legacy_and_interrupted_intent(self):
        self.create("a-legacy", kind="monitor")
        child = self.live_child()
        self.invoke("claim", "a-legacy", "--owner", "legacy", "--pid", str(child.pid))
        # A genuinely exited worker would normally be blocked during reconcile.
        self.stop_child(child)
        self.assertEqual(self.core_module.process_identity(child.pid), ("absent", None))
        self.create("z-bound", kind="monitor")
        bound = self.claim("z-bound")
        self.refuses_unchanged("reconcile")
        self.refuses_unchanged("reconcile", "a-legacy")
        bound["transition_intent"] = "Blocked"
        self.persist_fixture(self.task_path("z-bound"), bound)
        self.refuses_unchanged("reconcile", "z-bound")
        self.refuses_unchanged("transition", "z-bound", "Blocked", *self.owned(bound))
        self.refuses_unchanged("record", "z-bound", "validation", "fixture", *self.owned(bound))

    def test_schema2_defaults_and_schema1_migration_are_retained(self):
        initial = self.create()
        claimed = self.invoke("claim", "pilot", "--owner", "legacy", "--pid", str(os.getpid()))
        self.assertEqual(claimed["schema_version"], 2)
        self.assertNotIn("cooperative_binding", claimed)
        self.assertNotIn("session_id", claimed["worker"])
        recorded = self.invoke("record", "pilot", "validation", "legacy validation")
        self.invoke("transition", "pilot", "Blocked")
        old = copy.deepcopy(initial)
        old["schema_version"] = 1
        for field in ("tracker_type", "tracker_number", "head_sha", "reviewed_sha", "transition_intent", "rework_count"):
            del old[field]
        upgraded = self.core_module.validate_record(old)
        self.assertEqual(upgraded["schema_version"], 2)
        self.assertEqual(recorded["validation"], ["legacy validation"])
        downgraded = dict(initial, cooperative_binding={"session_id": SESSION, "generation": 1})
        with self.assertRaises(self.core_module.UnknownError):
            self.core_module.validate_record(downgraded)

    def test_owned_finding_resolution_and_head_cli(self):
        self.create()
        claimed = self.claim()
        reviewing = self.invoke("transition", "pilot", "Reviewing", *self.owned(claimed))
        finding = self.invoke("record", "pilot", "finding", "fixture finding", *self.owned(reviewing))
        resolved = self.invoke("resolve-finding", "pilot", "--finding-index", "0",
                               "--finding-sha256", self.core_module.scope_key("fixture finding"),
                               "--head-sha", HEAD, "--disposition", "fixed", "--reviewer", "independent-fixture",
                               "--evidence", "fixture evidence", *self.owned(finding))
        self.assertEqual(resolved["legacy_finding_dispositions"]["history"][0]["disposition"], "fixed")
        blocked = self.invoke("transition", "pilot", "Blocked", *self.owned(resolved))
        ready = self.invoke("transition", "pilot", "Ready", *self.operator(blocked))
        claimed = self.claim(generation=1, revision=ready["revision"])
        # Mock only external Git metadata; update-head is still the actual CLI.
        tools = self.root / "tools"
        tools.mkdir()
        git = tools / "git"
        git.write_text("#!/bin/sh\ncase \"$*\" in\n"
                       f"*--show-toplevel) printf '%s\\n' '{self.root / 'pilot'}';;\n"
                       "*symbolic-ref*) printf '%s\\n' task/pilot;;\n"
                       f"*'rev-parse HEAD') printf '%s\\n' '{'2' * 40}';;\n"
                       "*merge-base*) exit 0;;\n*) exit 9;;\nesac\n", encoding="utf-8")
        git.chmod(0o700)
        env = dict(self.env, PATH=str(tools) + os.pathsep + os.defpath)
        updated = self.invoke("update-head", "pilot", "2" * 40, *self.owned(claimed), env=env)
        self.assertEqual(updated["head_sha"], "2" * 40)
        self.assertEqual(updated["cooperative_binding"], claimed["cooperative_binding"])


if __name__ == "__main__":
    unittest.main()
