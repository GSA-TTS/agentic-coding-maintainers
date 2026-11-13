#!/usr/bin/env python3
"""Actual schema-3 intent CLI and bounded fake GET; isolated-guest execution only."""

import copy
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1]
SCRIPT = SOURCE / "scripts/record-claim-observation.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = load("receipt_observer_fixture", SOURCE / "tests/observe-claim-intent-test.py")
OBSERVATION = "d1" * 16


class ReceiptTests(unittest.TestCase):
    core_cli = fixture.IntentObservationTests.core_cli
    owned = fixture.IntentObservationTests.owned
    options = fixture.IntentObservationTests.options
    write = fixture.IntentObservationTests.write
    snapshot = fixture.IntentObservationTests.snapshot
    comment = fixture.IntentObservationTests.comment
    steps = fixture.IntentObservationTests.steps

    def setUp(self):
        fixture.IntentObservationTests.setUp(self)
        self.module = load("receipt_cli_fixture", SCRIPT)
        (self.prepare, self.core, self.journal, self.intent,
         self.observe, self.observer) = self.module.modules()

    def argv(self, overrides=None, extra=()):
        options = dict(self.options(), **{"store-id": self.store_id, "observation-id": OBSERVATION})
        options.update(overrides or {})
        return [str(SCRIPT), *[part for key, value in options.items() if value is not None
                              for part in ("--" + key, value)], *extra]

    def sanitized(self, output):
        text = json.dumps(output)
        for key in ("mutation_authorized", "absence_authorizing", "atomic_snapshot",
                    "remote_effects_enabled", "stored_freshness_current"):
            self.assertIs(output[key], False)
        self.assertIs(output["historical"], True)
        self.assertEqual(output["current_task_authority"], "UNVERIFIED")
        self.assertEqual(output["remote_operation_completion"], "UNVERIFIED")
        for value in (str(self.root), self.body, self.store_id, self.task["task_id"], self.task["scope"],
                      self.task["worker"]["token"], self.task["worker"]["worker_id"],
                      fixture.task_fixture.SESSION, fixture.task_fixture.OPERATION,
                      fixture.task_fixture.CLAIM, "octocat", "example/project"):
            self.assertNotIn(value, text)

    def invoke(self, records=None, overrides=None, extra=(), steps=None, show=False):
        if self.calls.exists():
            self.calls.unlink()
        self.answers.write_text(json.dumps(self.steps(records or []) if steps is None else steps))
        argv = ([str(SCRIPT), "--show", "--authority-root", str(self.root),
                 "--observation-id", OBSERVATION] if show else self.argv(overrides, extra))
        completed = subprocess.run([sys.executable, "-I", "-B", *argv], cwd=self.root,
                                   env=self.env, capture_output=True, timeout=15)
        self.assertFalse(completed.stderr, completed.stderr)
        output = json.loads(completed.stdout)
        self.sanitized(output)
        return completed.returncode, output

    def direct(self, records=None, overrides=None):
        if self.calls.exists():
            self.calls.unlink()
        self.answers.write_text(json.dumps(self.steps(records or [])))
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(sys, "argv", self.argv(overrides)), \
                mock.patch.object(self.module, "modules", return_value=(self.prepare, self.core,
                    self.journal, self.intent, self.observe, self.observer)), \
                mock.patch("builtins.print") as printed:
            code = self.module.main()
        output = json.loads(printed.call_args.args[0])
        self.sanitized(output)
        return code, output

    def retained(self):
        db = self.journal.open_store(self.monitor)
        try:
            return self.journal.claim_observation(db, OBSERVATION)
        finally:
            db.close()

    def version_count(self):
        db = self.journal.open_store(self.monitor)
        try:
            version = db.execute("SELECT version FROM meta").fetchone()[0]
            count = db.execute("SELECT count(*) FROM claim_observations").fetchone()[0] if version == 4 else 0
            return version, count
        finally:
            db.close()

    def test_visible_receipt_exact_summary_hash_and_historical_replay_no_get(self):
        task_bytes = self.task_path.read_bytes()
        code, output = self.invoke([self.comment()])
        self.assertEqual((code, output["status"], output["observation_status"]),
                         (3, "HISTORICAL_RECORDED", "HISTORICAL_VISIBLE_MATCH"))
        receipt = self.retained()
        self.assertEqual(output["receipt_sha256"], self.journal.fingerprint(receipt))
        self.assertEqual(receipt["intent_request_sha256"], self.journal.fingerprint(self.request))
        self.assertEqual(receipt["summary"]["comment_id"], 1)
        self.assertEqual(receipt["summary"]["comment_sha256"], self.request["comment_sha256"])
        self.assertEqual(len(json.loads(self.calls.read_text())), 5)
        self.assertEqual(self.version_count(), (4, 1))
        _, replay = self.invoke([self.comment(login="other")])
        self.assertEqual(replay["status"], "HISTORICAL_REPLAY")
        self.assertEqual(replay["receipt_sha256"], output["receipt_sha256"])
        self.assertEqual(self.retained(), receipt)
        self.assertFalse(self.calls.exists())
        self.assertEqual(self.task_path.read_bytes(), task_bytes)

    def test_receipt_report_requires_its_fingerprint_provider(self):
        receipt = {"observation_id": OBSERVATION, "status": "VISIBLE_MATCH"}
        with self.assertRaisesRegex(ValueError, "^receipt requires a journal$"):
            self.module.result("HISTORICAL_SHOWN", "LOCAL_HISTORY_ONLY", receipt)
        # The outer CLI boundary must still emit only its fixed failure report.
        with mock.patch.object(sys, "argv", self.argv()), \
                mock.patch.object(self.module, "modules", return_value=(self.prepare, self.core,
                    self.journal, self.intent, self.observe, self.observer)), \
                mock.patch.object(self.module, "record", side_effect=lambda *args:
                    self.module.result("HISTORICAL_SHOWN", "LOCAL_HISTORY_ONLY", receipt)), \
                mock.patch("builtins.print") as printed:
            self.assertEqual(self.module.main(), 3)
        output = json.loads(printed.call_args.args[0])
        self.assertEqual(output, self.module.result("UNVERIFIED", "STORE_OR_DURABILITY_UNVERIFIED"))
        self.assertNotIn("observation_id", output)
        self.assertFalse(self.calls.exists())

    def test_complete_missing_and_conflict_are_durable_zero_authority(self):
        for records, expected, code in (([], "NO_MATCH_OBSERVED", 3),
                                        ([self.comment(login="other")], "CONFLICT", 4)):
            identifier = OBSERVATION if not records else "d2" * 16
            result_code, output = self.invoke(records, {"observation-id": identifier})
            self.assertEqual((result_code, output["observation_status"]), (code, "HISTORICAL_" + expected))
            self.assertEqual(self.invoke([], {"observation-id": identifier})[0], code)
            self.assertFalse(self.calls.exists())
        self.assertEqual(self.version_count(), (4, 2))

    def test_malformed_marker_and_incomplete_pagination_do_not_migrate(self):
        steps = self.steps([self.comment()])
        steps[3]["raw"] = fixture.rest.http([self.comment()], 'Link: <https://evil.invalid/>; rel="next"\r\n')
        before = self.database.read_bytes()
        for records, custom in (([self.comment(body=self.body + "edited")], None), ([], steps)):
            self.assertEqual(self.invoke(records, steps=custom)[1]["status"], "UNVERIFIED")
            self.assertEqual(self.version_count(), (3, 0))
            self.assertEqual(self.database.read_bytes(), before)

    def test_stale_fences_private_identifier_and_duplicate_arguments_before_get(self):
        for overrides in ({"expected-revision": "1"}, {"expected-generation": "2"},
                          {"store-id": "f" * 32}, {"observation-id": self.store_id},
                          {"observation-id": self.task["worker"]["token"]},
                          {"observation-id": fixture.task_fixture.OPERATION},
                          {"observation-id": fixture.task_fixture.CLAIM}, {"observation-id": "short"}):
            with self.subTest(overrides=overrides):
                self.assertIn(self.invoke([self.comment()], overrides)[0], (3, 4))
                self.assertFalse(self.calls.exists())
                self.assertEqual(self.version_count(), (3, 0))
        for extra in (("--observation-id", OBSERVATION), ("--summary", "arbitrary.json"),
                      ("--observed-at", "2026-01-01T00:00:00Z")):
            self.assertEqual(self.invoke(extra=extra)[0], 3)
            self.assertFalse(self.calls.exists())

    def test_current_task_change_during_get_refuses_persistence(self):
        actual = self.observer.Transport.get

        def get(transport, *args, **kwargs):
            self.assertFalse((self.state / "locks/coordinator.lock").exists())
            self.write(self.task_path, dict(self.task, next_action="concurrent change"))
            return actual(transport, *args, **kwargs)

        with mock.patch.object(self.observer.Transport, "get", get):
            self.assertEqual(self.direct([self.comment()])[1]["reason"], "LOCAL_SNAPSHOT_CHANGED")
        self.assertEqual(self.version_count(), (3, 0))

    def test_network_closes_all_readers_and_precedes_coordinator(self):
        opened = []
        actual_open, actual_get = self.journal.open_store, self.observer.Transport.get

        def open_store(*args, **kwargs):
            db = actual_open(*args, **kwargs)
            opened.append(db)
            return db

        def get(transport, *args, **kwargs):
            self.assertFalse((self.state / "locks/coordinator.lock").exists())
            for db in opened:
                with self.assertRaises(sqlite3.ProgrammingError):
                    db.execute("SELECT 1")
            return actual_get(transport, *args, **kwargs)

        with mock.patch.object(self.journal, "open_store", side_effect=open_store), \
                mock.patch.object(self.observer.Transport, "get", get):
            self.assertEqual(self.direct([self.comment()])[1]["status"], "HISTORICAL_RECORDED")

    def test_lost_postcommit_sync_ack_retries_without_get(self):
        with mock.patch.object(self.intent, "durable", side_effect=OSError("private-canary")):
            self.assertEqual(self.direct([self.comment()])[1]["status"], "UNVERIFIED")
        receipt = self.retained()
        self.assertEqual(self.version_count(), (4, 1))
        with mock.patch.object(self.intent, "durable", wraps=self.intent.durable) as barrier:
            output = self.direct([self.comment(login="other")])[1]
        self.assertEqual(output["status"], "HISTORICAL_REPLAY")
        self.assertEqual(barrier.call_count, 1)
        self.assertFalse(self.calls.exists())
        self.assertEqual(self.retained(), receipt)

    def test_handed_off_task_refuses_replay_show_reads_only_history(self):
        self.invoke([self.comment()])
        self.write(self.task_path, dict(self.task, next_action="handed off"))
        self.assertEqual(self.invoke()[1]["status"], "CONFLICT")
        self.assertFalse(self.calls.exists())
        before = self.snapshot()
        self.assertEqual(self.invoke(show=True)[1]["status"], "HISTORICAL_SHOWN")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.calls.exists())

    def test_same_id_other_known_operation_conflicts_before_get(self):
        self.invoke()
        options = dict(self.options(), **{"operation-id": "e1" * 16})
        completed = subprocess.run([sys.executable, "-I", "-B", str(SOURCE / "scripts/journal-claim-intent.py"),
            *[part for key, value in options.items() for part in ("--" + key, value)]],
            cwd=self.root, env=self.env, capture_output=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(self.invoke(overrides={"operation-id": "e1" * 16})[1]["reason"], "OBSERVATION_CONFLICT")
        self.assertFalse(self.calls.exists())
        self.assertEqual(self.version_count(), (4, 1))

    def test_capacity_replay_and_migration_rollback(self):
        with mock.patch.object(self.journal, "MAX_CLAIM_OBSERVATIONS", 0):
            self.assertEqual(self.direct()[1]["reason"], "OBSERVATION_CAPACITY_REACHED")
        self.assertEqual(self.version_count(), (3, 0))
        self.invoke()
        with mock.patch.object(self.journal, "MAX_CLAIM_OBSERVATIONS", 1):
            self.assertEqual(self.direct(overrides={"observation-id": "d3" * 16})[1]["reason"],
                             "OBSERVATION_CAPACITY_REACHED")
            self.assertEqual(self.direct()[1]["status"], "HISTORICAL_REPLAY")
            self.assertFalse(self.calls.exists())

    def test_transaction_insert_failure_rolls_back_schema_and_receipt(self):
        actual = self.journal.open_store

        def open_store(*args, **kwargs):
            db = actual(*args, **kwargs)
            if kwargs.get("writable"):
                def deny(action, table, column, database, trigger):
                    return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_INSERT and table == "claim_observations" else sqlite3.SQLITE_OK
                db.set_authorizer(deny)
            return db

        with mock.patch.object(self.journal, "open_store", side_effect=open_store):
            self.assertEqual(self.direct()[1]["status"], "UNVERIFIED")
        self.assertEqual(self.version_count(), (3, 0))
        self.assertEqual(self.invoke()[1]["status"], "HISTORICAL_RECORDED")

    def test_legacy_versions_refused_without_get_or_migration(self):
        db = self.journal.open_store(self.monitor, writable=True)
        try:
            with db:
                db.execute("DROP TABLE claim_intents")
                db.execute("UPDATE meta SET version=2")
            self.assertEqual(self.invoke()[1]["status"], "UNVERIFIED")
            self.assertFalse(self.calls.exists())
            with db:
                db.execute("DROP TABLE binding_acks")
                db.execute("UPDATE meta SET version=1")
            self.assertEqual(self.invoke()[1]["status"], "UNVERIFIED")
            self.assertFalse(self.calls.exists())
            self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 1)
        finally:
            db.close()

    def test_transaction_context_commit_failure_rolls_back_migration(self):
        actual_connect = self.journal.sqlite3.connect
        base = self.journal.StoreConnection

        class FailedCommit(base):
            def __exit__(connection, kind, value, traceback):
                if kind is None:
                    connection.rollback()
                    raise sqlite3.OperationalError("private-commit-canary")
                return super().__exit__(kind, value, traceback)

        def connect(*args, **kwargs):
            if "mode=rw" in str(args[0]):
                kwargs["factory"] = FailedCommit
            return actual_connect(*args, **kwargs)

        with mock.patch.object(self.journal.sqlite3, "connect", side_effect=connect):
            self.assertEqual(self.direct()[1]["status"], "UNVERIFIED")
        self.assertEqual(self.version_count(), (3, 0))
        self.assertEqual(self.invoke()[1]["status"], "HISTORICAL_RECORDED")

    def test_real_fsync_failure_retains_commit_and_replay_syncs_again(self):
        actual_fsync = os.fsync
        actual_durable = self.intent.durable

        def fsync(fd):
            # Fail only the database descriptor barrier, after SQLite commit.
            import stat
            if stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("private-sync-canary")
            return actual_fsync(fd)

        def durable(*args):
            with mock.patch.object(self.intent.os, "fsync", side_effect=fsync):
                return actual_durable(*args)

        with mock.patch.object(self.intent, "durable", side_effect=durable):
            self.assertEqual(self.direct()[1]["status"], "UNVERIFIED")
        self.assertEqual(self.version_count(), (4, 1))
        self.assertEqual(self.invoke()[1]["status"], "HISTORICAL_REPLAY")
        self.assertFalse(self.calls.exists())

    def test_coordinator_contention_returns_conflict_without_persistence(self):
        lock = self.state / "locks/coordinator.lock"
        lock.mkdir(mode=0o700)
        self.assertEqual(self.invoke()[1]["reason"], "COORDINATOR_BUSY")
        self.assertEqual(self.version_count(), (3, 0))
        lock.rmdir()

    def test_selected_database_replacement_during_get_refuses_receipt(self):
        actual_get = self.observer.Transport.get
        original = self.database.read_bytes()

        def get(transport, *args, **kwargs):
            replacement = self.monitor / "replacement"
            replacement.write_bytes(original)
            replacement.chmod(0o600)
            os.replace(replacement, self.database)
            return actual_get(transport, *args, **kwargs)

        with mock.patch.object(self.observer.Transport, "get", get):
            self.assertEqual(self.direct([self.comment()])[1]["reason"], "LOCAL_SNAPSHOT_CHANGED")
        self.assertEqual(self.version_count(), (3, 0))

    def test_record_api_full_capacity_no_pruning_and_exact_replay(self):
        self.invoke()
        db = self.journal.open_store(self.monitor, writable=True)
        try:
            template = self.retained()
            with db:
                for number in range(999):
                    receipt = dict(template, observation_id=f"{number:032x}")
                    db.execute("INSERT INTO claim_observations VALUES(?,?,?,?,?)", (
                        receipt["observation_id"], receipt["operation_id"], receipt["intent_request_sha256"],
                        self.journal.canonical(receipt), self.journal.fingerprint(receipt)))
            self.assertEqual(self.journal.record_claim_observation(db, template, guard=lambda: None), "HISTORICAL_REPLAY")
            with self.assertRaisesRegex(self.journal.JournalError, "capacity reached"):
                self.journal.record_claim_observation(db, dict(template, observation_id="d4" * 16), guard=lambda: None)
            self.assertEqual(db.execute("SELECT count(*) FROM claim_observations").fetchone()[0], 1000)
        finally:
            db.close()

    def test_sqlite_contention_does_not_migrate(self):
        db = self.journal.open_store(self.monitor, writable=True)
        db.execute("BEGIN IMMEDIATE")
        try:
            self.assertEqual(self.invoke()[1]["status"], "UNVERIFIED")
        finally:
            db.rollback()
            db.close()
        self.assertEqual(self.version_count(), (3, 0))

    def test_symlink_private_modes_sidecars_and_missing_store_refused(self):
        before = self.database.read_bytes()
        sidecar = Path(str(self.database) + "-wal")
        sidecar.symlink_to(self.database)
        self.assertEqual(self.invoke()[1]["status"], "UNVERIFIED")
        self.assertFalse(self.calls.exists())
        sidecar.unlink()
        self.database.chmod(0o644)
        self.assertEqual(self.invoke()[1]["status"], "UNVERIFIED")
        self.assertFalse(self.calls.exists())
        self.database.chmod(0o600)
        target = self.monitor / "retained"
        self.database.rename(target)
        self.database.symlink_to(target)
        self.assertEqual(self.invoke(show=True)[1]["status"], "UNVERIFIED")
        self.database.unlink()
        self.assertEqual(self.invoke()[1]["status"], "UNVERIFIED")
        self.assertFalse(self.database.exists() or self.calls.exists())
        self.assertEqual(target.read_bytes(), before)

    def test_strict_version_table_pair_digest_and_reference_validation(self):
        self.invoke()
        db = self.journal.open_store(self.monitor, writable=True)
        try:
            for query in ("UPDATE meta SET version=3", "DROP TABLE claim_observations",
                          "UPDATE claim_observations SET receipt_sha256='invalid'",
                          "UPDATE claim_observations SET request_sha256='invalid'"):
                db.execute("BEGIN IMMEDIATE")
                db.execute(query)
                with self.assertRaises(self.journal.JournalError):
                    self.journal.validate_store(db)
                db.rollback()
        finally:
            db.close()

    def test_schema4_intent_replay_append_and_monitor_status_preserve_version(self):
        self.invoke()
        self.calls.unlink()
        self.answers.write_text(json.dumps(self.steps([self.comment()])))
        before = self.snapshot()
        options = self.options()
        observed = subprocess.run([sys.executable, "-I", "-B", str(SOURCE / "scripts/observe-claim-intent.py"),
            *[part for key, value in options.items() for part in ("--" + key, value)]],
            cwd=self.root, env=self.env, capture_output=True, timeout=15)
        self.assertEqual((observed.returncode, json.loads(observed.stdout)["status"]), (3, "VISIBLE_MATCH"))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(json.loads(self.calls.read_text())), 5)
        for operation in (fixture.task_fixture.OPERATION, "e2" * 16):
            options = dict(self.options(), **{"operation-id": operation})
            completed = subprocess.run([sys.executable, "-I", "-B", str(SOURCE / "scripts/journal-claim-intent.py"),
                *[part for key, value in options.items() for part in ("--" + key, value)]],
                cwd=self.root, env=self.env, capture_output=True, timeout=15)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertEqual(self.version_count(), (4, 1))
        db = self.journal.open_store(self.monitor)
        try:
            self.assertEqual(self.journal.status(db, ["repo:example/project"])["status"], "UNVERIFIED")
        finally:
            db.close()

    def test_later_intent_public_ids_refused_before_insert_history_unchanged(self):
        self.invoke()
        before = self.database.read_bytes()
        receipt = self.retained()
        for field in ("operation-id", "claim-id"):
            options = dict(self.options(), **{"operation-id": "e3" * 16, field: OBSERVATION})
            completed = subprocess.run([sys.executable, "-I", "-B", str(SOURCE / "scripts/journal-claim-intent.py"),
                *[part for key, value in options.items() for part in ("--" + key, value)]],
                cwd=self.root, env=self.env, capture_output=True, timeout=15)
            self.assertEqual(completed.returncode, 3, completed.stdout + completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["status"], "UNVERIFIED")
            self.assertEqual(self.database.read_bytes(), before)
            self.assertEqual(self.retained(), receipt)
        self.assertEqual(self.invoke(show=True)[1]["status"], "HISTORICAL_SHOWN")

    def test_later_intent_private_ids_refused_and_noncolliding_append_valid(self):
        self.invoke()
        db = self.journal.open_store(self.monitor, writable=True)
        try:
            before = self.database.read_bytes()
            for field in ("worker_id", "token", "session_id"):
                request = copy.deepcopy(self.request)
                request["operation_id"] = request["claim"]["operation_id"] = "e4" * 16
                request["comment"] = self.prepare.codec.render(request["claim"])
                request["comment_sha256"] = self.prepare.codec.digest(request["comment"])
                request["binding"]["worker"][field] = OBSERVATION
                if field == "session_id":
                    request["binding"]["session_id"] = OBSERVATION
                self.journal.validate_claim_intent(request)
                with self.assertRaisesRegex(self.journal.JournalError, "reserved claim observation identifier"):
                    self.journal.record_claim_intent(db, request)
                self.assertEqual(self.database.read_bytes(), before)
                self.journal.validate_store(db)
            request = copy.deepcopy(self.request)
            request["operation_id"] = request["claim"]["operation_id"] = "e5" * 16
            request["comment"] = self.prepare.codec.render(request["claim"])
            request["comment_sha256"] = self.prepare.codec.digest(request["comment"])
            self.assertEqual(self.journal.record_claim_intent(db, request), "INTENT_RECORDED")
            self.journal.validate_store(db)
            self.assertEqual(db.execute("SELECT count(*) FROM claim_intents").fetchone()[0], 2)
        finally:
            db.close()
        self.assertEqual(self.invoke(show=True)[1]["status"], "HISTORICAL_SHOWN")

    def test_forged_conflict_without_recognized_claim_refused_by_show(self):
        self.invoke()
        original = self.retained()
        db = self.journal.open_store(self.monitor, writable=True)
        try:
            forged = copy.deepcopy(original)
            forged.update(status="CONFLICT", reason="OBSERVED_CONFLICT")
            for comments in (0, 1):
                forged["summary"]["comment_count"] = comments
                with db:
                    db.execute("UPDATE claim_observations SET receipt=?,receipt_sha256=?", (
                        self.journal.canonical(forged), self.journal.fingerprint(forged)))
                with self.assertRaisesRegex(self.journal.JournalError, "conflict lacks recognized claim"):
                    self.journal.validate_store(db)
                code, output = self.invoke(show=True)
                self.assertEqual((code, output["status"]), (3, "UNVERIFIED"))
                self.assertNotIn("observation_id", output)
                self.assertFalse(self.calls.exists())
            with db:
                db.execute("UPDATE claim_observations SET receipt=?,receipt_sha256=?", (
                    self.journal.canonical(original), self.journal.fingerprint(original)))
            self.journal.validate_store(db)
        finally:
            db.close()


class BindingCompatibilityTests(unittest.TestCase):
    def schema4_lane(self):
        binding_fixture = load("receipt_collision_binding_fixture", SOURCE / ".agents/skills/workspace-orchestrator/tests/candidate-binding-test.py")
        lane = binding_fixture.BindingTests("test_positive_preserves_lifecycle_and_replays_after_source_moves")
        self.addCleanup(lane.doCleanups)
        lane.setUp()
        publication = ReceiptTests("test_visible_receipt_exact_summary_hash_and_historical_replay_no_get")
        self.addCleanup(publication.doCleanups)
        publication.setUp()
        publication.invoke()
        journal = binding_fixture.journal
        request = copy.deepcopy(publication.request)
        request["store_id"] = lane.db.execute("SELECT store_id FROM meta").fetchone()[0]
        journal.record_claim_intent(lane.db, request)
        receipt = copy.deepcopy(publication.retained())
        receipt["store_id"] = request["store_id"]
        receipt["intent_request_sha256"] = journal.fingerprint(request)
        journal.record_claim_observation(lane.db, receipt, guard=lambda: None)
        return lane, binding_fixture, receipt

    def test_actual_binding_collision_precedes_task_write_noncolliding_bind_valid(self):
        lane, binding_fixture, receipt = self.schema4_lane()
        path = lane.state / "tasks/review/task.json"
        before = path.read_bytes()
        database_before = (lane.state / "monitor/history.sqlite3").read_bytes()
        with self.assertRaisesRegex(binding_fixture.binding.Unverified, "identifier conflicts"):
            lane.bind(dict(lane.request, operation_id=OBSERVATION))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual((lane.state / "monitor/history.sqlite3").read_bytes(), database_before)
        self.assertEqual(lane.db.execute("SELECT count(*) FROM binding_acks").fetchone()[0], 0)
        binding_fixture.journal.validate_store(lane.db)
        self.assertEqual(lane.bind()["journal_ack"]["status"], "ACKNOWLEDGED")
        self.assertNotEqual(path.read_bytes(), before)
        binding_fixture.journal.validate_store(lane.db)
        self.assertEqual(binding_fixture.journal.claim_observation(lane.db, OBSERVATION), receipt)

    def test_acknowledge_collision_rolls_back_and_historical_ack_collision_refused(self):
        lane, binding_fixture, receipt = self.schema4_lane()
        self.assertEqual(lane.bind()["journal_ack"]["status"], "ACKNOWLEDGED")
        binding = copy.deepcopy(lane.record()["candidate_binding"])
        binding["request"]["operation_id"] = OBSERVATION
        before = (lane.state / "monitor/history.sqlite3").read_bytes()
        # acknowledge dynamically loads its own module: its exception class is
        # distinct from the fixture's separately loaded journal class. Pin that
        # actual dependency for this call and assert its exact exception type.
        acknowledgment_journal = binding_fixture.binding.load("monitor-journal")
        with mock.patch.object(binding_fixture.binding, "load", return_value=acknowledgment_journal), \
                self.assertRaisesRegex(acknowledgment_journal.JournalError, "reserved claim observation identifier"):
            binding_fixture.binding.acknowledge(lane.db, binding)
        self.assertEqual((lane.state / "monitor/history.sqlite3").read_bytes(), before)
        binding_fixture.journal.validate_store(lane.db)
        # Test exact hex32 acknowledgment identity too, with a new valid lane op.
        ack = copy.deepcopy(lane.record()["candidate_binding"])
        ack["request"].update(incarnation="f1" * 16, operation_id="f2" * 16)
        self.assertEqual(binding_fixture.binding.acknowledge(lane.db, ack)["status"], "ACKNOWLEDGED")
        for identifier in ("f1" * 16, "f2" * 16):
            with self.assertRaisesRegex(binding_fixture.journal.JournalError, "identifier reuse"):
                binding_fixture.journal.record_claim_observation(lane.db, dict(
                    receipt, observation_id=identifier), guard=lambda: None)
        lane.db.execute("BEGIN IMMEDIATE")
        lane.db.execute("UPDATE binding_acks SET operation_id=? WHERE incarnation=?", (OBSERVATION, "f1" * 16))
        with self.assertRaisesRegex(binding_fixture.journal.JournalError, "identifier reuse"):
            binding_fixture.journal.validate_store(lane.db)
        lane.db.rollback()
        binding_fixture.journal.validate_store(lane.db)

    def test_actual_orphan_binding_ack_guard_survives_schema4(self):
        binding_fixture = load("receipt_binding_fixture", SOURCE / ".agents/skills/workspace-orchestrator/tests/candidate-binding-test.py")
        lane = binding_fixture.BindingTests("test_positive_preserves_lifecycle_and_replays_after_source_moves")
        self.addCleanup(lane.doCleanups)
        lane.setUp()
        before = (lane.state / "tasks/review/task.json").read_bytes()
        binding = lane.bind()
        self.assertEqual(binding["journal_ack"]["status"], "ACKNOWLEDGED")
        # A separate actual schema-3 intent CLI fixture supplies a validated
        # request; adjust only its store incarnation for this journal API test.
        publication = ReceiptTests("test_visible_receipt_exact_summary_hash_and_historical_replay_no_get")
        self.addCleanup(publication.doCleanups)
        publication.setUp()
        request = copy.deepcopy(publication.request)
        request["store_id"] = lane.db.execute("SELECT store_id FROM meta").fetchone()[0]
        journal = binding_fixture.journal
        self.assertEqual(journal.record_claim_intent(lane.db, request), "INTENT_RECORDED")
        publication.invoke()
        receipt = copy.deepcopy(publication.retained())
        receipt["store_id"] = request["store_id"]
        receipt["intent_request_sha256"] = journal.fingerprint(request)
        self.assertEqual(journal.record_claim_observation(lane.db, receipt, guard=lambda: None), "HISTORICAL_RECORDED")
        self.assertEqual(lane.bind()["journal_ack"]["status"], "ACKNOWLEDGED")
        self.assertEqual(lane.db.execute("SELECT version FROM meta").fetchone()[0], 4)
        path = lane.state / "tasks/review/task.json"
        path.write_bytes(before)
        for operation in (lane.request["operation_id"], "different-bind-operation"):
            with self.assertRaisesRegex(binding_fixture.binding.Unverified, "receipt is missing"):
                lane.bind(dict(lane.request, operation_id=operation))
            self.assertEqual(path.read_bytes(), before)
        self.assertEqual(lane.db.execute("SELECT version FROM meta").fetchone()[0], 4)


if __name__ == "__main__":
    unittest.main()
