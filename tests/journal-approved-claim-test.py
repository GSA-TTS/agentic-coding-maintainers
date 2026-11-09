#!/usr/bin/env python3
"""Actual schema-3/SQLite/fake-gh fixtures; run only in an isolated guest."""

import copy
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/journal-approved-claim.py"
OPERATION = "e1" * 16


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixtures = load("bound_intent_approval_fixtures", ROOT / "tests/prepare-approved-claim-test.py")
receipts = load("bound_intent_receipt_fixtures", ROOT / "tests/record-claim-observation-test.py")


class ApprovedIntentTests(unittest.TestCase):
    def setUp(self):
        # Capture the real fixture-tool environment before ApprovalTests installs
        # its fake-gh-only PATH and credential/transport canaries.
        self.binding_environment = dict(os.environ)
        git = shutil.which("git", path=self.binding_environment.get("PATH", os.defpath))
        self.assertIsNotNone(git, "isolated fixture requires installed git")
        self.binding_environment["PATH"] = str(Path(git).parent) + os.pathsep + self.binding_environment.get("PATH", os.defpath)
        self.fixture = fixtures.ApprovalTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.module = load("bound_intent_cli", SCRIPT)
        (self.prepare, self.core, self.journal, self.intent,
         self.approval, self.observer) = self.module.modules()
        self.monitor = self.fixture.local.state / "monitor"
        self.database = self.monitor / "history.sqlite3"
        self.calls = self.fixture.remote.calls

    def argv(self, overrides=None, extra=()):
        return [str(SCRIPT), *self.fixture.argv(overrides, extra)[1:]]

    def answers(self, steps=None):
        if self.calls.exists():
            self.calls.unlink()
        self.fixture.remote.fixture.write_text(json.dumps(self.fixture.steps() if steps is None else steps))

    def sanitized(self, output):
        self.assertIs(output["mutation_authorized"], False)
        self.assertIs(output["remote_effects_enabled"], False)
        text = json.dumps(output)
        for value in (str(self.fixture.local.root), self.fixture.local.task["worker"]["token"],
                      fixtures.local.SESSION, "octocat", "public-reviewer", "U_fixture", "secret"):
            self.assertNotIn(value, text)
        self.assertNotIn("comment", output)

    def invoke(self, overrides=None, extra=(), steps=None):
        self.answers(steps)
        task = self.fixture.local.task_path.read_bytes()
        outcome = subprocess.run([sys.executable, "-I", "-B", *self.argv(overrides, extra)],
                                 env=self.fixture.env, cwd=self.fixture.local.root,
                                 capture_output=True, timeout=15)
        self.assertFalse(outcome.stderr)
        self.assertEqual(self.fixture.local.task_path.read_bytes(), task)
        output = json.loads(outcome.stdout)
        self.sanitized(output)
        return outcome.returncode, output

    def direct(self, overrides=None, steps=None):
        self.answers(steps)
        with mock.patch.dict(os.environ, self.fixture.env, clear=True), \
                mock.patch.object(sys, "argv", self.argv(overrides)), \
                mock.patch.object(self.module, "modules", return_value=(self.prepare, self.core,
                    self.journal, self.intent, self.approval, self.observer)), \
                mock.patch("builtins.print") as printed:
            code = self.module.main()
        output = json.loads(printed.call_args.args[0])
        self.sanitized(output)
        return code, output

    def assert_recorded(self, overrides=None, steps=None, *, direct=False):
        outcome = self.direct(overrides, steps) if direct else self.invoke(overrides, steps=steps)
        code, output = outcome
        # Include only the already-sanitized CLI contract, never raw exceptions,
        # stderr, body, argv, retained rows, credentials or filesystem evidence.
        self.assertEqual(code, 0, repr(output))
        self.assertEqual(output["status"], "INTENT_RECORDED", repr(output))
        return output

    def rows(self):
        db = self.journal.open_store(self.monitor)
        try:
            return db.execute("SELECT version FROM meta").fetchone()[0], [
                tuple(row) for row in db.execute("SELECT * FROM claim_intents ORDER BY operation_id")]
        finally:
            db.close()

    def request(self):
        return self.journal.decode_intent(self.rows()[1][0][1])

    def legacy(self):
        options = self.fixture.local.options()
        outcome = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "scripts/journal-claim-intent.py"),
                                  *[item for key, value in options.items() for item in ("--" + key, value)]],
                                 env=self.fixture.env, cwd=self.fixture.local.root, capture_output=True, timeout=15)
        self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
        return self.rows()[1][0]

    def new_options(self):
        claim = dict(version=1, action="claim", repo="example/project", issue=117,
                     branch="feat/public", actor="octocat", claim_id=fixtures.local.CLAIM,
                     operation_id=OPERATION, task_ref="issue:117", scope="implementation")
        return {"operation-id": OPERATION,
                "approved-body-sha256": self.prepare.codec.digest(self.prepare.codec.render(claim))}

    def test_fresh_six_gets_private_request_and_exact_zero_get_replay(self):
        self.assert_recorded()
        self.assertEqual(json.loads(self.calls.read_text()), self.fixture.urls)
        version, rows = self.rows()
        self.assertEqual(version, 5)
        request = self.request()
        self.assertEqual(request["schema_version"], 2)
        self.assertEqual(request["identity_observation"]["actor_node_id"], "U_fixture")
        self.assertEqual(request["identity_observation"]["actor_login"], "octocat")
        self.assertEqual(request["public_text_declaration"]["reviewer"], "public-reviewer")
        self.assertEqual(self.invoke(steps=[])[1]["status"], "REPLAYED_PENDING")
        self.assertFalse(self.calls.exists())
        self.assertEqual(self.rows(), (version, rows))
        self.assertEqual(self.request()["binding"]["generation"], self.fixture.local.task["cooperative_binding"]["generation"])

    def test_constant_directory_nlink_fresh_initialization_and_zero_get_replay(self):
        self.assertFalse(self.monitor.exists())
        actual_fingerprint = self.prepare.preflight.fingerprint

        def constant_directory_nlink(info):
            fingerprint = actual_fingerprint(info)
            # Model directory metadata only: regular-file link counts and all
            # physical identities, times, permissions and owners stay real.
            return (*fingerprint[:7], 1) if stat.S_ISDIR(info.st_mode) else fingerprint

        with mock.patch.object(sys, "argv", self.argv()):
            args, claim = self.approval.arguments(self.prepare)
        with mock.patch.object(self.prepare.preflight, "fingerprint", side_effect=constant_directory_nlink):
            before, public = self.approval.snapshot(args, claim, self.prepare)
            task_bytes = self.fixture.local.task_path.read_bytes()
            self.assert_recorded(direct=True)
            self.assertEqual(json.loads(self.calls.read_text()), self.fixture.urls)
            after, text = self.approval.snapshot(args, claim, self.prepare)
            self.assertEqual((before[2][7], after[2][7]), (1, 1))
            self.assertEqual(text, public)
            for index in (0, 1, 3, 4):
                self.assertEqual(after[index], before[index])
            version, rows = self.rows()
            self.assertEqual(version, 5)
            self.assertEqual(len(rows), 1)
            request = self.request()
            self.assertEqual(request["schema_version"], 2)
            self.assertEqual(request["binding"], self.module.binding(before[0], self.journal))
            self.assertEqual(request["comment_sha256"], args.approved_body_sha256)
            code, output = self.direct(steps=[])
            self.assertEqual(code, 0, repr(output))
            self.assertEqual(output["status"], "REPLAYED_PENDING", repr(output))
            self.assertFalse(self.calls.exists())
            self.assertEqual(self.rows(), (version, rows))
            self.assertEqual(self.approval.snapshot(args, claim, self.prepare), (after, text))
            self.assertEqual(self.fixture.local.task_path.read_bytes(), task_bytes)

    def test_fresh_initialization_portable_parent_metadata_preserves_task_and_leases(self):
        self.assertFalse(self.monitor.exists())
        with mock.patch.object(sys, "argv", self.argv()):
            args, claim = self.approval.arguments(self.prepare)
        before, public = self.approval.snapshot(args, claim, self.prepare)
        self.assert_recorded()
        after, text = self.approval.snapshot(args, claim, self.prepare)
        self.assertEqual(text, public)
        self.assertIn(after[2][7], (before[2][7], before[2][7] + 1))
        self.assertTrue(self.module.initialized_snapshot_matches(before, after, created=True))
        self.assertTrue(self.module.initialized_snapshot_matches(before, before, created=False))
        # Exercise both mkdir conventions regardless of the guest filesystem.
        for links in (before[2][7], before[2][7] + 1):
            changed = list(before)
            metadata = list(before[2])
            for index in (2, 3, 4):
                metadata[index] += 1
            metadata[7] = links
            changed[2] = tuple(metadata)
            self.assertTrue(self.module.initialized_snapshot_matches(before, tuple(changed), created=True))
            self.assertFalse(self.module.initialized_snapshot_matches(before, tuple(changed), created=False))
        for index in (0, 1, 3, 4):
            changed = list(after)
            changed[index] = None
            self.assertFalse(self.module.initialized_snapshot_matches(before, tuple(changed), created=True))
        for index in (0, 1, 5, 6):
            changed = list(after)
            metadata = list(after[2])
            metadata[index] += 1
            changed[2] = tuple(metadata)
            self.assertFalse(self.module.initialized_snapshot_matches(before, tuple(changed), created=True))
        for links in (before[2][7] - 1, before[2][7] + 2):
            changed = list(after)
            metadata = list(after[2])
            metadata[7] = links
            changed[2] = tuple(metadata)
            self.assertFalse(self.module.initialized_snapshot_matches(before, tuple(changed), created=True))
        self.assertEqual(self.rows()[0], 5)

    def test_fresh_record_boundary_diagnostic_without_cli_exception_suppression(self):
        self.answers()
        boundary = ["arguments"]

        def traced(name, function):
            def call(*args, **kwargs):
                boundary[0] = name
                value = function(*args, **kwargs)
                boundary[0] = name + "_returned"
                return value
            return call

        with mock.patch.dict(os.environ, self.fixture.env, clear=True), \
                mock.patch.object(sys, "argv", self.argv()), \
                mock.patch.object(self.approval, "snapshot", traced("snapshot", self.approval.snapshot)), \
                mock.patch.object(self.approval, "collect_private", traced("six_get_collection", self.approval.collect_private)), \
                mock.patch.object(self.module, "lookup", traced("readonly_lookup", self.module.lookup)), \
                mock.patch.object(self.journal, "validate_claim_intent", traced("typed_validation", self.journal.validate_claim_intent)), \
                mock.patch.object(self.journal, "open_store", traced("store_open", self.journal.open_store)), \
                mock.patch.object(self.journal, "record_claim_intent", traced("transaction", self.journal.record_claim_intent)), \
                mock.patch.object(self.intent, "durable", traced("durability", self.intent.durable)):
            try:
                args, claim = self.approval.arguments(self.prepare)
                output = self.module.record(args, claim, self.prepare, self.core, self.journal,
                                            self.intent, self.approval, self.observer)
            except Exception as exc:
                # Class and fixed fixture boundary only. Arbitrary exception text
                # can contain private data and must not appear in diagnostics.
                self.fail("fresh record boundary=" + boundary[0] + " exception_type=" + type(exc).__name__)
        self.sanitized(output)
        self.assertEqual(output["status"], "INTENT_RECORDED", repr(output))

    def test_actual_network_outside_coordinator_and_closed_sqlite_readers(self):
        self.legacy()
        opened = []
        actual_open, actual_get = self.journal.open_store, self.observer.Transport.get

        def open_store(*args, **kwargs):
            db = actual_open(*args, **kwargs)
            opened.append(db)
            return db

        def get(transport, *args, **kwargs):
            self.assertFalse((self.fixture.local.state / "locks/coordinator.lock").exists())
            for db in opened:
                with self.assertRaises(sqlite3.ProgrammingError):
                    db.execute("SELECT 1")
            return actual_get(transport, *args, **kwargs)

        with mock.patch.object(self.journal, "open_store", side_effect=open_store), \
                mock.patch.object(self.observer.Transport, "get", get):
            self.assert_recorded(self.new_options(), direct=True)
        self.assertEqual(len(json.loads(self.calls.read_text())), 6)

    def test_invalid_inputs_do_not_initialize_or_get(self):
        for overrides in ({"expected-actor-id": "0"}, {"expected-revision": "1"},
                          {"approved-body-sha256": "0" * 64}, {"reviewer": "bad--login"}):
            self.assertIn(self.invoke(overrides)[0], (3, 4))
            self.assertFalse(self.calls.exists())
            self.assertFalse(self.monitor.exists())
        self.assertEqual(self.invoke(extra=("--approve-public-text",))[0], 3)
        self.assertFalse(self.monitor.exists())

    def test_replay_changed_ids_declaration_and_task_fail_before_get(self):
        self.assert_recorded()
        before = self.rows()
        for overrides in ({"expected-actor-id": "8"}, {"expected-repo-id": "401"},
                          {"expected-issue-id": "501"}, {"reviewer": "other"},
                          {"approved-body-sha256": "0" * 64}, {"expected-generation": "2"},
                          {"actor": "other"}, {"branch": "feat/other"}):
            self.assertIn(self.invoke(overrides, steps=[])[0], (3, 4))
            self.assertFalse(self.calls.exists())
            self.assertEqual(self.rows(), before)
        self.fixture.local.write(self.fixture.local.task_path, dict(self.fixture.local.task, next_action="changed"))
        self.assertEqual(self.invoke(steps=[])[1]["status"], "CONFLICT")
        self.assertFalse(self.calls.exists())

    def test_v1_operation_conflict_and_v1_append_replay_preserve_v5(self):
        old = self.legacy()
        self.assertEqual(self.invoke()[1]["status"], "CONFLICT")
        self.assertFalse(self.calls.exists())
        self.assertEqual(self.rows(), (3, [old]))
        self.assert_recorded(self.new_options())
        before = self.rows()
        self.assertIn(old, before[1])
        self.legacy()
        self.assertEqual(self.rows(), before)

    def test_identity_changes_and_task_change_during_get_do_not_initialize(self):
        for index, change in ((0, {"id": 8}), (1, {"id": 401}), (2, {"id": 501}),
                              (3, {"node_id": "U_changed"}), (4, {"node_id": "R_changed"}),
                              (5, {"node_id": "I_changed"})):
            steps = self.fixture.steps()
            steps[index]["raw"] = fixtures.remote.http(dict(self.fixture.records[index % 3], **change))
            self.assertEqual(self.invoke(steps=steps)[0], 3)
            self.assertFalse(self.monitor.exists())
        actual = self.observer.Transport.get

        def get(transport, *args, **kwargs):
            self.fixture.local.write(self.fixture.local.task_path, dict(self.fixture.local.task, next_action="changed"))
            return actual(transport, *args, **kwargs)

        with mock.patch.object(self.observer.Transport, "get", get):
            self.assertEqual(self.direct()[1]["reason"], "LOCAL_SNAPSHOT_CHANGED")
        self.assertFalse(self.monitor.exists())

    def test_strict_identity_declaration_and_row_digest_validation(self):
        self.assert_recorded()
        request = self.request()
        for section, key, value in (("identity_observation", "actor_id", True),
                                    ("identity_observation", "actor_node_id", "arbitrary prose"),
                                    ("identity_observation", "issue_node_id", "x" * 257),
                                    ("identity_observation", "actor_login", "other"),
                                    ("identity_observation", "observed_at", "2026-01-01T00:00:00+00:00"),
                                    ("identity_observation", "observed_at", "2026-02-30T00:00:00.000000Z"),
                                    ("identity_observation", "remote_coverage", "complete_pagination"),
                                    ("public_text_declaration", "approved_body_sha256", "0" * 64),
                                    ("public_text_declaration", "public_text_approval", "AUTHENTICATED"),
                                    ("public_text_declaration", "reviewer", "bad--login")):
            changed = copy.deepcopy(request)
            changed[section][key] = value
            with self.assertRaises(self.journal.JournalError):
                self.journal.validate_claim_intent(changed)
        changed = copy.deepcopy(request)
        changed["identity_observation"]["extra"] = True
        with self.assertRaises(self.journal.JournalError):
            self.journal.validate_claim_intent(changed)
        db = self.journal.open_store(self.monitor, writable=True)
        with db:
            db.execute("UPDATE claim_intents SET request_sha256=?", ("0" * 64,))
        db.close()
        self.assertEqual(self.invoke(steps=[])[0], 3)
        self.assertFalse(self.calls.exists())

    def test_v1_to_v4_atomic_upgrade_and_rollback_preserve_old_rows(self):
        self.assert_recorded()
        request = self.request()
        history = receipts.ReceiptTests("test_visible_receipt_exact_summary_hash_and_historical_replay_no_get")
        history.setUp()
        self.addCleanup(history.doCleanups)
        history.invoke()
        historical = history.retained()
        for version in (1, 2, 3, 4):
            with self.subTest(version=version):
                monitor = self.fixture.local.root / ("store-" + str(version))
                monitor.mkdir(mode=0o700)
                db = self.journal.open_store(monitor, writable=True)
                legacy = copy.deepcopy(request)
                legacy["schema_version"] = 1
                del legacy["identity_observation"], legacy["public_text_declaration"]
                legacy["store_id"] = db.execute("SELECT store_id FROM meta").fetchone()[0]
                if version >= 3:
                    self.journal.record_claim_intent(db, legacy)
                elif version == 2:
                    with db:
                        db.execute("CREATE TABLE binding_acks (incarnation TEXT PRIMARY KEY, task_id TEXT NOT NULL, operation_id TEXT NOT NULL, receipt TEXT NOT NULL, receipt_sha256 TEXT NOT NULL)")
                        db.execute("UPDATE meta SET version=2")
                if version == 4:
                    receipt = copy.deepcopy(historical)
                    receipt["store_id"] = legacy["store_id"]
                    receipt["intent_request_sha256"] = self.journal.fingerprint(legacy)
                    self.journal.record_claim_observation(db, receipt, guard=lambda: None)
                old_receipts = [tuple(row) for row in db.execute("SELECT * FROM claim_observations")] if version == 4 else []
                bound = copy.deepcopy(request)
                bound["store_id"] = legacy["store_id"]
                bound["operation_id"] = bound["claim"]["operation_id"] = OPERATION
                bound["comment"] = self.prepare.codec.render(bound["claim"])
                bound["comment_sha256"] = self.prepare.codec.digest(bound["comment"])
                bound["public_text_declaration"]["approved_body_sha256"] = bound["comment_sha256"]
                old = [tuple(row) for row in db.execute("SELECT * FROM claim_intents")] if version >= 3 else []
                calls = []

                def interrupt():
                    calls.append(True)
                    if len(calls) == 2:
                        raise OSError("fixture interrupted after insert")

                with self.assertRaises(OSError):
                    self.journal.record_claim_intent(db, bound, guard=interrupt)
                self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], version)
                if version >= 3:
                    self.assertEqual([tuple(row) for row in db.execute("SELECT * FROM claim_intents")], old)
                self.assertEqual(self.journal.record_claim_intent(db, bound), "INTENT_RECORDED")
                self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 5)
                for row in old:
                    self.assertIn(row, [tuple(item) for item in db.execute("SELECT * FROM claim_intents")])
                self.assertEqual([tuple(row) for row in db.execute("SELECT * FROM claim_observations")], old_receipts)
                db.close()

    def test_postcommit_lost_ack_replay_repairs_without_get(self):
        with mock.patch.object(self.intent, "durable", side_effect=OSError("private-canary")):
            self.assertEqual(self.direct()[0], 3)
        before = self.rows()
        with mock.patch.object(self.intent, "durable", wraps=self.intent.durable) as barrier:
            self.assertEqual(self.direct(steps=[])[1]["status"], "REPLAYED_PENDING")
        self.assertEqual(barrier.call_count, 1)
        self.assertFalse(self.calls.exists())
        self.assertEqual(self.rows(), before)

    def test_commit_exception_rolls_back_migration_and_request(self):
        self.legacy()
        before = self.rows()
        actual_open = self.journal.open_store

        class FailedCommit(self.journal.StoreConnection):
            def __exit__(connection, kind, value, traceback):
                if kind is None and connection.execute("SELECT version FROM meta").fetchone()[0] == 5:
                    connection.rollback()
                    raise sqlite3.OperationalError("fixture commit failed")
                return super().__exit__(kind, value, traceback)

        def open_store(root, writable=False):
            db = actual_open(root, writable=writable)
            if not writable:
                return db
            identity = db.file_identity
            db.close()
            replacement = sqlite3.connect((root / "history.sqlite3").as_uri() + "?mode=rw",
                                          uri=True, factory=FailedCommit)
            replacement.row_factory = sqlite3.Row
            replacement.file_identity = identity
            replacement.execute("PRAGMA foreign_keys=ON")
            replacement.execute("PRAGMA synchronous=FULL")
            return replacement

        with mock.patch.object(self.journal, "open_store", side_effect=open_store):
            self.assertEqual(self.direct(self.new_options())[0], 3)
        self.assertEqual(self.rows(), before)

    def test_database_change_during_get_and_coordinator_contention_refuse(self):
        self.legacy()
        before = self.rows()
        actual = self.observer.Transport.get

        def get(transport, *args, **kwargs):
            db = self.journal.open_store(self.monitor, writable=True)
            with db:
                db.execute("UPDATE meta SET store_id=?", ("f" * 32,))
                rows = db.execute("SELECT operation_id,request FROM claim_intents").fetchall()
                for operation, raw in rows:
                    request = self.journal.decode_intent(raw)
                    request["store_id"] = "f" * 32
                    db.execute("UPDATE claim_intents SET request=?,request_sha256=? WHERE operation_id=?",
                               (self.journal.canonical(request), self.journal.fingerprint(request), operation))
            db.close()
            return actual(transport, *args, **kwargs)

        # Change once: later opens remain structurally valid, but the selected
        # store incarnation/full bytes differ from the pre-network snapshot.
        called = []

        def change_once(transport, *args, **kwargs):
            if not called:
                called.append(True)
                return get(transport, *args, **kwargs)
            return actual(transport, *args, **kwargs)

        with mock.patch.object(self.observer.Transport, "get", change_once):
            self.assertEqual(self.direct(self.new_options())[1]["reason"], "LOCAL_SNAPSHOT_CHANGED")
        self.assertEqual(self.rows()[0], before[0])
        self.assertEqual(len(self.rows()[1]), 1)
        with mock.patch.object(self.core, "CoordinatorLock", side_effect=self.core.BusyError("busy")):
            self.assertEqual(self.direct(self.new_options())[1]["reason"], "COORDINATOR_BUSY")

    def test_malformed_rehashed_declaration_refused_before_get(self):
        self.assert_recorded()
        request = self.request()
        for section, key, value in (("identity_observation", "actor_node_id", "node prose"),
                                    ("public_text_declaration", "approved_body_sha256", "0" * 64)):
            changed = copy.deepcopy(request)
            changed[section][key] = value
            # Raw SQLite is fixture corruption, not the supported append API.
            db = sqlite3.connect(self.database)
            with db:
                db.execute("UPDATE claim_intents SET request=?,request_sha256=?",
                           (self.journal.canonical(changed), self.journal.fingerprint(changed)))
            db.close()
            self.assertEqual(self.invoke(steps=[])[0], 3)
            self.assertFalse(self.calls.exists())
        db = sqlite3.connect(self.database)
        with db:
            db.execute("UPDATE claim_intents SET request=?,request_sha256=?",
                       (self.journal.canonical(request), self.journal.fingerprint(request)))
        db.close()
        self.assertEqual(self.invoke(steps=[])[0], 0)

    def test_old_version_boundary_and_v2_requires_v5(self):
        self.assert_recorded()
        db = self.journal.open_store(self.monitor, writable=True)
        try:
            # Exact previous v4 version boundary; no old runtime is executed.
            old_versions = {1: self.journal.TABLES, 2: self.journal.TABLES | {"binding_acks"},
                            3: self.journal.TABLES | {"binding_acks", "claim_intents"},
                            4: self.journal.TABLES | {"binding_acks", "claim_intents", "claim_observations"}}
            self.assertNotIn(db.execute("SELECT version FROM meta").fetchone()[0], old_versions)
            with db:
                db.execute("UPDATE meta SET version=4")
            with self.assertRaises(self.journal.JournalError):
                self.journal.validate_store(db)
        finally:
            db.close()

    def test_legacy_observer_and_receipt_replay_in_mixed_v5_store(self):
        self.assert_recorded()
        bound = self.request()
        legacy = receipts.ReceiptTests("test_visible_receipt_exact_summary_hash_and_historical_replay_no_get")
        legacy.setUp()
        self.addCleanup(legacy.doCleanups)
        legacy.invoke([legacy.comment()])
        retained = legacy.retained()
        db = legacy.journal.open_store(legacy.monitor, writable=True)
        try:
            old = tuple(db.execute("SELECT * FROM claim_intents").fetchone())
            bound["store_id"] = legacy.store_id
            bound["operation_id"] = bound["claim"]["operation_id"] = OPERATION
            bound["comment"] = legacy.prepare.codec.render(bound["claim"])
            bound["comment_sha256"] = legacy.prepare.codec.digest(bound["comment"])
            bound["public_text_declaration"]["approved_body_sha256"] = bound["comment_sha256"]
            legacy.journal.record_claim_intent(db, bound)
            self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 5)
            self.assertIn(old, [tuple(row) for row in db.execute("SELECT * FROM claim_intents")])
        finally:
            db.close()
        self.assertEqual(legacy.invoke([legacy.comment()])[1]["status"], "HISTORICAL_REPLAY")
        self.assertFalse(legacy.calls.exists())
        self.assertEqual(legacy.retained(), retained)
        legacy.answers.write_text(json.dumps(legacy.steps([legacy.comment()])))
        options = dict(legacy.options(), **{"store-id": legacy.store_id})
        with mock.patch.dict(os.environ, legacy.env, clear=True), \
                mock.patch.object(sys, "argv", [str(ROOT / "scripts/observe-claim-intent.py"),
                    *[item for key, value in options.items() for item in ("--" + key, value)]]):
            args, claim = legacy.observe.arguments(legacy.prepare)
        with mock.patch.dict(os.environ, legacy.env, clear=True):
            self.assertEqual(legacy.observe.observe(args, claim, legacy.prepare, legacy.journal,
                                                    legacy.observer)["status"], "VISIBLE_MATCH")

    def test_actual_orphan_ack_guard_and_monitor_write_preserve_v5(self):
        self.assert_recorded()
        request = self.request()
        binding_fixture = load("bound_candidate_fixture", ROOT / ".agents/skills/workspace-orchestrator/tests/candidate-binding-test.py")
        lane = binding_fixture.BindingTests("test_positive_preserves_lifecycle_and_replays_after_source_moves")
        self.addCleanup(lane.doCleanups)
        # The nested fixture captures this environment for its own bind/core
        # subprocesses. Restore fake-gh routing immediately after setup; no
        # actual GET uses the real-tool environment.
        with mock.patch.dict(os.environ, self.binding_environment, clear=True):
            lane.setUp()
        path = lane.state / "tasks/review/task.json"
        before = path.read_bytes()
        self.assertEqual(lane.bind()["journal_ack"]["status"], "ACKNOWLEDGED")
        request["store_id"] = lane.db.execute("SELECT store_id FROM meta").fetchone()[0]
        self.assertEqual(binding_fixture.journal.record_claim_intent(lane.db, request), "INTENT_RECORDED")
        self.assertEqual(lane.bind()["journal_ack"]["status"], "ACKNOWLEDGED")
        path.write_bytes(before)
        for operation in (lane.request["operation_id"], "different-bind-operation"):
            with self.assertRaisesRegex(binding_fixture.binding.Unverified, "receipt is missing"):
                lane.bind(dict(lane.request, operation_id=operation))
            self.assertEqual(path.read_bytes(), before)
        journal = binding_fixture.journal
        source = "repo:fixture/project"
        seq = journal.begin(lane.db, "v5-poll", "a" * 64, "monitor", [source], "start")
        item = {"repo": "fixture/project", "number": 1, "head": "a" * 40,
                "draft": False, "state": "OPEN", "review": "NONE", "merge": "UNKNOWN", "checks": []}
        journal.finish(lane.db, seq, {source: {"status": "OBSERVED", "items": [item], "digest": None, "reason": None}}, "done")
        self.assertEqual(lane.db.execute("SELECT version FROM meta").fetchone()[0], 5)
        self.assertEqual(journal.status(lane.db, [source])["status"], "AS_OF_POLL")


class BoundObservationTests(unittest.TestCase):
    def setUp(self):
        self.publication = ApprovedIntentTests()
        self.publication.setUp()
        self.addCleanup(self.publication.doCleanups)
        self.publication.assert_recorded()
        self.request = self.publication.request()
        self.fixture = self.publication.fixture
        self.module = load("bound_receipt_cli", ROOT / "scripts/record-claim-observation.py")
        self.prepare, self.core, self.journal, self.intent, self.observe, self.observer = self.module.modules()

    def steps(self, author_id=7):
        records = copy.deepcopy(self.fixture.records)
        comment = dict(fixtures.remote.comment(1, self.request["comment"], "octocat", author_id),
                       issue_url=self.fixture.urls[2])
        issue = dict(records[2], comments=1)
        return [{"url": self.fixture.urls[0], "raw": fixtures.remote.http(records[0])},
                {"url": self.fixture.urls[1], "raw": fixtures.remote.http(records[1])},
                {"url": self.fixture.urls[2], "raw": fixtures.remote.http(issue)},
                {"url": self.fixture.urls[2] + "/comments?per_page=100&page=1", "raw": fixtures.remote.http([comment])},
                {"url": self.fixture.urls[2], "raw": fixtures.remote.http(issue)}]

    def argv(self, overrides=None, observe=False):
        options = dict(self.fixture.local.options(), **{
            "expected-actor-id": "7", "expected-repo-id": "400", "expected-issue-id": "500"})
        if not observe:
            options["observation-id"] = receipts.OBSERVATION
        options.update(overrides or {})
        return [str(ROOT / ("scripts/observe-claim-intent.py" if observe else "scripts/record-claim-observation.py")),
                *[item for key, value in options.items() if value is not None for item in ("--" + key, value)]]

    def invoke(self, steps=None, overrides=None, observe=False):
        self.publication.answers(self.steps() if steps is None else steps)
        outcome = subprocess.run([sys.executable, "-I", "-B", *self.argv(overrides, observe)],
                                 env=self.fixture.env, cwd=self.fixture.local.root, capture_output=True, timeout=15)
        self.assertFalse(outcome.stderr)
        output = json.loads(outcome.stdout)
        self.assertIs(output["mutation_authorized"], False)
        self.assertNotIn(self.request["comment"], outcome.stdout.decode())
        return outcome.returncode, output

    def test_v2_visible_receipt_request_hash_and_zero_get_replay(self):
        self.assertEqual(self.invoke(observe=True)[1]["status"], "VISIBLE_MATCH")
        self.assertEqual(self.invoke()[1]["observation_status"], "HISTORICAL_VISIBLE_MATCH")
        db = self.journal.open_store(self.publication.monitor)
        try:
            receipt = self.journal.claim_observation(db, receipts.OBSERVATION)
            self.assertEqual(receipt["intent_request_sha256"], self.journal.fingerprint(self.request))
            self.assertEqual((receipt["summary"]["repository_id"], receipt["summary"]["issue_id"]), (400, 500))
            self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 5)
            for key in ("repository_id", "issue_id"):
                changed = copy.deepcopy(receipt)
                changed["summary"][key] += 1
                with self.assertRaises(self.journal.JournalError):
                    self.journal.validate_claim_observation(db, changed)
        finally:
            db.close()
        self.assertEqual(self.invoke(steps=[])[1]["status"], "HISTORICAL_REPLAY")
        self.assertFalse(self.publication.calls.exists())

    def test_expected_ids_required_and_mismatch_refused_before_get(self):
        for key in ("expected-actor-id", "expected-repo-id", "expected-issue-id"):
            for value in (None, "999"):
                for observe in (False, True):
                    self.assertEqual(self.invoke(overrides={key: value}, observe=observe)[0], 3)
                    self.assertFalse(self.publication.calls.exists())

    def test_numeric_and_node_mismatch_no_comment_get_or_receipt(self):
        for index in (0, 1, 2):
            for key, value in (("id", 999), ("node_id", "Changed_node")):
                steps = self.steps()
                record = copy.deepcopy(self.fixture.records[index])
                if index == 2:
                    record["comments"] = 1
                record[key] = value
                steps[index]["raw"] = fixtures.remote.http(record)
                for observe in (False, True):
                    self.assertEqual(self.invoke(steps, observe=observe)[0], 3)
                    self.assertEqual(len(json.loads(self.publication.calls.read_text())), index + 1)
                db = self.journal.open_store(self.publication.monitor)
                self.assertEqual(db.execute("SELECT count(*) FROM claim_observations").fetchone()[0], 0)
                db.close()

    def test_final_issue_node_change_refuses_receipt(self):
        steps = self.steps()
        steps[4]["raw"] = fixtures.remote.http(dict(self.fixture.records[2], comments=1, node_id="I_changed"))
        self.assertEqual(self.invoke(steps)[0], 3)
        db = self.journal.open_store(self.publication.monitor)
        self.assertEqual(db.execute("SELECT count(*) FROM claim_observations").fetchone()[0], 0)
        db.close()

    def test_v5_reserved_observation_ids_refuse_future_intents(self):
        self.invoke()
        db = self.journal.open_store(self.publication.monitor, writable=True)
        try:
            changed = copy.deepcopy(self.request)
            changed["operation_id"] = changed["claim"]["operation_id"] = receipts.OBSERVATION
            changed["comment"] = self.prepare.codec.render(changed["claim"])
            changed["comment_sha256"] = self.prepare.codec.digest(changed["comment"])
            changed["public_text_declaration"]["approved_body_sha256"] = changed["comment_sha256"]
            with self.assertRaisesRegex(self.journal.JournalError, "reserved claim observation identifier"):
                self.journal.record_claim_intent(db, changed)
            self.assertEqual(db.execute("SELECT count(*) FROM claim_intents").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM claim_observations").fetchone()[0], 1)
        finally:
            db.close()

    def test_comment_author_numeric_id_must_match_bound_current_user(self):
        self.assertEqual(self.invoke(self.steps(author_id=99))[1]["observation_status"], "HISTORICAL_CONFLICT")


if __name__ == "__main__":
    unittest.main()
