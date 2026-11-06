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


def previous_schema3_extension_excerpt(raw, *, allow_bound=False):
    """Actual validate_record excerpt, not a complete previous-core reader.

    Source: aeaa68ce36ab515d76640205326be0e4df8142ad,
    .agents/skills/workspace-orchestrator/bin/orchestrator-state.py:292-295,
    307-319. Copied verbatim schema/extension checks and required-field set;
    omitted migration and missing-field checks. No Git history needed at runtime.
    """
    BOUND_SCHEMA = 3
    UnknownError = ValueError
    if type(raw.get("schema_version")) is not int:
        raise UnknownError("task schema is invalid")
    if raw.get("schema_version") == BOUND_SCHEMA and not allow_bound:
        raise UnknownError("cooperative schema 3 is unsupported by this controller")
    required = {
        "schema_version", "task_id", "state", "scope", "scope_key", "kind",
        "owner", "repo", "branch", "worktree", "base_sha", "owned_paths",
        "tracker_type", "tracker_number", "head_sha", "reviewed_sha",
        "restricted_paths", "acceptance_criteria", "dependencies", "reviewers",
        "findings", "validation", "next_action", "worker", "leases",
        "transition_intent", "rework_count", "revision", "created_at", "updated_at",
    }
    if raw["schema_version"] == BOUND_SCHEMA and raw.keys() - required - {"cooperative_binding", "legacy_finding_dispositions"}:
        raise UnknownError("cooperative core-only task has unsupported retained extensions")


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
        child = subprocess.Popen([sys.executable, "-I", "-B", "-c", "import time; time.sleep(120)"],
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

    def interruption(self, record, target, boundary="intent"):
        """Intercept real fixture-local writes/releases after a durable boundary."""
        core = self.core_module
        write, release = core.write_task, core.release_dir

        def trace_write(root, value, **kwargs):
            write(root, value, **kwargs)
            if boundary == "intent" and value["transition_intent"] == target:
                raise RuntimeError("fixture interrupted after durable intent")

        def trace_release(path, token):
            release(path, token)
            if path.parent.name == boundary:
                raise RuntimeError("fixture interrupted after exact release")

        args = core.parser().parse_args(["transition", record["task_id"], target, *self.owned(record)])
        with (mock.patch.dict(os.environ, self.env, clear=True),
              mock.patch.object(core, "write_task", side_effect=trace_write),
              mock.patch.object(core, "release_dir", side_effect=trace_release),
              self.assertRaisesRegex(RuntimeError, "fixture interrupted")):
            core.command_transition(args, self.state)
        return self.invoke("show", record["task_id"])

    def interrupted_worker(self, source="Implementing", target="Blocked", boundary="intent"):
        self.create()
        child = self.live_child()
        record = self.claim(pid=child.pid)
        if source != "Claimed":
            record = self.invoke("transition", "pilot", source, *self.owned(record))
        record = self.interruption(record, target, boundary)
        self.stop_child(child)
        self.assertEqual(self.core_module.process_identity(child.pid), ("absent", None))
        return record

    def recovery(self, record):
        return ["reconcile", "--recover", record["task_id"], *self.operator(record)]

    def directory_snapshot(self):
        # Coordinator-lock parent timestamps reflect taking the guard, not task
        # mutation. Every task/reservation directory identity and mode is kept.
        return {str(path.relative_to(self.state)): (path.lstat().st_ino, path.lstat().st_mode,
                                                   path.lstat().st_mtime_ns)
                for group in ("tasks", "scopes", "slots", "implementation")
                for path in (self.state / group).rglob("*") if path.is_dir()}

    def recovery_refuses(self, *args, expected=3):
        directories = self.directory_snapshot()
        self.refuses_unchanged(*args, expected=expected)
        self.assertEqual(self.directory_snapshot(), directories)

    def assert_recovered(self, old, result):
        new = result["changed"][0]
        self.assertEqual(new["state"], "Blocked")
        self.assertIsNone(new["worker"])
        self.assertIsNone(new["transition_intent"])
        self.assertEqual(new["cooperative_binding"], old["cooperative_binding"])
        for field in ("findings", "head_sha", "reviewed_sha", "rework_count", "validation", "reviewers"):
            self.assertEqual(new[field], old[field])
        self.assertEqual(new["leases"], dict(old["leases"], global_slot=None, implementation_lane=None))
        self.assertEqual(new["transition_recovery"]["phase"], "settled")
        self.assertEqual(list((self.state / "slots").iterdir()), [])
        self.assertEqual(list((self.state / "implementation").iterdir()), [])
        return new

    def test_recovery_complete_intent_preserves_unrelated_task_and_scope(self):
        self.create("unrelated", kind="monitor")
        record = self.interrupted_worker()
        unrelated = self.task_path("unrelated").read_bytes()
        scope = self.state / "scopes" / f"{record['scope_key']}.lock"
        before = (scope.stat().st_ino, scope.stat().st_mode, scope.stat().st_mtime_ns,
                  (scope / "owner.json").read_bytes())
        settled = self.assert_recovered(record, self.invoke(*self.recovery(record)))
        self.assertEqual(settled["revision"], record["revision"] + 2)
        self.assertEqual(self.task_path("unrelated").read_bytes(), unrelated)
        self.assertEqual((scope.stat().st_ino, scope.stat().st_mode, scope.stat().st_mtime_ns,
                          (scope / "owner.json").read_bytes()), before)
        self.recovery_refuses(*self.recovery(settled))
        self.recovery_refuses("reconcile")

    def test_recovery_partial_slot_cleanup_and_rework_no_double_increment(self):
        record = self.interrupted_worker(source="Reviewing", target="Rework", boundary="slots")
        self.assertEqual(record["rework_count"], 1)
        new = self.assert_recovered(record, self.invoke(*self.recovery(record)))
        self.assertEqual(new["rework_count"], 1)

    def test_recovery_partial_lane_release_from_implementing(self):
        record = self.interrupted_worker(target="Reviewing", boundary="implementation")
        self.assert_recovered(record, self.invoke(*self.recovery(record)))

    def pending_before_cleanup(self, record):
        core = self.core_module
        with (mock.patch.dict(os.environ, self.env, clear=True),
              mock.patch.object(core, "release_capacity", side_effect=RuntimeError("fixture before cleanup")),
              self.assertRaisesRegex(RuntimeError, "before cleanup")):
            core.command_reconcile(core.parser().parse_args(self.recovery(record)), self.state)
        return self.invoke("show", "pilot")

    def test_recovery_original_full_release_lane_first_refuses(self):
        record = self.interrupted_worker()
        lane = self.state / "implementation" / f"{record['leases']['implementation_lane']}.lock"
        (lane / "owner.json").unlink()
        lane.rmdir()
        self.recovery_refuses(*self.recovery(record))
        self.assertNotIn("transition_recovery", json.loads(self.task_path().read_text()))

    def test_recovery_pending_truthful_both_present_lane_first_refuses(self):
        record = self.interrupted_worker(target="Reviewing")
        pending = self.pending_before_cleanup(record)
        self.assertEqual(pending["transition_recovery"]["capacity_observed"],
                         {"slots": True, "implementation": True})
        lane = self.state / "implementation" / f"{pending['leases']['implementation_lane']}.lock"
        (lane / "owner.json").unlink()
        lane.rmdir()
        self.recovery_refuses(*self.recovery(pending))
        forged = copy.deepcopy(pending)
        forged["transition_recovery"]["capacity_observed"]["implementation"] = False
        self.persist_fixture(self.task_path(), forged)
        self.recovery_refuses(*self.recovery(pending))

    def test_recovery_pending_forged_full_release_observation_refuses(self):
        record = self.interrupted_worker()
        pending = self.pending_before_cleanup(record)
        forged = copy.deepcopy(pending)
        receipt = forged["transition_recovery"]
        receipt["capacity_observed"]["implementation"] = False
        # Even a recomputed correlation cannot make lane-first original full
        # release reachable. This is not a claim of tamper-proof storage.
        receipt["correlation_sha256"] = self.core_module.recovery_digest(
            {key: value for key, value in receipt.items() if key not in {"phase", "correlation_sha256"}})
        self.persist_fixture(self.task_path(), forged)
        self.recovery_refuses(*self.recovery(pending))

    def test_recovery_pending_original_reviewing_lane_absent_accepted(self):
        record = self.interrupted_worker(target="Reviewing", boundary="implementation")
        pending = self.pending_before_cleanup(record)
        self.assertEqual(pending["transition_recovery"]["capacity_observed"],
                         {"slots": True, "implementation": False})
        self.assertTrue((self.state / "slots" / f"{record['leases']['global_slot']}.lock").exists())
        lane = self.state / "implementation" / f"{record['leases']['implementation_lane']}.lock"
        lane.mkdir(mode=0o700)
        self.persist_fixture(lane / "owner.json", record["worker"])
        self.recovery_refuses(*self.recovery(pending))
        (lane / "owner.json").unlink()
        lane.rmdir()
        self.assert_recovered(record, self.invoke(*self.recovery(pending)))

    def test_previous_schema3_extension_excerpt_refuses_pending_and_settled_receipts(self):
        record = self.interrupted_worker()
        before = self.snapshot()
        previous_schema3_extension_excerpt(record, allow_bound=True)
        self.assertEqual(self.snapshot(), before)
        pending = self.pending_before_cleanup(record)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "unsupported retained extensions"):
            previous_schema3_extension_excerpt(pending, allow_bound=True)
        self.assertEqual(self.snapshot(), before)
        settled = self.assert_recovered(record, self.invoke(*self.recovery(pending)))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "unsupported retained extensions"):
            previous_schema3_extension_excerpt(settled, allow_bound=True)
        self.assertEqual(self.snapshot(), before)

    def test_recovery_implementing_intent_with_durable_lane(self):
        record = self.interrupted_worker(source="Claimed", target="Implementing")
        self.assertIsNotNone(record["leases"]["implementation_lane"])
        self.assert_recovered(record, self.invoke(*self.recovery(record)))

    def test_recovery_pending_receipt_precedes_cleanup_and_retry(self):
        record = self.interrupted_worker(source="Claimed", target="Implementing")
        core = self.core_module
        release = core.release_dir

        def trace_release(path, token):
            persisted = json.loads(self.task_path().read_text())
            self.assertEqual(persisted["transition_recovery"]["phase"], "pending")
            release(path, token)
            if path.parent.name == "slots":
                raise RuntimeError("fixture pending cleanup interruption")

        args = core.parser().parse_args(self.recovery(record))
        with (mock.patch.dict(os.environ, self.env, clear=True),
              mock.patch.object(core, "release_dir", side_effect=trace_release),
              self.assertRaisesRegex(RuntimeError, "pending cleanup")):
            core.command_reconcile(args, self.state)
        pending = self.invoke("show", "pilot")
        self.assertEqual(pending["revision"], record["revision"] + 1)
        self.recovery_refuses(*self.recovery(record), expected=4)
        for command in (("record", "pilot", "validation", "pending"),
                        ("update-head", "pilot", HEAD), ("transition", "pilot", "Blocked")):
            self.recovery_refuses(*command, *self.owned(pending))
        self.recovery_refuses("claim", "pilot", "--owner", "fixture")
        self.recovery_refuses("create", "extra", "--scope", "extra", "--kind", "monitor")
        final = self.assert_recovered(record, self.invoke(*self.recovery(pending)))
        self.assertEqual(final["revision"], record["revision"] + 2)

    def test_recovery_pending_snapshot_identity_changes_refuse_before_release(self):
        record = self.interrupted_worker()
        core = self.core_module
        args = core.parser().parse_args(self.recovery(record))
        with (mock.patch.dict(os.environ, self.env, clear=True),
              mock.patch.object(core, "release_capacity", side_effect=RuntimeError("fixture before cleanup")),
              self.assertRaisesRegex(RuntimeError, "before cleanup")):
            core.command_reconcile(args, self.state)
        pending = self.invoke("show", "pilot")
        changed_reason = self.recovery(pending)
        changed_reason[changed_reason.index("--operator-reason") + 1] = "different rationale"
        self.recovery_refuses(*changed_reason, expected=4)
        for field, value in (("owner", "changed"), ("token", "f" * 32), ("generation", 2),
                             ("process_start", "changed"), ("worker_id", "f" * 32)):
            lane = self.state / "implementation" / f"{pending['leases']['implementation_lane']}.lock/owner.json"
            original = json.loads(lane.read_text())
            self.persist_fixture(lane, dict(original, **{field: value}))
            self.recovery_refuses(*self.recovery(pending))
            self.persist_fixture(lane, original)
        for field, value in (("source", "Claimed"), ("intent", "Reviewing"), ("generation", 2),
                             ("base_revision", 0), ("pending_revision", True), ("extra", 1)):
            changed = copy.deepcopy(pending)
            changed["transition_recovery"][field] = value
            self.persist_fixture(self.task_path(), changed)
            self.recovery_refuses(*self.recovery(pending))
        self.persist_fixture(self.task_path(), pending)
        for field, value in (("worker_id", "f" * 32), ("process_start", "changed"), ("token", "f" * 32)):
            changed = copy.deepcopy(pending)
            changed["worker"][field] = value
            self.persist_fixture(self.task_path(), changed)
            self.recovery_refuses(*self.recovery(pending))
        self.persist_fixture(self.task_path(), pending)
        changed = copy.deepcopy(pending)
        changed["next_action"] = "changed retained snapshot"
        self.persist_fixture(self.task_path(), changed)
        self.recovery_refuses(*self.recovery(pending))
        self.persist_fixture(self.task_path(), pending)
        self.assert_recovered(record, self.invoke(*self.recovery(pending)))

    def test_recovery_pending_all_capacity_released_before_final_write(self):
        record = self.interrupted_worker(source="Claimed", target="Implementing")
        core = self.core_module
        atomic = core.atomic_json

        def trace_atomic(path, value):
            if value.get("transition_recovery", {}).get("phase") == "settled":
                raise RuntimeError("fixture before final write")
            atomic(path, value)

        args = core.parser().parse_args(self.recovery(record))
        with (mock.patch.dict(os.environ, self.env, clear=True),
              mock.patch.object(core, "atomic_json", side_effect=trace_atomic),
              self.assertRaisesRegex(RuntimeError, "before final write")):
            core.command_reconcile(args, self.state)
        pending = self.invoke("show", "pilot")
        self.assertEqual(list((self.state / "slots").iterdir()), [])
        self.assertEqual(list((self.state / "implementation").iterdir()), [])
        empty = self.state / "slots" / f"{pending['leases']['global_slot']}.lock"
        empty.mkdir(mode=0o700)
        self.recovery_refuses(*self.recovery(pending))
        empty.rmdir()
        self.assert_recovered(record, self.invoke(*self.recovery(pending)))

    def test_recovery_inputs_live_foreign_reused_and_unknown_process_refuse(self):
        self.create()
        child = self.live_child()
        claimed = self.claim(pid=child.pid)
        record = self.interruption(claimed, "Blocked")
        self.recovery_refuses(*self.recovery(record))
        for suffix, expected in (([], 3), (["--operator-action"], 3),
                                 (["--operator-action", "--operator-reason", "fixture"], 3),
                                 ([*self.operator(record), "--expected-revision", "0"], 4),
                                 ([*self.operator(record), "--expected-generation", "0"], 4)):
            self.recovery_refuses("reconcile", "--recover", "pilot", *suffix, expected=expected)
        self.recovery_refuses("reconcile", "pilot", "--recover", "pilot", *self.operator(record), expected=2)
        self.recovery_refuses("reconcile", "--rec", "pilot", *self.operator(record), expected=2)
        self.recovery_refuses("reconcile", *self.operator(record), expected=2)
        for status, start in (("alive", "reused process"), ("unknown", None)):
            with (mock.patch.dict(os.environ, self.env, clear=True),
                  mock.patch.object(self.core_module, "process_identity", return_value=(status, start)),
                  self.assertRaises(self.core_module.UnknownError)):
                before, directories = self.snapshot(), self.directory_snapshot()
                self.core_module.command_reconcile(self.core_module.parser().parse_args(self.recovery(record)), self.state)
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(self.directory_snapshot(), directories)
        foreign = copy.deepcopy(record)
        foreign["worker"]["hostname"] = "fixture-foreign-host"
        self.persist_fixture(self.task_path(), foreign)
        self.recovery_refuses(*self.recovery(foreign))
        self.persist_fixture(self.task_path(), record)
        self.stop_child(child)
        self.assert_recovered(record, self.invoke(*self.recovery(record)))

    def test_recovery_missing_scope_empty_duplicate_and_changed_metadata_refuse(self):
        record = self.interrupted_worker()
        for group, index in (("scopes", record["scope_key"]), ("slots", record["leases"]["global_slot"]),
                             ("implementation", record["leases"]["implementation_lane"])):
            lock = self.state / group / f"{index}.lock"
            owner = lock / "owner.json"
            original = json.loads(owner.read_text())
            self.persist_fixture(owner, dict(original, token="f" * 32))
            self.recovery_refuses(*self.recovery(record))
            self.persist_fixture(owner, original)
            owner.unlink()
            self.recovery_refuses(*self.recovery(record))
            lock.rmdir()
            if group == "scopes":
                self.recovery_refuses(*self.recovery(record))
            lock.mkdir(mode=0o700)
            self.persist_fixture(owner, original)
        duplicate = self.state / "slots/5.lock"
        duplicate.mkdir(mode=0o700)
        self.persist_fixture(duplicate / "owner.json", record["worker"])
        self.recovery_refuses(*self.recovery(record))
        (duplicate / "owner.json").unlink()
        duplicate.rmdir()
        owner = self.state / "slots" / f"{record['leases']['global_slot']}.lock/owner.json"
        original = owner.read_bytes()
        owner.write_text('{"task_id":"pilot",' + original.decode().lstrip()[1:], encoding="utf-8")
        self.recovery_refuses(*self.recovery(record))
        owner.write_bytes(original)
        self.assert_recovered(record, self.invoke(*self.recovery(record)))

    def test_recovery_nonreleasing_missing_lane_and_terminal_scope_refuse(self):
        record = self.interrupted_worker(source="Claimed", target="Implementing")
        slot = self.state / "slots" / f"{record['leases']['global_slot']}.lock"
        owner = json.loads((slot / "owner.json").read_text())
        (slot / "owner.json").unlink()
        slot.rmdir()
        self.recovery_refuses(*self.recovery(record))
        slot.mkdir(mode=0o700)
        self.persist_fixture(slot / "owner.json", owner)
        lane = self.state / "implementation" / f"{record['leases']['implementation_lane']}.lock"
        (lane / "owner.json").unlink()
        lane.rmdir()
        self.recovery_refuses(*self.recovery(record))

    def test_recovery_actual_lane_acquisition_before_intent_refuses(self):
        self.create()
        child = self.live_child()
        record = self.claim(pid=child.pid)
        core = self.core_module
        args = core.parser().parse_args(["transition", "pilot", "Implementing", *self.owned(record)])
        with (mock.patch.dict(os.environ, self.env, clear=True),
              mock.patch.object(core, "write_task", side_effect=RuntimeError("fixture before intent")),
              self.assertRaisesRegex(RuntimeError, "before intent")):
            core.command_transition(args, self.state)
        self.stop_child(child)
        self.assertEqual(core.process_identity(child.pid), ("absent", None))
        self.assertEqual(self.invoke("show", "pilot"), record)
        self.assertEqual(len(list((self.state / "implementation").iterdir())), 1)
        self.recovery_refuses(*self.recovery(record))

    def test_recovery_actual_terminal_scope_cleanup_refuses(self):
        record = self.interrupted_worker(target="Cancelled", boundary="scopes")
        self.assertFalse((self.state / "scopes" / f"{record['scope_key']}.lock").exists())
        self.recovery_refuses(*self.recovery(record))

    def test_recovery_actual_inactive_parent_intent(self):
        self.create()
        claimed = self.claim()
        blocked = self.invoke("transition", "pilot", "Blocked", *self.owned(claimed))
        core = self.core_module
        write = core.write_task

        def trace_write(root, value, **kwargs):
            write(root, value, **kwargs)
            if value["transition_intent"]:
                raise RuntimeError("fixture inactive intent")

        args = core.parser().parse_args(["transition", "pilot", "Ready", *self.operator(blocked)])
        with (mock.patch.dict(os.environ, self.env, clear=True),
              mock.patch.object(core, "write_task", side_effect=trace_write),
              self.assertRaisesRegex(RuntimeError, "inactive intent")):
            core.command_transition(args, self.state)
        record = self.invoke("show", "pilot")
        self.assertIsNone(record["worker"])
        self.assert_recovered(record, self.invoke(*self.recovery(record)))

    def test_recovery_legacy_and_stable_active_worker_none_remain_unsupported(self):
        self.create()
        legacy = self.invoke("claim", "pilot", "--owner", "fixture", "--pid", str(os.getpid()))
        self.recovery_refuses("reconcile", "--recover", "pilot", "--operator-action",
                              "--operator-reason", "fixture", "--expected-generation", "0",
                              "--expected-revision", str(legacy["revision"]))
        self.invoke("transition", "pilot", "Blocked")
        self.invoke("transition", "pilot", "Ready")
        bound = self.claim(revision=self.invoke("show", "pilot")["revision"])
        malformed = copy.deepcopy(bound)
        malformed["worker"] = None
        self.persist_fixture(self.task_path(), malformed)
        self.recovery_refuses(*self.recovery(bound))
        with self.assertRaises(self.core_module.UnknownError):
            self.core_module.validate_record(malformed, allow_bound=True)

    def test_recovery_prepared_size_and_unknown_runtime_guard_before_effects(self):
        record = self.interrupted_worker()
        core = self.core_module
        args = core.parser().parse_args(self.recovery(record))
        for guard in ("require_execution_stopped", "require_repair_settled"):
            before, directories = self.snapshot(), self.directory_snapshot()
            with (mock.patch.dict(os.environ, self.env, clear=True),
                  mock.patch.object(core, guard, side_effect=core.UnknownError("fixture unknown runtime")),
                  self.assertRaises(core.UnknownError)):
                core.command_reconcile(args, self.state)
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(self.directory_snapshot(), directories)
        enlarged = copy.deepcopy(record)
        for field in ("validation", "findings", "reviewers", "dependencies", "acceptance_criteria"):
            enlarged[field] = ["x" * 1000] * 190
        # Fill the normal record to the byte limit; a recovery receipt cannot fit.
        while len(core.serialized_json(enlarged)) < 999_500:
            remaining = 999_500 - len(core.serialized_json(enlarged))
            enlarged["restricted_paths"].append("x" * min(1000, remaining))
        core.validate_record(enlarged, allow_bound=True)
        self.task_path().write_bytes(core.serialized_json(enlarged))
        self.recovery_refuses(*self.recovery(record), expected=2)

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

    def test_same_account_two_live_sessions_acknowledged_handoff(self):
        initial = self.create()
        child_a, child_b = self.live_child(), self.live_child()
        self.assertNotEqual(child_a.pid, child_b.pid)
        claimed = self.claim(revision=initial["revision"], pid=child_a.pid)
        active = self.invoke("transition", "pilot", "Implementing", *self.owned(claimed))
        wrong_session = self.owned(active)
        wrong_session[1] = OTHER_SESSION
        wrong_worker = self.owned(active)
        wrong_worker[3] = "f" * 32
        for flags in (wrong_session, wrong_worker):
            self.recovery_refuses("record", "pilot", "validation", "session B premature write",
                                  *flags, expected=4)
        claim_b = ["claim", "pilot", "--owner", active["owner"], "--pid", str(child_b.pid),
                   "--session-id", OTHER_SESSION, "--expected-generation", "1",
                   "--expected-revision", str(active["revision"])]
        self.recovery_refuses(*claim_b, expected=4)
        self.recovery_refuses("transition", "pilot", "Ready", *self.operator(active), expected=4)
        acknowledgement = "Cooperative handoff acknowledged; work preserved in private checkpoint"
        acknowledged = self.invoke("record", "pilot", "validation", acknowledgement, *self.owned(active))
        # Each step observes anew; session/worker expectations still belong to A.
        fresh = self.invoke("show", "pilot")
        self.assertEqual(fresh, acknowledged)
        blocked = self.invoke("transition", "pilot", "Blocked", *self.owned(fresh))
        self.assertIsNone(child_a.poll())  # Releasing ownership does not stop its process.
        self.assertIsNone(blocked["worker"])
        self.assertEqual(blocked["cooperative_binding"], active["cooperative_binding"])
        self.assertEqual(blocked["leases"], dict(active["leases"], global_slot=None, implementation_lane=None))
        self.assertEqual(list((self.state / "slots").iterdir()), [])
        self.assertEqual(list((self.state / "implementation").iterdir()), [])
        claim_b[-1] = str(blocked["revision"])
        self.recovery_refuses(*claim_b, expected=4)  # Blocked is not claimable.
        self.stop_child(child_a)  # Independent operator prerequisite, outside the state CLI.
        self.assertIsNotNone(child_a.returncode)
        self.assertEqual(self.core_module.process_identity(child_a.pid), ("absent", None))
        fresh = self.invoke("show", "pilot")
        ready = self.invoke("transition", "pilot", "Ready", *self.operator(fresh))
        fresh = self.invoke("show", "pilot")
        self.assertEqual(fresh, ready)
        self.assertIsNone(child_b.poll())  # B's already-live PID is a valid new worker.
        second = self.claim(session=OTHER_SESSION, generation=fresh["cooperative_binding"]["generation"],
                            revision=fresh["revision"], pid=child_b.pid)
        self.assertEqual(second["owner"], active["owner"])
        self.assertEqual(second["worker"]["pid"], child_b.pid)
        self.assertEqual(second["cooperative_binding"], {"session_id": OTHER_SESSION, "generation": 2})
        self.assertNotEqual(second["worker"]["worker_id"], active["worker"]["worker_id"])
        self.assertEqual(second["validation"], [acknowledgement])
        for command in (("record", "pilot", "validation", "stale A"),
                        ("update-head", "pilot", HEAD), ("transition", "pilot", "Blocked")):
            self.recovery_refuses(*command, *self.owned(acknowledged), expected=4)
            stale_identity = self.owned(second)
            stale_identity[1], stale_identity[3] = SESSION, active["worker"]["worker_id"]
            self.recovery_refuses(*command, *stale_identity, expected=4)
        recorded = self.invoke("record", "pilot", "validation", "session B resumed", *self.owned(second))
        resumed = self.invoke("transition", "pilot", "Implementing", *self.owned(recorded))
        for group, index in (("slots", resumed["leases"]["global_slot"]),
                             ("implementation", resumed["leases"]["implementation_lane"])):
            owner = self.state / group / f"{index}.lock/owner.json"
            self.assertEqual(json.loads(owner.read_text()), resumed["worker"])

    def test_handoff_lost_responses_observe_before_retry_and_preserve_conflicts(self):
        initial = self.create()
        child_a, child_b = self.live_child(), self.live_child()
        claimed = self.claim(revision=initial["revision"], pid=child_a.pid)
        acknowledgement = "Cooperative handoff acknowledged; private checkpoint retained"
        record_args = ["record", "pilot", "validation", acknowledgement, *self.owned(claimed)]
        self.invoke(*record_args)  # Successful durable action; caller loses its response.
        observed = self.invoke("show", "pilot")
        self.assertEqual(observed["validation"], [acknowledgement])
        self.assertEqual(observed["revision"], claimed["revision"] + 1)
        self.recovery_refuses(*record_args, expected=4)
        release_args = ["transition", "pilot", "Blocked", *self.owned(observed)]
        self.invoke(*release_args)
        observed = self.invoke("show", "pilot")
        self.assertEqual(observed["state"], "Blocked")
        self.assertIsNone(observed["worker"])
        self.recovery_refuses(*release_args, expected=4)
        self.stop_child(child_a)
        self.assertEqual(self.core_module.process_identity(child_a.pid), ("absent", None))
        observed = self.invoke("show", "pilot")
        ready_args = ["transition", "pilot", "Ready", *self.operator(observed)]
        self.invoke(*ready_args)
        ready = self.invoke("show", "pilot")
        self.assertEqual(ready["state"], "Ready")
        self.recovery_refuses(*ready_args, expected=4)
        claim_args = ["claim", "pilot", "--owner", claimed["owner"], "--pid", str(child_b.pid),
                      "--session-id", OTHER_SESSION, "--expected-generation",
                      str(ready["cooperative_binding"]["generation"]), "--expected-revision", str(ready["revision"])]
        self.invoke(*claim_args)
        second = self.invoke("show", "pilot")
        self.assertEqual(second["cooperative_binding"], {"session_id": OTHER_SESSION, "generation": 2})
        self.assertEqual(second["worker"]["pid"], child_b.pid)
        self.recovery_refuses(*claim_args, expected=4)
        # A different successful action advances revision: observation does not
        # authorize blindly rebasing an earlier request onto that newer revision.
        stale = self.owned(second)
        current = self.invoke("record", "pilot", "validation", "session B checkpoint", *stale)
        self.recovery_refuses("record", "pilot", "validation", "unobserved competing request", *stale, expected=4)
        self.assertEqual(self.invoke("show", "pilot"), current)
        self.assertNotIn("unobserved competing request", current["validation"])

    def test_released_live_worker_ready_guard_cannot_prove_stop(self):
        self.create()
        child = self.live_child()
        claimed = self.claim(pid=child.pid)
        blocked = self.invoke("transition", "pilot", "Blocked", *self.owned(claimed))
        self.assertIsNone(child.poll())
        self.assertIsNone(blocked["worker"])
        # Deliberate negative-policy fixture: the operator prerequisite is NOT
        # implemented by the inactive-state guard. Never use this as a recipe.
        ready = self.invoke("transition", "pilot", "Ready", *self.operator(blocked))
        self.assertEqual(ready["state"], "Ready")
        self.assertIsNone(child.poll())

    def test_settled_recovery_receipt_survives_ready_and_new_session_claim(self):
        interrupted = self.interrupted_worker()
        settled = self.assert_recovered(interrupted, self.invoke(*self.recovery(interrupted)))
        receipt = copy.deepcopy(settled["transition_recovery"])
        fresh = self.invoke("show", "pilot")
        ready = self.invoke("transition", "pilot", "Ready", *self.operator(fresh))
        self.assertEqual(ready["transition_recovery"], receipt)
        child_b = self.live_child()
        fresh = self.invoke("show", "pilot")
        second = self.claim(session=OTHER_SESSION, generation=fresh["cooperative_binding"]["generation"],
                            revision=fresh["revision"], pid=child_b.pid)
        self.assertEqual(second["cooperative_binding"]["generation"], receipt["generation"] + 1)
        self.assertEqual(second["transition_recovery"], receipt)
        self.assertEqual(second["worker"]["pid"], child_b.pid)
        self.assertEqual(self.invoke("show", "pilot"), second)
        result = self.invoke("record", "pilot", "validation", "session B after recovery", *self.owned(second))
        self.assertEqual(result["transition_recovery"], receipt)

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

    def test_opt_in_validates_complete_legacy_scope_before_capacity_or_persistence(self):
        self.create()
        initial = self.invoke("show", "pilot")
        scope_path = self.state / "scopes" / f"{initial['scope_key']}.lock/owner.json"
        original = json.loads(scope_path.read_text())
        malformed = [dict(original, scope="wrong-scope"), dict(original, schema_version=3),
                     dict(original, schema_version=True), dict(original, extra="unsupported")]
        for metadata in malformed:
            with self.subTest(metadata=metadata):
                self.persist_fixture(scope_path, metadata)
                self.refuses_unchanged("claim", "pilot", "--owner", "fixture", "--pid", str(os.getpid()),
                                      "--session-id", SESSION, "--expected-generation", "0",
                                      "--expected-revision", "0")
                self.assertEqual(json.loads(self.task_path().read_text()), initial)
                self.assertEqual(list((self.state / "slots").iterdir()), [])
                self.assertEqual(list((self.state / "implementation").iterdir()), [])
        self.persist_fixture(scope_path, original)
        self.assertEqual(self.claim()["schema_version"], 3)

    def test_retained_extensions_cannot_enter_or_bypass_bound_schema(self):
        self.create()
        initial = self.invoke("show", "pilot")
        for extension in ("unsupported", "execution_observations", "review_protocol", "candidate_binding"):
            with self.subTest(extension=extension):
                self.persist_fixture(self.task_path(), dict(initial, **{extension: {}}))
                self.refuses_unchanged("claim", "pilot", "--owner", "fixture", "--pid", str(os.getpid()),
                                      "--session-id", SESSION, "--expected-generation", "0",
                                      "--expected-revision", "0")
        self.persist_fixture(self.task_path(), initial)
        bound = self.claim()
        for extension in ("unsupported", "execution_observations", "review_protocol", "candidate_binding"):
            with self.subTest(bound_extension=extension):
                forged = dict(bound, **{extension: {}})
                self.persist_fixture(self.task_path(), forged)
                self.refuses_unchanged("show", "pilot")
                self.refuses_unchanged("record", "pilot", "validation", "fixture", *self.owned(bound))
                with self.assertRaises(self.core_module.UnknownError):
                    self.core_module.validate_record(forged)
                with self.assertRaises(self.core_module.UnknownError):
                    self.core_module.validate_record(forged, allow_bound=True)
        self.persist_fixture(self.task_path(), bound)

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
