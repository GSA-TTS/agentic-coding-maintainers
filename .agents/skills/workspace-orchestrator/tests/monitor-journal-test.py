#!/usr/bin/env python3
"""Durable observation positives, restart, gaps and transactional refusal."""

import importlib.util
import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / "bin" / "monitor-journal.py"
spec = importlib.util.spec_from_file_location("journal", SOURCE)
assert spec and spec.loader
journal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journal)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = journal.open_store(self.root, writable=True)
        self.addCleanup(lambda: self.db.close())
        self.counter = 0
        self.sources = ["repo:fixture/project"]

    def start(self, sources=None):
        self.counter += 1
        return journal.begin(self.db, f"attempt{self.counter}", "a" * 64, "monitor", sources or self.sources, "start")

    def pr(self, head="a" * 40, number=1):
        return {"repo": "fixture/project", "number": number, "head": head, "draft": False, "state": "OPEN", "review": "NONE", "merge": "UNKNOWN", "checks": []}

    def observed(self, items):
        return {self.sources[0]: {"status": "OBSERVED", "items": items, "digest": None, "reason": None}}

    def snapshot(self):
        return journal.status(self.db, self.sources)

    def test_restart_unchanged_and_a_b_a_generations(self):
        first = self.start()
        self.assertEqual(journal.finish(self.db, first, self.observed([self.pr()]), "done")["status"], "CHANGED")
        store = self.snapshot()["store_id"]
        self.db.close()
        self.db = journal.open_store(self.root, writable=True)
        self.assertEqual(journal.finish(self.db, self.start(), self.observed([{**self.pr(), "title": "changed ignored title"}]), "done")["status"], "CURRENT")
        self.assertEqual(self.snapshot()["candidates"][0]["generation"], 1)
        for head in ("b" * 40, "a" * 40):
            journal.finish(self.db, self.start(), self.observed([self.pr(head)]), "done")
        self.assertEqual(self.snapshot()["candidates"][0]["generation"], 3)
        self.assertEqual(self.snapshot()["store_id"], store)

    def test_failure_preserves_candidates_and_successful_absence_is_not_closure(self):
        journal.finish(self.db, self.start(), self.observed([self.pr()]), "done")
        failed = {self.sources[0]: {"status": "UNVERIFIED", "items": [], "digest": None, "reason": "FETCH_FAILED"}}
        self.assertEqual(journal.finish(self.db, self.start(), failed, "done")["status"], "UNVERIFIED")
        self.assertEqual(self.snapshot()["candidates"][0]["generation"], 1)
        self.assertFalse(self.snapshot()["candidates"][0]["latest_poll_observed_source"])
        journal.finish(self.db, self.start(), self.observed([]), "done")
        candidate = self.snapshot()["candidates"][0]
        self.assertEqual(candidate["observation"]["presence"], "NOT_IN_OPEN_SET")
        self.assertEqual(candidate["observation"]["state"], "OPEN")
        journal.finish(self.db, self.start(), self.observed([self.pr()]), "done")
        self.assertEqual(self.snapshot()["candidates"][0]["generation"], 3)

    def test_duplicate_finalization_no_new_events_and_conflict_refused(self):
        seq = self.start()
        result = journal.finish(self.db, seq, self.observed([self.pr()]), "done")
        self.assertEqual(journal.finish(self.db, seq, self.observed([self.pr()]), "later"), result)
        self.assertEqual(self.db.execute("SELECT count(*) FROM events").fetchone()[0], 1)
        with self.assertRaises(journal.JournalError):
            journal.finish(self.db, seq, self.observed([self.pr("b" * 40)]), "later")

    def test_crashed_poll_is_interrupted_never_reapplied_after_empty_snapshot(self):
        old = self.start()
        new = self.start()
        journal.finish(self.db, new, self.observed([]), "done")
        with self.assertRaises(journal.JournalError):
            journal.finish(self.db, old, self.observed([self.pr()]), "late")
        self.assertEqual(self.snapshot()["candidates"], [])
        self.assertEqual(self.db.execute("SELECT status FROM polls WHERE seq=?", (old,)).fetchone()[0], "INTERRUPTED")

    def test_partial_project_failure_still_retains_observed_repository(self):
        sources = self.sources + ["project:fixture/1"]
        results = self.observed([self.pr()])
        results[sources[1]] = {"status": "UNVERIFIED", "items": [], "digest": None, "reason": "FETCH_FAILED"}
        self.assertEqual(journal.finish(self.db, self.start(sources), results, "done")["status"], "UNVERIFIED")
        self.assertEqual(len(journal.status(self.db, sources)["candidates"]), 1)
        self.assertEqual(journal.status(self.db, ["repo:other/project"])["candidates"][0]["scope"], "OUT_OF_SCOPE")

    def test_limits_rollback_without_losing_existing_projection(self):
        journal.finish(self.db, self.start(), self.observed([self.pr()]), "done")
        seq = self.start()
        with mock.patch.object(journal, "MAX_EVENTS", 1):
            with self.assertRaises(journal.JournalError):
                journal.finish(self.db, seq, self.observed([self.pr("b" * 40)]), "done")
        self.assertEqual(self.snapshot()["candidates"][0]["generation"], 1)
        self.assertEqual(self.snapshot()["status"], "UNVERIFIED")

    def test_duplicate_malformed_pr_never_overwrites(self):
        seq = self.start()
        for items in ([self.pr(), self.pr()], [self.pr(head="invalid")], [self.pr(number=0)]):
            with self.assertRaises(journal.JournalError):
                journal.finish(self.db, seq, self.observed(items), "done")
        self.assertEqual(self.snapshot()["candidates"], [])

    def test_status_is_read_only_and_absent_history_unknown(self):
        journal.finish(self.db, self.start(), self.observed([]), "done")
        self.db.close()
        path = self.root / "history.sqlite3"
        before = path.read_bytes()
        self.db = journal.open_store(self.root)
        self.assertEqual(self.snapshot()["status"], "AS_OF_POLL")
        self.assertEqual(path.read_bytes(), before)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(journal.JournalError):
                journal.open_store(Path(directory))

    def test_database_symlink_hardlink_permissions_and_corruption_refused(self):
        self.db.close()
        path = self.root / "history.sqlite3"
        path.chmod(0o644)
        with self.assertRaises(journal.JournalError):
            journal.open_store(self.root)
        path.chmod(0o600)
        os.link(path, self.root / "alias")
        with self.assertRaises(journal.JournalError):
            journal.open_store(self.root)
        (self.root / "alias").unlink()
        (self.root / "history.sqlite3-journal").symlink_to(path)
        with self.assertRaises(journal.JournalError):
            journal.open_store(self.root)
        (self.root / "history.sqlite3-journal").unlink()
        path.write_bytes(b"corrupt")
        with self.assertRaises(Exception):
            journal.open_store(self.root)

    def test_valid_sqlite_with_corrupted_receipt_or_event_is_unknown(self):
        journal.finish(self.db, self.start(), self.observed([self.pr()]), "done")
        self.db.execute("UPDATE polls SET response='{}'")
        self.db.commit()
        with self.assertRaises(journal.JournalError):
            self.snapshot()

    def test_deleted_candidate_and_altered_coverage_are_unverified(self):
        journal.finish(self.db, self.start(), self.observed([self.pr()]), "done")
        self.db.execute("UPDATE coverage SET count=99")
        self.db.commit()
        with self.assertRaises(journal.JournalError):
            self.snapshot()
        self.db.execute("UPDATE coverage SET count=1")
        self.db.execute("DELETE FROM candidates")
        self.db.commit()
        with self.assertRaises(journal.JournalError):
            self.snapshot()

    def test_status_read_transaction_retains_single_snapshot(self):
        journal.finish(self.db, self.start(), self.observed([self.pr()]), "done")
        # WAL is test-only to force a writer commit between reader SELECTs.
        # Production uses DELETE, where the same read transaction blocks commit.
        self.db.execute("PRAGMA journal_mode=WAL")
        writer = journal.sqlite3.connect(self.root / "history.sqlite3", timeout=2)
        writer.row_factory = journal.sqlite3.Row
        fired = False
        def interleave(sql):
            nonlocal fired
            if not fired and sql == "SELECT * FROM polls ORDER BY seq DESC LIMIT 1":
                fired = True
                seq = journal.begin(writer, "concurrent", "a"*64, "monitor", self.sources, "now")
                journal.finish(writer, seq, self.observed([self.pr("b"*40)]), "done")
        self.db.set_trace_callback(interleave)
        try:
            result = self.snapshot()
        finally:
            self.db.set_trace_callback(None)
            writer.close()
        self.assertTrue(fired)
        self.assertEqual(result["poll_seq"], 1)
        self.assertEqual(result["candidates"][0]["generation"], 1)
        self.assertEqual(self.snapshot()["poll_seq"], 2)

    def test_raw_github_malformed_types_never_normalize_clean(self):
        path = SOURCE.with_name("orchestrator-monitor.py")
        spec = importlib.util.spec_from_file_location("monitor", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        good = {"number":1,"headRefOid":"a"*40,"isDraft":False,"state":"OPEN",
                "reviewDecision":None,"mergeStateStatus":"UNKNOWN","statusCheckRollup":[]}
        for changed in ({"reviewDecision":False},{"mergeStateStatus":[]},{"statusCheckRollup":[{}]},
                        {"statusCheckRollup":[{"status":None}]},{"statusCheckRollup":[{"conclusion":None}]},
                        {"statusCheckRollup":[{"status":"COMPLETED","conclusion":None}]}):
            with self.subTest(changed=changed), self.assertRaises(module.MonitorError):
                module.pr_snapshot(["fixture/project"], lambda _: json.dumps([{**good,**changed}]))
        with self.assertRaises(module.MonitorError):
            module.project_snapshot({"number":1,"owner":"fixture"}, lambda _: '{"items":[null],"totalCount":1}')

    def test_open_validation_uses_one_snapshot(self):
        journal.finish(self.db, self.start(), self.observed([self.pr()]), "done")
        self.db.execute("PRAGMA journal_mode=WAL")
        actual_connect = journal.sqlite3.connect
        writer = actual_connect(self.root / "history.sqlite3")
        writer.row_factory = journal.sqlite3.Row
        fired = False
        def connect(*args, **kwargs):
            connection = actual_connect(*args, **kwargs)
            def interleave(sql):
                nonlocal fired
                if not fired and sql == "SELECT * FROM polls ORDER BY seq":
                    fired = True
                    seq = journal.begin(writer, "during-open", "a" * 64, "monitor", self.sources, "now")
                    journal.finish(writer, seq, self.observed([self.pr("b" * 40)]), "done")
            connection.set_trace_callback(interleave)
            return connection
        try:
            with mock.patch.object(journal.sqlite3, "connect", side_effect=connect):
                reader = journal.open_store(self.root)
                reader.close()
            self.assertTrue(fired)
            self.assertEqual(self.snapshot()["poll_seq"], 2)
        finally:
            writer.close()

    def test_replay_utility_accepts_relative_output(self):
        capture = self.root / "capture.json"
        capture.write_text(json.dumps({"fixture/project":[self.pr()]}))
        result = subprocess.run([sys.executable, "-I", "-B", str(SOURCE.parent.parent/"tests/monitor-capture-replay.py"), str(capture), "relative-output"],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root/"relative-output/outcome.json").is_file())

    def test_busy_writer_cannot_commit_partial_poll(self):
        second = journal.open_store(self.root, writable=True)
        try:
            second.execute("PRAGMA busy_timeout=1")
            self.db.execute("BEGIN IMMEDIATE")
            with self.assertRaises(Exception):
                journal.begin(second, "competing", "a" * 64, "monitor", self.sources, "now")
            self.db.rollback()
            self.assertEqual(self.db.execute("SELECT count(*) FROM polls").fetchone()[0], 0)
        finally:
            second.close()

    def test_public_monitor_restart_failure_and_status(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        state = workspace / ".orchestrator"
        config = workspace / "config.json"
        config.write_text(json.dumps({"schema_version":1,"repositories":["example/one"]}))
        scripts = SOURCE.parent
        env = {**os.environ, "WORKSPACE_ORCHESTRATOR_ROOT":str(workspace), "ORCHESTRATOR_TEST_MODE":"1", "ORCHESTRATOR_STATE_DIR":str(state),
               "PATH":str(scripts.parent/"tests/fixtures/orchestrator-monitor-bin")+":/usr/bin:/bin", "MONITOR_STUB_MODE":"success"}
        for args in (["create","monitor","--kind","monitor","--scope","fixture:monitor"], ["claim","monitor","--owner","fixture","--pid",str(os.getpid())]):
            result = subprocess.run([sys.executable,"-I","-B",str(scripts/"orchestrator-state.py"),*args],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
        command = [sys.executable,"-I","-B",str(scripts/"orchestrator-monitor.py"),"--config",str(config)]
        for _ in range(2):
            polled = subprocess.run(command+["--task-id","monitor","--durable"],env=env,capture_output=True,text=True)
            self.assertEqual(polled.returncode,0,polled.stdout+polled.stderr)
        before = (state/"monitor/history.sqlite3").read_bytes()
        status = subprocess.run(command+["--status"],env=env,capture_output=True,text=True)
        self.assertEqual(status.returncode,0,status.stdout+status.stderr)
        self.assertEqual(json.loads(status.stdout)["candidates"][0]["generation"],1)
        self.assertEqual((state/"monitor/history.sqlite3").read_bytes(),before)
        failed = subprocess.run(command+["--task-id","monitor","--durable"],env={**env,"MONITOR_STUB_MODE":"failure"},capture_output=True,text=True)
        self.assertEqual(failed.returncode,3)
        status = subprocess.run(command+["--status"],env=env,capture_output=True,text=True)
        self.assertEqual(status.returncode,3)
        self.assertEqual(len(json.loads(status.stdout)["candidates"]),1)
        (state/"monitor/poll.lock").mkdir()
        before = (state/"monitor/history.sqlite3").read_bytes()
        refused = subprocess.run(command+["--task-id","monitor","--durable"],env=env,capture_output=True,text=True)
        self.assertEqual(refused.returncode,3)
        self.assertEqual((state/"monitor/history.sqlite3").read_bytes(),before)


if __name__ == "__main__":
    unittest.main()
