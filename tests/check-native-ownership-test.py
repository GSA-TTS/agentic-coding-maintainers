#!/usr/bin/env python3
"""Actual retained task/lease adversarial fixtures; isolated execution only."""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check-native-ownership.py"


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


class OwnershipTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.task = task_fixture()
        self.task_path = self.root / ".orchestrator/tasks/fixture-task/task.json"
        self.slot_path = self.root / ".orchestrator/slots/0.lock/owner.json"
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

    def persist(self):
        self.write(self.task_path, self.task)
        self.write(self.slot_path, self.task["worker"])
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
                        "private-process-start", "example/project", "1" * 32, "2" * 32, "3" * 32):
            self.assertNotIn(private, outcome.stdout)
        return outcome.returncode, output["status"], output["reason"]

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
        for schema in (1, 3, True, 2.0, "2"):
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
        # This is a three-file consistency projection, never a capacity/readiness gate.
        self.write(self.root / ".orchestrator/implementation/0.lock/owner.json", b'malformed')
        self.write(self.root / ".orchestrator/slots/5.lock/owner.json", b'malformed')
        self.write(self.root / ".orchestrator/tasks/unrelated/task.json", b'malformed')
        self.assertEqual(self.invoke(), (0, "STATIC_MATCH", "RETAINED_WORKER_CONSISTENT"))

    def test_cli_errors_do_not_echo_private_arguments(self):
        for overrides in ({"task-id": "../private-task"}, {"expected-revision": "true"},
                          {"expected-revision": "01"}, {"expected-worker-id": "private-token"},
                          {"expected-worker-id": None}):
            self.assertEqual(self.invoke(overrides)[1], "UNVERIFIED")
        self.assertEqual(self.invoke(extra=("--native-session", "private-token"))[1], "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
