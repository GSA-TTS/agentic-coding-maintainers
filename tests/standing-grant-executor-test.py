#!/usr/bin/env python3
"""Sandbox-only integration: real TTY/controller/core/SQLite; injected HTTP."""

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import pty
import re
import select
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
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
        self.real_implementation_head = self.adapter.implementation_head
        self.adapter.implementation_head = lambda head: head
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(dispatch, "modules", return_value=(self.adapter, self.publisher, self.grant)).start()
        task = copy.deepcopy(self.local.task)
        old_scope = task["scope_key"]
        old_lane = task["leases"]["implementation_lane"]
        shutil.rmtree(self.local.state / "scopes" / (old_scope + ".lock"))
        if old_lane is not None:
            shutil.rmtree(self.local.state / "implementation" / (str(old_lane) + ".lock"))
        shutil.rmtree(self.local.state / "slots" / (str(task["leases"]["global_slot"]) + ".lock"))
        shutil.rmtree(self.local.task_path.parent)
        self.admit_intake(task["task_id"], "fixture")
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
                fixture.assertTrue(any(row["binding"]["operation_id"] == fixture.task()["assignment_dispatch"]["operation_id"]
                                       for row in fixture.requests()))
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

            def fresh(self, observed, *, admission=True):
                self.fresh_repository(observed)
                fixture.assertEqual(observed["issue_id"], 901)
                if fixture.scenario == "capacity-recovery":
                    fixture.assertFalse(admission)
                    return list(range(12, 22))
                return [11, 12] if fixture.scenario == "present" else [12]

            def assign(self, observed):
                self.no_locks()
                with fixture.trace.open("a") as stream:
                    stream.write("ASSIGN\n")

            def issue(self, observed):
                self.no_locks()
                if fixture.scenario == "assignment-get-failed":
                    raise OSError("synthetic observation lost")
                return [11, 12]

            def close(self):
                pass

        mock.patch.object(self.parts[-1], "Transport", HTTP).start()

    def admit_intake(self, task_id, work_item):
        core = self.parts[1]
        create = SimpleNamespace(task_id=task_id, scope=self.grant.REPOSITORY + ":intake:synthetic:" + work_item,
            kind="intake", repo=self.grant.REPOSITORY, worktree="", branch="", base_sha="", head_sha="",
            owned_path=[], restricted_path=[], acceptance=["Synthetic issue created and publisher assigned"], dependency=[],
            tracker_type="none", tracker_number=0, next_action="Create synthetic tracking issue")
        core.command_create(create, self.local.state)
        claim = SimpleNamespace(task_id=task_id, owner="fixture-intake-owner", pid=self.fixture.worker.pid,
                                session_id="fixture-intake-session", expected_revision=0, expected_generation=0)
        with mock.patch.dict(os.environ, self.real_environment, clear=True):
            task = core.command_claim(claim, self.local.state)
        self.local.task_path = core.task_path(self.local.state, task_id)
        self.args.task_id = task_id
        self.args.expected_revision = task["revision"]
        self.args.expected_worker_id = task["worker"]["worker_id"]
        self.args.expected_session_id = task["worker"]["session_id"]
        self.args.expected_generation = task["worker"]["generation"]

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
        self.manifest = {"version": 1, "qualification_id": hashlib.sha256(self.definition["work_item"].encode()).hexdigest()[:32], "mode": "OFFLINE_REVIEWED_ONE_USE_LIVE_PILOT",
                         "human_identity": "fixture-human", "scope": report["scope"],
                         "report": {"name": "report.json", "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)},
                         "transcript": {"name": "transcript.txt", "sha256": hashlib.sha256(transcript).hexdigest(), "size": len(transcript)}}
        evidence = self.local.state / "qualification-evidence"
        evidence.mkdir(mode=0o700, exist_ok=True)
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

    def human(self, action="activate", approve=True, tick=None, before_answer=None, cli=False):
        self.args.action = action
        if action in {"revoke", "revoke-qualification"}:
            self.args.proposal = None
        child, fd = pty.fork()
        if child == 0:
            try:
                with mock.patch.dict(os.environ, {"GH_TOKEN": "synthetic"}, clear=True):
                    if cli:
                        argv = ["control-standing-grant.py", action,
                                "--authority-root", self.args.authority_root, "--invoking-root", self.args.invoking_root,
                                "--implementation-head", self.args.implementation_head,
                                "--expected-epoch", str(self.args.expected_epoch)]
                        if self.args.proposal is not None:
                            argv.extend(["--proposal", self.args.proposal])
                        output = io.StringIO()
                        with (mock.patch.object(sys, "argv", argv),
                              mock.patch.object(controller, "load_dispatch", return_value=dispatch),
                              contextlib.redirect_stdout(output)):
                            code = controller.main()
                        result = json.loads(output.getvalue()) | {"cli_exit": code}
                    else:
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
        db = self.parts[2].open_store(self.fixture.fixture.monitor)
        try:
            self.args.expected_epoch = self.grant.selector(db)["epoch"] if db.execute("SELECT count(*) FROM standing_selector").fetchone()[0] else 0
        finally:
            db.close()
        self.assertEqual(self.human()["status"], "GRANT_ACTIVATED")
        self.args.expected_epoch += 1

    def install(self):
        self.args.proposal = self.qualification_proposal
        db = self.parts[2].open_store(self.fixture.fixture.monitor)
        try:
            self.args.expected_epoch = self.grant.qualification_selector(db)["epoch"] if db.execute("SELECT version FROM meta").fetchone()[0] == 7 else 0
        finally:
            db.close()
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
        self.complete_intake()
        self.assertEqual(self.task()["state"], "Done")
        self.assertEqual(self.task()["head_sha"], "")
        self.assertEqual(self.task()["reviewers"], [])
        self.assertEqual(self.human("revoke")["status"], "GRANT_REVOKED_QUIESCENT")
        with self.assertRaises(Exception):
            self.runtime("assignees-add")

    def complete_intake(self):
        before = self.task()
        self.args.expected_revision = before["revision"]
        with mock.patch.object(self.parts[-1], "Transport", side_effect=AssertionError("completion must not GET")):
            result = dispatch.complete(self.args)
        self.assertEqual(result["status"], "INTAKE_COMPLETED")
        self.assertIsNone(self.task()["worker"])
        self.assertFalse((self.local.state / "slots" / (str(before["leases"]["global_slot"]) + ".lock")).exists())
        self.assertFalse((self.local.state / "scopes" / (before["scope_key"] + ".lock")).exists())

    def test_intake_completion_resumes_partial_lease_release(self):
        self.activate()
        self.runtime("issue-create")
        self.runtime("assignees-add")
        core = self.parts[1]
        release = core.intake_release_lease

        def fail_scope(root, record, key, path, owner):
            if key == "scope":
                raise OSError("fixture interruption after slot release")
            return release(root, record, key, path, owner)

        self.args.expected_revision = self.task()["revision"]
        with mock.patch.object(core, "intake_release_lease", side_effect=fail_scope):
            with self.assertRaises(OSError):
                dispatch.complete(self.args)
        pending = self.task()
        self.assertEqual(pending["transition_intent"], "Done")
        self.assertFalse((self.local.state / "slots" / (str(pending["leases"]["global_slot"]) + ".lock")).exists())
        self.complete_intake()

    def prepare_completion(self):
        self.activate()
        self.runtime("issue-create")
        self.runtime("assignees-add")
        self.args.expected_revision = self.task()["revision"]
        return self.parts[1]

    def test_completion_rejects_all_unreachable_phase_pairs_before_effects(self):
        core = self.prepare_completion()
        with mock.patch.object(core, "intake_task_barrier", side_effect=OSError("fixture stop before releases")):
            with self.assertRaises(OSError):
                dispatch.complete(self.args)
        original = self.task()
        scope = self.local.state / "scopes" / (original["scope_key"] + ".lock")
        parked = self.local.task_path.parent / "fixture-parked-scope"
        owner = (scope / "owner.json").read_bytes()
        database = self.fixture.fixture.monitor / "history.sqlite3"

        def lease_snapshot():
            return {str(path.relative_to(self.local.state)): (path.stat().st_dev, path.stat().st_ino,
                    path.read_bytes() if path.is_file() else None)
                    for group in ("slots", "scopes") for path in (self.local.state / group).rglob("*")}

        pairs = (("reserved", "cleanup"), ("reserved", "released"),
                 ("cleanup", "cleanup"), ("cleanup", "released"))
        for slot_phase, scope_phase in pairs:
            for physical in ("empty", "absent"):
                with self.subTest(slot=slot_phase, scope=scope_phase, physical=physical):
                    forged = copy.deepcopy(original)
                    receipt = forged["intake_completion"]
                    receipt["leases"]["slot"]["phase"] = slot_phase
                    receipt["leases"]["scope"]["phase"] = scope_phase
                    # Match the old sum-based validator exactly, so the failure
                    # must enforce reachability rather than merely revision math.
                    forged["revision"] = receipt["base_revision"] + 1 + sum(
                        {"reserved": 0, "cleanup": 1, "released": 2}[phase] for phase in (slot_phase, scope_phase))
                    core.atomic_json(self.local.task_path, forged)
                    if physical == "empty":
                        (scope / "owner.json").unlink()
                    else:
                        scope.rename(parked)
                    self.args.expected_revision = forged["revision"]
                    task_before, db_before, leases_before = self.local.task_path.read_bytes(), database.read_bytes(), lease_snapshot()
                    try:
                        with self.assertRaisesRegex(core.UnknownError, "unreachable intake completion progression"):
                            core.validate_record(forged, allow_bound=True)
                        with self.assertRaises(Exception):
                            self.parts[0].validate_task(forged)
                        with self.assertRaisesRegex(core.UnknownError, "unreachable intake completion progression"):
                            dispatch.complete(self.args)
                        self.assertEqual(self.local.task_path.read_bytes(), task_before)
                        self.assertEqual(database.read_bytes(), db_before)
                        self.assertEqual(lease_snapshot(), leases_before)
                    finally:
                        if physical == "empty":
                            (scope / "owner.json").write_bytes(owner)
                            (scope / "owner.json").chmod(0o600)
                        else:
                            parked.rename(scope)

    def test_completion_at_six_revision_boundary_resumes_to_limit(self):
        self.initialize_boundary_revision(remaining=10)
        core = self.prepare_completion()
        base = self.task()["revision"]
        self.assertEqual(base, core.MAX_GENERATION - 6)
        release = core.intake_release_lease

        def stop_after_slot(root, record, key, path, owner):
            if key == "scope":
                raise OSError("fixture interrupt at base plus three")
            return release(root, record, key, path, owner)

        with mock.patch.object(core, "intake_release_lease", side_effect=stop_after_slot):
            with self.assertRaises(OSError):
                dispatch.complete(self.args)
        self.assertEqual(self.task()["revision"], base + 3)
        self.complete_intake()
        self.assertEqual(self.task()["revision"], core.MAX_GENERATION)
        self.assertEqual(self.task()["state"], "Done")
        core.validate_record(self.task(), allow_bound=True)
        self.parts[0].validate_task(self.task())

    def initialize_boundary_revision(self, remaining):
        # Fixture initialization precedes qualification, activation and both
        # immutable request captures. Each real dispatch reserves/settles (+2),
        # so four revisions are consumed before completion. Do not patch the
        # shared integer limit (which also validates immutable GitHub IDs).
        core = self.parts[1]
        task = self.task()
        self.assertNotIn("assignment_dispatch", task)
        task["revision"] = core.MAX_GENERATION - remaining
        core.validate_record(task, allow_bound=True)
        self.parts[0].validate_task(task)
        with core.CoordinatorLock(self.local.state):
            core.verify_reservations(self.local.state, task)
            core.atomic_json(self.local.task_path, task)
        self.args.expected_revision = task["revision"]

    def test_completion_initial_base_above_six_revision_budget_refuses(self):
        self.initialize_boundary_revision(remaining=9)
        core = self.prepare_completion()
        base = self.task()["revision"]
        self.assertEqual(base, core.MAX_GENERATION - 5)
        before = self.local.task_path.read_bytes()
        database = self.fixture.fixture.monitor / "history.sqlite3"
        db_before = database.read_bytes()
        with self.assertRaisesRegex(core.UnknownError, "exact settlement binding changed"):
            dispatch.complete(self.args)
        self.assertEqual(self.local.task_path.read_bytes(), before)
        self.assertEqual(database.read_bytes(), db_before)
        self.assertTrue((self.local.state / "slots" / (str(self.task()["leases"]["global_slot"]) + ".lock")).is_dir())
        self.assertTrue((self.local.state / "scopes" / (self.task()["scope_key"] + ".lock")).is_dir())

    def test_completion_reproves_replaced_intent_durability_before_release(self):
        core = self.prepare_completion()
        atomic = core.atomic_json
        fsync = core.os.fsync

        def replaced_then_failed(path, record):
            def fail_parent(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    raise OSError("fixture parent fsync failed after replace")
                return fsync(fd)
            if record.get("intake_completion") and record["transition_intent"] == "Done":
                with mock.patch.object(core.os, "fsync", side_effect=fail_parent):
                    return atomic(path, record)
            return atomic(path, record)

        with mock.patch.object(core, "atomic_json", side_effect=replaced_then_failed):
            with self.assertRaises(core.AmbiguousWriteError):
                dispatch.complete(self.args)
        pending = self.task()
        self.args.expected_revision = pending["revision"]
        before = {group: sorted(p.name for p in (self.local.state / group).iterdir()) for group in ("slots", "scopes")}
        real_fsync = core.os.fsync
        barrier = core.intake_task_barrier
        for kind in ("file", "parent"):
            with self.subTest(kind=kind):
                def fail(fd):
                    is_dir = stat.S_ISDIR(os.fstat(fd).st_mode)
                    if (kind == "parent" and is_dir) or (kind == "file" and not is_dir):
                        raise OSError("fixture barrier failure")
                    return real_fsync(fd)
                def failing_barrier(root, record):
                    with mock.patch.object(core.os, "fsync", side_effect=fail):
                        return barrier(root, record)
                with mock.patch.object(core, "intake_task_barrier", side_effect=failing_barrier):
                    with self.assertRaises(OSError):
                        dispatch.complete(self.args)
                self.assertEqual({group: sorted(p.name for p in (self.local.state / group).iterdir()) for group in before}, before)
        self.complete_intake()

    def completion_cleanup_crash(self, key, stage):
        core = self.prepare_completion()
        unlink, rmdir, rename = core.os.unlink, core.os.rmdir, core.os.rename
        tomb = self.local.task_path.parent / ("intake-" + key + "-release")

        def interrupted_unlink(path, *args, **kwargs):
            result = unlink(path, *args, **kwargs)
            if Path(path) == tomb / "owner.json" and stage == "owner-unlinked":
                raise OSError("fixture owner unlink acknowledgement lost")
            return result

        def interrupted_rmdir(path, *args, **kwargs):
            if Path(path) == tomb and stage == "rmdir-failed":
                raise OSError("fixture rmdir failed")
            result = rmdir(path, *args, **kwargs)
            if Path(path) == tomb and stage == "rmdir-done":
                raise OSError("fixture rmdir acknowledgement lost")
            return result

        def interrupted_rename(source, destination, *args, **kwargs):
            result = rename(source, destination, *args, **kwargs)
            if Path(destination) == tomb and stage == "renamed":
                raise OSError("fixture rename acknowledgement lost")
            return result

        with (mock.patch.object(core.os, "unlink", side_effect=interrupted_unlink),
              mock.patch.object(core.os, "rmdir", side_effect=interrupted_rmdir),
              mock.patch.object(core.os, "rename", side_effect=interrupted_rename)):
            with self.assertRaises(OSError):
                dispatch.complete(self.args)
        self.assertEqual(self.task()["transition_intent"], "Done")
        self.complete_intake()
        self.assertFalse(tomb.exists())

    def test_completion_slot_owner_unlink_crash(self):
        self.completion_cleanup_crash("slot", "owner-unlinked")

    def test_completion_scope_owner_unlink_crash(self):
        self.completion_cleanup_crash("scope", "owner-unlinked")

    def test_completion_slot_rmdir_failure(self):
        self.completion_cleanup_crash("slot", "rmdir-failed")

    def test_completion_scope_rmdir_failure(self):
        self.completion_cleanup_crash("scope", "rmdir-failed")

    def test_completion_slot_rename_ack_failure(self):
        self.completion_cleanup_crash("slot", "renamed")

    def test_completion_scope_rename_ack_failure(self):
        self.completion_cleanup_crash("scope", "renamed")

    def test_completion_scope_rmdir_ack_failure(self):
        self.completion_cleanup_crash("scope", "rmdir-done")

    def test_completion_refuses_empty_original_or_foreign_reused_slot(self):
        core = self.prepare_completion()
        with mock.patch.object(core, "intake_task_barrier", side_effect=OSError("fixture stop before release")):
            with self.assertRaises(OSError):
                dispatch.complete(self.args)
        task = self.task()
        slot = self.local.state / "slots" / (str(task["leases"]["global_slot"]) + ".lock")
        owner_bytes = (slot / "owner.json").read_bytes()
        (slot / "owner.json").unlink()
        self.args.expected_revision = task["revision"]
        with self.assertRaises(core.UnknownError):
            dispatch.complete(self.args)
        (slot / "owner.json").write_bytes(owner_bytes)
        foreign = dict(task["worker"], token="0" * 32)
        self.local.write(slot / "owner.json", foreign)
        with self.assertRaises(core.UnknownError):
            dispatch.complete(self.args)
        self.assertEqual(json.loads((slot / "owner.json").read_text()), foreign)
        # Even copied original owner bytes cannot authenticate a newly created
        # directory after the original inode has been moved elsewhere.
        parked = self.local.task_path.parent / "parked-original-slot"
        slot.rename(parked)
        slot.mkdir(mode=0o700)
        (slot / "owner.json").write_bytes(owner_bytes)
        with self.assertRaisesRegex(core.UnknownError, "physical identity changed"):
            dispatch.complete(self.args)

    def test_intake_completion_requires_successful_assignment(self):
        self.activate()
        self.runtime("issue-create")
        self.args.expected_revision = self.task()["revision"]
        before = self.local.task_path.read_bytes()
        with self.assertRaises(self.parts[1].BusyError):
            dispatch.complete(self.args)
        self.assertEqual(self.local.task_path.read_bytes(), before)

    def test_intake_completion_accepts_satisfied_no_post(self):
        self.activate()
        self.runtime("issue-create")
        self.scenario = "present"
        self.assertEqual(self.runtime("assignees-add")["status"], "SATISFIED_NO_POST")
        self.complete_intake()
        self.assertEqual(self.trace.read_text(), "CREATE\n")

    def test_warm_module_loaders_preserve_live_validation_and_selector_fences(self):
        self.activate()
        self.runtime("issue-create")
        journal = self.parts[2]
        db = journal.open_store(self.fixture.fixture.monitor)
        try:
            journal.validate_store(db)  # Warm every retained-request validator.
            cached_typed = journal.assignment_journal()
            # A live validator patch must be observed, not bypassed by a cached
            # validation outcome or a captured function pointer.
            with mock.patch.object(cached_typed, "CAPACITY", 0):
                with self.assertRaises(cached_typed.Invalid):
                    journal.validate_store(db)
            journal.validate_store(db)
        finally:
            db.close()
        store, _ = dispatch.make_store(self.args, self.adapter)
        with store.locked() as db:
            selected = self.grant.selector(db)
            selected["state"] = "paused"
            with db:
                db.execute("BEGIN IMMEDIATE")
                self.grant.put_selector(db, selected)
            store.durable(db)
        with self.assertRaisesRegex(self.grant.Invalid, "GRANT_INACTIVE_OR_EPOCH_CHANGED"):
            self.runtime("assignees-add")
        self.assertEqual(self.trace.read_text(), "CREATE\n")
        self.assertEqual(len(self.requests()), 1)

    def expired_clock(self):
        db = self.parts[2].open_store(self.fixture.fixture.monitor)
        try:
            selected = self.grant.selector(db)
            record = self.grant.get(db, selected["grant_id"])
        finally:
            db.close()
        amount = record["definition"]["lifetime_seconds"] + 1
        return {key: value + amount if key in {"wall", "elapsed", "awake"} else value for key, value in record["activated"].items()}

    def test_expired_before_reservation_zero_post(self):
        self.activate()
        before = self.local.task_path.read_bytes()
        with mock.patch.object(self.grant, "clock", return_value=self.expired_clock()):
            with self.assertRaisesRegex(self.grant.Invalid, "GRANT_EXPIRED"):
                self.runtime("issue-create")
        self.assertEqual(self.local.task_path.read_bytes(), before)
        self.assertEqual(self.requests(), [])
        self.assertFalse(self.trace.exists())

    def test_expiry_after_reservation_settles_not_sent(self):
        self.activate()
        expired = self.expired_clock()
        reserve = self.parts[3].reserve

        def expire_after_commit(db, request):
            reserve(db, request)
            patcher = mock.patch.object(self.grant, "clock", return_value=expired)
            patcher.start()
            self.addCleanup(patcher.stop)

        with mock.patch.object(self.parts[3], "reserve", side_effect=expire_after_commit):
            self.assertEqual(self.runtime("issue-create")["status"], "NOT_SENT")
        self.assertEqual(self.task()["assignment_dispatch"]["phase"], "settled")
        self.assertFalse(self.trace.exists())

    def test_confirmed_get_settlement_after_expiry(self):
        self.activate()
        self.scenario = "get-failed"
        self.assertEqual(self.runtime("issue-create")["reservation"], "pending")
        self.scenario = "success"
        self.args.operation_id = self.requests()[0]["binding"]["operation_id"]
        self.args.expected_revision = self.task()["revision"]
        with (mock.patch.object(self.grant, "clock", return_value=self.expired_clock()),
              mock.patch.dict(os.environ, {"GH_TOKEN": "synthetic"}, clear=True)):
            self.assertEqual(dispatch.recover(self.args)["status"], "ISSUE_CREATED_OBSERVED")
        self.assertEqual(self.trace.read_text(), "CREATE\n")

    def test_standing_recovery_observes_full_assignee_set_without_admission(self):
        self.activate()
        self.runtime("issue-create")
        self.scenario = "assignment-get-failed"
        self.assertEqual(self.runtime("assignees-add")["reservation"], "pending")
        request = next(row for row in self.requests() if row["binding"]["action"] == "assignees-add")
        self.args.operation_id = request["binding"]["operation_id"]
        self.args.expected_revision = self.task()["revision"]
        self.scenario = "capacity-recovery"
        with mock.patch.dict(os.environ, {"GH_TOKEN": "synthetic"}, clear=True):
            self.assertEqual(dispatch.recover(self.args)["status"], "FAILED_ACTUAL_RESULT")
        self.assertEqual(self.trace.read_text(), "CREATE\nASSIGN\n")

    def test_closed_standing_producer_retains_receipt_after_worker_stops(self):
        self.activate()
        self.before_observe = self.fixture.stop_worker
        self.assertEqual(self.runtime("issue-create")["status"], "ISSUE_CREATED_OBSERVED")
        self.assertEqual(self.task()["assignment_dispatch"]["phase"], "settled")
        self.assertEqual(self.trace.read_text(), "CREATE\n")

    def test_standing_closed_receipt_retries_only_settlement_lock_entry(self):
        self.activate()
        finish = dispatch.finish
        locked = self.adapter.Store.locked
        entries = []

        @contextlib.contextmanager
        def contended(store):
            entries.append(True)
            if len(entries) == 1:
                raise self.parts[1].BusyError("synthetic entry contention")
            with locked(store) as db:
                yield db

        def finish_with_contention(*args, **kwargs):
            with mock.patch.object(self.adapter.Store, "locked", contended):
                return finish(*args, **kwargs)

        with mock.patch.object(dispatch, "finish", side_effect=finish_with_contention):
            self.assertEqual(self.runtime("issue-create")["status"], "ISSUE_CREATED_OBSERVED")
        self.assertEqual(len(entries), 2)
        self.assertEqual(self.trace.read_text(), "CREATE\n")

    def test_actual_clean_checkout_verifier_refuses_changed_implementation(self):
        self.activate()
        checkout = self.local.root / "implementation-probe"
        installed = checkout / ".agents/skills/workspace-orchestrator/bin"
        installed.parent.mkdir(parents=True)
        shutil.copytree(SOURCE / ".agents/skills/workspace-orchestrator/bin", installed)
        self.assertEqual((installed / "runtime-observation.py").read_bytes(),
                         (SOURCE / ".agents/skills/workspace-orchestrator/bin/runtime-observation.py").read_bytes())
        (checkout / "scripts").mkdir()
        (checkout / "scripts/assignment-dispatch.py").write_bytes((SOURCE / "scripts/assignment-dispatch.py").read_bytes())
        env = {"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}

        def git(*args):
            return subprocess.check_output(["/usr/bin/git", "-C", str(checkout), *args], env=env, stderr=subprocess.DEVNULL).decode().strip()

        git("init")
        git("add", ".")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "-m", "test: clean fixture")
        head = git("rev-parse", "HEAD")
        self.args.implementation_head = head
        with mock.patch.object(self.adapter, "__file__", str(checkout / "scripts/assignment-dispatch.py")):
            self.assertEqual(self.real_implementation_head(head), head)
            (checkout / "scripts/assignment-dispatch.py").write_text("changed fixture bytes\n")
            with mock.patch.object(self.adapter, "implementation_head", self.real_implementation_head):
                with self.assertRaises(Exception):
                    self.runtime("issue-create")
        self.assertFalse(self.trace.exists())
        self.assertEqual(self.requests(), [])

    def test_real_executor_five_creates_exhaust_repository_daily_budget(self):
        for index in range(6):
            if index:
                self.assertEqual(self.human("revoke")["status"], "GRANT_REVOKED_QUIESCENT")
                self.assertEqual(self.human("revoke-qualification")["status"], "QUALIFICATION_REVOKED")
                item = "fixture-" + str(index)
                self.admit_intake("intake-budget-" + str(index), item)
                self.definition.update(grant_id=hashlib.sha256(item.encode()).hexdigest()[32:], work_item=item,
                                       title="Synthetic standing-grant tracking fixture: " + item)
                self.make_qualification_artifacts()
                Path(self.grant_proposal).write_text(self.parts[3].canonical(self.definition))
            self.activate()
            if index == 5:
                before = self.local.task_path.read_bytes()
                with self.assertRaisesRegex(Exception, "DAILY_BUDGET_EXHAUSTED"):
                    self.runtime("issue-create")
                self.assertEqual(self.local.task_path.read_bytes(), before)
            else:
                self.runtime("issue-create")
                self.runtime("assignees-add")
                self.complete_intake()
        self.assertEqual(self.trace.read_text().count("CREATE\n"), 5)
        self.assertEqual(len(self.requests()), 10)

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

    def test_revocation_completion_does_not_retry_durability_failure(self):
        self.activate()
        with mock.patch.object(controller, "complete_revocation", side_effect=OSError("fixture request boundary")):
            self.assertIn("error", self.human("revoke"))
        store, _ = dispatch.make_store(self.args, self.adapter)
        with store.locked() as db:
            pending = self.grant.selector(db)
        with mock.patch.object(store, "durable", side_effect=store.core.BusyError("fixture barrier failure")) as barrier:
            with self.assertRaisesRegex(store.core.BusyError, "fixture barrier failure"):
                controller.complete_revocation(store, dispatch, self.grant, copy.deepcopy(pending))
        self.assertEqual(barrier.call_count, 1)
        self.assertFalse(dispatch.gate_path(store, self.definition["grant_id"]).exists())
        with store.locked() as db:
            final = self.grant.selector(db)
        self.assertEqual(final["state"], "revoked")
        self.assertEqual(final["revocation"], pending["revocation"])

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
        packaged = SOURCE / "tests/fixtures/standing-grant-legacy"
        manifest = json.loads((packaged / "manifest.json").read_text())
        self.assertEqual(manifest["source_revision"], revision)
        expected = {".agents/skills/workspace-orchestrator/bin/" + name for name in (
            "orchestrator-state.py", "reservation-history.py", "monitor-journal.py", "assignment-journal.py")}
        expected.add("scripts/check-native-ownership.py")
        self.assertEqual({entry["source_path"] for entry in manifest["files"]}, expected)
        self.assertEqual(len(manifest["files"]), len(expected))
        for entry in manifest["files"]:
            name = Path(entry["source_path"]).name
            self.assertEqual(entry["file"], name + ".txt")
            raw = (packaged / entry["file"]).read_bytes()
            self.assertEqual(len(raw), entry["size"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"])
            (target / name).write_bytes(raw)
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

    def revocation_race(self, phase, *, hold_gate_removal=False):
        self.activate()
        ready_read, ready_write = os.pipe()
        release_read, release_write = os.pipe()
        busy_read, busy_write = os.pipe()
        producer_result = self.local.root / "revocation-producer-result.json"

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
                release_dir = self.parts[1].release_dir
                def release_then_hold(path, token):
                    release_dir(path, token)
                    if hold_gate_removal and path.name.startswith("standing-effect-"):
                        # The gate is gone, but release_gate still owns the real
                        # coordinator. Parent releases us only after the revoker
                        # has actually encountered that lock contention.
                        os.write(ready_write, b"d")
                        if not select.select([release_read], [], [], 10)[0]:
                            raise AssertionError("revoker did not encounter gate-removal window")
                        self.assertEqual(os.read(release_read, 1), b"g")
                with mock.patch.object(self.parts[1], "release_dir", side_effect=release_then_hold):
                    result = self.runtime("issue-create")
                producer_result.write_text(json.dumps(result))
                os._exit(0)
            except Exception as exc:
                producer_result.write_text(json.dumps({"error": type(exc).__name__, "reason": str(exc)}))
                os._exit(3)
        requested = []
        removal_seen, contention_seen = [], []
        try:
            self.assertTrue(select.select([ready_read], [], [], 10)[0])
            self.assertEqual(os.read(ready_read, 1), b"r")

            def observe_requested():
                if requested:
                    if hold_gate_removal and not contention_seen:
                        if not removal_seen and select.select([ready_read], [], [], 0)[0]:
                            self.assertEqual(os.read(ready_read, 1), b"d")
                            self.assertFalse((self.local.state / "locks" / ("standing-effect-" + self.definition["grant_id"] + ".lock")).exists())
                            self.assertTrue((self.local.state / "locks/coordinator.lock").is_dir())
                            removal_seen.append(True)
                        if removal_seen and select.select([busy_read], [], [], 0)[0]:
                            self.assertEqual(os.read(busy_read, 1), b"b")
                            contention_seen.append(True)
                            os.write(release_write, b"g")
                    return
                db = self.parts[2].open_store(self.fixture.fixture.monitor)
                try:
                    selected = self.grant.selector(db)
                finally:
                    db.close()
                if selected["state"] == "revoke-requested":
                    # Visibility of the SQLite commit precedes durable() and
                    # coordinator exit. The fake transport checks no coordinator
                    # is held, so do not resume it inside that controller section.
                    if (self.local.state / "locks/coordinator.lock").exists():
                        return
                    # The real controller has committed request, but cannot ack
                    # quiescence until the actual runtime producer leaves its gate.
                    self.assertTrue((self.local.state / "locks" / ("standing-effect-" + self.definition["grant_id"] + ".lock")).is_dir())
                    self.assertEqual(os.waitpid(child, os.WNOHANG), (0, 0))
                    requested.append(selected)
                    os.write(release_write, b"g")

            enter = self.parts[1].CoordinatorLock.__enter__
            def observed_enter(lock):
                try:
                    return enter(lock)
                except self.parts[1].BusyError:
                    if hold_gate_removal:
                        os.write(busy_write, b"b")
                    raise
            with mock.patch.object(self.parts[1].CoordinatorLock, "__enter__", observed_enter):
                result = self.human("revoke", tick=observe_requested)
            self.assertEqual(result.get("status"), "GRANT_REVOKED_QUIESCENT", result)
            self.assertEqual(len(requested), 1)
            if hold_gate_removal:
                self.assertEqual((removal_seen, contention_seen), ([True], [True]))
            _, status = os.waitpid(child, 0)
            child = None
            producer = json.loads(producer_result.read_text())
            db = self.parts[2].open_store(self.fixture.fixture.monitor)
            try:
                evidence = [tuple(row) for row in db.execute("SELECT document FROM assignment_evidence")]
            finally:
                db.close()
            diagnostic = {"producer": producer, "evidence": evidence, "task": self.task()}
            self.assertEqual(os.waitstatus_to_exitcode(status), 3 if phase == "fresh" else 0, diagnostic)
            if phase == "fresh":
                self.assertFalse(self.trace.exists())
            else:
                self.assertEqual(producer.get("status"), "ISSUE_CREATED_OBSERVED", diagnostic)
                self.assertEqual(self.trace.read_text(), "CREATE\n")
                self.assertEqual(self.task()["tracker_number"], 501, diagnostic)
            with self.assertRaises(Exception):
                self.runtime("issue-create")
        finally:
            if child is not None:
                os.kill(child, signal.SIGKILL)
                os.waitpid(child, 0)
            for fd in (ready_read, ready_write, release_read, release_write, busy_read, busy_write):
                os.close(fd)

    def test_real_controller_revocation_before_reservation_prevents_post(self):
        self.revocation_race("fresh")

    def test_real_controller_revocation_waits_for_inflight_post(self):
        self.revocation_race("post")

    def test_revocation_retries_coordinator_entry_after_producer_gate_removal(self):
        self.revocation_race("post", hold_gate_removal=True)

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


class BootstrapTests(unittest.TestCase):
    """Fresh core layout, no legacy intent fixture and a real controlling TTY."""

    human = ExecutorTests.human
    make_qualification_artifacts = ExecutorTests.make_qualification_artifacts

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        self.adapter, self.publisher, self.grant = dispatch.modules()
        self.parts = self.adapter.modules()
        with mock.patch.dict(os.environ, {"ORCHESTRATOR_TEST_MODE": "1",
                             "ORCHESTRATOR_STATE_DIR": str(root / ".orchestrator")}, clear=True):
            state = self.parts[1].state_root()
        self.local = SimpleNamespace(root=root, state=state)
        self.monitor = state / "monitor"
        self.database = self.monitor / "history.sqlite3"
        # Exercise the actual public parser without invented task/worker IDs.
        with mock.patch.object(sys, "argv", ["control-standing-grant.py", "install-qualification",
                "--authority-root", str(root), "--invoking-root", str(root),
                "--implementation-head", "6" * 40, "--expected-epoch", "0",
                "--proposal", str(root / "qualification-proposal.json")]):
            self.args = dispatch.arguments(controller=True)
        self.definition = {"version": 1, "grant_id": "a" * 32, "objective": "synthetic", "work_item": "bootstrap",
            "repository": self.grant.REPOSITORY, "repository_id": self.grant.REPOSITORY_ID,
            "repository_node_id": "R_synthetic", "publisher": {"id": 11, "node_id": "U_synthetic", "login": "fixture-publisher"},
            "policy_sha256": dispatch.policy_digest(), "implementation_head": self.args.implementation_head,
            "lifetime_seconds": 86400, "title": "Synthetic standing-grant tracking fixture: bootstrap",
            "body": "Synthetic fixture for the synthetic objective. No production change requested.",
            "qualification": {"endpoint_evidence_sha256": "c" * 64},
            "workflow_effects": {"events": ["issues.opened", "issues.assigned"],
                "decision": "AUTHORIZE_REVIEWED_SYNTHETIC_ISSUE_EVENT_WORKFLOWS_AND_COST", "evidence_sha256": "d" * 64}}
        self.make_qualification_artifacts()
        self.args.proposal = self.qualification_proposal
        for patcher in (mock.patch.object(dispatch, "modules", return_value=(self.adapter, self.publisher, self.grant)),
                        mock.patch.object(self.adapter, "modules", return_value=self.parts),
                        mock.patch.object(self.adapter, "implementation_head", side_effect=lambda head: head),
                        mock.patch.object(self.parts[-1], "Transport", side_effect=AssertionError("bootstrap network"))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def install(self, **options):
        return self.human("install-qualification", **options)

    def assert_installed(self, new_store=True):
        db = self.parts[2].open_store(self.monitor)
        try:
            self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 7)
            record = self.grant.qualification_get(db, self.manifest["qualification_id"])
            self.assertEqual(record["installation"]["new_store"], new_store)
            self.assertIn(record["store_id"].encode(), self.last_human_output)
            self.assertEqual(record["installation"]["directories"], [[path.stat().st_dev, path.stat().st_ino]
                for path in (self.local.root, self.local.state, self.local.state / "locks", self.monitor)])
            for table in ("standing_grants", "standing_selector", "claim_intents", "assignment_requests"):
                self.assertEqual(db.execute("SELECT count(*) FROM " + table).fetchone()[0], 0)
            with self.assertRaisesRegex(self.grant.Invalid, "NO_ACTIVE_GRANT"):
                self.grant.selector(db)
        finally:
            db.close()

    def test_fresh_core_real_tty_install_and_no_preapproval_authority(self):
        self.assertFalse(self.monitor.exists())
        store, _ = dispatch.make_store(self.args, self.adapter)
        with self.assertRaises(FileNotFoundError), store.locked():
            self.fail("runtime prepared directories")
        self.assertFalse(self.monitor.exists())
        def before():
            self.assertTrue(self.monitor.is_dir())
            self.assertFalse(self.database.exists())
        result = self.install(before_answer=before)
        self.assertEqual(result.get("status"), "OFFLINE_QUALIFICATION_INSTALLED_FOR_ONE_USE_LIVE_PILOT", result)
        self.assert_installed()

    def test_missing_file_in_existing_monitor_and_runtime_refusal(self):
        self.monitor.mkdir(mode=0o700)
        store, _ = dispatch.make_store(self.args, self.adapter)
        with self.assertRaisesRegex(self.adapter.Refusal, "EXISTING_JOURNAL_REQUIRED"), store.locked():
            self.fail("runtime created store")
        self.assertFalse(self.database.exists())
        self.assertIn("status", self.install())
        self.assert_installed()

    def test_decline_preserves_artifacts_without_creating_journal(self):
        before = {path: path.read_bytes() for path in self.evidence_dir.iterdir()}
        self.assertIn("error", self.install(approve=False))
        self.assertFalse(self.database.exists())
        self.assertEqual({path: path.read_bytes() for path in self.evidence_dir.iterdir()}, before)

    def test_no_controlling_tty_leaves_journal_absent(self):
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
        self.assertEqual(os.waitstatus_to_exitcode(os.waitpid(child, 0)[1]), 0)
        self.assertFalse(self.database.exists())

    def test_directory_replacement_during_prompt_refuses(self):
        def replace():
            self.monitor.rename(self.local.state / "parked-monitor")
            self.monitor.mkdir(mode=0o700)
        self.assertEqual(self.install(before_answer=replace).get("reason"), "STORE_IDENTITY_CHANGED")
        self.assertFalse(self.database.exists())

    def test_concurrent_store_creation_preserves_human_state(self):
        def create():
            self.parts[2].open_store(self.monitor, writable=True).close()
            self.concurrent_bytes = self.database.read_bytes()
        self.assertEqual(self.install(before_answer=create).get("reason"), "STORE_IDENTITY_CHANGED")
        self.assertEqual(self.database.read_bytes(), self.concurrent_bytes)

    def test_orphan_sidecar_refuses_bootstrap(self):
        self.monitor.mkdir(mode=0o700)
        sidecar = self.monitor / "history.sqlite3-journal"
        sidecar.write_bytes(b"private-recovery-secret-canary")
        sidecar.chmod(0o600)
        result = self.install(cli=True)
        self.assertEqual(result.get("reason"), "JOURNAL_RECOVERY_REQUIRED")
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertNotEqual(result["cli_exit"], 0)
        self.assertNotIn(b"private-recovery-secret-canary", self.last_human_output)
        self.assertNotIn(str(self.local.root).encode(), self.last_human_output)
        self.assertNotIn(b"Type exactly", self.last_human_output)
        self.assertFalse(self.database.exists())
        self.assertEqual(sidecar.read_bytes(), b"private-recovery-secret-canary")

    def test_taskless_public_controller_install_revoke_cycle(self):
        result = self.install(cli=True)
        self.assertEqual(result.get("status"), "OFFLINE_QUALIFICATION_INSTALLED_FOR_ONE_USE_LIVE_PILOT", result)
        self.assertEqual(result["cli_exit"], 0)
        self.assert_installed()
        self.args.expected_epoch = 1
        result = self.human("revoke-qualification", cli=True)
        self.assertEqual(result.get("status"), "QUALIFICATION_REVOKED", result)
        self.assertEqual(result["cli_exit"], 0)
        self.assertIn(b"Type exactly REVOKE-QUALIFICATION", self.last_human_output)
        db = self.parts[2].open_store(self.monitor)
        try:
            self.assertEqual(self.grant.qualification_selector(db)["state"], "revoked")
            self.assertEqual(db.execute("SELECT count(*) FROM standing_grants").fetchone()[0], 0)
        finally:
            db.close()

    def test_other_actions_still_require_each_task_fence(self):
        fences = {"task-id": "fixture", "expected-revision": "1", "expected-worker-id": "a" * 32,
                  "expected-session-id": "fixture-session", "expected-generation": "1"}
        for action in ("activate", "revoke", "issue-create", "assignees-add", "settle", "complete"):
            for omitted in fences:
                with self.subTest(action=action, omitted=omitted):
                    argv = ["fixture", action, "--authority-root", self.args.authority_root,
                            "--invoking-root", self.args.invoking_root, "--implementation-head", self.args.implementation_head,
                            "--expected-epoch", "0"]
                    argv.extend(part for key, value in fences.items() if key != omitted for part in ("--" + key, value))
                    if action == "activate":
                        argv.extend(["--proposal", self.qualification_proposal])
                    if action == "settle":
                        argv.extend(["--operation-id", "b" * 32])
                    with mock.patch.object(sys, "argv", argv), self.assertRaisesRegex(self.adapter.Refusal, "INVALID_ARGUMENTS"):
                        dispatch.arguments(controller=action in {"activate", "revoke"})

    def test_unclean_code_and_changed_artifact_do_not_initialize(self):
        with mock.patch.object(self.adapter, "implementation_head", side_effect=RuntimeError("IMPLEMENTATION_HEAD_CHANGED")):
            self.assertEqual(self.install().get("reason"), "IMPLEMENTATION_HEAD_CHANGED")
        self.assertFalse(self.database.exists())
        def alter():
            path = self.evidence_dir / "transcript.txt"
            path.write_bytes(b"x" * path.stat().st_size)
        self.assertEqual(self.install(before_answer=alter).get("reason"), "QUALIFICATION_ARTIFACT_CHANGED")
        self.assertFalse(self.database.exists())

    def test_installed_qualification_is_bound_to_physical_directories(self):
        self.assertIn("status", self.install())
        moved = self.local.state / "retained-monitor"
        self.monitor.rename(moved)
        self.monitor.mkdir(mode=0o700)
        shutil.copyfile(moved / "history.sqlite3", self.database)
        self.database.chmod(0o600)
        store, _ = dispatch.make_store(self.args, self.adapter)
        with store.locked() as db:
            with self.assertRaisesRegex(self.grant.Invalid, "STORE_IDENTITY_CHANGED"):
                dispatch.require_endpoint_qualification(store, db, self.grant, self.definition)

    def fail_commit(self):
        original = self.grant.put_qualification_selector
        def denied(db, value):
            original(db, value)
            db.set_authorizer(lambda operation, first, *_: sqlite3.SQLITE_DENY
                if operation == sqlite3.SQLITE_TRANSACTION and first == "COMMIT" else sqlite3.SQLITE_OK)
        return mock.patch.object(self.grant, "put_qualification_selector", side_effect=denied)

    def test_fresh_commit_failure_retains_empty_v1_for_human_retry(self):
        with self.fail_commit():
            self.assertIn("error", self.install())
        db = self.parts[2].open_store(self.monitor)
        try:
            identity = db.execute("SELECT store_id FROM meta").fetchone()[0]
            self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 1)
            self.assertIn(identity.encode(), self.last_human_output)
        finally:
            db.close()

        self.assertIn("status", self.install())
        self.assert_installed(new_store=False)
        db = self.parts[2].open_store(self.monitor)
        try:
            self.assertEqual(db.execute("SELECT store_id FROM meta").fetchone()[0], identity)
        finally:
            db.close()

    def test_initial_v1_commit_failure_retains_partial_file_without_repair(self):
        journal = self.parts[2]
        class InitialCommitFailure(journal.StoreConnection):
            def execute(self, sql, parameters=()):
                result = super().execute(sql, parameters)
                if sql == "INSERT INTO meta VALUES (1, ?)":
                    self.set_authorizer(lambda operation, first, *_: sqlite3.SQLITE_DENY
                        if operation == sqlite3.SQLITE_TRANSACTION and first == "COMMIT" else sqlite3.SQLITE_OK)
                return result
        with mock.patch.object(journal, "StoreConnection", InitialCommitFailure):
            result = self.install(cli=True)
        self.assertEqual(result.get("status"), "UNVERIFIED", result)
        self.assertNotEqual(result["cli_exit"], 0)
        self.assertTrue(self.database.is_file())
        before = (self.database.stat().st_ino, self.database.read_bytes())
        db = sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True)
        try:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [])
        finally:
            db.close()
        # With injection removed, neither runtime nor another install repairs
        # the retained partial file or collects fresh approval for overwriting it.
        store, _ = dispatch.make_store(self.args, self.adapter)
        with self.assertRaises(journal.JournalError), store.locked():
            self.fail("runtime repaired partial store")
        result = self.install(cli=True)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertNotIn(b"Type exactly", self.last_human_output)
        self.assertEqual((self.database.stat().st_ino, self.database.read_bytes()), before)

    def test_existing_commit_failure_and_decline_preserve_history_bytes(self):
        self.monitor.mkdir(mode=0o700)
        db = self.parts[2].open_store(self.monitor, writable=True)
        self.parts[2].begin(db, "bootstrap-history", "a" * 64, "monitor", ["repo:fixture/project"], "start")
        db.close()
        before = self.database.read_bytes()
        self.assertIn("error", self.install(approve=False))
        self.assertEqual(self.database.read_bytes(), before)
        with self.fail_commit():
            self.assertIn("error", self.install())
        self.assertEqual(self.database.read_bytes(), before)

    def test_postcommit_durability_failure_retains_selected_qualification(self):
        with mock.patch.object(self.parts[4], "durable", side_effect=OSError("fixture durability failure")):
            self.assertIn("error", self.install())
        self.assert_installed()
        self.assertEqual(self.install().get("reason"), "QUALIFICATION_EPOCH_CHANGED")


if __name__ == "__main__":
    unittest.main()
