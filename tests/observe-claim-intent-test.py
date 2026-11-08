#!/usr/bin/env python3
"""Actual task/intent CLI + fake GET fixtures; execute only in an isolated guest."""

import copy
import json
import os
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock
import importlib.util

SOURCE = Path(__file__).resolve().parents[1]
SCRIPT = SOURCE / "scripts/observe-claim-intent.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


intent_fixture = load("observation_intent_fixture", SOURCE / "tests/journal-claim-intent-test.py")
rest = load("observation_rest_fixture", SOURCE / "tests/observe-github-claims-test.py")
task_fixture = intent_fixture.fixture


class IntentObservationTests(unittest.TestCase):
    core_cli = task_fixture.PreparationTest.core_cli
    owned = task_fixture.PreparationTest.owned
    options = task_fixture.PreparationTest.options
    write = task_fixture.PreparationTest.write
    snapshot = task_fixture.PreparationTest.snapshot

    def setUp(self):
        task_fixture.PreparationTest.setUp(self)
        # Construct real schema-3 task and journal intent through their actual
        # CLIs; only GH is faked. No public-summary/capture input is accepted.
        options = self.options()
        completed = subprocess.run([sys.executable, "-I", "-B",
                                   str(SOURCE / "scripts/journal-claim-intent.py"),
                                   *[part for key, value in options.items() for part in ("--" + key, value)]],
                                  cwd=self.root, env=self.env, capture_output=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "INTENT_RECORDED")
        self.module = load("fixture_observe_intent", SCRIPT)
        self.prepare, self.journal, self.observer = self.module.modules()
        self.monitor = self.state / "monitor"
        self.database = self.monitor / "history.sqlite3"
        db = self.journal.open_store(self.monitor, writable=False)
        try:
            self.request = self.journal.decode_intent(db.execute("SELECT request FROM claim_intents").fetchone()[0])
        finally:
            db.close()
        self.store_id = self.request["store_id"]
        self.body = self.request["comment"]
        self.answers = self.root / "answers.json"
        self.calls = self.root / "calls.json"
        gh = self.root / "gh"
        gh.write_text(f"#!{sys.executable}\n" + rest.FAKE)
        gh.chmod(0o700)
        self.env.update(PATH=str(self.root), GH_TOKEN="fixture-credential",
                        FIXTURE=str(self.answers), CALLS=str(self.calls))
        self.repo_url = self.observer.API + "/repos/example/project"
        self.issue_url = self.repo_url + "/issues/117"

    def argv(self, overrides=None, extra=()):
        options = dict(self.options(), **{"store-id": self.store_id})
        options.update(overrides or {})
        return [str(SCRIPT), *[part for key, value in options.items() if value is not None
                              for part in ("--" + key, value)], *extra]

    def comment(self, identifier=1, body=None, login="octocat", actor_id=7):
        return dict(rest.comment(identifier, self.body if body is None else body, login, actor_id),
                    issue_url=self.issue_url)

    def steps(self, records):
        issue = dict(rest.ISSUE, url=self.issue_url, repository_url=self.repo_url,
                     html_url="https://github.com/example/project/issues/117", comments=len(records))
        return [{"url": self.observer.API + "/user", "raw": rest.http({"id": 7, "login": "octocat", "type": "User"})},
                {"url": self.repo_url, "raw": rest.http({"id": 400, "full_name": "example/project", "url": self.repo_url})},
                {"url": self.issue_url, "raw": rest.http(issue)},
                {"url": self.issue_url + "/comments?per_page=100&page=1", "raw": rest.http(records)},
                {"url": self.issue_url, "raw": rest.http(issue)}]

    def sanitized(self, output):
        text = json.dumps(output)
        self.assertFalse(output["mutation_authorized"] or output["absence_authorizing"] or output["atomic_snapshot"])
        self.assertEqual(output["current_task_authority"], "UNVERIFIED")
        self.assertEqual(output["remote_operation_completion"], "UNVERIFIED")
        for private in (str(self.root), task_fixture.SESSION, self.store_id, self.body,
                        self.task["task_id"], self.task["scope"], self.task["worker"]["worker_id"],
                        self.task["worker"]["token"], self.task["owner"], task_fixture.CLAIM,
                        task_fixture.OPERATION, "octocat", "example/project"):
            self.assertNotIn(private, text)

    def invoke(self, records=None, overrides=None, extra=(), steps=None):
        if self.calls.exists():
            self.calls.unlink()
        self.answers.write_text(json.dumps(self.steps(records or []) if steps is None else steps))
        before = self.snapshot()
        completed = subprocess.run([sys.executable, "-I", "-B", *self.argv(overrides, extra)],
                                   cwd=self.root, env=self.env, capture_output=True, timeout=15)
        self.assertFalse(completed.stderr)
        self.assertEqual(self.snapshot(), before)
        output = json.loads(completed.stdout)
        self.sanitized(output)
        return completed.returncode, output

    def direct(self, steps, overrides=None):
        if self.calls.exists():
            self.calls.unlink()
        self.answers.write_text(json.dumps(steps))
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(sys, "argv", self.argv(overrides)), \
                mock.patch.object(self.module, "modules", return_value=(self.prepare, self.journal, self.observer)), \
                mock.patch("builtins.print") as printed:
            code = self.module.main()
        output = json.loads(printed.call_args.args[0])
        self.sanitized(output)
        return code, output

    def test_cli_exact_visible_match_remains_exit3_no_authority_or_storage_changes(self):
        code, output = self.invoke([self.comment()])
        self.assertEqual((code, output["status"]), (3, "VISIBLE_MATCH"))
        self.assertEqual(output["comment_id"], 1)
        self.assertEqual(output["comment_sha256"], self.request["comment_sha256"])
        self.assertTrue(output["bound_retained_snapshot"])
        self.assertEqual(output["remote_coverage"], "complete_pagination")
        self.assertEqual(len(json.loads(self.calls.read_text())), 5)

    def test_absence_not_authorizing_and_optional_store_fence(self):
        code, output = self.invoke(overrides={"store-id": None})
        self.assertEqual((code, output["status"], output["reason"]), (3, "UNVERIFIED", "NO_MATCH_OBSERVED"))
        self.assertNotIn("comment_id", output)
        self.assertEqual(self.invoke([self.comment()], {"store-id": None})[1]["status"], "VISIBLE_MATCH")

    def test_actor_id_login_body_competing_and_duplicate_operation_conflicts(self):
        claim = self.request["claim"]
        cases = [[self.comment(login="other")], [self.comment(actor_id=99)],
                 [self.comment(body=self.prepare.codec.render(dict(claim, actor="other")), login="other", actor_id=8)],
                 [self.comment(body=self.prepare.codec.render(dict(claim, branch="edited")))],
                 [self.comment(), self.comment(2)],
                 [self.comment(), self.comment(2, self.prepare.codec.render(dict(claim, claim_id="a" * 32,
                                                                              operation_id="b" * 32)))]]
        for records in cases:
            with self.subTest(records=records):
                code, output = self.invoke(records)
                self.assertEqual((code, output["status"]), (4, "CONFLICT"))
                self.assertNotIn("comment_id", output)

    def test_malformed_body_mentions_do_not_prove_operation_conflict(self):
        operation = self.request["operation_id"]
        for body in (f"Ordinary prose mentions native-claim and {operation}.",
                     "```text\n" + self.body + "```\n",
                     '<!-- native-claim:v1 {"operation_id":"' + operation + '"',
                     "<!-- native-claim:v1 {} -->\nOperation outside payload: " + operation,
                     self.body + "edited",
                     self.body.replace("Operator review", "Human review")):
            with self.subTest(body=body):
                code, output = self.invoke([self.comment(body=body)])
                self.assertEqual((code, output["status"]), (3, "UNVERIFIED"))
                self.assertNotIn("comment_id", output)
                self.assertEqual(output["remote_coverage"], "unmeasured")

    def test_stale_private_public_and_store_fences_fail_before_get(self):
        for overrides in ({"expected-revision": "1"}, {"expected-generation": "2"},
                          {"expected-worker-id": "e" * 32}, {"expected-session-id": "other-session"},
                          {"actor": "other"}, {"store-id": "e" * 32}, {"operation-id": "a" * 32}):
            with self.subTest(overrides=overrides):
                code, output = self.invoke([self.comment()], overrides)
                self.assertIn(code, (3, 4))
                self.assertNotEqual(output["status"], "VISIBLE_MATCH")
                self.assertFalse(self.calls.exists())

    def test_current_valid_task_with_same_revision_differs_from_retained_intent(self):
        self.write(self.task_path, dict(self.task, next_action="changed private narrative"))
        self.assertEqual(self.invoke([self.comment()])[1]["reason"], "OPERATION_CONFLICT")
        self.assertFalse(self.calls.exists())

    def test_unknown_unsafe_and_legacy_store_fail_without_creation_or_upgrade(self):
        for suffix in ("-journal", "-wal", "-shm"):
            path = Path(str(self.database) + suffix)
            path.symlink_to(self.database)
            self.assertEqual(self.invoke()[0], 3)
            self.assertFalse(self.calls.exists())
            path.unlink()
        original = self.database.read_bytes()
        # WAL read-only open can create -shm. Reject its persistent header before
        # calling SQLite, including a WAL database with no sidecars yet.
        self.database.write_bytes(original[:18] + b"\x02\x02" + original[20:])
        self.assertEqual(self.invoke()[1]["reason"], "JOURNAL_RECOVERY_UNVERIFIED")
        self.assertFalse(self.calls.exists() or Path(str(self.database) + "-shm").exists())
        self.database.write_bytes(original)
        self.database.chmod(0o644)
        self.assertEqual(self.invoke()[0], 3)
        self.assertFalse(self.calls.exists())
        self.database.chmod(0o600)
        db = self.journal.open_store(self.monitor, writable=True)
        with db:
            db.execute("UPDATE claim_intents SET request_sha256=?", ("a" * 64,))
        db.close()
        self.assertEqual(self.invoke()[0], 3)
        self.assertFalse(self.calls.exists())

    def test_missing_store_and_uninitialized_root_never_create_state(self):
        self.database.unlink()
        self.assertEqual(self.invoke()[0], 3)
        self.assertFalse(self.database.exists() or self.calls.exists())
        other = self.root / "empty"
        other.mkdir()
        self.assertEqual(self.invoke(overrides={"authority-root": str(other), "invoking-root": str(other)})[0], 3)
        self.assertFalse((other / ".orchestrator").exists() or self.calls.exists())

    def test_legacy_journal_and_schema2_task_are_not_migrated(self):
        db = self.journal.open_store(self.monitor, writable=True)
        with db:
            db.execute("DROP TABLE claim_intents")
            db.execute("UPDATE meta SET version=2")
        db.close()
        self.assertEqual(self.invoke()[0], 3)
        self.assertFalse(self.calls.exists())
        legacy = copy.deepcopy(self.task)
        legacy["schema_version"] = 2
        del legacy["cooperative_binding"]
        for key in ("session_id", "generation"):
            del legacy["worker"][key]
        self.write(self.task_path, legacy)
        self.assertEqual(self.invoke()[0], 3)
        self.assertFalse(self.calls.exists())

    def test_malformed_pagination_duplicate_records_and_issue_changed_are_unverified(self):
        steps = self.steps([self.comment()])
        malformed = copy.deepcopy(steps)
        malformed[3]["raw"] = rest.http([self.comment()], "Link: <https://evil.invalid/>; rel=\"next\"\r\n")
        changed = copy.deepcopy(steps)
        changed[-1]["raw"] = changed[-1]["raw"].replace('"id": 500', '"id": 501')
        for fixture in (malformed, changed, self.steps([self.comment(), self.comment()])):
            self.assertEqual(self.invoke(steps=fixture)[0], 3)

    def test_deadline_failure_sanitized_and_private_state_unchanged(self):
        steps = self.steps([self.comment()])
        steps[0]["delay"] = 30
        before = self.snapshot()
        with mock.patch.object(self.observer, "DEADLINE_SECONDS", 0.1):
            code, output = self.direct(steps)
        self.assertEqual((code, output["reason"]), (3, "DEADLINE_EXCEEDED"))
        self.assertEqual(self.snapshot(), before)

    def test_network_has_no_open_database_or_coordinator_lock(self):
        real_open = self.journal.open_store
        connections = []
        statements = []

        def opened(*args, **kwargs):
            self.assertIs(kwargs.get("writable"), False)
            db = real_open(*args, **kwargs)
            db.set_trace_callback(statements.append)
            connections.append(db)
            return db

        real_get = self.observer.Transport.get

        def get(transport, *args, **kwargs):
            self.assertFalse((self.state / "locks/coordinator.lock").exists())
            for db in connections:
                with self.assertRaises(sqlite3.ProgrammingError):
                    db.execute("SELECT 1")
            return real_get(transport, *args, **kwargs)

        before = self.snapshot()
        with mock.patch.object(self.journal, "open_store", side_effect=opened), \
                mock.patch.object(self.observer.Transport, "get", get):
            self.assertEqual(self.direct(self.steps([self.comment()]))[1]["status"], "VISIBLE_MATCH")
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(statements)
        self.assertTrue(all(statement.lstrip().split()[0].upper() in {"SELECT", "PRAGMA", "BEGIN", "ROLLBACK"}
                            for statement in statements), statements)

    def test_task_change_during_get_invalidates_positive_and_conflict(self):
        real_get = self.observer.Transport.get

        def get(transport, *args, **kwargs):
            self.write(self.task_path, dict(self.task, next_action="private concurrent change"))
            return real_get(transport, *args, **kwargs)

        with mock.patch.object(self.observer.Transport, "get", get):
            for records in ([self.comment()], [self.comment(login="other")]):
                code, output = self.direct(self.steps(records))
                self.assertEqual((code, output["reason"]), (3, "LOCAL_SNAPSHOT_CHANGED"))
                self.write(self.task_path, self.task)

    def test_database_replacement_or_row_change_during_get_invalidates_match(self):
        real_get = self.observer.Transport.get
        original = self.database.read_bytes()

        def replace(transport, *args, **kwargs):
            replacement = self.monitor / "replacement"
            replacement.write_bytes(original)
            replacement.chmod(0o600)
            os.replace(replacement, self.database)
            return real_get(transport, *args, **kwargs)

        with mock.patch.object(self.observer.Transport, "get", replace):
            self.assertEqual(self.direct(self.steps([self.comment()]))[1]["reason"], "LOCAL_SNAPSHOT_CHANGED")
        changed = False

        def row_change(transport, *args, **kwargs):
            nonlocal changed
            if not changed:
                db = self.journal.open_store(self.monitor, writable=True)
                with db:
                    db.execute("DELETE FROM claim_intents")
                db.close()
                changed = True
            return real_get(transport, *args, **kwargs)

        with mock.patch.object(self.observer.Transport, "get", row_change):
            self.assertEqual(self.direct(self.steps([self.comment()]))[1]["reason"], "LOCAL_SNAPSHOT_CHANGED")

    def test_private_binding_lease_change_during_get_invalidates_match(self):
        real_get = self.observer.Transport.get
        path = self.state / "slots" / f'{self.task["leases"]["global_slot"]}.lock/owner.json'

        def get(transport, *args, **kwargs):
            self.write(path, dict(self.task["worker"], token="e" * 32))
            return real_get(transport, *args, **kwargs)

        with mock.patch.object(self.observer.Transport, "get", get):
            self.assertEqual(self.direct(self.steps([self.comment()]))[1]["reason"], "LOCAL_SNAPSHOT_CHANGED")

    def test_duplicate_missing_malformed_arguments_and_summary_file_refused_before_get(self):
        for extra in (("--operation-id=" + task_fixture.OPERATION,), ("--store-id", self.store_id),
                      ("--comments", "private-capture"), ("--summary", "private-summary")):
            self.assertEqual(self.invoke(extra=extra)[0], 3)
            self.assertFalse(self.calls.exists())
        for overrides in ({"store-id": "a" * 16}, {"operation-id": None}, {"expected-generation": None}):
            self.assertEqual(self.invoke(overrides=overrides)[0], 3)
            self.assertFalse(self.calls.exists())

    def test_arbitrary_storage_error_never_leaks_exception_text(self):
        with mock.patch.object(self.journal, "open_store", side_effect=OSError("private-path-canary")):
            code, output = self.direct(self.steps([self.comment()]))
        self.assertEqual((code, output["reason"]), (3, "READ_UNAVAILABLE"))
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
