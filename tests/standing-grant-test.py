#!/usr/bin/env python3
"""Offline strict shapes and supported-clock refusal tests; run in sandbox."""

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("grant", SOURCE / ".agents/skills/workspace-orchestrator/bin/standing-grant.py")
grant = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grant)


class GrantTests(unittest.TestCase):
    def test_rollback_suspend_and_reboot_are_not_continuity(self):
        before = {"boot": "a" * 36, "wall": 1000, "elapsed": 100, "awake": 100}
        grant.continuity(before, dict(before, wall=1001, elapsed=101, awake=101))
        for after in (dict(before, wall=999), dict(before, boot="b" * 36),
                      dict(before, wall=1010, elapsed=110, awake=101)):
            with self.subTest(after=after), self.assertRaises(grant.Invalid):
                grant.continuity(before, after)

    def test_stable_logical_key_excludes_grant_or_operation(self):
        original = {"repository_id": 1, "objective": "synthetic", "work_item": "fixture", "grant_id": "a" * 32}
        self.assertEqual(grant.logical_key(original), grant.logical_key(dict(original, grant_id="b" * 32)))
        self.assertNotEqual(grant.logical_key(original), grant.logical_key(dict(original, work_item="other")))

    def test_unknown_fields_refused_before_any_effect(self):
        with self.assertRaises(Exception):
            grant.validate_definition({"approved": True, "version": 1})


class BudgetTests(unittest.TestCase):
    """Exercise accounting against retained SQLite history, including renewals.

    Whole-request/core validation belongs to the separate executor vertical.
    This fixture isolates counters without manufacturing a TTY authorization.
    """

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.t = grant.typed()
        self.db.execute("CREATE TABLE meta(version INTEGER,store_id TEXT)")
        self.db.execute("INSERT INTO meta VALUES(5,?)", ("0" * 32,))
        grant.migrate(self.db)
        self.clock = {"boot": "a" * 36, "wall": 1000000, "elapsed": 100, "awake": 100}
        self.definition = {"grant_id": "b" * 32, "repository_id": 1422648445, "objective": "synthetic"}
        self.record = {"definition": self.definition, "epoch": 1, "activated": self.clock, "expires": self.clock["wall"] + 86400}
        self.db.execute("INSERT INTO standing_grants VALUES(?,?,?)", ("b" * 32, self.t.canonical(self.record), self.t.digest(self.record)))
        grant.put_selector(self.db, {"grant_id": "b" * 32, "epoch": 1, "state": "active", "clock": self.clock, "revocation": None})
        self.current = {"authorization": {"grant_id": "b" * 32, "epoch": 1}, "binding": {
            "action": "issue-create", "clock": self.clock, "logical_key": "current",
            "target": {"repository_id": 1422648445}}}
        self.db.commit()
        # Accounting-only fixture: authorization/TTY/artifact resolution is
        # exercised by ExecutorTests with the actual installed qualification.
        patcher = mock.patch.object(grant, "resolve", side_effect=lambda db, epoch, current:
            grant.get(db, grant.selector(db)["grant_id"]))
        patcher.start()
        self.addCleanup(patcher.stop)

    def history(self, count, action="issue-create", completion="CONFIRMED", settled=True):
        for index in range(count):
            evidence_id, settlement_id = str(index) + "e", str(index) + "s"
            request = {"version": 2, "authorization": {"grant_id": "b" * 32},
                       "binding": {"action": action, "clock": self.clock, "logical_key": "old" + str(index),
                                   "target": {"repository_id": 1422648445, "issue": index + 100}},
                       "evidence_id": evidence_id, "settlement_id": settlement_id}
            self.db.execute("INSERT INTO assignment_requests VALUES(?,?,?,?)",
                            (str(index), self.t.canonical(request), self.t.digest(request), b""))
            for table, identity, value in (("assignment_evidence", evidence_id, {"completion": completion}),
                                           ("assignment_settlements", settlement_id, {} if settled else None)):
                self.db.execute("INSERT INTO " + table + " VALUES(?,?,?,?)",
                    (identity, self.t.canonical(value) if value is not None else None,
                     self.t.digest(value) if value is not None else None, b""))
        self.db.commit()

    def test_fifth_issue_charges_both_and_next_refuses(self):
        self.history(5)
        with self.assertRaisesRegex(grant.Invalid, "DAILY_BUDGET_EXHAUSTED"):
            grant.reserve_budget(self.db, self.current)

    def test_twenty_metadata_actions_exhaust_create_budget(self):
        self.history(20, action="assignees-add")
        with self.assertRaisesRegex(grant.Invalid, "DAILY_BUDGET_EXHAUSTED"):
            grant.reserve_budget(self.db, self.current)

    def test_outstanding_and_cumulative_unknown_risk_are_reserved(self):
        self.history(3, action="assignees-add", completion="UNKNOWN", settled=False)
        with self.assertRaisesRegex(grant.Invalid, "UNRESOLVED_BUDGET_EXHAUSTED"):
            grant.reserve_budget(self.db, self.current)
        # Even hypothetical later settlement never refunds UNKNOWN provenance.
        for row in self.db.execute("SELECT id FROM assignment_settlements").fetchall():
            self.db.execute("UPDATE assignment_settlements SET document=?,sha256=? WHERE id=?",
                            (self.t.canonical({}), self.t.digest({}), row[0]))
        with self.assertRaisesRegex(grant.Invalid, "UNRESOLVED_BUDGET_EXHAUSTED"):
            grant.reserve_budget(self.db, self.current)

    def test_new_grant_id_does_not_reset_retained_daily_history(self):
        self.history(5)
        renewed = {"definition": dict(self.definition, grant_id="c" * 32), "epoch": 2,
                   "activated": self.clock, "expires": self.clock["wall"] + 86400}
        self.db.execute("INSERT INTO standing_grants VALUES(?,?,?)", ("c" * 32, self.t.canonical(renewed), self.t.digest(renewed)))
        grant.put_selector(self.db, {"grant_id": "c" * 32, "epoch": 2, "state": "active", "clock": self.clock, "revocation": None})
        self.current["authorization"] = {"grant_id": "c" * 32, "epoch": 2}
        with self.assertRaisesRegex(grant.Invalid, "DAILY_BUDGET_EXHAUSTED"):
            grant.reserve_budget(self.db, self.current)

    def terminal_no_post(self, outcome):
        for row in self.db.execute("SELECT id FROM assignment_settlements").fetchall():
            terminal = {"completion": "NOT_SENT", "outcome": outcome}
            self.db.execute("UPDATE assignment_settlements SET document=?,sha256=? WHERE id=?",
                            (self.t.canonical(terminal), self.t.digest(terminal), row[0]))
        self.db.commit()

    def test_not_sent_releases_remote_quota_only_after_durable_terminal(self):
        self.history(5, completion="NOT_SENT")
        # Evidence alone, or a terminal without the exact no-launch outcome,
        # cannot refund a reservation that might still launch.
        with self.assertRaisesRegex(grant.Invalid, "DAILY_BUDGET_EXHAUSTED"):
            grant.reserve_budget(self.db, self.current)
        self.terminal_no_post("NOT_SENT")
        grant.reserve_budget(self.db, self.current)
        self.assertEqual(self.db.execute("SELECT count(*) FROM assignment_requests").fetchone()[0], 5)

    def test_satisfied_no_post_does_not_spend_metadata_quota(self):
        self.history(20, action="assignees-add", completion="NOT_SENT")
        self.terminal_no_post("SATISFIED_NO_POST")
        grant.reserve_budget(self.db, self.current)
        self.assertEqual(self.db.execute("SELECT count(*) FROM assignment_requests").fetchone()[0], 20)

    def test_already_satisfied_action_needs_no_remote_quota(self):
        self.history(20, action="assignees-add")
        self.current["binding"].update(action="assignees-add", publisher={"id": 11}, prior_assignee_ids=[11])
        grant.reserve_budget(self.db, self.current)

    def test_objective_hop_does_not_reset_unknown_risk(self):
        self.history(3, action="assignees-add", completion="UNKNOWN", settled=False)
        renewed = {"definition": dict(self.definition, grant_id="c" * 32, objective="other"), "epoch": 2,
                   "activated": self.clock, "expires": self.clock["wall"] + 86400}
        self.db.execute("INSERT INTO standing_grants VALUES(?,?,?)", ("c" * 32, self.t.canonical(renewed), self.t.digest(renewed)))
        grant.put_selector(self.db, {"grant_id": "c" * 32, "epoch": 2, "state": "active", "clock": self.clock, "revocation": None})
        self.current["authorization"] = {"grant_id": "c" * 32, "epoch": 2}
        with self.assertRaisesRegex(grant.Invalid, "UNRESOLVED_BUDGET_EXHAUSTED"):
            grant.reserve_budget(self.db, self.current)


class MigrationTests(unittest.TestCase):
    def migrate_and_compare(self, journal, db, version):
        journal.validate_store(db)
        self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], version)
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'meta'")]
        before = {table: [tuple(row) for row in db.execute("SELECT * FROM " + table)] for table in tables}
        identity = db.execute("SELECT store_id FROM meta").fetchone()[0]
        with db:
            db.execute("BEGIN IMMEDIATE")
            grant.migrate(db)
            journal.validate_store(db)
        self.assertEqual(tuple(db.execute("SELECT version,store_id FROM meta").fetchone()), (7, identity))
        self.assertEqual({table: [tuple(row) for row in db.execute("SELECT * FROM " + table)] for table in tables}, before)
        self.assertEqual(db.execute("SELECT count(*) FROM standing_grants").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT count(*) FROM standing_qualifications").fetchone()[0], 0)

    def test_v1_v2_observation_and_ack_rows_preserved(self):
        typed = grant.typed()
        journal = typed.module("monitor-journal")
        spec = importlib.util.spec_from_file_location("migration_binding_fixture",
            SOURCE / ".agents/skills/workspace-orchestrator/bin/candidate-binding.py")
        binding = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(binding)
        for version in (1, 2):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                db = journal.open_store(Path(directory), writable=True)
                try:
                    source = "repo:fixture/project"
                    sequence = journal.begin(db, "historical-attempt", "a" * 64, "monitor", [source], "start")
                    item = {"repo": "fixture/project", "number": 1, "head": "a" * 40, "draft": False,
                            "state": "OPEN", "review": "NONE", "merge": "UNKNOWN", "checks": []}
                    journal.finish(db, sequence, {source: {"status": "OBSERVED", "items": [item],
                                   "digest": None, "reason": None}}, "done")
                    if version == 2:
                        candidate = {"store_id": db.execute("SELECT store_id FROM meta").fetchone()[0],
                                     "repo": "fixture/project", "number": 1, "generation": 1,
                                     "fingerprint": db.execute("SELECT fingerprint FROM events").fetchone()[0]}
                        binding.acknowledge(db, {"request": {"candidate": candidate, "incarnation": "b" * 32,
                                            "operation_id": "c" * 32, "task_id": "historical-fixture"}})
                    self.migrate_and_compare(journal, db, version)
                finally:
                    db.close()

    def test_v3_v4_legacy_claim_and_observation_rows_preserved(self):
        spec = importlib.util.spec_from_file_location("migration_receipt_fixture", SOURCE / "tests/record-claim-observation-test.py")
        fixture_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture_module)
        for version in (3, 4):
            with self.subTest(version=version):
                fixture = fixture_module.ReceiptTests()
                try:
                    fixture.setUp()
                    if version == 4:
                        self.assertEqual(fixture.invoke([fixture.comment()])[1]["status"], "HISTORICAL_RECORDED")
                    db = fixture.journal.open_store(fixture.monitor, writable=True)
                    try:
                        self.assertGreater(db.execute("SELECT count(*) FROM claim_intents").fetchone()[0], 0)
                        if version == 4:
                            self.assertGreater(db.execute("SELECT count(*) FROM claim_observations").fetchone()[0], 0)
                        self.migrate_and_compare(fixture.journal, db, version)
                    finally:
                        db.close()
                finally:
                    fixture.doCleanups()


if __name__ == "__main__":
    unittest.main()
