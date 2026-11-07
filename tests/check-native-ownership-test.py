#!/usr/bin/env python3
"""Actual retained task/lease adversarial fixtures; isolated execution only."""

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check-native-ownership.py"
PRIVATE_SESSION = "session-private-canary-token-01"


def task_fixture():
    """Schema-2 command_create shape plus command_claim/Implementing metadata."""
    scope = "fixture:issue116"
    worker = {"task_id": "fixture-task", "owner": "private-owner", "pid": 999,
              "process_start": "private-process-start", "worker_id": "1" * 32,
              "token": "2" * 32, "hostname": "private-hostname", "created_at": "fixture-time"}
    return {
        "schema_version": 2, "task_id": "fixture-task", "state": "Implementing",
        "scope": scope, "scope_key": hashlib.sha256(scope.encode()).hexdigest(), "kind": "implementation",
        "owner": worker["owner"], "repo": "example/project", "branch": "feat/fixture-task",
        "worktree": "/private/fixture-worktree", "base_sha": "a" * 40,
        "tracker_type": "issue", "tracker_number": 116, "head_sha": "b" * 40, "reviewed_sha": "",
        "owned_paths": ["docs/NATIVE-OWNERSHIP.md"], "restricted_paths": [],
        "acceptance_criteria": ["offline fixture"], "dependencies": [], "reviewers": [],
        "findings": [], "validation": [], "next_action": "fixture only", "worker": worker,
        "leases": {"global_slot": 0, "implementation_lane": 0, "scope_token": "3" * 32},
        "transition_intent": None, "rework_count": 0, "revision": 7,
        "created_at": "fixture-time", "updated_at": "fixture-time"}


def bound_task_fixture(state="Implementing", generation=2, revision=7):
    """Schema-3 cooperative session-bound shape."""
    task = task_fixture()
    task["schema_version"] = 3
    task["state"] = state
    task["revision"] = revision
    task["cooperative_binding"] = {"session_id": PRIVATE_SESSION, "generation": generation}
    task["worker"].update(task["cooperative_binding"])
    if state != "Implementing":
        task["leases"]["implementation_lane"] = None
    return task


def recovery_digest(value):
    return hashlib.sha256((json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")).hexdigest()


def attach_recovery_receipt(task, phase="settled"):
    """Construct a valid pending or settled transition_recovery receipt."""
    old_worker = copy.deepcopy(task["worker"])
    old_worker["session_id"] = "prior-session-token"
    old_worker["generation"] = 1
    old_leases = {"global_slot": 0, "implementation_lane": 0, "scope_token": task["leases"]["scope_token"]}
    base = copy.deepcopy(task)
    base.pop("transition_recovery", None)
    base.pop("legacy_finding_dispositions", None)
    base.update(
        state="Implementing",
        transition_intent="Blocked",
        worker=old_worker,
        leases=old_leases,
        revision=3,
        cooperative_binding={"session_id": "prior-session-token", "generation": 1},
    )
    retained = {k: v for k, v in base.items() if k not in {"transition_recovery", "revision", "updated_at"}}
    receipt = {
        "phase": phase,
        "source": "Implementing",
        "intent": "Blocked",
        "generation": 1,
        "base_revision": 3,
        "pending_revision": 4,
        "worker": old_worker,
        "leases": old_leases,
        "capacity_observed": {"slots": True, "implementation": True},
        "operator_reason": "Preserved interrupted work; checkpoint for operator review",
        "task_sha256": recovery_digest(retained),
    }
    receipt["correlation_sha256"] = recovery_digest({k: v for k, v in receipt.items() if k != "phase"})
    if phase == "pending":
        pending_task = copy.deepcopy(base)
        pending_task["revision"] = 4
        pending_task["transition_recovery"] = receipt
        return pending_task
    settled_task = copy.deepcopy(task)
    settled_task["transition_recovery"] = receipt
    return settled_task


class OwnershipTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.task = task_fixture()
        self.task_path = self.root / ".orchestrator/tasks/fixture-task/task.json"
        self.slot_path = self.root / ".orchestrator/slots/0.lock/owner.json"
        self.lane_path = self.root / ".orchestrator/implementation/0.lock/owner.json"
        self.scope_path = self.root / (".orchestrator/scopes/" + self.task["scope_key"] + ".lock/owner.json")
        self.persist()

    def write(self, path, value):
        if not path.parent.exists():
            missing = []
            parent = path.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir(mode=0o700)
        path.write_bytes(value if type(value) is bytes else json.dumps(value).encode("utf-8"))
        path.chmod(0o600)

    def persist(self, include_lane=False):
        self.write(self.task_path, self.task)
        if self.task.get("worker") is not None:
            self.write(self.slot_path, self.task["worker"])
            if include_lane and self.task["leases"].get("implementation_lane") is not None:
                self.write(self.lane_path, self.task["worker"])
        self.write(self.scope_path, {"schema_version": 2, "task_id": self.task["task_id"],
                                    "scope": self.task["scope"], "token": self.task["leases"]["scope_token"]})

    def invoke(self, overrides=None, extra=()):
        options = {"authority-root": str(self.root), "invoking-root": str(self.root),
                   "task-id": "fixture-task", "expected-revision": "7", "expected-worker-id": "1" * 32,
                   "expected-branch": "feat/fixture-task", "expected-repo": "example/project"}
        options.update(overrides or {})
        args = [sys.executable, "-I", "-B", str(SCRIPT)]
        for key, value in options.items():
            if value is not None:
                args.extend(["--" + key, value])
        outcome = subprocess.run([*args, *extra], capture_output=True, text=True, check=False, timeout=10)
        self.assertEqual(outcome.stderr, "")
        output = json.loads(outcome.stdout)
        self.assertEqual(set(output), {"status", "reason", "native_session_authentication", "mutation_authorized"})
        self.assertEqual(output["native_session_authentication"], "UNVERIFIED")
        self.assertIs(output["mutation_authorized"], False)
        for private in (str(self.root), "private-owner", "private-hostname", "999", "fixture-task",
                        "private-process-start", "example/project", "1" * 32, "2" * 32, "3" * 32,
                        PRIVATE_SESSION, "prior-session-token"):
            self.assertNotIn(private, outcome.stdout)
        return outcome.returncode, output["status"], output["reason"]

    def invoke_bound(self, overrides=None, extra=()):
        bound_defaults = {"expected-session-id": PRIVATE_SESSION, "expected-generation": "2"}
        bound_defaults.update(overrides or {})
        return self.invoke(bound_defaults, extra=extra)

    def test_actual_retained_match_without_native_authentication_or_mutation(self):
        before = {path: path.read_bytes() for path in (self.task_path, self.slot_path, self.scope_path)}
        entries = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))
        self.assertEqual(self.invoke(), (0, "STATIC_MATCH", "RETAINED_WORKER_CONSISTENT"))
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertEqual(entries, sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*")))
        # No fabricated immutable repository identity or native session fields.
        self.assertEqual(self.invoke({"expected-repo": None, "expected-branch": None})[1], "STATIC_MATCH")

    def test_two_same_user_callers_copying_worker_id_are_not_authenticated(self):
        self.assertEqual(self.invoke()[1], "STATIC_MATCH")
        self.assertEqual(self.invoke()[1], "STATIC_MATCH")
        self.assertEqual(self.invoke({"expected-worker-id": "4" * 32}), (4, "CONFLICT", "WORKER_MISMATCH"))

    def test_complete_expectation_conflicts(self):
        for overrides, reason in (({"expected-revision": "6"}, "REVISION_MISMATCH"),
                                  ({"expected-revision": "8"}, "REVISION_MISMATCH"),
                                  ({"expected-branch": "feat/other"}, "REPOSITORY_OR_BRANCH_MISMATCH"),
                                  ({"expected-repo": "other/project"}, "REPOSITORY_OR_BRANCH_MISMATCH")):
            with self.subTest(overrides=overrides):
                self.assertEqual(self.invoke(overrides), (4, "CONFLICT", reason))
        self.task["task_id"] = "another-task"
        self.persist()
        self.assertEqual(self.invoke(), (4, "CONFLICT", "TASK_MISMATCH"))

    def test_owner_worker_and_scope_slot_conflicts(self):
        for group, key, changed, reason in (
                ("task", "owner", "other-owner", "WORKER_MISMATCH"),
                ("worker", "task_id", "other-task", "TASK_MISMATCH"),
                ("slot", "token", "4" * 32, "RETAINED_LEASE_MISMATCH"),
                ("slot", "worker_id", "4" * 32, "RETAINED_LEASE_MISMATCH"),
                ("slot", "hostname", "other-host", "RETAINED_LEASE_MISMATCH"),
                ("scope", "token", "4" * 32, "RETAINED_LEASE_MISMATCH"),
                ("scope", "task_id", "other-task", "RETAINED_LEASE_MISMATCH"),
                ("scope", "scope", "another:scope", "RETAINED_LEASE_MISMATCH")):
            with self.subTest(group=group, key=key):
                self.task = task_fixture()
                self.persist()
                path = {"task": self.task_path, "worker": self.task_path,
                        "slot": self.slot_path, "scope": self.scope_path}[group]
                value = json.loads(path.read_bytes())
                (value["worker"] if group == "worker" else value)[key] = changed
                self.write(path, value)
                self.assertEqual(self.invoke(), (4, "CONFLICT", reason))

    def test_idle_missing_worker_and_partial_state_are_unverified(self):
        for state in ("Ready", "Rework", "Blocked", "Cancelled", "Done", "Ready for human review"):
            self.task["state"] = state
            self.write(self.task_path, self.task)
            self.assertEqual(self.invoke({"expected-revision": "6"}), (3, "UNVERIFIED", "INACTIVE_OR_TRANSITIONING"))
        self.task = task_fixture()
        self.task["transition_intent"] = "Reviewing"
        self.write(self.task_path, self.task)
        self.assertEqual(self.invoke()[1], "UNVERIFIED")
        for field in ("worker", "global_slot"):
            self.task = task_fixture()
            (self.task if field == "worker" else self.task["leases"])[field] = None
            self.write(self.task_path, self.task)
            self.assertEqual(self.invoke(), (3, "UNVERIFIED", "MISSING_WORKER_OR_SLOT"))

    def test_missing_task_slot_scope_or_wrong_selected_store(self):
        for path in (self.task_path, self.slot_path, self.scope_path):
            raw = path.read_bytes()
            path.unlink()
            self.assertEqual(self.invoke()[1], "UNVERIFIED")
            self.write(path, raw)
        self.assertEqual(self.invoke({"task-id": "missing-task"})[1], "UNVERIFIED")
        missing = str(self.root / "missing")
        self.assertEqual(self.invoke({"authority-root": missing, "invoking-root": missing})[1], "UNVERIFIED")
        other = self.root / "worktree"
        other.mkdir()
        self.assertEqual(self.invoke({"invoking-root": str(other)}), (4, "CONFLICT", "ROOT_MISMATCH"))
        self.assertEqual(self.invoke({"authority-root": str(other), "invoking-root": str(other)})[1], "UNVERIFIED")

    def test_symlink_root_and_ancestor_aliases(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(self.invoke({"invoking-root": str(alias)})[1], "UNVERIFIED")
        for spelling in (str(self.root) + "/.", str(self.root) + "/../x", str(self.root) + "/", "/", "relative"):
            self.assertEqual(self.invoke({"authority-root": spelling})[1], "UNVERIFIED")
        actual = self.task_path.parent
        saved = actual.with_name("saved-task")
        actual.rename(saved)
        actual.symlink_to(saved, target_is_directory=True)
        self.assertEqual(self.invoke()[1], "UNVERIFIED")

    def test_hardlinks_symlinks_fifo_directory_and_file_permissions(self):
        for path in (self.task_path, self.scope_path, self.slot_path):
            raw = path.read_bytes()
            saved = path.with_name("saved.json")
            path.rename(saved)
            path.symlink_to(saved)
            self.assertEqual(self.invoke()[1], "UNVERIFIED")
            path.unlink()
            os.link(saved, path)
            self.assertEqual(self.invoke()[1], "UNVERIFIED")
            path.unlink()
            os.mkfifo(path, 0o600)
            self.assertEqual(self.invoke()[1], "UNVERIFIED")
            path.unlink()
            path.mkdir(mode=0o700)
            self.assertEqual(self.invoke()[1], "UNVERIFIED")
            path.rmdir()
            saved.unlink()
            self.write(path, raw)
            path.chmod(0o644)
            self.assertEqual(self.invoke()[1], "UNVERIFIED")
            path.chmod(0o600)
        self.task_path.parent.chmod(0o755)
        self.assertEqual(self.invoke()[1], "UNVERIFIED")
        self.task_path.parent.chmod(0o700)

    def test_unknown_or_partial_fields_and_schema_versions(self):
        for path in (self.task_path, self.slot_path, self.scope_path):
            original = json.loads(path.read_bytes())
            extra = copy.deepcopy(original)
            extra["native_session_id"] = "invented"
            self.write(path, extra)
            self.assertEqual(self.invoke()[1], "UNVERIFIED")
            for field in original:
                with self.subTest(path=path.name, field=field):
                    value = copy.deepcopy(original)
                    del value[field]
                    self.write(path, value)
                    self.assertEqual(self.invoke()[1], "UNVERIFIED")
            self.write(path, original)
        for schema in (1, 3, 4, True, 2.0, "2"):
            self.task["schema_version"] = schema
            self.write(self.task_path, self.task)
            self.assertEqual(self.invoke()[1], "UNVERIFIED")
        for group in ("worker", "leases"):
            original = task_fixture()
            extra = copy.deepcopy(original)
            extra[group]["native_session_id"] = "invented"
            self.write(self.task_path, extra)
            self.assertEqual(self.invoke()[1], "UNVERIFIED")
            for field in original[group]:
                value = copy.deepcopy(original)
                del value[group][field]
                self.write(self.task_path, value)
                self.assertEqual(self.invoke()[1], "UNVERIFIED")

    def test_exact_types_counts_hashes_enums_and_legacy_prose(self):
        for group, field, value in (
                (None, "revision", True), (None, "revision", -1), (None, "revision", "7"),
                (None, "revision", 7.0), (None, "state", []), (None, "kind", "native"),
                (None, "tracker_number", False), (None, "tracker_type", "github"),
                (None, "owned_paths", [True]), (None, "findings", ["x"] * 201),
                (None, "scope_key", "a" * 64), (None, "scope", 116), (None, "base_sha", "short"),
                ("leases", "global_slot", True), ("leases", "global_slot", 6),
                ("leases", "implementation_lane", 2), ("leases", "scope_token", "bad"),
                ("worker", "pid", False), ("worker", "worker_id", "BAD"), ("worker", "hostname", [])):
            with self.subTest(group=group, field=field):
                value_task = task_fixture()
                (value_task if group is None else value_task[group])[field] = value
                self.write(self.task_path, value_task)
                self.assertEqual(self.invoke()[1], "UNVERIFIED")
        self.task = task_fixture()
        self.task["validation"] = ["legacy prose\nwith another line"]
        self.write(self.task_path, self.task)
        self.assertEqual(self.invoke()[1], "STATIC_MATCH")

    def test_raw_parser_attacks_and_resource_bounds(self):
        raw = json.dumps(self.task).encode()
        for attack in (raw.replace(b'"revision": 7', b'"revision": 7, "revision": 7'),
                       raw.replace(b'"revision": 7', b'"revision": 7, "revis\\u0069on": 7'),
                       raw.replace(b'"pid": 999', b'"pid": 999, "pid": 999'),
                       raw.replace(b'"revision": 7', b'"revision": NaN'),
                       raw.replace(b'"revision": 7', b'"revision": Infinity'),
                       raw.replace(b'"private-owner"', b'"\\ud800"'),
                       raw.decode().encode("utf-16"), b'\xff', b'{', b'',
                       b'[' * 100 + b'0' + b']' * 100, raw + b' ' * 1_000_001):
            self.write(self.task_path, attack)
            self.assertEqual(self.invoke()[1], "UNVERIFIED")
        self.task["validation"] = ["x" * 1001]
        self.write(self.task_path, self.task)
        self.assertEqual(self.invoke()[1], "UNVERIFIED")
        for path in (self.scope_path, self.slot_path):
            raw = path.read_bytes()
            self.write(self.task_path, task_fixture())
            attack = raw.replace(b'"token":', b'"token": "' + b'4' * 32 + b'", "token":')
            self.write(path, attack)
            self.assertEqual(self.invoke()[1], "UNVERIFIED")
            self.write(path, raw)

    def test_no_scan_of_unrelated_state_or_implementation_lane(self):
        # Schema 2 remains a three-file consistency projection, never scanning implementation/0.lock.
        self.write(self.root / ".orchestrator/implementation/0.lock/owner.json", b'malformed')
        self.write(self.root / ".orchestrator/slots/5.lock/owner.json", b'malformed')
        self.write(self.root / ".orchestrator/tasks/unrelated/task.json", b'malformed')
        self.assertEqual(self.invoke(), (0, "STATIC_MATCH", "RETAINED_WORKER_CONSISTENT"))

    def test_cli_errors_do_not_echo_private_arguments(self):
        for overrides in ({"task-id": "../private-task"}, {"expected-revision": "true"},
                          {"expected-revision": "01"}, {"expected-worker-id": "private-token"},
                          {"expected-worker-id": None},
                          {"expected-session-id": PRIVATE_SESSION},
                          {"expected-generation": "2"},
                          {"expected-session-id": "../bad", "expected-generation": "2"},
                          {"expected-session-id": PRIVATE_SESSION, "expected-generation": "0"},
                          {"expected-session-id": PRIVATE_SESSION, "expected-generation": "01"}):
            self.assertEqual(self.invoke(overrides), (3, "UNVERIFIED", "INVALID_ARGUMENTS"))
        self.assertEqual(self.invoke(extra=("--native-session", "private-token"))[1], "UNVERIFIED")

    def test_schema3_bound_lifecycle_states_and_flag_separation(self):
        # Schema 2 rejects bound expectations.
        self.assertEqual(
            self.invoke_bound(),
            (3, "UNVERIFIED", "UNEXPECTED_BOUND_EXPECTATIONS"),
        )
        # Schema 3 in Implementing requires 4 files (including implementation/0.lock/owner.json).
        self.task = bound_task_fixture(state="Implementing")
        self.persist(include_lane=True)
        self.assertEqual(
            self.invoke(),
            (3, "UNVERIFIED", "MISSING_BOUND_EXPECTATIONS"),
        )
        self.assertEqual(
            self.invoke_bound(),
            (0, "STATIC_MATCH", "RETAINED_WORKER_CONSISTENT"),
        )
        # Missing implementation lane file in Implementing is UNVERIFIED.
        self.lane_path.unlink()
        self.assertEqual(self.invoke_bound(), (3, "UNVERIFIED", "STORE_UNAVAILABLE"))
        # Claimed and Reviewing require implementation_lane == None and read only 3 files.
        for state in ("Claimed", "Reviewing"):
            self.task = bound_task_fixture(state=state)
            self.persist(include_lane=False)
            self.write(self.lane_path, b"malformed")
            self.assertEqual(
                self.invoke_bound(),
                (0, "STATIC_MATCH", "RETAINED_WORKER_CONSISTENT"),
            )
            # Holding an implementation_lane in Claimed/Reviewing is invalid metadata.
            self.task["leases"]["implementation_lane"] = 0
            self.write(self.task_path, self.task)
            self.assertEqual(self.invoke_bound(), (3, "UNVERIFIED", "INVALID_METADATA"))

    def test_schema3_session_generation_and_lane_conflicts(self):
        self.task = bound_task_fixture(state="Implementing")
        self.persist(include_lane=True)
        self.assertEqual(
            self.invoke_bound({"expected-session-id": "other-session"}),
            (4, "CONFLICT", "SESSION_OR_GENERATION_MISMATCH"),
        )
        self.assertEqual(
            self.invoke_bound({"expected-generation": "1"}),
            (4, "CONFLICT", "SESSION_OR_GENERATION_MISMATCH"),
        )
        # Disagreement between task worker and implementation lane lock is a lease conflict.
        for key, bad in (("session_id", "other-session"), ("generation", 1), ("token", "9" * 32)):
            lane_copy = copy.deepcopy(self.task["worker"])
            lane_copy[key] = bad
            self.write(self.lane_path, lane_copy)
            self.assertEqual(
                self.invoke_bound(),
                (4, "CONFLICT", "RETAINED_LEASE_MISMATCH"),
            )
        self.write(self.lane_path, self.task["worker"])
        # Internal worker/binding disagreement or boolean generation is INVALID_METADATA.
        bad_task = copy.deepcopy(self.task)
        bad_task["worker"]["session_id"] = "other-session"
        self.write(self.task_path, bad_task)
        self.assertEqual(self.invoke_bound(), (3, "UNVERIFIED", "INVALID_METADATA"))
        bad_gen = copy.deepcopy(self.task)
        bad_gen["cooperative_binding"]["generation"] = True
        bad_gen["worker"]["generation"] = True
        self.write(self.task_path, bad_gen)
        self.assertEqual(self.invoke_bound(), (3, "UNVERIFIED", "INVALID_METADATA"))

    def test_schema3_lane_confinement_and_permissions(self):
        self.task = bound_task_fixture(state="Implementing")
        self.persist(include_lane=True)
        raw = self.lane_path.read_bytes()
        saved = self.lane_path.with_name("saved.json")
        self.lane_path.rename(saved)
        self.lane_path.symlink_to(saved)
        self.assertEqual(self.invoke_bound()[1], "UNVERIFIED")
        self.lane_path.unlink()
        os.link(saved, self.lane_path)
        self.assertEqual(self.invoke_bound()[1], "UNVERIFIED")
        self.lane_path.unlink()
        saved.unlink()
        self.write(self.lane_path, raw)
        self.lane_path.chmod(0o644)
        self.assertEqual(self.invoke_bound(), (3, "UNVERIFIED", "UNSAFE_STORE"))
        self.lane_path.chmod(0o600)
        self.lane_path.parent.chmod(0o755)
        self.assertEqual(self.invoke_bound(), (3, "UNVERIFIED", "UNSAFE_STORE"))
        self.lane_path.parent.chmod(0o700)

    def test_schema3_recovery_receipt_and_legacy_dispositions(self):
        # Pending recovery is transitioning -> UNVERIFIED / INACTIVE_OR_TRANSITIONING.
        pending = attach_recovery_receipt(bound_task_fixture(state="Implementing"), phase="pending")
        self.task = pending
        self.persist(include_lane=True)
        self.assertEqual(
            self.invoke_bound({"expected-session-id": "prior-session-token", "expected-generation": "1", "expected-revision": "4"}),
            (3, "UNVERIFIED", "INACTIVE_OR_TRANSITIONING"),
        )
        # Settled recovery receipt surviving a new generation claim passes.
        settled = attach_recovery_receipt(bound_task_fixture(state="Implementing", generation=2, revision=7), phase="settled")
        finding = "P2: synthetic finding"
        settled["findings"] = [finding]
        settled["legacy_finding_dispositions"] = {
            "epoch": 1,
            "history": [{
                "finding_index": 0,
                "finding_sha256": hashlib.sha256(finding.encode("utf-8")).hexdigest(),
                "head_sha": settled["head_sha"],
                "epoch": 1,
                "disposition": "fixed",
                "reviewer": "qa-reviewer",
                "implementation_owner": settled["owner"],
                "evidence": "resolved in synthetic fixture",
                "revision": 6,
            }],
        }
        self.task = settled
        self.persist(include_lane=True)
        self.assertEqual(
            self.invoke_bound(),
            (0, "STATIC_MATCH", "RETAINED_WORKER_CONSISTENT"),
        )
        # Tampered correlation digest in settled receipt is rejected as INVALID_METADATA.
        tampered = copy.deepcopy(settled)
        tampered["transition_recovery"]["correlation_sha256"] = "0" * 64
        self.write(self.task_path, tampered)
        self.assertEqual(self.invoke_bound(), (3, "UNVERIFIED", "INVALID_METADATA"))
        # Tampered disposition digest is rejected as INVALID_METADATA.
        bad_disp = copy.deepcopy(settled)
        bad_disp["legacy_finding_dispositions"]["history"][0]["finding_sha256"] = "0" * 64
        self.write(self.task_path, bad_disp)
        self.assertEqual(self.invoke_bound(), (3, "UNVERIFIED", "INVALID_METADATA"))
        # Unhashable JSON values in receipt or disposition enum fields return INVALID_METADATA, not STORE_UNAVAILABLE.
        for field in ("phase", "source", "intent"):
            unhashable = copy.deepcopy(settled)
            unhashable["transition_recovery"][field] = []
            self.write(self.task_path, unhashable)
            self.assertEqual(self.invoke_bound(), (3, "UNVERIFIED", "INVALID_METADATA"))
        bad_disp_type = copy.deepcopy(settled)
        bad_disp_type["legacy_finding_dispositions"]["history"][0]["disposition"] = {}
        self.write(self.task_path, bad_disp_type)
        self.assertEqual(self.invoke_bound(), (3, "UNVERIFIED", "INVALID_METADATA"))
        # Active task with settled receipt at the SAME generation (generation == receipt.generation) is rejected.
        same_gen_active = attach_recovery_receipt(
            bound_task_fixture(state="Implementing", generation=1, revision=7), phase="settled"
        )
        self.task = same_gen_active
        self.persist(include_lane=True)
        self.assertEqual(
            self.invoke_bound({"expected-generation": "1"}),
            (3, "UNVERIFIED", "INVALID_METADATA"),
        )


if __name__ == "__main__":
    unittest.main()
