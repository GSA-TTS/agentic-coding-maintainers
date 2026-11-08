#!/usr/bin/env python3
"""Actual schema-3 CLI fixtures; execute only in an independently isolated guest."""

import copy
import json
import os
import sqlite3
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock
import importlib.util

SOURCE = Path(__file__).resolve().parents[1]
SCRIPT = SOURCE / "scripts/journal-claim-intent.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = load("intent_schema3_fixture", SOURCE / "tests/prepare-task-claim-test.py")


class IntentTests(unittest.TestCase):
    # Reuse real create/claim/transition fixture construction, not hand-invented
    # valid task metadata. Inherited preparation tests are not rediscovered here.
    core_cli = fixture.PreparationTest.core_cli
    owned = fixture.PreparationTest.owned
    options = fixture.PreparationTest.options
    write = fixture.PreparationTest.write

    def setUp(self):
        fixture.PreparationTest.setUp(self)
        self.intent = load("fixture_local_intent", SCRIPT)
        self.prepare, self.coordinator, self.journal = self.intent.modules()
        self.monitor = self.state / "monitor"
        self.database = self.monitor / "history.sqlite3"
        self.task_bytes = self.task_path.read_bytes()

    def argv(self, overrides=None, extra=()):
        options = self.options()
        options.update(overrides or {})
        return [str(SCRIPT), *[part for key, value in options.items() if value is not None
                              for part in ("--" + key, value)], *extra]

    def invoke(self, overrides=None, extra=()):
        outcome = subprocess.run([sys.executable, "-I", "-B", *self.argv(overrides, extra)],
                                 env=self.env, cwd=self.root, capture_output=True, text=True,
                                 check=False, timeout=15)
        self.assertEqual(outcome.stderr, "")
        self.assertEqual(self.task_path.read_bytes(), self.task_bytes)
        self.assertFalse((self.state / "locks/coordinator.lock").exists())
        output = json.loads(outcome.stdout)
        self.assertFalse(output["mutation_authorized"])
        self.assertFalse(output["remote_effects_enabled"])
        self.assertNotIn("comment", output)
        for value in (str(self.root), self.task["task_id"], self.task["scope"],
                      fixture.SESSION, self.task["worker"]["worker_id"],
                      self.task["worker"]["token"], self.task["leases"]["scope_token"],
                      self.task["owner"]):
            self.assertNotIn(value, outcome.stdout)
        return outcome.returncode, output

    def direct(self, overrides=None):
        with mock.patch.object(sys, "argv", self.argv(overrides)):
            args, claim = self.prepare.arguments()
        return self.intent.record(args, claim, self.prepare, self.coordinator, self.journal)

    def db(self):
        db = self.journal.open_store(self.monitor, writable=True)
        self.addCleanup(db.close)
        return db

    def retained(self, db=None):
        db = db or self.db()
        return json.loads(db.execute("SELECT request FROM claim_intents").fetchone()[0])

    def initialize(self):
        self.monitor.mkdir(mode=0o700)
        return self.db()

    def test_cli_record_exact_replay_and_private_request(self):
        code, first = self.invoke()
        self.assertEqual((code, first["status"]), (0, "INTENT_RECORDED"))
        code, replay = self.invoke()
        self.assertEqual((code, replay["status"]), (0, "REPLAYED_PENDING"))
        db = self.db()
        self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 3)
        self.assertEqual(db.execute("SELECT count(*) FROM claim_intents").fetchone()[0], 1)
        request = self.retained(db)
        self.assertEqual(request["claim"]["operation_id"], fixture.OPERATION)
        self.assertEqual(request["comment"], self.prepare.codec.render(request["claim"]))
        self.assertEqual(first["comment_sha256"], self.prepare.codec.digest(request["comment"]))
        self.assertEqual(request["binding"]["created_at"], self.task["created_at"])
        self.assertEqual(request["binding"]["task_sha256"], self.journal.fingerprint(self.task))
        self.assertEqual(request["binding"]["worker"], self.task["worker"])
        self.assertEqual(set(first), {"status", "reason", "operation_id", "comment_sha256",
                                     "mutation_authorized", "remote_effects_enabled"})

    def test_conflicting_operation_public_body_refused(self):
        self.invoke()
        code, output = self.invoke({"actor": "anotheractor"})
        self.assertEqual((code, output["reason"]), (4, "OPERATION_CONFLICT"))
        self.assertEqual(self.db().execute("SELECT count(*) FROM claim_intents").fetchone()[0], 1)

    def test_stale_fences_refused_before_replay(self):
        self.invoke()
        for overrides in ({"expected-revision": "1"}, {"expected-generation": "2"},
                          {"expected-session-id": "other-session"}, {"expected-worker-id": "e" * 32}):
            with self.subTest(overrides=overrides):
                self.assertEqual(self.invoke(overrides)[1]["status"], "CONFLICT")

    def test_changed_task_with_same_revision_conflicts_with_retained_request(self):
        self.invoke()
        self.task["next_action"] = "changed private task narrative"
        self.write(self.task_path, self.task)
        self.task_bytes = self.task_path.read_bytes()
        self.assertEqual(self.invoke()[1]["reason"], "OPERATION_CONFLICT")

    def test_bad_inputs_never_create_monitor_store(self):
        for extra in (("--unexpected", "private-canary"), ("--actor", "octocat")):
            self.assertEqual(self.invoke(extra=extra)[0], 3)
            self.assertFalse(self.monitor.exists())
        self.assertEqual(self.invoke({"operation-id": self.task["worker"]["token"]})[0], 3)
        self.assertFalse(self.monitor.exists())

    def test_failed_ownership_never_creates_monitor_store(self):
        self.assertEqual(self.invoke({"expected-generation": "2"})[0], 4)
        self.assertFalse(self.monitor.exists())

    def test_schema2_never_upgrades_task_or_creates_monitor(self):
        legacy = copy.deepcopy(self.task)
        legacy["schema_version"] = 2
        del legacy["cooperative_binding"]
        for key in ("session_id", "generation"):
            del legacy["worker"][key]
        self.write(self.task_path, legacy)
        self.task_bytes = self.task_path.read_bytes()
        self.assertEqual(self.invoke()[0], 3)
        self.assertFalse(self.monitor.exists())

    def test_uninitialized_authority_does_not_create_state(self):
        other = self.root / "uninitialized"
        other.mkdir()
        self.assertEqual(self.invoke({"authority-root": str(other), "invoking-root": str(other)})[0], 3)
        self.assertFalse((other / ".orchestrator").exists())

    def test_preparation_change_rolls_back_before_intent(self):
        real = self.prepare.codec.prepare

        def change(claim):
            output = real(claim)
            self.write(self.task_path, dict(self.task, next_action="changed during render"))
            return output

        with mock.patch.object(self.prepare.codec, "prepare", side_effect=change):
            with self.assertRaises(self.prepare.preflight.Unverified):
                self.direct()
        self.assertFalse(self.monitor.exists())

    def test_change_after_prepare_before_insert_refuses(self):
        real = self.journal.record_claim_intent

        def change(db, request, **kwargs):
            self.write(self.task_path, dict(self.task, next_action="late task change"))
            return real(db, request, **kwargs)

        with mock.patch.object(self.journal, "record_claim_intent", side_effect=change):
            with self.assertRaises(self.prepare.preflight.Unverified):
                self.direct()
        db = self.db()
        self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 1)

    def test_fsync_failure_retains_pending_and_exact_retry_repairs(self):
        real = self.intent.durable

        def failed(journal, db, root):
            with mock.patch.object(os, "fsync", side_effect=OSError("private-path-canary")):
                real(journal, db, root)

        with mock.patch.object(self.intent, "durable", side_effect=failed):
            with self.assertRaises(OSError):
                self.direct()
        self.assertEqual(self.db().execute("SELECT count(*) FROM claim_intents").fetchone()[0], 1)
        self.assertEqual(self.direct()["status"], "REPLAYED_PENDING")
        self.assertEqual(self.task_path.read_bytes(), self.task_bytes)

    def test_cli_unknown_commit_result_has_fixed_failure(self):
        with mock.patch.object(self.intent, "modules", return_value=(self.prepare, self.coordinator, self.journal)), \
                mock.patch.object(sys, "argv", self.argv()), \
                mock.patch.object(self.intent, "durable", side_effect=OSError("private-path-canary")), \
                mock.patch("builtins.print") as printed:
            self.assertEqual(self.intent.main(), 3)
        value = json.loads(printed.call_args.args[0])
        self.assertEqual(value, self.intent.result("UNVERIFIED", "STORE_OR_DURABILITY_UNVERIFIED"))
        self.assertEqual(self.invoke()[1]["status"], "REPLAYED_PENDING")

    def test_interrupted_upgrade_and_insert_roll_back_together(self):
        self.invoke()
        request = self.retained()
        other = self.root / "empty"
        other.mkdir(mode=0o700)
        db = self.journal.open_store(other, writable=True)
        self.addCleanup(db.close)
        request["store_id"] = db.execute("SELECT store_id FROM meta").fetchone()[0]
        calls = []

        def interrupt():
            calls.append(True)
            if len(calls) == 2:
                raise RuntimeError("interrupted after insert")

        with self.assertRaises(RuntimeError):
            self.journal.record_claim_intent(db, request, guard=interrupt)
        self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 1)
        self.assertNotIn("claim_intents", {row[0] for row in db.execute("SELECT name FROM sqlite_master")})
        self.assertEqual(self.journal.record_claim_intent(db, request), "INTENT_RECORDED")

    def test_store_identity_mismatch_refuses_without_upgrade(self):
        self.invoke()
        request = self.retained()
        request["store_id"] = "f" * 32
        with self.assertRaises(self.journal.JournalError):
            self.journal.record_claim_intent(self.db(), request)

    def test_unknown_history_and_duplicate_keys_refuse_readers(self):
        self.invoke()
        db = self.db()
        request = self.retained(db)
        variants = [dict(request, extra="private-canary"), dict(request, action="dispatch"),
                    dict(request, schema_version=True), dict(request, comment="changed body")]
        for changed in variants:
            with self.subTest(changed=changed):
                db.execute("UPDATE claim_intents SET request=?,request_sha256=?",
                           (self.journal.canonical(changed), self.journal.fingerprint(changed)))
                db.commit()
                with self.assertRaises(self.journal.JournalError):
                    self.journal.status(db, [])
        duplicate = self.journal.canonical(request).replace('"schema_version":1', '"schema_version":1,"schema_version":1')
        db.execute("UPDATE claim_intents SET request=?", (duplicate,))
        db.commit()
        with self.assertRaises(self.journal.JournalError):
            self.journal.validate_store(db)

    def test_private_binding_types_and_digest_are_strict(self):
        self.invoke()
        original = self.retained()
        for key, value in (("revision", True), ("generation", 0), ("worker", {}),
                           ("session_id", []), ("created_at", "not-a-timestamp"),
                           ("task_sha256", "bad")):
            changed = copy.deepcopy(original)
            changed["binding"][key] = value
            with self.subTest(key=key), self.assertRaises(self.journal.JournalError):
                self.journal.validate_claim_intent(changed)

    def test_request_byte_limit_and_store_row_digest_refuse(self):
        self.invoke()
        db = self.db()
        request = self.retained(db)
        with mock.patch.object(self.journal, "MAX_INTENT_BYTES", 100):
            with self.assertRaises(self.journal.JournalError):
                self.journal.validate_claim_intent(request)
        db.execute("UPDATE claim_intents SET request_sha256=?", ("a" * 64,))
        db.commit()
        with self.assertRaises(self.journal.JournalError):
            self.journal.validate_store(db)

    def test_full_capacity_refuses_new_but_allows_exact_replay(self):
        self.invoke()
        db = self.db()
        template = self.retained(db)
        with db:
            for number in range(999):
                request = copy.deepcopy(template)
                operation = f"{number:032x}"
                request["operation_id"] = request["claim"]["operation_id"] = operation
                request["comment"] = self.prepare.codec.render(request["claim"])
                request["comment_sha256"] = self.prepare.codec.digest(request["comment"])
                db.execute("INSERT INTO claim_intents VALUES(?,?,?)",
                           (operation, self.journal.canonical(request), self.journal.fingerprint(request)))
        self.assertEqual(self.invoke()[1]["status"], "REPLAYED_PENDING")
        self.assertEqual(self.invoke({"operation-id": "e" * 32})[1]["reason"], "INTENT_CAPACITY_REACHED")
        self.assertEqual(db.execute("SELECT count(*) FROM claim_intents").fetchone()[0], 1000)

    def test_sqlite_lock_is_bounded_and_no_success(self):
        db = self.initialize()
        db.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        try:
            self.assertEqual(self.invoke()[0], 3)
        finally:
            db.rollback()
        self.assertLess(time.monotonic() - started, 8)
        self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 1)

    def test_unsafe_database_and_sidecars_refused(self):
        self.initialize().close()
        target = self.root / "foreign"
        target.write_bytes(self.database.read_bytes())
        target.chmod(0o600)
        self.database.unlink()
        self.database.symlink_to(target)
        self.assertEqual(self.invoke()[0], 3)
        self.database.unlink()
        os.link(target, self.database)
        self.assertEqual(self.invoke()[0], 3)
        self.database.unlink()
        self.database.write_bytes(target.read_bytes())
        self.database.chmod(0o600)
        sidecar = Path(str(self.database) + "-journal")
        sidecar.symlink_to(target)
        self.assertEqual(self.invoke()[0], 3)
        sidecar.unlink()
        os.link(target, sidecar)
        self.assertEqual(self.invoke()[0], 3)
        sidecar.unlink()
        self.database.chmod(0o644)
        self.assertEqual(self.invoke()[0], 3)

    def test_unsafe_monitor_ancestor_refused(self):
        other = self.root / "other-monitor"
        other.mkdir(mode=0o700)
        self.monitor.symlink_to(other, target_is_directory=True)
        self.assertEqual(self.invoke()[0], 3)
        self.assertFalse((other / "history.sqlite3").exists())

    def test_database_replacement_before_sync_refused(self):
        self.invoke()
        db = self.db()
        replacement = self.monitor / "replacement"
        replacement.write_bytes(self.database.read_bytes())
        replacement.chmod(0o600)
        os.replace(replacement, self.database)
        with self.assertRaises(self.journal.JournalError):
            self.intent.durable(self.journal, db, self.monitor)

    def test_observations_and_binding_ack_work_before_and_after_v3(self):
        db = self.initialize()
        binding = load("intent_candidate_binding", SOURCE / ".agents/skills/workspace-orchestrator/bin/candidate-binding.py")
        source = "repo:fixture/project"

        def poll(attempt):
            seq = self.journal.begin(db, attempt, "a" * 64, "monitor", [source], "start")
            item = {"repo": "fixture/project", "number": 1, "head": "a" * 40,
                    "draft": False, "state": "OPEN", "review": "NONE", "merge": "UNKNOWN", "checks": []}
            return self.journal.finish(db, seq, {source: {"status": "OBSERVED", "items": [item], "digest": None, "reason": None}}, "done")

        self.assertEqual(poll("before")["status"], "CHANGED")
        event = db.execute("SELECT fingerprint FROM events").fetchone()[0]
        acknowledgment = {"request": {"incarnation": "private-incarnation", "task_id": "task",
                                      "operation_id": "bind", "candidate": {
                                          "store_id": db.execute("SELECT store_id FROM meta").fetchone()[0],
                                          "repo": "fixture/project", "number": 1,
                                          "generation": 1, "fingerprint": event}}}
        self.assertEqual(binding.acknowledge(db, acknowledgment)["status"], "ACKNOWLEDGED")
        self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 2)
        self.invoke()
        self.assertEqual(poll("after")["status"], "CURRENT")
        self.assertEqual(binding.acknowledge(db, acknowledgment)["status"], "ACKNOWLEDGED")
        acknowledgment = copy.deepcopy(acknowledgment)
        acknowledgment["request"]["incarnation"] = "second-incarnation"
        self.assertEqual(binding.acknowledge(db, acknowledgment)["status"], "ACKNOWLEDGED")
        self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 3)
        self.assertEqual(self.journal.status(db, [source])["status"], "AS_OF_POLL")
        reader = self.journal.open_store(self.monitor)
        try:
            self.assertEqual(reader.execute("SELECT version FROM meta").fetchone()[0], 3)
        finally:
            reader.close()

    def test_observation_open_never_upgrades(self):
        self.initialize().close()
        reader = self.journal.open_store(self.monitor)
        try:
            self.assertEqual(reader.execute("SELECT version FROM meta").fetchone()[0], 1)
        finally:
            reader.close()

    def test_actual_bind_missing_task_receipt_refuses_before_and_after_intent_migration(self):
        binding_fixture = load("intent_actual_binding_fixture", SOURCE / ".agents/skills/workspace-orchestrator/tests/candidate-binding-test.py")
        lane = binding_fixture.BindingTests("test_positive_preserves_lifecycle_and_replays_after_source_moves")
        self.addCleanup(lane.doCleanups)
        lane.setUp()
        # Binding's fixture normally selects root/state via its test override;
        # the public intent API deliberately requires physical .orchestrator.
        lane.db.close()
        lane.state.rename(lane.root / ".orchestrator")
        lane.state = lane.root / ".orchestrator"
        lane.environment["ORCHESTRATOR_STATE_DIR"] = str(lane.state)
        lane.db = binding_fixture.journal.open_store(lane.state / "monitor", writable=True)
        path = lane.state / "tasks/review/task.json"
        before = path.read_bytes()
        incarnation = lane.request["incarnation"]
        self.assertEqual(lane.bind()["journal_ack"]["status"], "ACKNOWLEDGED")
        self.assertEqual(lane.db.execute("SELECT version FROM meta").fetchone()[0], 2)
        path.write_bytes(before)

        def refuse_retries():
            for operation in (lane.request["operation_id"], "different-bind-operation"):
                with self.subTest(version=lane.db.execute("SELECT version FROM meta").fetchone()[0], operation=operation):
                    with self.assertRaises(binding_fixture.binding.Unverified):
                        lane.bind(dict(lane.request, operation_id=operation))
                    self.assertEqual(path.read_bytes(), before)
                    self.assertEqual(binding_fixture.binding.incarnation(json.loads(before)), incarnation)

        refuse_retries()
        # A separate issue-backed task is created/claimed by the actual core CLI
        # in the SAME authority store; no synthetic journal request migrates it.
        # The review task owns lane.source. Add a distinct checkout and branch
        # through the fixture's hermetic Git helper without checking out or
        # changing files in that existing owner checkout.
        publication_worktree = lane.root / "publication-checkout"
        review_head = lane.git("rev-parse", "HEAD")
        review_status = lane.git("status", "--porcelain")
        lane.git("worktree", "add", "-q", "-b", "feat/publication",
                 str(publication_worktree), lane.head)
        self.assertEqual(lane.git("rev-parse", "HEAD"), review_head)
        self.assertEqual(lane.git("status", "--porcelain"), review_status)
        created = lane.command("create", "publication-task", "--kind", "implementation",
                               "--scope", "fixture:publication", "--repo", "fixture/project",
                               "--branch", "feat/publication", "--worktree", str(publication_worktree),
                               "--head-sha", lane.head, "--base-sha", lane.head,
                               "--tracker-type", "issue", "--tracker-number", "117")
        self.assertEqual(created.returncode, 0, created.stderr)
        claimed = lane.command("claim", "publication-task", "--owner", "private-owner",
                               "--pid", str(os.getpid()), "--session-id", "private-publication-session",
                               "--expected-generation", "0", "--expected-revision", "0")
        self.assertEqual(claimed.returncode, 0, claimed.stderr)
        task = json.loads(claimed.stdout)
        options = {"authority-root": str(lane.root), "invoking-root": str(lane.root),
                   "task-id": task["task_id"], "expected-revision": str(task["revision"]),
                   "expected-worker-id": task["worker"]["worker_id"],
                   "expected-session-id": task["cooperative_binding"]["session_id"],
                   "expected-generation": str(task["cooperative_binding"]["generation"]),
                   "repo": "fixture/project", "branch": "feat/publication", "issue": "117",
                   "actor": "octocat", "claim-id": "c" * 32, "operation-id": "d" * 32,
                   "scope": "implementation"}
        outcome = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT),
                                  *[part for key, value in options.items() for part in ("--" + key, value)]],
                                 cwd=lane.root, env=lane.environment, capture_output=True,
                                 text=True, check=False, timeout=15)
        self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
        self.assertEqual(json.loads(outcome.stdout)["status"], "INTENT_RECORDED")
        self.assertEqual(lane.db.execute("SELECT version FROM meta").fetchone()[0], 3)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(lane.git("rev-parse", "HEAD"), review_head)
        self.assertEqual(lane.git("status", "--porcelain"), review_status)
        refuse_retries()

    def test_actual_transaction_commit_exception_rolls_back_upgrade_and_row(self):
        self.initialize().close()
        real_open = self.journal.open_store
        journal = self.journal

        class FailedCommit(journal.StoreConnection):
            def __exit__(connection, kind, value, traceback):
                if kind is None:
                    # Exercise the actual SQLite transaction at the context
                    # commit boundary, not an exception after successful commit.
                    self.assertTrue(connection.in_transaction)
                    self.assertEqual(connection.execute("SELECT version FROM meta").fetchone()[0], 3)
                    self.assertEqual(connection.execute("SELECT count(*) FROM claim_intents").fetchone()[0], 1)
                    connection.rollback()
                    raise sqlite3.OperationalError("private commit failure canary")
                return super().__exit__(kind, value, traceback)

        def failing_open(root, writable=False):
            opened = real_open(root, writable=writable)
            identity = opened.file_identity
            opened.close()
            connection = sqlite3.connect((root / "history.sqlite3").as_uri() + "?mode=rw",
                                         uri=True, timeout=2, factory=FailedCommit)
            connection.row_factory = sqlite3.Row
            connection.file_identity = identity
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            return connection

        with mock.patch.object(self.journal, "open_store", side_effect=failing_open), \
                mock.patch.object(self.intent, "modules", return_value=(self.prepare, self.coordinator, self.journal)), \
                mock.patch.object(sys, "argv", self.argv()), mock.patch("builtins.print") as printed:
            self.assertEqual(self.intent.main(), 3)
        self.assertEqual(json.loads(printed.call_args.args[0]),
                         self.intent.result("UNVERIFIED", "STORE_OR_DURABILITY_UNVERIFIED"))
        db = self.db()
        self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 1)
        self.assertNotIn("claim_intents", {row[0] for row in db.execute("SELECT name FROM sqlite_master")})
        self.assertNotIn("binding_acks", {row[0] for row in db.execute("SELECT name FROM sqlite_master")})
        self.assertEqual(self.task_path.read_bytes(), self.task_bytes)
        self.assertEqual(self.invoke()[1]["status"], "INTENT_RECORDED")

    def test_previous_reader_rejects_v3_before_observation_replay(self):
        self.invoke()
        db = self.db()
        # Pinned schema guard from cb5323f6 monitor-journal.py:108-116.
        # This excerpt proves old schema refusal, not a complete old-core run.
        old_tables = {"meta", "polls", "sources", "coverage", "events", "candidates"}
        objects = db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        names = {row["name"] for row in objects}
        self.assertNotIn(names, (old_tables, old_tables | {"binding_acks"}))
        self.assertNotIn(db.execute("SELECT version FROM meta").fetchone()[0], {1, 2})

    def test_unsupported_intent_table_structure_is_refused(self):
        db = self.initialize()
        with db:
            db.execute("CREATE TABLE binding_acks (incarnation TEXT PRIMARY KEY, task_id TEXT NOT NULL, operation_id TEXT NOT NULL, receipt TEXT NOT NULL, receipt_sha256 TEXT NOT NULL)")
            db.execute("CREATE TABLE claim_intents (operation_id TEXT, request TEXT, request_sha256 TEXT)")
            db.execute("UPDATE meta SET version=3")
        with self.assertRaises(self.journal.JournalError):
            self.journal.validate_store(db)


if __name__ == "__main__":
    unittest.main()
