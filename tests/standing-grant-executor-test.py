#!/usr/bin/env python3
"""Sandbox-only integration: real TTY/controller/core/SQLite; injected HTTP."""

import copy
import hashlib
import importlib.util
import json
import os
import pty
import re
import select
import shutil
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixtures = load("grant_executor_fixtures", SOURCE / "tests/assignment-dispatch-test.py")
dispatch = load("grant_executor", SOURCE / "scripts/standing-grant-dispatch.py")
controller = load("grant_controller", SOURCE / "scripts/control-standing-grant.py")


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.real_environment = dict(os.environ)
        self.fixture = fixtures.DispatchTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.local = self.fixture.local
        self.args = copy.copy(self.fixture.args)
        self.adapter, self.publisher, self.grant = dispatch.modules()
        self.parts = self.adapter.modules()
        self.adapter.modules = lambda: self.parts
        self.adapter.implementation_head = lambda head: head
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(dispatch, "modules", return_value=(self.adapter, self.publisher, self.grant)).start()
        task = copy.deepcopy(self.local.task)
        old_scope = task["scope_key"]
        old_lane = task["leases"]["implementation_lane"]
        task.update(kind="intake", state="Claimed", branch="", worktree="", owned_paths=[], restricted_paths=[],
                    repo=self.grant.REPOSITORY, scope=self.grant.REPOSITORY + ":intake:synthetic:fixture",
                    tracker_type="none", tracker_number=0)
        task["scope_key"] = self.parts[1].scope_key(task["scope"])
        task["leases"]["implementation_lane"] = None
        shutil.rmtree(self.local.state / "scopes" / (old_scope + ".lock"))
        if old_lane is not None:
            shutil.rmtree(self.local.state / "implementation" / (str(old_lane) + ".lock"))
        owner = {"schema_version": 2, "task_id": task["task_id"], "scope": task["scope"], "token": task["leases"]["scope_token"]}
        self.parts[1].acquire_dir(self.local.state / "scopes" / (task["scope_key"] + ".lock"), owner)
        self.local.write(self.local.task_path, task)
        self.parts[1].validate_record(task, allow_bound=True)
        self.args.action, self.args.expected_epoch, self.args.operation_id = "activate", 0, None
        self.definition = {"version": 1, "grant_id": "a" * 32, "objective": "synthetic", "work_item": "fixture",
                           "repository": self.grant.REPOSITORY, "repository_id": self.grant.REPOSITORY_ID,
                           "repository_node_id": "R_synthetic", "publisher": {"id": 11, "node_id": "U_synthetic", "login": "fixture-publisher"},
                           "policy_sha256": dispatch.policy_digest(), "implementation_head": self.args.implementation_head,
                           "lifetime_seconds": 86400, "title": "Synthetic standing-grant tracking fixture: fixture",
                           "body": "Synthetic fixture for the synthetic objective. No production change requested.",
                           "qualification": {"endpoint_evidence_sha256": "c" * 64},
                           "workflow_effects": {"events": ["issues.opened", "issues.assigned"],
                               "decision": "AUTHORIZE_REVIEWED_SYNTHETIC_ISSUE_EVENT_WORKFLOWS_AND_COST", "evidence_sha256": "d" * 64}}
        self.args.proposal = str(self.local.root / "grant-proposal.json")
        self.grant_proposal = self.args.proposal
        self.make_qualification_artifacts()
        Path(self.grant_proposal).write_text(self.parts[3].canonical(self.definition))
        self.trace = self.local.root / "grant-http-trace"
        self.scenario = "success"
        self.before_fresh = None
        self.before_create = None
        self.before_observe = None
        fixture = self

        class HTTP:
            def __init__(self, repository, number, token):
                fixture.assertEqual(repository, fixture.grant.REPOSITORY)
                self.number, self.http_status = number, None

            def no_locks(self):
                fixture.assertFalse((fixture.local.state / "locks/coordinator.lock").exists())
                db = fixture.parts[2].open_store(fixture.fixture.fixture.monitor, writable=True)
                try:
                    db.execute("BEGIN IMMEDIATE")
                    db.rollback()
                finally:
                    db.close()

            def fresh_repository(self, observed):
                self.no_locks()
                fixture.assertEqual(observed["actor_id"], 11)
                if fixture.before_fresh is not None:
                    fixture.before_fresh()

            def complete_issues(self):
                self.no_locks()
                return []

            def create(self, payload, observed):
                fixture.assertEqual(observed["actor_id"], 11)
                self.no_locks()
                fixture.assertEqual(fixture.task()["assignment_dispatch"]["phase"], "pending")
                fixture.assertEqual(len(fixture.requests()), 1)
                with fixture.trace.open("a") as stream:
                    stream.write("CREATE\n")
                if fixture.before_create is not None:
                    fixture.before_create()
                if fixture.scenario == "unknown":
                    raise OSError("synthetic response lost")
                return {"id": 901, "node_id": "I_synthetic", "number": 501, **payload}

            def observe_created(self, created, expected, observed):
                fixture.assertEqual(observed["actor_id"], 11)
                self.no_locks()
                if fixture.before_observe is not None:
                    fixture.before_observe()
                if fixture.scenario == "get-failed":
                    raise OSError("synthetic GET failed")
                fixture.assertEqual({key: created[key] for key in ("title", "body")}, expected)
                return created

            def fresh(self, observed):
                self.fresh_repository(observed)
                fixture.assertEqual(observed["issue_id"], 901)
                return [11, 12] if fixture.scenario == "present" else [12]

            def assign(self, observed):
                self.no_locks()
                with fixture.trace.open("a") as stream:
                    stream.write("ASSIGN\n")

            def issue(self, observed):
                self.no_locks()
                return [11, 12]

            def close(self):
                pass

        mock.patch.object(self.parts[-1], "Transport", HTTP).start()

    def make_qualification_artifacts(self):
        t = self.parts[3]
        report = {"version": 1, "scope": self.grant.qualification_scope(self.definition),
                  "cases": {key: "PASS" for key in self.grant.QUALIFICATION_CASES},
                  "independent_reviews": [{"role": role, "reviewer": "fixture-" + role,
                      "inspected_head": self.args.implementation_head, "result": "PASS", "evidence_sha256": char * 64}
                      for role, char in (("qa", "e"), ("security", "f"))],
                  "assessment": "OFFLINE_FIXTURES_ONLY_HUMAN_MUST_ASSESS_ARTIFACT_MEANING"}
        transcript = b"Synthetic isolated executor transcript; fixture data, not live qualification.\n"
        raw = t.canonical(report).encode("ascii")
        self.manifest = {"version": 1, "qualification_id": "9" * 32, "mode": "OFFLINE_REVIEWED_ONE_USE_LIVE_PILOT",
                         "human_identity": "fixture-human", "scope": report["scope"],
                         "report": {"name": "report.json", "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)},
                         "transcript": {"name": "transcript.txt", "sha256": hashlib.sha256(transcript).hexdigest(), "size": len(transcript)}}
        evidence = self.local.state / "qualification-evidence"
        evidence.mkdir(mode=0o700)
        self.evidence_dir = evidence / self.manifest["qualification_id"]
        self.evidence_dir.mkdir(mode=0o700)
        for name, content in (("report.json", raw), ("transcript.txt", transcript)):
            path = self.evidence_dir / name
            path.write_bytes(content)
            path.chmod(0o600)
        self.qualification_proposal = str(self.local.root / "qualification-proposal.json")
        Path(self.qualification_proposal).write_text(t.canonical(self.manifest))
        self.definition["qualification"]["endpoint_evidence_sha256"] = self.manifest["report"]["sha256"]

    def task(self):
        return json.loads(self.local.task_path.read_text())

    def requests(self):
        db = self.parts[2].open_store(self.fixture.fixture.monitor)
        try:
            return [self.parts[3].decode(row[0]) for row in db.execute("SELECT document FROM assignment_requests")]
        finally:
            db.close()

    def human(self, action="activate", approve=True, tick=None, before_answer=None):
        self.args.action = action
        if action in {"revoke", "revoke-qualification"}:
            self.args.proposal = None
        child, fd = pty.fork()
        if child == 0:
            try:
                with mock.patch.dict(os.environ, {"GH_TOKEN": "synthetic"}, clear=True):
                    result = {"activate": controller.activate, "revoke": controller.revoke,
                              "install-qualification": controller.install_qualification,
                              "revoke-qualification": controller.revoke_qualification}[action](self.args, dispatch)
                print("RESULT " + json.dumps(result), flush=True)
                os._exit(0)
            except Exception as exc:
                print("RESULT " + json.dumps({"error": type(exc).__name__, "reason": str(exc)}), flush=True)
                os._exit(3)
        output, sent = bytearray(), False
        until = time.monotonic() + 15
        try:
            while time.monotonic() < until:
                if tick is not None:
                    tick()
                if select.select([fd], [], [], 0.05)[0]:
                    try:
                        chunk = os.read(fd, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output.extend(chunk)
                    if not sent and b"anything else to decline:" in output:
                        self.assertFalse((self.local.state / "locks/coordinator.lock").exists())
                        match = re.search(rb"Type exactly ((?:ACTIVATE|REVOKE|INSTALL-QUALIFICATION|REVOKE-QUALIFICATION) [0-9a-f]{64})", output)
                        self.assertIsNotNone(match)
                        if before_answer is not None:
                            before_answer()
                        os.write(fd, match[1] + b"\n" if approve else b"decline\n")
                        sent = True
            done, _ = os.waitpid(child, os.WNOHANG)
            if not done:
                os.kill(child, signal.SIGKILL)
                os.waitpid(child, 0)
        finally:
            os.close(fd)
        results = [json.loads(line[7:]) for line in output.splitlines() if line.startswith(b"RESULT ")]
        self.assertEqual(len(results), 1, output.decode(errors="replace"))
        self.last_human_output = bytes(output)
        return results[0]

    def runtime(self, action):
        self.args.action = action
        self.args.expected_revision = self.task()["revision"]
        with (mock.patch.dict(os.environ, {"GH_TOKEN": "synthetic"}, clear=True),
              mock.patch.object(self.publisher, "collect_terminal", side_effect=AssertionError("runtime TTY"))):
            return dispatch.dispatch(self.args)

    def activate(self):
        self.install()
        self.args.proposal = self.grant_proposal
        self.args.expected_epoch = 0
        self.assertEqual(self.human()["status"], "GRANT_ACTIVATED")
        self.args.expected_epoch = 1

    def install(self):
        self.args.proposal = self.qualification_proposal
        self.args.expected_epoch = 0
        result = self.human("install-qualification")
        self.assertEqual(result.get("status"), "OFFLINE_QUALIFICATION_INSTALLED_FOR_ONE_USE_LIVE_PILOT", result)

    def test_full_vertical_real_terminal_and_bound_issue(self):
        self.activate()
        self.assertEqual(self.runtime("issue-create")["status"], "ISSUE_CREATED_OBSERVED")
        self.assertEqual((self.task()["kind"], self.task()["tracker_type"], self.task()["tracker_number"]), ("intake", "issue", 501))
        self.assertEqual(self.runtime("assignees-add")["status"], "ASSIGNMENT_CONFIRMED_OBSERVED")
        self.assertEqual(self.trace.read_text(), "CREATE\nASSIGN\n")
        requests = self.requests()
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(row["authorization"]["source"] == "STANDING_GRANT" and "approval" not in row for row in requests))
        self.assertEqual(self.human("revoke")["status"], "GRANT_REVOKED_QUIESCENT")
        with self.assertRaises(Exception):
            self.runtime("assignees-add")

    def test_no_active_grant_ignores_proposal_and_environment(self):
        with mock.patch.dict(os.environ, {"APPROVED": "true", "STANDING_GRANT": self.args.proposal}):
            with self.assertRaises(Exception):
                self.runtime("issue-create")
        self.assertFalse(self.trace.exists())

    def test_declined_activation(self):
        self.install()
        self.args.proposal = self.grant_proposal
        self.args.expected_epoch = 0
        self.assertIn("error", self.human(approve=False))
        with self.assertRaises(Exception):
            self.runtime("issue-create")
        self.assertFalse(self.trace.exists())

    def test_uninstalled_qualification_refuses_caller_hashes_and_booleans(self):
        with mock.patch.dict(os.environ, {"QUALIFIED": "true", "APPROVED": "true"}):
            result = self.human()
        self.assertEqual(result["reason"], "ENDPOINT_QUALIFICATION_NOT_INSTALLED")
        self.assertNotIn(b"Type exactly ACTIVATE", self.last_human_output)
        self.assertFalse(self.trace.exists())

    def test_terminal_displays_full_effective_scope(self):
        self.activate()
        for text in (b'"issues_per_utc_day":5', b'"metadata_per_utc_day":20',
                     b'"cumulative_unknown_and_pending":3', b'"maximum_lifetime_seconds":86400',
                     b'"actions":["issue-create","assignees-add"]', b'issues.opened', b'issues.assigned',
                     b'endpoint_evidence_sha256', b'AUTHORIZE_REVIEWED_SYNTHETIC_ISSUE_EVENT_WORKFLOWS_AND_COST'):
            self.assertIn(text, self.last_human_output)

    def test_installation_changed_artifact_during_human_review_refuses(self):
        self.args.proposal = self.qualification_proposal

        def alter():
            path = self.evidence_dir / "transcript.txt"
            path.write_bytes(b"x" * path.stat().st_size)

        result = self.human("install-qualification", before_answer=alter)
        self.assertEqual(result["reason"], "QUALIFICATION_ARTIFACT_CHANGED")
        db = self.parts[2].open_store(self.fixture.fixture.monitor)
        try:
            self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 5)
        finally:
            db.close()

    def test_installation_failed_case_cannot_be_human_overridden(self):
        report = json.loads((self.evidence_dir / "report.json").read_text())
        report["cases"]["revocation_inflight"] = "FAIL"
        raw = self.parts[3].canonical(report).encode("ascii")
        (self.evidence_dir / "report.json").write_bytes(raw)
        self.manifest["report"].update(sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))
        Path(self.qualification_proposal).write_text(self.parts[3].canonical(self.manifest))
        self.args.proposal = self.qualification_proposal
        result = self.human("install-qualification")
        self.assertEqual(result["reason"], "QUALIFICATION_CASE_FAILED")
        self.assertNotIn(b"Type exactly", self.last_human_output)

    def test_installation_wrong_head_and_unsafe_artifact_refuse(self):
        self.args.proposal = self.qualification_proposal
        self.args.implementation_head = "7" * 40
        self.assertEqual(self.human("install-qualification")["reason"], "QUALIFICATION_BINDING_CHANGED")
        self.args.implementation_head = self.definition["implementation_head"]
        (self.evidence_dir / "transcript.txt").chmod(0o644)
        self.assertEqual(self.human("install-qualification")["reason"], "QUALIFICATION_ARTIFACT_UNSAFE")

    def test_installation_missing_or_symlink_artifact_refuses(self):
        self.args.proposal = self.qualification_proposal
        path = self.evidence_dir / "transcript.txt"
        original = path.read_bytes()
        path.unlink()
        self.assertIn("error", self.human("install-qualification"))
        outside = self.local.root / "outside-transcript.txt"
        outside.write_bytes(original)
        outside.chmod(0o600)
        path.symlink_to(outside)
        self.assertIn("error", self.human("install-qualification"))
        self.assertNotIn(b"Type exactly", self.last_human_output)

    def test_declined_qualification_installation_retains_v5(self):
        self.args.proposal = self.qualification_proposal
        self.assertIn("error", self.human("install-qualification", approve=False))
        db = self.parts[2].open_store(self.fixture.fixture.monitor)
        try:
            self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 5)
        finally:
            db.close()

    def test_installation_without_controlling_tty_refuses(self):
        self.args.proposal = self.qualification_proposal
        child = os.fork()
        if child == 0:
            try:
                os.setsid()
                controller.install_qualification(self.args, dispatch)
                os._exit(1)
            except OSError:
                os._exit(0)
            except Exception:
                os._exit(2)
        _, status = os.waitpid(child, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)

    def test_installed_artifact_drift_blocks_activation_and_runtime(self):
        self.install()
        self.args.proposal, self.args.expected_epoch = self.grant_proposal, 0
        path = self.evidence_dir / "transcript.txt"
        original = path.read_bytes()
        path.write_bytes(b"x" * len(original))
        self.assertEqual(self.human()["reason"], "QUALIFICATION_ARTIFACT_CHANGED")
        path.write_bytes(original)
        self.assertEqual(self.human()["status"], "GRANT_ACTIVATED")
        self.args.expected_epoch = 1
        path.write_bytes(b"x" * len(original))
        with self.assertRaisesRegex(self.grant.Invalid, "QUALIFICATION_ARTIFACT_CHANGED"):
            self.runtime("issue-create")
        self.assertFalse(self.trace.exists())

    def test_qualification_revocation_is_real_tty_and_stops_activation(self):
        self.install()
        self.args.expected_epoch = 1
        self.assertEqual(self.human("revoke-qualification")["status"], "QUALIFICATION_REVOKED")
        self.args.proposal, self.args.expected_epoch = self.grant_proposal, 0
        self.assertEqual(self.human()["reason"], "QUALIFICATION_REVOKED")

    def test_revocation_resume_after_durable_request_crash_has_no_new_tty(self):
        self.activate()
        with mock.patch.object(controller, "complete_revocation", side_effect=OSError("fixture crash after request fsync")):
            self.assertIn("error", self.human("revoke"))
        store, _ = dispatch.make_store(self.args, self.adapter)
        with store.locked() as db:
            pending = self.grant.selector(db)
        self.assertEqual(pending["state"], "revoke-requested")
        with mock.patch.object(self.publisher, "collect_terminal", side_effect=AssertionError("resume must not mint receipt")):
            result = controller.revoke(self.args, dispatch)
        self.assertEqual(result["status"], "GRANT_REVOKED_QUIESCENT")
        with store.locked() as db:
            final = self.grant.selector(db)
        self.assertEqual(final["revocation"], pending["revocation"])

    def test_revocation_timeout_then_original_gate_owner_releases_and_resume(self):
        self.activate()
        store, _ = dispatch.make_store(self.args, self.adapter)
        with store.locked():
            token = dispatch.acquire_gate(store, self.definition["grant_id"])
        with mock.patch.object(controller, "REVOKE_WAIT_SECONDS", 0):
            self.assertEqual(self.human("revoke")["status"], "REVOKE_REQUESTED_GATE_UNVERIFIED")
        with store.locked() as db:
            pending = self.grant.selector(db)
        self.assertTrue(dispatch.gate_path(store, self.definition["grant_id"]).exists())
        # Only the original owner token releases it, exactly as the normal
        # synchronous producer does; resume cannot take it over.
        dispatch.release_gate(store, self.definition["grant_id"], token)
        with mock.patch.object(self.publisher, "collect_terminal", side_effect=AssertionError("unexpected TTY")):
            self.assertEqual(controller.revoke(self.args, dispatch)["status"], "GRANT_REVOKED_QUIESCENT")
        with store.locked() as db:
            self.assertEqual(self.grant.selector(db)["revocation"], pending["revocation"])

    def test_recovery_wrong_explicit_revision_is_read_only_zero_get(self):
        self.activate()
        self.scenario = "get-failed"
        self.assertEqual(self.runtime("issue-create")["reservation"], "pending")
        request = self.requests()[0]
        self.args.operation_id = request["binding"]["operation_id"]
        self.args.expected_revision = self.task()["revision"] - 1
        task_before = self.local.task_path.read_bytes()
        db_path = self.fixture.fixture.monitor / "history.sqlite3"
        db_before = db_path.read_bytes()
        with (mock.patch.object(self.parts[-1], "Transport", side_effect=AssertionError("no GET permitted")),
              mock.patch.dict(os.environ, {"GH_TOKEN": "synthetic"}, clear=True)):
            with self.assertRaisesRegex(self.adapter.Refusal, "REVISION_MISMATCH"):
                dispatch.recover(self.args)
        self.assertEqual(self.local.task_path.read_bytes(), task_before)
        self.assertEqual(db_path.read_bytes(), db_before)

    def assert_manual_fenced(self):
        store, _ = dispatch.make_store(self.args, self.adapter)
        before = self.local.task_path.read_bytes()
        with store.locked() as db:
            for issue in (501, 999):
                with self.assertRaisesRegex(self.adapter.Refusal, "TARGET_PENDING"):
                    self.adapter.standing_target_fence(store, db, self.definition["repository_id"], issue)
            # The target fence is repository-scoped, not a global metadata ban.
            self.adapter.standing_target_fence(store, db, self.definition["repository_id"] + 1, 501)
        self.assertEqual(self.local.task_path.read_bytes(), before)

    def test_manual_target_gate_during_create_post_before_get(self):
        self.activate()
        self.before_observe = self.assert_manual_fenced
        self.assertEqual(self.runtime("issue-create")["status"], "ISSUE_CREATED_OBSERVED")
        self.assertEqual(self.trace.read_text(), "CREATE\n")

    def test_manual_target_gate_preserves_unknown_create(self):
        self.activate()
        self.scenario = "unknown"
        self.assertEqual(self.runtime("issue-create")["status"], "UNKNOWN")
        self.assert_manual_fenced()
        self.assertEqual(self.trace.read_text(), "CREATE\n")

    def test_manual_target_gate_preserves_marker_only_create_fence(self):
        self.activate()
        with mock.patch.object(self.parts[3], "reserve", side_effect=OSError("fixture commit failure")):
            with self.assertRaises(OSError):
                self.runtime("issue-create")
        self.assertEqual(self.requests(), [])
        self.assert_manual_fenced()
        self.assertFalse(self.trace.exists())

    def pinned_readers(self):
        """Materialize immutable production-base source; execute only in sandbox."""
        revision = "5d2c0a2b58ea7ba725ec0ce61044b523652482ff"
        target = self.local.root / "pinned-readers"
        target.mkdir(mode=0o700)
        environment = {"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                       "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1"}
        git = ["/usr/bin/git", "-c", "protocol.allow=never", "-c", "core.hooksPath=" + os.devnull, "-C", str(SOURCE)]
        for name in ("orchestrator-state.py", "reservation-history.py", "monitor-journal.py", "assignment-journal.py"):
            raw = subprocess.check_output(git + ["show", revision + ":.agents/skills/workspace-orchestrator/bin/" + name],
                                          env=environment, stderr=subprocess.DEVNULL, timeout=5)
            (target / name).write_bytes(raw)
        raw = subprocess.check_output(git + ["show", revision + ":scripts/check-native-ownership.py"],
                                      env=environment, stderr=subprocess.DEVNULL, timeout=5)
        (target / "check-native-ownership.py").write_bytes(raw)
        return target

    def test_pinned_premigration_readers_refuse_v7_and_marker_versions(self):
        pinned = self.pinned_readers()
        old_journal = load("pinned_v6_journal", pinned / "monitor-journal.py")
        old_core = load("pinned_v6_core", pinned / "orchestrator-state.py")
        old_native = load("pinned_v6_native", pinned / "check-native-ownership.py")
        self.activate()
        db_path = self.fixture.fixture.monitor / "history.sqlite3"
        before = db_path.read_bytes()
        with self.assertRaises(Exception):
            db = old_journal.open_store(self.fixture.fixture.monitor, writable=True)
            try:
                old_journal.validate_store(db)
            finally:
                db.close()
        self.assertEqual(db_path.read_bytes(), before)
        self.runtime("issue-create")
        reserved = self.requests()[0]["reserved_task"]
        for task in (reserved, self.task()):
            # Use a kind recognized by the pinned validators to ensure refusal
            # is from the new marker, rather than merely the new intake kind.
            candidate = dict(copy.deepcopy(task), kind="monitor")
            with self.assertRaises(Exception):
                old_core.validate_record(candidate, allow_bound=True)
            with self.assertRaises(Exception):
                old_native.validate_task(candidate)
            before_task, before_db = self.local.task_path.read_bytes(), db_path.read_bytes()
            with self.assertRaises(Exception):
                old_core.write_task(self.local.state, candidate, allow_bound=True)
            self.assertEqual(self.local.task_path.read_bytes(), before_task)
            self.assertEqual(db_path.read_bytes(), before_db)

    def test_satisfied_assignment_retains_durable_no_post(self):
        self.activate()
        self.runtime("issue-create")
        self.scenario = "present"
        self.assertEqual(self.runtime("assignees-add")["status"], "SATISFIED_NO_POST")
        request = next(row for row in self.requests() if row["binding"]["action"] == "assignees-add")
        db = self.parts[2].open_store(self.fixture.fixture.monitor)
        try:
            receipt = self.parts[3].get(db, "assignment_evidence", request["evidence_id"])
            terminal = self.parts[3].get(db, "assignment_settlements", request["settlement_id"])
            self.assertEqual(receipt["completion"], "NOT_SENT")
            self.assertEqual(terminal["outcome"], "SATISFIED_NO_POST")
        finally:
            db.close()
        self.assertEqual(self.trace.read_text(), "CREATE\n")

    def revocation_race(self, phase):
        self.activate()
        ready_read, ready_write = os.pipe()
        release_read, release_write = os.pipe()

        def hold_producer():
            os.write(ready_write, b"r")
            if not select.select([release_read], [], [], 10)[0]:
                raise AssertionError("revocation fixture did not release producer")
            self.assertEqual(os.read(release_read, 1), b"g")

        if phase == "fresh":
            self.before_fresh = hold_producer
        else:
            self.before_create = hold_producer
        child = os.fork()
        if child == 0:
            try:
                self.runtime("issue-create")
                os._exit(0)
            except Exception:
                os._exit(3)
        requested = []
        try:
            self.assertTrue(select.select([ready_read], [], [], 10)[0])
            self.assertEqual(os.read(ready_read, 1), b"r")

            def observe_requested():
                if requested:
                    return
                db = self.parts[2].open_store(self.fixture.fixture.monitor)
                try:
                    selected = self.grant.selector(db)
                finally:
                    db.close()
                if selected["state"] == "revoke-requested":
                    # The real controller has committed request, but cannot ack
                    # quiescence until the actual runtime producer leaves its gate.
                    self.assertTrue((self.local.state / "locks" / ("standing-effect-" + self.definition["grant_id"] + ".lock")).is_dir())
                    self.assertEqual(os.waitpid(child, os.WNOHANG), (0, 0))
                    requested.append(selected)
                    os.write(release_write, b"g")

            result = self.human("revoke", tick=observe_requested)
            self.assertEqual(result["status"], "GRANT_REVOKED_QUIESCENT")
            self.assertEqual(len(requested), 1)
            _, status = os.waitpid(child, 0)
            child = None
            self.assertEqual(os.waitstatus_to_exitcode(status), 3 if phase == "fresh" else 0)
            if phase == "fresh":
                self.assertFalse(self.trace.exists())
            else:
                self.assertEqual(self.trace.read_text(), "CREATE\n")
                self.assertEqual(self.task()["tracker_number"], 501)
            with self.assertRaises(Exception):
                self.runtime("issue-create")
        finally:
            if child is not None:
                os.kill(child, signal.SIGKILL)
                os.waitpid(child, 0)
            for fd in (ready_read, ready_write, release_read, release_write):
                os.close(fd)

    def test_real_controller_revocation_before_reservation_prevents_post(self):
        self.revocation_race("fresh")

    def test_real_controller_revocation_waits_for_inflight_post(self):
        self.revocation_race("post")

    def test_real_legacy_v6_unknown_rows_and_core_bytes_survive_migration(self):
        legacy = fixtures.DispatchTest()
        with mock.patch.dict(os.environ, self.real_environment, clear=True):
            legacy.setUp()
        self.addCleanup(legacy.doCleanups)
        self.assertEqual(legacy.run_vertical("lost"), "UNKNOWN")
        journal, typed = legacy.parts[2:4]
        marker = legacy.local.task_path.read_bytes()
        tables = ("claim_intents", "assignment_requests", "assignment_attempts", "assignment_evidence", "assignment_settlements")
        with legacy.parts[1].CoordinatorLock(legacy.local.state):
            db = journal.open_store(legacy.fixture.monitor, writable=True)
            try:
                self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 6)
                before = {table: [tuple(row) for row in db.execute("SELECT * FROM " + table)] for table in tables}
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    self.grant.migrate(db)
                legacy.parts[4].durable(journal, db, legacy.fixture.monitor)
                journal.validate_store(db)
                self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 7)
                self.assertEqual({table: [tuple(row) for row in db.execute("SELECT * FROM " + table)] for table in tables}, before)
                request = typed.decode(db.execute("SELECT document FROM assignment_requests").fetchone()[0])
                self.assertEqual(typed.get(db, "assignment_evidence", request["evidence_id"])["completion"], "UNKNOWN")
                self.assertIsNone(typed.get(db, "assignment_settlements", request["settlement_id"]))
            finally:
                db.close()
        self.assertEqual(legacy.local.task_path.read_bytes(), marker)
        legacy.assert_pending_guards()
        args = copy.copy(legacy.args)
        args.action, args.expected_revision = "settle", legacy.task()["revision"]
        args.assignment_operation_id = request["binding"]["operation_id"]
        with (mock.patch.dict(os.environ, {}, clear=True),
              mock.patch.object(fixtures.adapter, "modules", return_value=legacy.parts),
              mock.patch.object(fixtures.adapter, "implementation_head", side_effect=lambda head: head),
              mock.patch.object(legacy.parts[-1], "Transport", side_effect=AssertionError("UNKNOWN recovery must not GET"))):
            with self.assertRaisesRegex(fixtures.adapter.Refusal, "PRODUCER_TERMINATION_PROOF_UNSUPPORTED"):
                fixtures.adapter.recover(args, fixtures.publisher)
            args.action = "arbitrate"
            with self.assertRaisesRegex(fixtures.adapter.Refusal, "PRODUCER_TERMINATION_PROOF_UNSUPPORTED"):
                fixtures.adapter.recover(args, fixtures.publisher)
        self.assertEqual(legacy.local.task_path.read_bytes(), marker)
        with self.assertRaises(legacy.parts[1].BusyError):
            legacy.parts[1].require_assignment_settled(legacy.task())

    def test_unknown_create_cannot_new_operation_retry(self):
        self.activate()
        self.scenario = "unknown"
        self.assertEqual(self.runtime("issue-create")["status"], "UNKNOWN")
        self.assertEqual(self.task()["tracker_type"], "none")
        with self.assertRaises(Exception):
            self.runtime("issue-create")
        self.assertEqual(self.trace.read_text(), "CREATE\n")

    def test_marker_first_commit_failure_blocks_replay(self):
        self.activate()
        with mock.patch.object(self.parts[3], "reserve", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError):
                self.runtime("issue-create")
        self.assertEqual(self.task()["assignment_dispatch"]["phase"], "pending")
        self.assertEqual(self.requests(), [])
        with self.assertRaises(Exception):
            self.runtime("issue-create")
        self.assertFalse(self.trace.exists())

    def test_concurrent_dispatchers_have_one_effect(self):
        self.activate()
        children = []
        for _ in range(2):
            child = os.fork()
            if child == 0:
                try:
                    self.runtime("issue-create")
                    os._exit(0)
                except Exception:
                    os._exit(3)
            children.append(child)
        statuses = [os.waitstatus_to_exitcode(os.waitpid(child, 0)[1]) for child in children]
        self.assertEqual(sorted(statuses), [0, 3])
        self.assertEqual(self.trace.read_text(), "CREATE\n")
        self.assertEqual(len(self.requests()), 1)

    def test_wrong_epoch_and_task_generation(self):
        self.activate()
        self.args.expected_epoch = 2
        with self.assertRaises(Exception):
            self.runtime("issue-create")
        self.args.expected_epoch = 1
        self.args.expected_generation += 1
        with self.assertRaises(Exception):
            self.runtime("issue-create")
        self.assertFalse(self.trace.exists())

    def test_pause_during_fresh_read_stops_launch(self):
        self.activate()

        def revoke_requested():
            store, _ = dispatch.make_store(self.args, self.adapter)
            with store.locked() as db:
                selected = self.grant.selector(db)
                # Exercise the runtime race with a paused selector, which requires
                # no forged human receipt and has identical no-new-launch semantics.
                selected["state"] = "paused"
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    self.grant.put_selector(db, selected)
                store.durable(db)

        self.before_fresh = revoke_requested
        with self.assertRaises(Exception):
            self.runtime("issue-create")
        self.assertFalse(self.trace.exists())

    def test_clock_rollback_durably_pauses_then_restart_refuses(self):
        self.activate()
        store, _ = dispatch.make_store(self.args, self.adapter)
        with store.locked() as db:
            previous = self.grant.selector(db)["clock"]
        with mock.patch.object(self.grant, "clock", return_value=dict(previous, wall=previous["wall"] - 1)):
            with self.assertRaises(Exception):
                self.runtime("issue-create")
        with store.locked() as db:
            self.assertEqual(self.grant.selector(db)["state"], "paused")
        with self.assertRaises(Exception):
            self.runtime("issue-create")
        self.assertFalse(self.trace.exists())

    def test_migration_preserves_legacy_intent_bytes(self):
        db = self.parts[2].open_store(self.fixture.fixture.monitor)
        try:
            original = [tuple(row) for row in db.execute("SELECT * FROM claim_intents")]
        finally:
            db.close()
        self.activate()
        self.runtime("issue-create")
        db = self.parts[2].open_store(self.fixture.fixture.monitor)
        try:
            self.parts[2].validate_store(db)
            self.assertEqual([tuple(row) for row in db.execute("SELECT * FROM claim_intents")], original)
        finally:
            db.close()

    def test_unknown_history_survives_revocation_and_renewal(self):
        self.activate()
        self.scenario = "unknown"
        self.assertEqual(self.runtime("issue-create")["status"], "UNKNOWN")
        before = self.requests()
        self.assertEqual(self.human("revoke")["status"], "GRANT_REVOKED_QUIESCENT")
        self.definition["grant_id"] = "b" * 32
        self.args.proposal = str(self.local.root / "grant-proposal.json")
        Path(self.args.proposal).write_text(self.parts[3].canonical(self.definition))
        self.args.expected_revision = self.task()["revision"]
        # Pending intake cannot receive a new activation to bypass its old marker.
        self.assertIn("error", self.human("activate"))
        self.assertEqual(self.requests(), before)
        self.assertEqual(self.trace.read_text(), "CREATE\n")

    def test_confirmed_create_get_failure_then_get_only_settlement(self):
        self.activate()
        self.scenario = "get-failed"
        self.assertEqual(self.runtime("issue-create")["reservation"], "pending")
        self.assertEqual(self.task()["tracker_type"], "none")
        self.scenario = "success"
        self.args.operation_id = self.requests()[0]["binding"]["operation_id"]
        self.args.expected_revision = self.task()["revision"]
        with mock.patch.dict(os.environ, {"GH_TOKEN": "synthetic"}, clear=True):
            self.assertEqual(dispatch.recover(self.args)["status"], "ISSUE_CREATED_OBSERVED")
        self.assertEqual(self.trace.read_text(), "CREATE\n")


if __name__ == "__main__":
    unittest.main()
