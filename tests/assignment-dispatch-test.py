#!/usr/bin/env python3
"""Offline vertical: actual core/SQLite/TTY, injected HTTP only; isolated guest only."""

import copy
import importlib.util
import io
import json
import os
import pty
import re
import select
import shutil
import signal
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


fixture_module = load("dispatch_intent_fixtures", SOURCE / "tests/journal-approved-claim-test.py")
adapter = load("dispatch_fixture_adapter", SOURCE / "scripts/assignment-dispatch.py")
publisher = load("dispatch_fixture_publisher", SOURCE / "scripts/publish-github-assignment.py")


class DispatchTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.ApprovedIntentTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.local = self.fixture.fixture.local
        # Bind intent to a real separately stoppable worker BEFORE recording it.
        self.worker = subprocess.Popen([sys.executable, "-I", "-B", "-c", "import time; time.sleep(120)"],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop_worker)
        status, start = self.fixture.core.process_identity(
            self.worker.pid, environment={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        self.assertEqual(status, "alive")
        self.local.task["worker"].update(pid=self.worker.pid, process_start=start)
        self.local.original_worker = copy.deepcopy(self.local.task["worker"])
        self.local.write(self.local.task_path, self.local.task)
        for group, index in (("slots", self.local.task["leases"]["global_slot"]),
                             ("implementation", self.local.task["leases"]["implementation_lane"])):
            self.local.write(self.local.state / group / (str(index) + ".lock") / "owner.json", self.local.task["worker"])
        self.fixture.assert_recorded()
        self.local = self.fixture.fixture.local
        self.intent = self.fixture.request()
        task = self.local.task
        self.args = SimpleNamespace(action="assign", authority_root=str(self.local.root), invoking_root=str(self.local.root),
            task_id=task["task_id"], expected_revision=task["revision"], expected_worker_id=task["worker"]["worker_id"],
            expected_session_id=task["worker"]["session_id"], expected_generation=task["worker"]["generation"],
            intent_operation_id=self.intent["operation_id"], implementation_head="6" * 40, assignment_operation_id=None)
        self.parts = adapter.modules()
        self.trace = self.local.root / "transport-trace"

    def stop_worker(self):
        if self.worker.poll() is None:
            self.worker.kill()
        self.worker.wait(timeout=5)

    def task(self):
        return json.loads(self.local.task_path.read_text())

    def rows(self):
        journal, typed = self.parts[2:4]
        db = journal.open_store(self.fixture.monitor)
        try:
            version = db.execute("SELECT version FROM meta").fetchone()[0]
            if version != 6:
                return version, None, None, None
            request = typed.decode(db.execute("SELECT document FROM assignment_requests").fetchone()[0])
            return version, request, typed.get(db, "assignment_evidence", request["evidence_id"]), typed.get(db, "assignment_settlements", request["settlement_id"])
        finally:
            db.close()

    def run_vertical(self, scenario="success", approve=True):
        parts = self.parts
        real_transport = parts[-1]
        fixture = self
        actor = self.intent["identity_observation"]["actor_id"]
        original_transport = real_transport.Transport

        def truncated(method, observed):
            claim = fixture.intent["claim"]
            path = "/repos/" + claim["repo"] + "/issues/" + str(claim["issue"])
            body = json.dumps({"id": observed["issue_id"], "node_id": observed["issue_node_id"],
                "number": claim["issue"], "url": real_transport.API + path,
                "repository_url": real_transport.API + "/repos/" + claim["repo"], "state": "open",
                "locked": False, "assignees": [{"id": actor}]}).encode()

            class Socket:
                def makefile(self, mode):
                    return io.BytesIO(b"HTTP/1.1 " + (b"201 Created" if method == "POST" else b"200 OK")
                        + b"\r\nContent-Type: application/json\r\nContent-Length: "
                        + str(len(body) + 10).encode() + b"\r\n\r\n" + body)

            class Connection:
                def __init__(self, *args, **kwargs):
                    pass

                def request(self, *args, **kwargs):
                    pass

                def getresponse(self):
                    response = real_transport.http.client.HTTPResponse(Socket())
                    response.begin()
                    return response

                def close(self):
                    pass

            client = original_transport(claim["repo"], claim["issue"], "ghp_" + "x" * 36)
            try:
                with mock.patch.object(real_transport, "BoundedHTTPSConnection", Connection):
                    return (client.assign if method == "POST" else client.issue)(observed)
            finally:
                client.close()

        class FakeTransport:
            def __init__(self, *args):
                self.closed = False
                self.http_status = None

            def no_locks(self):
                if (fixture.local.state / "locks/coordinator.lock").exists():
                    raise AssertionError("network under coordinator")
                db = parts[2].open_store(fixture.fixture.monitor, writable=True)
                try:
                    db.execute("BEGIN IMMEDIATE")
                    db.rollback()
                finally:
                    db.close()

            def fresh(self, observed):
                self.no_locks()
                if scenario == "preflight-refused":
                    raise real_transport.Refusal("ASSIGNMENT_PERMISSION_UNPROVEN")
                return [actor] if scenario == "present" else [actor + 1] if scenario == "drift" else []

            def assign(self, observed):
                self.no_locks()
                version, request, evidence, settlement = fixture.rows()
                assert version == 6 and request and evidence is None and settlement is None
                assert fixture.task() == request["reserved_task"]
                fixture.trace.write_text("POST")
                if scenario == "lost":
                    raise OSError("lost response")
                if scenario == "both-fail":
                    self.http_status = 201
                    raise real_transport.Refusal("ROUTING_OR_INCOMPLETE_RESPONSE")
                if scenario == "canary":
                    raise RuntimeError("private-canary-token-header-id")
                if scenario == "truncated-post":
                    truncated("POST", observed)

            def issue(self, observed):
                self.no_locks()
                if scenario == "both-fail":
                    self.http_status = 403
                    raise real_transport.Refusal("RATE_LIMITED")
                if scenario == "canary":
                    raise RuntimeError("private-canary-token-header-id")
                if scenario == "incomplete":
                    raise OSError("incomplete GET")
                if scenario == "truncated-get":
                    return truncated("GET", observed)
                return [] if scenario == "ignored" else [actor]

            def close(self):
                self.closed = True

        # The child uses the actual controlling-terminal collector. Parent answers
        # only the displayed digest challenge. No approval factory is substituted.
        child, fd = pty.fork()
        if child == 0:
            try:
                with (mock.patch.dict(os.environ, {"GH_TOKEN": "fixture-token"}, clear=True),
                      mock.patch.object(adapter, "modules", return_value=parts),
                      mock.patch.object(adapter, "implementation_head", side_effect=lambda expected: expected),
                      mock.patch.object(real_transport, "Transport", FakeTransport)):
                    original_reserve = parts[3].reserve
                    original_durable = parts[4].durable
                    original_build = adapter.build
                    original_release = parts[1].assignment_release
                    original_evidence = adapter.evidence

                    def evidence(*args):
                        receipt = original_evidence(*args)
                        if scenario == "legacy-evidence":
                            receipt["version"] = 1
                            del receipt["diagnostics"]
                        return receipt

                    def release(*args):
                        if scenario == "terminal-crash":
                            raise RuntimeError("durable settlement before marker acknowledgment")
                        return original_release(*args)

                    def build(*args):
                        request = original_build(*args)
                        if scenario == "collision":
                            request["evidence_id"] = fixture.intent["operation_id"]
                        return request

                    def reserve(db, request):
                        if scenario == "marker-crash":
                            raise RuntimeError("after marker")
                        return original_reserve(db, request)

                    def durable(journal, db, root):
                        original_durable(journal, db, root)
                        if scenario == "commit-crash":
                            raise RuntimeError("lost commit acknowledgment")
                        if scenario == "expired":
                            publisher.MAX_APPROVAL_SECONDS = 0

                    with (mock.patch.object(parts[3], "reserve", side_effect=reserve),
                          mock.patch.object(parts[4], "durable", side_effect=durable),
                          mock.patch.object(adapter, "build", side_effect=build),
                          mock.patch.object(adapter, "evidence", side_effect=evidence),
                          mock.patch.object(parts[1], "assignment_release", side_effect=release),
                          mock.patch.object(parts[3], "CAPACITY", 0 if scenario == "full" else parts[3].CAPACITY),
                          mock.patch.object(publisher, "load_adapter", return_value=adapter),
                          mock.patch.object(adapter, "arguments", return_value=self.args)):
                        code = publisher.main()
                os._exit(code)  # Bypass shutdown buffering: main must flush JSON itself.
            except BaseException:
                os._exit(2)
        output = bytearray()
        sent = False
        status = None
        until = time.monotonic() + 20
        try:
            while time.monotonic() < until:
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
                        match = re.search(rb"Type exactly (APPROVE [0-9a-f]{64})", output)
                        self.assertIsNotNone(match)
                        os.write(fd, match[1] + b"\n" if approve else b"decline\n")
                        sent = True
            done, status = os.waitpid(child, 0 if time.monotonic() < until else os.WNOHANG)
            if not done:
                os.kill(child, signal.SIGKILL)
                _, status = os.waitpid(child, 0)
        finally:
            os.close(fd)
        lines = [json.loads(line) for line in output.splitlines() if line.startswith(b'{"completion":')]
        self.assertEqual(len(lines), 1, output.decode(errors="replace"))
        result = lines[0]
        self.assertEqual(os.waitstatus_to_exitcode(status), 0 if result["reservation"] == "settled" else 3)
        self.assertNotIn(b"private-canary", output)
        self.last_output = result
        return "REFUSED:" + result["reason"] if result["status"] == "UNVERIFIED" else result["status"]

    def test_success_exact_intent_and_durable_terminal(self):
        self.assertEqual(self.run_vertical(), "ASSIGNMENT_CONFIRMED_OBSERVED")
        version, request, evidence, settlement = self.rows()
        self.assertEqual(version, 6)
        self.assertEqual(request["original_task"], self.local.task)
        self.assertEqual(request["binding"]["task_binding"]["revision"], self.local.task["revision"] + 1)
        self.assertEqual(self.fixture.request(), self.intent)
        self.assertEqual(evidence["completion"], "CONFIRMED")
        self.assertTrue(settlement["satisfaction"])
        self.assertEqual(self.task()["assignment_dispatch"]["phase"], "settled")

    def test_present_no_post(self):
        self.assertEqual(self.run_vertical("present"), "SATISFIED_NO_POST")
        self.assertFalse(self.trace.exists())
        self.assertEqual(self.rows()[2]["completion"], "NOT_SENT")

    def test_ignored_assignment_terminal_failure(self):
        self.assertEqual(self.run_vertical("ignored"), "FAILED_ACTUAL_RESULT")
        self.assertFalse(self.rows()[3]["satisfaction"])

    def test_removed_prior_assignee_is_drift(self):
        self.assertEqual(self.run_vertical("drift"), "DRIFT")
        self.assertFalse(self.rows()[3]["satisfaction"])

    def test_v6_preserves_intents_and_observation_namespaces(self):
        self.assertEqual(self.run_vertical(), "ASSIGNMENT_CONFIRMED_OBSERVED")
        journal, typed = self.parts[2:4]
        _, request, _, _ = self.rows()
        db = journal.open_store(self.fixture.monitor, writable=True)
        try:
            # Old exact v2 replay cannot downgrade the v6 header.
            self.assertEqual(journal.record_claim_intent(db, self.intent), "REPLAYED_PENDING")
            self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 6)
            for identity in (request["binding"]["operation_id"], request["binding"]["attempt_id"],
                             request["evidence_id"], request["settlement_id"]):
                with self.assertRaises(journal.JournalError):
                    journal.validate_observation_id(db, identity)
                with self.assertRaises(journal.JournalError):
                    journal.reject_reserved_observation_ids(db, {identity})
            new = copy.deepcopy(self.intent)
            new["operation_id"] = "9" * 32
            new["claim"]["operation_id"] = new["operation_id"]
            new["comment"] = self.fixture.prepare.codec.render(new["claim"])
            new["comment_sha256"] = self.fixture.prepare.codec.digest(new["comment"])
            new["public_text_declaration"]["approved_body_sha256"] = new["comment_sha256"]
            self.assertEqual(journal.record_claim_intent(db, new), "INTENT_RECORDED")
            self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 6)
            journal.validate_store(db)
            with self.assertRaises(Exception):
                typed.reserve(db, request)
            journal.validate_store(db)
        finally:
            db.close()

    def test_decline_preserves_original_without_attempt(self):
        self.assertIn("APPROVAL_DECLINED", self.run_vertical(approve=False))
        self.assertEqual(self.task(), self.local.task)
        self.assertEqual(self.rows()[0], 5)
        self.assertFalse(self.trace.exists())

    def test_marker_only_crash_blocks_release(self):
        self.assertIn("REFUSED", self.run_vertical("marker-crash"))
        self.assertEqual(self.rows()[0], 5)
        self.assert_pending_guards()

    def test_full_journal_refuses_before_marker(self):
        self.assertEqual(self.run_vertical("full"), "REFUSED:ASSIGNMENT_CAPACITY_EXHAUSTED")
        self.assertEqual(self.task(), self.local.task)
        self.assertEqual(self.rows()[0], 5)
        self.assertFalse(self.trace.exists())

    def test_reserved_identifier_collision_refuses_before_marker(self):
        self.assertEqual(self.run_vertical("collision"), "REFUSED:ASSIGNMENT_IDENTIFIER_COLLISION")
        self.assertEqual(self.task(), self.local.task)
        self.assertEqual(self.rows()[0], 5)
        self.assertFalse(self.trace.exists())

    def test_commit_acknowledgment_loss_never_launches(self):
        self.assertIn("REFUSED", self.run_vertical("commit-crash"))
        self.assertEqual(self.rows()[0], 6)
        self.assertIsNone(self.rows()[2])
        self.assertFalse(self.trace.exists())
        self.assert_pending_guards()

    def test_expired_committed_approval_settles_not_sent(self):
        self.assertEqual(self.run_vertical("expired"), "NOT_SENT")
        self.assertFalse(self.trace.exists())
        self.assertEqual(self.rows()[3]["outcome"], "NOT_SENT")

    def test_unknown_presence_never_confirms_or_releases(self):
        self.assertEqual(self.run_vertical("lost"), "UNKNOWN")
        self.stop_worker()
        self.assertEqual(self.rows()[2]["completion"], "UNKNOWN")
        self.assertIsNone(self.rows()[3])
        self.assert_pending_guards()
        args = copy.copy(self.args)
        args.action = "settle"
        args.expected_revision = self.task()["revision"]
        args.assignment_operation_id = self.rows()[1]["binding"]["operation_id"]
        with (mock.patch.dict(os.environ, {}, clear=True),
              mock.patch.object(adapter, "modules", return_value=self.parts),
              mock.patch.object(adapter, "implementation_head", side_effect=lambda expected: expected),
              self.assertRaisesRegex(adapter.Refusal, "PRODUCER_TERMINATION_PROOF_UNSUPPORTED")):
            adapter.recover(args, publisher)
        args.action = "arbitrate"
        with self.assertRaisesRegex(adapter.Refusal, "PRODUCER_TERMINATION_PROOF_UNSUPPORTED"):
            adapter.recover(args, publisher)
        self.assert_pending_guards()

    def test_confirmed_incomplete_retains_completion(self):
        self.assertEqual(self.run_vertical("incomplete"), "UNKNOWN")
        self.assertEqual(self.rows()[2]["completion"], "CONFIRMED")
        self.assertIsNone(self.rows()[2]["result_ids"])
        self.assert_pending_guards()

    def test_primary_post_failure_survives_correlation_failure(self):
        self.assertEqual(self.run_vertical("both-fail"), "UNKNOWN")
        receipt = self.rows()[2]
        self.assertEqual(receipt["diagnostics"], [
            {"stage": "POST", "reason": "ROUTING_OR_INCOMPLETE_RESPONSE", "http_status": 201},
            {"stage": "CORRELATION", "reason": "RATE_LIMITED", "http_status": 403}])
        self.assertEqual(self.last_output["diagnostics"], receipt["diagnostics"])
        self.assertIsNone(receipt["result_ids"])
        self.assertIsNone(self.rows()[3])
        self.assert_pending_guards()

    def test_canary_exceptions_are_not_retained_or_printed(self):
        self.assertEqual(self.run_vertical("canary"), "UNKNOWN")
        receipt = self.rows()[2]
        self.assertNotIn("private-canary", json.dumps(receipt))
        self.assertEqual([item["reason"] for item in receipt["diagnostics"]], ["UNEXPECTED_FAILURE"] * 2)

    def test_known_transport_preflight_refusal_reaches_cli(self):
        self.assertEqual(self.run_vertical("preflight-refused"), "REFUSED:ASSIGNMENT_PERMISSION_UNPROVEN")
        self.assertEqual(self.task(), self.local.task)
        self.assertEqual(self.rows()[0], 5)
        self.assertFalse(self.trace.exists())

    def test_old_v6_evidence_reads_without_rewriting(self):
        self.assertEqual(self.run_vertical("legacy-evidence"), "ASSIGNMENT_CONFIRMED_OBSERVED")
        journal, typed = self.parts[2:4]
        _, request, receipt, terminal = self.rows()
        self.assertEqual(receipt["version"], 1)
        self.assertNotIn("diagnostics", receipt)
        db = journal.open_store(self.fixture.monitor, writable=True)
        try:
            before = [tuple(row) for row in db.execute("SELECT * FROM assignment_evidence")]
            journal.validate_store(db)
            typed.fill(db, "assignment_evidence", request["evidence_id"], receipt)
            self.assertEqual(before, [tuple(row) for row in db.execute("SELECT * FROM assignment_evidence")])
            self.assertEqual(typed.get(db, "assignment_settlements", request["settlement_id"]), terminal)
            with self.assertRaises(typed.Invalid):
                typed.fill(db, "assignment_evidence", request["evidence_id"], dict(receipt, version=2, diagnostics=[]))
        finally:
            db.close()

    def test_typed_diagnostics_reject_unbounded_or_unrecognized_content(self):
        typed = self.parts[3]
        class CanaryError(Exception):
            def __str__(self):
                raise AssertionError("exception stringification attempted")

        self.assertEqual(typed.diagnostic("POST", CanaryError("private-canary"), True),
                         {"stage": "POST", "reason": "UNEXPECTED_FAILURE", "http_status": None})
        request = {"binding": {"attempt_id": "1" * 32}}
        valid = adapter.evidence(request, "UNKNOWN", None, [
            {"stage": "POST", "reason": "HTTP_STATUS_REFUSED", "http_status": 422}])
        typed.validate_evidence(request, valid)
        for field, value in (("stage", "private-canary"), ("reason", "private-canary"),
                             ("http_status", True), ("http_status", 600), ("http_status", "201")):
            changed = copy.deepcopy(valid)
            changed["diagnostics"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(typed.Invalid):
                typed.validate_evidence(request, changed)
        with self.assertRaises(typed.Invalid):
            typed.validate_evidence(request, dict(valid, diagnostics=valid["diagnostics"] * 3))

    def test_confirmed_incomplete_get_only_settlement(self):
        self.assertEqual(self.run_vertical("incomplete"), "UNKNOWN")
        self.stop_worker()
        self.assertEqual(self.parts[1].process_identity(
            self.worker.pid, environment={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}), ("absent", None))
        _, request, original_evidence, _ = self.rows()
        args = copy.copy(self.args)
        args.action = "settle"
        args.expected_revision = request["reserved_task"]["revision"]
        args.assignment_operation_id = request["binding"]["operation_id"]
        actor = request["binding"]["publisher"]["id"]
        calls = []
        fixture = self

        class ReadOnlyTransport:
            def __init__(self, *args):
                pass

            def fresh(self, observed):
                fixture.assertFalse((fixture.local.state / "locks/coordinator.lock").exists())
                calls.append("GET")
                return [actor]

            def assign(self, observed):
                raise AssertionError("settlement attempted POST")

            def close(self):
                pass

        with (mock.patch.dict(os.environ, {"GH_TOKEN": "fixture-token"}, clear=True),
              mock.patch.object(adapter, "modules", return_value=self.parts),
              mock.patch.object(adapter, "implementation_head", side_effect=lambda expected: expected),
              mock.patch.object(self.parts[-1], "Transport", ReadOnlyTransport)):
            result = adapter.recover(args, publisher)
        self.assertEqual(result["status"], "ASSIGNMENT_CONFIRMED_OBSERVED")
        self.assertEqual(calls, ["GET"])
        self.assertEqual(self.rows()[2], original_evidence)
        self.assertEqual(self.rows()[3]["result_ids"], [actor])
        self.assertEqual(self.task()["assignment_dispatch"]["phase"], "settled")

    def test_dead_worker_terminal_acknowledgment_recovery(self):
        self.assertIn("REFUSED", self.run_vertical("terminal-crash"))
        _, request, receipt, terminal = self.rows()
        self.assertIsNotNone(terminal)
        self.stop_worker()
        args = copy.copy(self.args)
        args.action = "settle"
        args.expected_revision = request["reserved_task"]["revision"]
        args.assignment_operation_id = request["binding"]["operation_id"]
        with (mock.patch.dict(os.environ, {}, clear=True),
              mock.patch.object(adapter, "modules", return_value=self.parts),
              mock.patch.object(adapter, "implementation_head", side_effect=lambda expected: expected),
              mock.patch.object(self.parts[-1], "Transport", side_effect=AssertionError("unexpected network"))):
            result = adapter.recover(args, publisher)
        self.assertEqual(result["status"], "ASSIGNMENT_CONFIRMED_OBSERVED")
        self.assertEqual(self.rows()[2:], (receipt, terminal))
        self.assertEqual(self.task()["worker"], request["reserved_task"]["worker"])
        self.assertEqual(self.task()["leases"], request["reserved_task"]["leases"])

    def test_truncated_post_never_confirms(self):
        self.assertEqual(self.run_vertical("truncated-post"), "UNKNOWN")
        self.assertEqual(self.rows()[2]["completion"], "UNKNOWN")
        self.assertIsNone(self.rows()[3])
        self.assert_pending_guards()

    def test_truncated_get_never_settles(self):
        self.assertEqual(self.run_vertical("truncated-get"), "UNKNOWN")
        self.assertEqual(self.rows()[2]["completion"], "CONFIRMED")
        self.assertIsNone(self.rows()[2]["result_ids"])
        self.assertIsNone(self.rows()[3])
        self.assert_pending_guards()

    def assert_pending_guards(self):
        core = self.parts[1]
        task = self.task()
        before = self.local.task_path.read_bytes()
        self.assertEqual(task["assignment_dispatch"]["phase"], "pending")
        for call in (lambda: core.release_capacity(self.local.state, copy.deepcopy(task)),
                     lambda: core.release_implementation_lane(self.local.state, copy.deepcopy(task)),
                     lambda: core.write_task(self.local.state, copy.deepcopy(task), allow_bound=True),
                     lambda: core.finish_intent(self.local.state, copy.deepcopy(task)),
                     lambda: core.reconcile_one(self.local.state, copy.deepcopy(task)),
                     lambda: core.recovery_reservations(self.local.state, copy.deepcopy(task), False)):
            with self.assertRaises(core.BusyError):
                call()
        with self.assertRaises(Exception):
            core.assignment_release(self.local.state, task)
        self.assertEqual(self.local.task_path.read_bytes(), before)


class ImplementationProbeTest(unittest.TestCase):
    def test_raw_checkout_probe_disables_configured_execution_and_credentials(self):
        with tempfile.TemporaryDirectory(prefix="assignment-probe-") as directory:
            root = Path(directory).resolve()
            installed = root / ".agents/skills/workspace-orchestrator/bin"
            shutil.copytree(SOURCE / ".agents/skills/workspace-orchestrator/bin", installed,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (root / "scripts").mkdir()
            (root / "scripts/assignment-dispatch.py").write_text("fixture\n")
            (root / ".gitignore").write_text("ignored-extra\n")
            env = {"PATH": "/usr/bin:/bin", "HOME": str(root), "GIT_CONFIG_NOSYSTEM": "1",
                   "GIT_CONFIG_GLOBAL": os.devnull}

            def git(*args):
                return subprocess.run(["/usr/bin/git", "-C", str(root), *args], env=env,
                                      capture_output=True, text=True, check=True).stdout.strip()

            git("init")
            git("add", ".")
            git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "-c", "commit.gpgsign=false", "commit", "-m", "test: fixture")
            head = git("rev-parse", "HEAD")
            canary = root / "probe-executed"
            script = root / ".git/probe-hook"
            script.write_text("#!/bin/sh\ntouch '" + str(canary) + "'\nexit 1\n")
            script.chmod(0o700)
            git("config", "core.fsmonitor", str(script))
            git("config", "core.hooksPath", str(root / ".git"))
            git("config", "filter.probe.clean", str(script))
            git("config", "filter.probe.required", "true")
            (root / ".git/info/attributes").write_text("* filter=probe\n")
            run = subprocess.run

            def inspect(argv, **kwargs):
                self.assertNotIn("GH_TOKEN", kwargs["env"])
                self.assertNotIn("GITHUB_TOKEN", kwargs["env"])
                self.assertIn("core.fsmonitor=false", argv)
                self.assertIn("protocol.allow=never", argv)
                return run(argv, **kwargs)

            with (mock.patch.object(adapter, "__file__", str(root / "scripts/assignment-dispatch.py")),
                  mock.patch.dict(os.environ, {"GH_TOKEN": "fixture-secret", "GITHUB_TOKEN": "other-fixture"}),
                  mock.patch.object(adapter.subprocess, "run", side_effect=inspect)):
                self.assertEqual(adapter.implementation_head(head), head)
                self.assertFalse(canary.exists())
                (root / "ignored-extra").write_text("untracked imported material\n")
                with self.assertRaises(Exception):
                    adapter.implementation_head(head)
                self.assertFalse(canary.exists())


if __name__ == "__main__":
    unittest.main()
