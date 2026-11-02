#!/usr/bin/env python3
"""Offline production CLI integration: real reservations and clean Git HEAD.

Run only in the approved isolated environment. Synthetic runtime observations
exercise the handoff protocol; they are not model or execution evidence.
"""

import base64
import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
delivery = load(ROOT / "bin/foreground-delivery.py", "foreground_delivery")
fixtures = load(Path(__file__).with_name("review-collect-test.py"), "collection_fixtures")
c, e = fixtures.collector, fixtures.evidence


class ForegroundTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="foreground-production-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.worktree = self.root / "work" / "candidate"
        self.worktree.mkdir(parents=True)
        self.state_root = self.root / ".orchestrator"
        self.task_path = self.state_root / "tasks" / "fixture" / "task.json"
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("GIT_", "ORCHESTRATOR_", "WORKSPACE_ORCHESTRATOR_"))}
        home = self.root / "home"
        home.mkdir()
        template = self.root / "empty-template"
        template.mkdir()
        self.env.update(WORKSPACE_ORCHESTRATOR_ROOT=str(self.root), HOME=str(home),
                        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        self.git("init", "-q", "-b", "fixture", "--template=" + str(template))
        self.source = b"result = 1\n"
        (self.worktree / "source.py").write_bytes(self.source)
        self.git("add", "source.py")
        self.git("commit", "-qm", "test: offline fixture")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.cli("state", "create", "fixture", "--scope", "fixture:source", "--kind", "implementation",
                 "--repo", "fixture/project", "--branch", "fixture", "--worktree", str(self.worktree),
                 "--base-sha", self.head, "--head-sha", self.head, "--owned-path", "source.py",
                 "--acceptance", "result must be bounded")
        self.cli("state", "claim", "fixture", "--owner", "writer", "--pid", str(os.getpid()))
        self.cli("state", "transition", "fixture", "Reviewing")
        path_key = base64.b64encode(b"source.py").decode()
        packet = {"schema_version": 1, "kind": "committed-local-source", "base": self.head,
                  "head": self.head, "policy_sha256": "d" * 64, "changed_inventory": "COMPLETE",
                  "files": [{"path_base64": path_key, "after": {"kind": "blob", "encoding": "utf-8",
                      "content": self.source.decode(), "bytes": len(self.source), "sha256": c.digest(self.source)}}]}
        self.packet = c.canonical(packet)
        packet_path = self.root / "packet.json"
        packet_path.write_bytes(self.packet)
        self.domain("review-evidence", "begin", {"base": self.head, "head": self.head,
            "packet": c.digest(self.packet), "policy": "d" * 64, "obligations": sorted(e.BASELINE)}, "begin")
        self.domain("review-evidence", "assign", {"generation": 1, "run_id": "run", "reviewer": "reviewer",
            "profile": "e" * 64, "obligations": sorted(e.BASELINE), "adapter": "native-session",
            "session": "ses_fixed"}, "assign")
        admitted = self.domain("review-collect", "admit", {"generation": 1, "run_id": "run",
            "binary_sha256": "f" * 64, "model": "fixture/model", "agent": "reviewer", "cwd": "/review",
            "sources": {"/candidate/source.py": {"path_base64": path_key, "side": "after"}}},
            "admit", "--packet", str(packet_path))
        self.admission_id = admitted["admission_id"]
        self.bundle_path = self.root / "bundle"
        self.bundle_path.mkdir()
        self.set_bundle()
        self.assertNotIn("ORCHESTRATOR_TEST_MODE", self.env)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def git(self, *args):
        process = subprocess.run(["git", "-C", str(self.worktree), "-c", "user.name=Fixture",
            "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
            "-c", "core.hooksPath=/dev/null", *args], env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        return process.stdout

    def cli(self, *args, expected=0):
        # Each invocation is a fresh public CLI process, including after pause.
        process = subprocess.run(["bash", str(ROOT / "run.sh"), *args], cwd=self.root,
            env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, expected, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def record(self):
        return json.loads(self.task_path.read_bytes())

    def store_record(self, record):
        self.task_path.write_bytes(c.canonical(record))

    def domain(self, tool, action, payload, operation, *extra):
        path = self.root / "domain-request.json"
        path.write_bytes(c.canonical({"schema_version": 1, "expected_revision": self.record()["revision"],
                                     "operation_id": operation, "action": action, "payload": payload}))
        return self.cli(tool, "fixture", "--request", str(path), *extra)

    def set_bundle(self, findings=None):
        self.bundle = fixtures.CollectionTests.bundle(self)
        final = json.dumps({"schema_version": 1, "coverage": dict.fromkeys(e.BASELINE, "reviewed"),
                            "findings": findings or [], "dispositions": [], "limitations": ["synthetic claims only"]})
        receipt = c.decode(self.bundle["receipt.json"])
        receipt["final_text"] = final
        events = [json.loads(line) for line in self.bundle["transcript.jsonl"].splitlines()]
        for event in events:
            if event["type"] == "text":
                event["part"]["text"] = final
        self.bundle["transcript.jsonl"] = b"".join(c.canonical(event) for event in events)
        receipt["transcript_sha256"] = c.digest(self.bundle["transcript.jsonl"])
        exported = c.decode(self.bundle["session-export.json"])
        exported["messages"][0]["content"][0]["text"] = final
        self.bundle["session-export.json"] = c.canonical(exported)
        self.bundle["receipt.json"] = c.canonical(receipt)
        for name, data in self.bundle.items():
            (self.bundle_path / name).write_bytes(data)

    def request(self, action, operation=None):
        record = self.record()
        payload = {"admission_id": self.admission_id} if action in {"collect-review", "accept-review"} else {}
        if action == "collect-review":
            payload["artifact_sha256"] = {name: c.digest(data) for name, data in self.bundle.items()}
        return {"schema_version": 1, "task_id": "fixture", "incarnation":
                delivery.dependency("candidate-binding").incarnation(record), "expected_revision": record["revision"],
                "operation_id": operation or action, "action": action, "payload": payload}

    def dispatch(self, request=None, expected=0, bundle=False):
        args = ["foreground-delivery", "fixture"]
        if request is not None:
            path = self.root / "foreground-request.json"
            path.write_bytes(c.canonical(request))
            args += ["--request", str(path)]
        if bundle:
            args += ["--bundle", str(self.bundle_path)]
        before = self.task_path.read_bytes()
        result = self.cli(*args, expected=expected)
        if expected == 3:
            self.assertEqual(result["status"], "UNVERIFIED")
            self.assertEqual(self.task_path.read_bytes(), before)
        return result

    def test_collect_pause_restart_resume_accept_and_exact_replay(self):
        original = self.record()
        collect = self.request("collect-review")
        collected = self.dispatch(collect, bundle=True)
        self.assertEqual(collected["status"], "OBSERVATION_COLLECTED")
        self.assertEqual(self.record()["revision"], original["revision"] + 1)
        self.assertEqual(len(self.record()["foreground_control"]["receipts"]), 1)
        self.assertEqual(self.dispatch()["next_action"], "ACCEPT_COLLECTED_REVIEW")
        pause = self.request("pause")
        paused = self.dispatch(pause)
        self.assertEqual(paused["pause_scope"], "dispatcher-only")
        before = self.task_path.read_bytes()
        self.assertTrue(self.dispatch()["paused"])
        self.assertEqual(self.task_path.read_bytes(), before)
        self.dispatch(self.request("accept-review"), expected=3)
        self.dispatch(self.request("resume"))
        accepted = self.request("accept-review")
        result = self.dispatch(accepted)
        self.assertEqual(result["status"], "CLAIM_ACCEPTED")
        self.assertFalse(result["candidate_ready"])
        self.assertFalse(result["delivery_credit"])
        self.assertEqual(e.assess(self.record())["review_process"], "CLAIMS_COMPLETE")
        before = self.task_path.read_bytes()
        for request, response in ((accepted, result), (collect, collected), (pause, paused)):
            self.assertEqual(self.dispatch(request), response)
            self.assertEqual(self.task_path.read_bytes(), before)
        self.assertFalse(self.dispatch()["paused"])  # Historical pause does not reapply.
        self.assertEqual(self.dispatch()["next_action"], "HUMAN_HANDOFF_REQUIRES_VALIDATION_AND_LIVE_PR_CHECKS")
        for field in ("worker", "leases", "state"):
            self.assertEqual(self.record()[field], original[field])
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_stale_conflicting_incarnation_and_strict_requests(self):
        request = self.request("collect-review")
        self.dispatch(request, bundle=True)
        self.dispatch(self.request("accept-review") | {"expected_revision": 0}, expected=3)
        changed = copy.deepcopy(request)
        changed["payload"]["admission_id"] = "0" * 64
        self.dispatch(changed, expected=3)
        for patch in ({"incarnation": "0" * 64}, {"task_id": "other"}, {"schema_version": True},
                      {"expected_revision": True}, {"expected_revision": 2**53}, {"action": "execute"},
                      {"operation_id": "../bad"}, {"extra": "not allowed"}, {"payload": {"command": "ignored"}}):
            with self.subTest(patch=patch):
                self.dispatch(self.request("pause") | patch, expected=3)
        path = self.root / "invalid.json"
        for raw in (b'{"schema_version":1,"schema_version":1}', b'{"x":NaN}', b"x" * 16_385):
            path.write_bytes(raw)
            before = self.task_path.read_bytes()
            self.cli("foreground-delivery", "fixture", "--request", str(path), expected=3)
            self.assertEqual(self.task_path.read_bytes(), before)

    def test_missing_corrupt_artifacts_and_domain_receipts_refuse_status_replay(self):
        request = self.request("collect-review")
        self.dispatch(request, bundle=True)
        self.dispatch(self.request("accept-review"))
        saved = self.record()
        for table, key in (("runtime_collections", "collect-review"), ("review_protocol", "accept-review")):
            damaged = copy.deepcopy(saved)
            del damaged[table]["operations"][key]
            self.store_record(damaged)
            self.dispatch(expected=3)
            self.dispatch(request, expected=3)
        self.store_record(saved)
        artifact = self.state_root / "review-artifacts" / c.digest(self.bundle["receipt.json"])
        retained = artifact.read_bytes()
        artifact.chmod(0o600)
        artifact.write_bytes(b"corrupt")
        self.dispatch(expected=3)
        self.dispatch(request, expected=3)
        artifact.write_bytes(retained)
        artifact.rename(artifact.with_suffix(".missing"))
        self.dispatch(expected=3)
        self.dispatch(request, expected=3)

    def test_corrupt_control_and_duplicate_task_keys_are_unverified(self):
        self.dispatch(self.request("pause"))
        saved = self.record()
        for change in ("pause", "hash", "reference", "revision", "result", "bool-as-int"):
            record = copy.deepcopy(saved)
            control = record["foreground_control"]
            receipt = control["receipts"]["pause"]
            if change == "pause":
                control["paused"] = False
            elif change == "hash":
                receipt["request_sha256"] = "0" * 64
            elif change == "reference":
                receipt["reference"] = {"table": "fake", "key": "fake"}
            elif change == "revision":
                receipt["result"]["resulting_revision"] += 1
            elif change == "bool-as-int":
                receipt["result"]["delivery_credit"] = 0
            else:
                receipt["result"]["delivery_credit"] = True
            self.store_record(record)
            self.dispatch(expected=3)
        self.task_path.write_bytes(c.canonical(saved).rstrip()[:-1] + b',"foreground_control":{}}\n')
        self.dispatch(expected=3)

    def test_worker_loss_reservation_loss_and_lock_contention(self):
        self.dispatch(self.request("collect-review"), bundle=True)
        request = self.request("accept-review")
        saved = self.record()
        dead = subprocess.Popen([sys.executable, "-I", "-B", "-c", "pass"], env=self.env)
        dead.wait(timeout=10)
        record = copy.deepcopy(saved)
        record["worker"]["pid"] = dead.pid
        self.store_record(record)
        self.dispatch(request, expected=3)
        self.dispatch(expected=3)
        self.store_record(saved)
        reservation = self.state_root / "slots" / f'{saved["leases"]["global_slot"]}.lock' / "owner.json"
        reservation.rename(reservation.with_suffix(".missing"))
        self.dispatch(request, expected=3)
        reservation.with_suffix(".missing").rename(reservation)
        coordinator = delivery.dependency("orchestrator-state")
        with coordinator.CoordinatorLock(self.state_root):
            self.dispatch(request, expected=3)
        # Success with exactly one revision proves no nested coordinator lock.
        self.dispatch(request)
        self.assertEqual(self.record()["revision"], saved["revision"] + 1)

    def test_terminal_and_superseded_history_never_reapply(self):
        request = self.request("collect-review")
        result = self.dispatch(request, bundle=True)
        record = self.record()
        record["review_protocol"]["material_epoch"] += 1
        self.store_record(record)
        self.dispatch(self.request("accept-review"), expected=3)
        self.assertEqual(self.dispatch(request), result)
        self.cli("state", "transition", "fixture", "Cancelled")
        before = self.task_path.read_bytes()
        self.assertEqual(self.dispatch(request), result)
        self.assertEqual(self.task_path.read_bytes(), before)
        for action in ("accept-review", "prepare-correction", "pause", "resume", "collect-review"):
            self.dispatch(self.request(action, "terminal-" + action), expected=3, bundle=action == "collect-review")
        self.assertEqual(self.dispatch()["task_state"], "Cancelled")
        terminal = self.record()
        terminal["state"] = "Done"
        self.store_record(terminal)
        self.dispatch(self.request("pause", "done-pause"), expected=3)
        self.assertEqual(self.dispatch(request), result)

    def test_prepare_only_already_rework_and_replay_keeps_files(self):
        self.dispatch(self.request("prepare-correction"), expected=3)
        self.set_bundle([{"id": "F1", "invariant": "bounded result", "trigger": "call", "path": "source.py:1",
                          "impact": "wrong result", "evidence": "synthetic observation"}])
        self.dispatch(self.request("collect-review"), bundle=True)
        self.dispatch(self.request("accept-review"))
        self.cli("state", "transition", "fixture", "Rework")
        request = self.request("prepare-correction")
        before = self.record()
        response = self.dispatch(request)
        self.assertEqual(response["status"], "CORRECTION_PREPARED")
        self.assertEqual(self.record()["revision"], before["revision"] + 1)
        saved = self.task_path.read_bytes()
        self.assertEqual(self.dispatch(request), response)
        self.assertEqual(self.task_path.read_bytes(), saved)
        self.assertEqual((self.worktree / "source.py").read_bytes(), self.source)
        self.assertEqual(self.record()["state"], "Rework")
        damaged = self.record()
        damaged["repair_protocol"]["corrections"].clear()
        self.store_record(damaged)
        self.dispatch(expected=3)

    def test_one_write_atomic_failure_and_no_same_object_mutation(self):
        request = self.request("collect-review")
        before = self.record()
        saved = copy.deepcopy(before)
        updated, response, changed = delivery.dispatch(before, request, self.state_root, self.bundle_path)
        self.assertTrue(changed)
        self.assertEqual(before, saved)
        self.assertIsNot(updated, before)
        self.assertIn("collect-review", updated["foreground_control"]["receipts"])
        self.assertIn("collect-review", updated["runtime_collections"]["operations"])
        self.assertEqual(response["resulting_revision"], before["revision"] + 1)
        coordinator = delivery.dependency("orchestrator-state")
        original_dependency = delivery.dependency
        request_path = self.root / "atomic-request.json"
        request_path.write_bytes(c.canonical(request))
        argv = ["foreground-delivery", "fixture", "--request", str(request_path), "--bundle", str(self.bundle_path)]
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(sys, "argv", argv), \
                mock.patch.object(delivery, "dependency", side_effect=lambda name:
                    coordinator if name == "orchestrator-state" else original_dependency(name)):
            original_atomic = coordinator.atomic_json
            def fail_task(path, data):
                if path == self.task_path:
                    raise OSError("injected failure before task replacement")
                original_atomic(path, data)
            with mock.patch.object(coordinator, "atomic_json", side_effect=fail_task), \
                    mock.patch.object(coordinator, "write_task", wraps=coordinator.write_task) as writes:
                self.assertEqual(delivery.main(), 3)
                self.assertEqual(writes.call_count, 1)
            self.assertEqual(self.record(), saved)
            with mock.patch.object(coordinator, "write_task", wraps=coordinator.write_task) as writes:
                self.assertEqual(delivery.main(), 0)
                self.assertEqual(writes.call_count, 1)
        self.assertEqual(self.record()["revision"], saved["revision"] + 1)
        self.assertEqual(self.dispatch(request), response)

    def test_bundle_digest_mismatch_and_external_operation_collision(self):
        request = self.request("collect-review")
        request["payload"]["artifact_sha256"]["receipt.json"] = "0" * 64
        self.dispatch(request, expected=3, bundle=True)
        self.dispatch(self.request("collect-review"), expected=3)
        self.dispatch(self.request("pause"), expected=3, bundle=True)
        self.dispatch(self.request("collect-review", "begin"), expected=3, bundle=True)

    def test_receipt_budget_keeps_exact_replay_and_read_only_status(self):
        record = self.record()
        first, first_result = None, None
        for index in range(delivery.MAX_RECEIPTS):
            request = self.request("pause", f"pause-{index}")
            request["expected_revision"] = record["revision"]
            record, result, changed = delivery.dispatch(record, request, self.state_root)
            self.assertTrue(changed)
            record["revision"] += 1
            if first is None:
                first, first_result = request, result
        self.store_record(record)
        self.dispatch(self.request("resume"), expected=3)
        self.assertEqual(self.dispatch(first), first_result)
        self.assertEqual(self.dispatch()["receipt_count"], delivery.MAX_RECEIPTS)
        record["foreground_control"]["receipts"]["overflow"] = copy.deepcopy(
            record["foreground_control"]["receipts"]["pause-0"])
        self.store_record(record)
        self.dispatch(expected=3)

    def test_unfinished_transition_and_wrong_worker_identity_refused(self):
        saved = self.record()
        record = copy.deepcopy(saved)
        record["transition_intent"] = "Cancelled"
        self.store_record(record)
        self.dispatch(expected=3)
        self.dispatch(self.request("pause"), expected=3)
        for field in ("owner", "hostname", "process_start"):
            record = copy.deepcopy(saved)
            record["worker"][field] = "different"
            self.store_record(record)
            self.dispatch(expected=3)

    def test_status_request_is_read_only_and_current_revision_bound(self):
        request = self.request("status")
        before = self.task_path.read_bytes()
        result = self.dispatch(request)
        self.assertEqual(result["status"], "FOREGROUND_STATUS")
        self.assertEqual(self.task_path.read_bytes(), before)
        self.dispatch(self.request("pause"))
        self.dispatch(request, expected=3)


if __name__ == "__main__":
    unittest.main()
