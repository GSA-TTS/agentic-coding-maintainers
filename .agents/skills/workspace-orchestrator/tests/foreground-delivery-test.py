#!/usr/bin/env python3
"""Offline production CLI integration: real reservations and clean Git HEAD.

Run only in the approved isolated environment. Synthetic runtime observations
exercise the handoff protocol; they are not model or execution evidence.
"""

import base64
import copy
import contextlib
import errno
import importlib.util
import io
import json
import os
import shlex
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
diagnostic = load(Path(__file__).with_name("foreground-cli-diagnostic.py"), "foreground_diagnostic")
delivery = load(ROOT / "bin/foreground-delivery.py", "foreground_delivery")
fixtures = load(Path(__file__).with_name("review-collect-test.py"), "collection_fixtures")
c, e = fixtures.collector, fixtures.evidence


class ForegroundTests(unittest.TestCase):
    def setUp(self):
        # Direct helper calls reload installed modules too, especially when filling
        # receipt history. Reuse only compiled bytes for this one test; unittest
        # restores the loader after all cleanups, even when setUp itself fails.
        self.enterContext(diagnostic.compiled_installed_sources())
        # Check the real installed package, not just the disposable task checkout.
        # On a read-only mount cache writes fail silently; run this fixture from a
        # writable sandbox copy to exercise the subprocess pollution regression.
        self.package_inventory = {path.relative_to(ROOT) for path in ROOT.rglob("*")}
        self.addCleanup(self.assert_package_inventory_unchanged)
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
        # run.sh state -> orchestrator-state.sh launches a fresh Python without
        # -B. The parent interpreter's -B is not inherited by that subprocess.
        self.env.update(PYTHONDONTWRITEBYTECODE="1",
                        WORKSPACE_ORCHESTRATOR_ROOT=str(self.root), HOME=str(home),
                        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        self.git("init", "-q", "-b", "fixture", "--template=" + str(template))
        self.source = b"result = 1\n"
        (self.worktree / "source.py").write_bytes(self.source)
        (self.worktree / "second.py").write_bytes(self.source)
        self.git("add", "source.py", "second.py")
        self.git("commit", "-qm", "test: offline fixture")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.cli("state", "create", "fixture", "--scope", "fixture:source", "--kind", "implementation",
                 "--repo", "fixture/project", "--branch", "fixture", "--worktree", str(self.worktree),
                 "--base-sha", self.head, "--head-sha", self.head, "--owned-path", "source.py",
                  "--owned-path", "second.py", "--acceptance", "result must be bounded")
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

    def assert_package_inventory_unchanged(self):
        self.assertEqual({path.relative_to(ROOT) for path in ROOT.rglob("*")}, self.package_inventory,
                         "fixture subprocess changed the installed canonical package inventory")

    def git(self, *args):
        process = subprocess.run(["git", "-C", str(self.worktree), "-c", "user.name=Fixture",
            "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
            "-c", "core.hooksPath=/dev/null", *args], env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        return process.stdout

    def cli(self, *args, expected=0):
        # Each invocation is a fresh public CLI process, including after pause.
        env = self.env
        if args[0] == "foreground-delivery":
            # Test-local interpreter shim: still invoke run.sh, exactly once.
            # The observer captures main's suppressed exception in that process;
            # it never replays mutation or changes the expected return code.
            directory = self.root / "diagnostic-bin"
            directory.mkdir(exist_ok=True)
            shim = directory / "python3"
            launcher = Path(__file__).with_name("foreground-cli-diagnostic.py")
            shim.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable)
                            + " -I -B " + shlex.quote(str(launcher))
                            + " " + str(expected) + ' "$@"\n')
            shim.chmod(0o700)
            env = {**self.env, "PATH": str(directory) + os.pathsep + self.env["PATH"]}
        process = subprocess.run(["bash", str(ROOT / "run.sh"), *args], cwd=self.root,
            env=env, capture_output=True, text=True, timeout=20)
        if process.returncode != expected:
            # Only structural, bounded observer output is permitted in failures.
            prefix = "FOREGROUND_FIXTURE_DIAGNOSTIC "
            diagnostic = next((line for line in process.stderr.splitlines()
                               if line.startswith(prefix) and len(line) <= 3100),
                              "CLI diagnostic unavailable; output withheld")
            self.assertEqual(process.returncode, expected, diagnostic)
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
        if action == "admit-owner-proposal":
            payload = {"correction_id": self.correction_id, "session": "ses_owner", "model": "fixture/model",
                       "agent": "owner", "binary_sha256": "a" * 64, "profile_sha256": "b" * 64,
                       "cwd": "/review", "sources": {"/candidate/source.py": "source.py"}}
        if action == "collect-owner-proposal":
            payload = {"admission_id": self.proposal_id}
        if action == "apply-owner-proposal":
            payload = {"admission_id": self.proposal_id}
        if action == "reconcile-owner-proposal":
            payload = {"apply_operation_id": "apply-owner-proposal"}
        if action in delivery.COLLECT_ACTIONS:
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

    def prepare_owner(self):
        self.set_bundle([{"id": "F1", "invariant": "bounded result", "trigger": "call", "path": "source.py:1",
                          "impact": "wrong result", "evidence": "synthetic observation"}])
        self.dispatch(self.request("collect-review"), bundle=True)
        self.dispatch(self.request("accept-review"))
        self.assertEqual(self.dispatch()["next_action"], "OWNER_REWORK_ADMISSION_REQUIRED")
        self.cli("state", "transition", "fixture", "Rework")
        self.assertEqual(self.dispatch()["next_action"], "PREPARE_CORRECTION")
        prepared = self.dispatch(self.request("prepare-correction"))
        self.correction_id = prepared["domain_result"]["correction_id"]
        self.assertEqual(self.dispatch()["next_action"], "ORIGINAL_OWNER_RECLAIM")
        self.assertIsNone(self.record()["worker"])
        self.dispatch(self.request("admit-owner-proposal"), expected=3)
        self.cli("state", "claim", "fixture", "--owner", "writer", "--pid", str(os.getpid()))
        self.assertEqual(self.dispatch()["next_action"], "ORIGINAL_OWNER_IMPLEMENTING_REQUIRED")
        self.dispatch(self.request("admit-owner-proposal"), expected=3)
        self.cli("state", "transition", "fixture", "Implementing")
        self.assertEqual(self.dispatch()["next_action"], "ADMIT_OWNER_PROPOSAL")

    def owner_bundle(self, unable=False):
        admitted = self.record()["repair_proposals"][self.proposal_id]["admission"]
        session = admitted["session"]
        final = json.dumps({"schema_version": 1, "status": "unable" if unable else "proposed",
                           "replacements": [] if unable else [{"path": path, "content": "result = 2\n"}
                               for path in admitted["sources"].values()],
                           "limitations": ["synthetic owner claims only"]})
        events = [{"type": "tool_use", "sessionID": session, "part": {"tool": "read", "state": {
            "status": "completed", "input": {"path": "/candidate/source.py"},
            "output": "Read file /candidate/source.py, lines 1-1\n1: result = 1"}}},
            {"type": "text", "sessionID": session, "part": {"text": final}},
            {"type": "step_finish", "sessionID": session, "part": {"reason": "stop", "tokens": {"input": 100, "output": 50}}}]
        if "/candidate/second.py" in admitted["sources"]:
            second = copy.deepcopy(events[0])
            second["part"]["state"]["input"]["path"] = "/candidate/second.py"
            second["part"]["state"]["output"] = "Read file /candidate/second.py, lines 1-1\n1: result = 1"
            events.insert(1, second)
        transcript = b"".join(c.canonical(event) for event in events)
        exported = c.canonical({"info": {"id": session, "outcome": "succeeded", "agent": "owner",
            "model": {"providerID": "fixture", "id": "model"}, "tokens": {"input": 100, "output": 50}},
            "messages": [{"type": "assistant", "finish": "stop", "content": [{"type": "text", "text": final}]}]})
        receipt = {name: admitted[name] for name in ("model", "agent", "binary_sha256", "profile_sha256", "source_sha256")}
        receipt.update(role="owner-proposal", context_sha256=c.digest(c.canonical(admitted["context"])),
                       sessions=[session], status="REVIEW_OBSERVED", candidate_ready=False, execution_credit=False,
                       transcript_sha256=c.digest(transcript), stderr_sha256=c.digest(b""), returncode=0,
                       export_returncode=0, export_failure=None, final_text=final)
        self.bundle = {"receipt.json": c.canonical(receipt), "transcript.jsonl": transcript,
                       "session-export.json": exported, "stderr.txt": b"", "export-stderr.txt": b""}
        self.write_bundle()

    def write_bundle(self):
        for name, data in self.bundle.items():
            (self.bundle_path / name).write_bytes(data)

    def admit_owner(self):
        request = self.request("admit-owner-proposal")
        result = self.dispatch(request)
        self.proposal_id = result["domain_result"]["admission_id"]
        self.owner_bundle()
        return request, result

    def assert_candidate_unchanged(self, before):
        self.assertEqual((self.worktree / "source.py").read_bytes(), self.source)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.head)
        for field in ("worker", "leases", "state", "head_sha", "base_sha"):
            self.assertEqual(self.record()[field], before[field])
        self.assertEqual(self.record()["repair_protocol"]["operations"], {})

    def test_owner_routing_from_review_preserves_v1_receipts_and_candidate(self):
        self.prepare_owner()
        before = self.record()
        old_receipts = copy.deepcopy(before["foreground_control"]["receipts"])
        admitted_request, admitted = self.admit_owner()
        self.assertEqual(admitted["status"], "PROPOSAL_ADMITTED")
        self.assertEqual(self.record()["revision"], before["revision"] + 1)
        self.assertEqual(self.dispatch()["next_action"], "COLLECT_OWNER_PROPOSAL")
        collect = self.request("collect-owner-proposal")
        collected = self.dispatch(collect, bundle=True)
        self.assertEqual(collected["status"], "PROPOSAL_COLLECTED")
        self.assertEqual(self.record()["revision"], before["revision"] + 2)
        sha = collected["domain_result"]["bundle_sha256"]
        raw = (self.state_root / "review-artifacts" / sha).read_bytes()
        self.assertEqual(c.digest(raw), sha)
        self.assertEqual(c.decode(raw), {"schema_version": 1, "correction_id": self.correction_id,
            "replacements": [{"path": "source.py", "before_sha256": c.digest(self.source),
                              "after_base64": base64.b64encode(b"result = 2\n").decode()}]})
        self.assertEqual(self.dispatch()["next_action"], "COLLECTED_OWNER_BUNDLE_REQUIRES_GUARDED_APPLY")
        self.assertEqual(self.record()["foreground_control"]["schema_version"], 1)
        for operation, receipt in old_receipts.items():
            self.assertEqual(self.record()["foreground_control"]["receipts"][operation], receipt)
            self.assertEqual(self.dispatch(receipt["request"]), receipt["result"])
        saved = self.task_path.read_bytes()
        for request, response in ((admitted_request, admitted), (collect, collected)):
            self.assertEqual(self.dispatch(request), response)
            self.assertEqual(self.task_path.read_bytes(), saved)
            self.assertEqual(self.record()["foreground_control"]["receipts"][request["operation_id"]]["reference"],
                             {"table": "repair_proposals", "key": self.proposal_id})
            for flag in ("candidate_ready", "execution_credit", "delivery_credit", "current_applicability"):
                self.assertIs(response[flag], False)
        self.assert_candidate_unchanged(before)

    def test_latest_owner_admission_and_terminal_history_do_not_revive_old_bundle(self):
        self.prepare_owner()
        admit, admitted = self.admit_owner()
        collect = self.request("collect-owner-proposal")
        collected = self.dispatch(collect, bundle=True)
        next_request = self.request("admit-owner-proposal", "second-owner-admission")
        next_request["payload"]["session"] = "ses_second_owner"
        self.dispatch(next_request)
        self.assertEqual(self.dispatch()["next_action"], "COLLECT_OWNER_PROPOSAL")
        self.assertEqual(self.dispatch(collect), collected)
        self.assertEqual(self.dispatch()["next_action"], "COLLECT_OWNER_PROPOSAL")
        self.cli("state", "transition", "fixture", "Cancelled")
        before = self.task_path.read_bytes()
        self.assertEqual(self.dispatch(admit), admitted)
        self.assertEqual(self.dispatch(collect), collected)
        self.assertEqual(self.task_path.read_bytes(), before)
        self.assertEqual(self.dispatch()["next_action"], "TERMINAL_NO_DISPATCH")
        self.dispatch(self.request("admit-owner-proposal", "terminal-owner-admit"), expected=3)
        self.dispatch(self.request("collect-owner-proposal", "terminal-owner-collect"), expected=3, bundle=True)

    def test_not_applied_same_head_new_generation_clears_historical_boundary(self):
        self.require_repair_metadata()
        self.prepare_owner()
        self.admit_owner()
        collected = self.dispatch(self.request("collect-owner-proposal"), bundle=True)
        sha = collected["domain_result"]["bundle_sha256"]
        raw = (self.state_root / "review-artifacts" / sha).read_bytes()
        request = {"schema_version": 1, "operation_id": "interrupted-repair",
                   "expected_revision": self.record()["revision"],
                   "correction_id": self.correction_id, "bundle_sha256": sha}
        repair = delivery.dependency("repair-apply")
        coordinator = delivery.dependency("orchestrator-state")
        # Inject only the interruption. The production API publishes the bundle
        # and durable APPLYING fence under the real coordinator lock/reservations.
        with mock.patch.dict(os.environ, self.env, clear=True), \
                coordinator.CoordinatorLock(self.state_root), \
                mock.patch.object(repair, "replace_one", side_effect=OSError("before first write")):
            record = coordinator.read_task(self.state_root, "fixture")
            coordinator.verify_reservations(self.state_root, record)
            with self.assertRaisesRegex(OSError, "before first write"):
                repair.apply_repair(record, self.state_root, request, raw,
                                    lambda value: coordinator.write_task(self.state_root, value))
        self.assertEqual(self.record()["repair_protocol"]["operations"]["interrupted-repair"]["phase"], "APPLYING")
        self.assertEqual(self.dispatch()["next_action"], "REPAIR_RECONCILIATION_REQUIRED")
        result = self.cli("repair-apply", "fixture", "reconcile", "--operation-id", "interrupted-repair")
        self.assertEqual(result["status"], "NOT_APPLIED_OBSERVED")
        self.assertEqual(self.dispatch()["next_action"], "REPAIR_RECONCILIATION_REQUIRED")
        generation = self.record()["review_protocol"]["generations"][-1]
        self.cli("state", "transition", "fixture", "Reviewing")
        begun = self.domain("review-evidence", "begin",
                            {name: generation[name] for name in ("base", "head", "packet", "policy", "obligations")},
                            "same-head-new-generation")
        self.assertEqual(begun["generation"], 2)
        self.assertEqual(self.record()["head_sha"], self.head)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.head)
        self.assertEqual((self.worktree / "source.py").read_bytes(), self.source)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.dispatch()["next_action"], "OWNER_REWORK_ADMISSION_REQUIRED")
        # A numerically newer but stale generation must not clear the boundary.
        saved = self.record()
        stale = copy.deepcopy(saved)
        stale["review_protocol"]["material_epoch"] += 1
        self.store_record(stale)
        self.assertEqual(self.dispatch()["next_action"], "REPAIR_RECONCILIATION_REQUIRED")
        self.store_record(saved)
        # Phase-specific projection guard: even a newer current generation at
        # this head cannot clear APPLIED_UNREVIEWED. This projection-only copy
        # is not persisted or presented as an admitted review generation.
        applied = copy.deepcopy(saved)
        applied["repair_protocol"]["operations"]["interrupted-repair"]["phase"] = "APPLIED_UNREVIEWED"
        self.assertEqual(delivery.owner_boundary(applied), "REPAIRED_CANDIDATE_REQUIRES_COMMIT_EXECUTION_AND_REVIEW")
        applied["head_sha"] = "1" * 40
        applied["review_protocol"]["generations"][-1]["head"] = applied["head_sha"]
        self.assertIsNone(delivery.owner_boundary(applied))

    def test_owner_pause_exact_replay_and_unable_outcome(self):
        self.prepare_owner()
        before = self.record()
        self.dispatch(self.request("pause", "pause-admission"))
        self.dispatch(self.request("admit-owner-proposal"), expected=3)
        self.dispatch(self.request("resume", "resume-admission"))
        request, admitted = self.admit_owner()
        self.owner_bundle(unable=True)
        self.dispatch(self.request("pause", "pause-collection"))
        self.assertEqual(self.dispatch(request), admitted)
        self.dispatch(self.request("collect-owner-proposal"), expected=3, bundle=True)
        self.dispatch(self.request("resume", "resume-collection"))
        collect = self.request("collect-owner-proposal")
        result = self.dispatch(collect, bundle=True)
        self.assertEqual(result["status"], "UNABLE_OBSERVED")
        self.assertIsNone(result["domain_result"]["bundle_sha256"])
        self.assertFalse(result["candidate_ready"])
        self.assertEqual(self.dispatch()["next_action"], "OWNER_PROPOSAL_UNABLE_REQUIRES_OPERATOR")
        self.dispatch(self.request("pause", "pause-after-unable"))
        saved = self.task_path.read_bytes()
        self.assertEqual(self.dispatch(collect), result)
        self.assertEqual(self.dispatch(request), admitted)
        self.assertEqual(self.task_path.read_bytes(), saved)
        self.assertEqual(self.dispatch()["next_action"], "RESUME_FOREGROUND")
        self.assert_candidate_unchanged(before)
        artifact = self.state_root / "review-artifacts" / c.digest(self.bundle["receipt.json"])
        artifact.rename(artifact.with_suffix(".missing"))
        self.dispatch(expected=3)
        self.dispatch(collect, expected=3)
        self.dispatch(request, expected=3)

    def test_owner_missing_stale_wrong_role_and_source_refused(self):
        self.correction_id = "0" * 64
        self.dispatch(self.request("admit-owner-proposal"), expected=3)
        self.prepare_owner()
        before = self.record()
        request = self.request("admit-owner-proposal")
        for payload in ({"correction_id": "0" * 64}, {"session": "ses_fixed"},
                        {"sources": {}}, {"sources": {"/candidate/other.py": "other.py"}},
                        {"sources": {"/candidate/source.py": "../source.py"}}, {"role": "reviewer"}):
            with self.subTest(payload=payload):
                changed = copy.deepcopy(request)
                changed["payload"].update(payload)
                self.dispatch(changed, expected=3)
        self.dispatch(request | {"expected_revision": request["expected_revision"] - 1}, expected=3)
        self.dispatch(request, expected=3, bundle=True)
        admitted_request, admitted = self.admit_owner()
        self.dispatch(self.request("pause", admitted_request["operation_id"]), expected=3)
        changed = copy.deepcopy(admitted_request)
        changed["payload"]["session"] = "ses_changed"
        self.dispatch(changed, expected=3)
        collect = self.request("collect-owner-proposal")
        self.dispatch(collect, expected=3)
        self.dispatch(collect | {"expected_revision": collect["expected_revision"] - 1}, expected=3, bundle=True)
        changed = copy.deepcopy(collect)
        changed["payload"]["admission_id"] = "0" * 64
        self.dispatch(changed, expected=3, bundle=True)
        changed = copy.deepcopy(collect)
        changed["payload"]["artifact_sha256"]["receipt.json"] = "0" * 64
        self.dispatch(changed, expected=3, bundle=True)
        saved_bundle = copy.deepcopy(self.bundle)
        for field, value in (("role", "review"), ("sessions", ["ses_fixed"]), ("context_sha256", "0" * 64),
                             ("source_sha256", {"/candidate/source.py": "0" * 64})):
            self.bundle = copy.deepcopy(saved_bundle)
            receipt = c.decode(self.bundle["receipt.json"])
            receipt[field] = value
            self.bundle["receipt.json"] = c.canonical(receipt)
            self.write_bundle()
            self.dispatch(self.request("collect-owner-proposal"), expected=3, bundle=True)
        self.bundle = saved_bundle
        self.write_bundle()
        (self.worktree / "source.py").write_bytes(b"result = 9\n")
        self.dispatch(collect, expected=3, bundle=True)
        self.assertEqual(self.dispatch()["next_action"], "OWNER_PROPOSAL_CONTEXT_RECONCILIATION_REQUIRED")
        # Replay acknowledges the original admission, not these dirty bytes.
        self.assertEqual(self.dispatch(admitted_request), admitted)
        (self.worktree / "source.py").write_bytes(self.source)
        missing = self.bundle_path / "session-export.json"
        missing.rename(missing.with_suffix(".missing"))
        self.dispatch(collect, expected=3, bundle=True)
        missing.with_suffix(".missing").rename(missing)
        self.dispatch(collect, bundle=True)
        self.assert_candidate_unchanged(before)

    def test_owner_retained_domain_and_artifact_loss_refuse_status_and_replay(self):
        self.prepare_owner()
        admit, _ = self.admit_owner()
        collect = self.request("collect-owner-proposal")
        result = self.dispatch(collect, bundle=True)
        saved = self.record()
        for damage in ("ledger", "admission", "collection", "request", "reference", "result"):
            record = copy.deepcopy(saved)
            if damage == "ledger":
                del record["repair_proposals"]
            elif damage == "admission":
                del record["repair_proposals"][self.proposal_id]
            elif damage == "collection":
                record["repair_proposals"][self.proposal_id]["collection"] = None
            elif damage == "request":
                item = record["repair_proposals"][self.proposal_id]["collection"]
                item["request"]["operation_id"] = "different"
                item["request_sha256"] = c.digest(c.canonical(item["request"]))
            elif damage == "reference":
                record["foreground_control"]["receipts"][collect["operation_id"]]["reference"]["key"] = "0" * 64
            else:
                record["foreground_control"]["receipts"][collect["operation_id"]]["result"]["domain_result"]["status"] = "UNABLE_OBSERVED"
            self.store_record(record)
            self.dispatch(expected=3)
            self.dispatch(admit, expected=3)
            self.dispatch(collect, expected=3)
        self.store_record(saved)
        for sha in (result["domain_result"]["bundle_sha256"], c.digest(self.bundle["receipt.json"]),
                    c.digest(self.bundle["transcript.jsonl"])):
            artifact = self.state_root / "review-artifacts" / sha
            raw = artifact.read_bytes()
            artifact.chmod(0o600)
            artifact.write_bytes(b"corrupt")
            self.dispatch(expected=3)
            self.dispatch(collect, expected=3)
            artifact.write_bytes(raw)
            missing = artifact.with_suffix(".missing")
            artifact.rename(missing)
            self.dispatch(expected=3)
            self.dispatch(admit, expected=3)
            missing.rename(artifact)
        self.assertEqual(self.dispatch(collect), result)

    def test_owner_external_operation_collision_and_stale_context(self):
        self.prepare_owner()
        request = self.request("admit-owner-proposal", "external-admission")
        result = self.domain("repair-proposal", "admit", request["payload"], request["operation_id"])
        self.proposal_id = result["admission_id"]
        self.owner_bundle()
        self.assertEqual(self.dispatch()["next_action"], "COLLECT_OWNER_PROPOSAL")
        self.dispatch(request, expected=3)
        self.dispatch(self.request("pause", "external-admission"), expected=3)
        collect = self.request("collect-owner-proposal", "external-collection")
        self.domain("repair-proposal", "collect", collect["payload"], collect["operation_id"],
                    "--bundle", str(self.bundle_path))
        self.dispatch(collect, expected=3)
        self.dispatch(self.request("pause", "external-collection"), expected=3)
        self.assertEqual(self.dispatch()["next_action"], "COLLECTED_OWNER_BUNDLE_REQUIRES_GUARDED_APPLY")
        saved = self.record()
        for field in ("material_epoch", "head_sha", "owner"):
            record = copy.deepcopy(saved)
            if field == "material_epoch":
                record["review_protocol"][field] += 1
            elif field == "head_sha":
                record[field] = "0" * 40
            else:
                record["owner"] = "other-owner"
            self.store_record(record)
            self.dispatch(self.request("admit-owner-proposal", "stale-admit"), expected=3)
            if field == "owner":
                self.dispatch(expected=3)  # Worker identity remains bound to writer.
            else:
                self.assertEqual(self.dispatch()["next_action"], "OWNER_PROPOSAL_CONTEXT_RECONCILIATION_REQUIRED")
        self.store_record(saved)

    def test_owner_worker_and_reservation_guards_still_apply(self):
        self.prepare_owner()
        admit, _ = self.admit_owner()
        collect = self.request("collect-owner-proposal")
        saved = self.record()
        for field in ("owner", "hostname", "process_start"):
            record = copy.deepcopy(saved)
            record["worker"][field] = "different"
            self.store_record(record)
            self.dispatch(expected=3)
            self.dispatch(admit, expected=3)
            self.dispatch(collect, expected=3, bundle=True)
        self.store_record(saved)
        reservation = self.state_root / "implementation" / f'{saved["leases"]["implementation_lane"]}.lock' / "owner.json"
        reservation.rename(reservation.with_suffix(".missing"))
        self.dispatch(expected=3)
        self.dispatch(collect, expected=3, bundle=True)
        reservation.with_suffix(".missing").rename(reservation)
        self.dispatch(collect, bundle=True)
        self.assert_candidate_unchanged(saved)

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
        self.assertEqual(self.dispatch()["next_action"], "FRESH_REVIEW_GENERATION_REQUIRED")
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

    def test_blocked_pause_requires_readmission_not_resume(self):
        self.dispatch(self.request("pause"))
        self.cli("state", "transition", "fixture", "Blocked", "--reason", "operator pause of task")
        self.assertEqual(self.dispatch()["next_action"], "COORDINATOR_READMISSION_REQUIRED")
        self.dispatch(self.request("resume"), expected=3)

    def test_missing_initialized_history_never_clears_pause(self):
        self.dispatch(self.request("pause"))
        record = self.record()
        del record["foreground_control"]
        self.store_record(record)
        self.dispatch(expected=3)
        self.dispatch(self.request("collect-review"), expected=3, bundle=True)
        record.pop("foreground_initialized")
        record["foreground_initialized"] = None
        self.store_record(record)
        self.dispatch(expected=3)

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

    def collected_two_file_proposal(self):
        self.prepare_owner()
        request = self.request("admit-owner-proposal")
        request["payload"]["sources"]["/candidate/second.py"] = "second.py"
        self.proposal_id = self.dispatch(request)["domain_result"]["admission_id"]
        self.owner_bundle()
        self.dispatch(self.request("collect-owner-proposal"), bundle=True)
        return self.request("apply-owner-proposal")

    def repair_metadata_unavailable(self):
        """Measure the host independently; never skip on a production refusal."""
        if not hasattr(os, "listxattr"):
            return "host Python lacks fd xattr inspection; successful repair unmeasured"
        for name in ("source.py", "second.py"):
            with (self.worktree / name).open("rb") as handle:
                try:
                    attrs = os.listxattr(handle.fileno())
                except OSError as exc:
                    if exc.errno in {errno.ENOTSUP, errno.EOPNOTSUPP}:
                        return "fixture filesystem lacks xattr inspection; successful repair unmeasured"
                    raise
                if attrs:
                    return "fixture has extended metadata; successful ordinary-file repair unmeasured"
        return None

    def require_repair_metadata(self):
        reason = self.repair_metadata_unavailable()
        if reason:
            self.skipTest(reason)

    def injected_apply(self, request, failure=None):
        """Only fault seams are mocked; main, locks, validators and writes are real."""
        if request["action"] == "apply-owner-proposal":
            self.require_repair_metadata()
        bridge = delivery.dependency("foreground-repair")
        repair = bridge.load("repair-apply")
        coordinator = delivery.dependency("orchestrator-state")
        original_dependency, original_load = delivery.dependency, bridge.load
        path = self.root / "injected-request.json"
        path.write_bytes(c.canonical(request))
        argv = ["foreground-delivery", "fixture", "--request", str(path)]
        replacements, persists = [], []
        original_replace, original_write = repair.replace_one, coordinator.write_task
        def replace(root, entry, mode):
            if failure == "before-first" or (failure == "between-files" and replacements):
                raise OSError("injected target interruption")
            original_replace(root, entry, mode)
            replacements.append(entry["path"])
        def write(root, value):
            persists.append(copy.deepcopy(value))
            if failure == "first-persist" and len(persists) == 1:
                raise OSError("injected intent persistence failure")
            if failure == "after-writes" and len(persists) == 2:
                raise OSError("injected final persistence failure")
            original_write(root, value)
        output = io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(sys, "argv", argv), \
                mock.patch.object(delivery, "dependency", side_effect=lambda name:
                    bridge if name == "foreground-repair" else coordinator if name == "orchestrator-state"
                    else original_dependency(name)), \
                mock.patch.object(bridge, "load", side_effect=lambda name:
                    repair if name == "repair-apply" else original_load(name)), \
                mock.patch.object(repair, "replace_one", side_effect=replace), \
                mock.patch.object(coordinator, "write_task", side_effect=write), \
                contextlib.redirect_stdout(output):
            code = delivery.main()
        self.assertEqual(code, 3 if failure else 0, output.getvalue())
        return replacements, persists, json.loads(output.getvalue())

    def repair_cli(self, request, expected=0):
        if expected == 0 and request["action"] == "apply-owner-proposal":
            self.require_repair_metadata()
        path = self.root / "repair-foreground-request.json"
        path.write_bytes(c.canonical(request))
        return self.cli("foreground-delivery", "fixture", "--request", str(path), expected=expected)

    def target_bytes(self):
        return [(self.worktree / name).read_bytes() for name in ("source.py", "second.py")]

    def test_unavailable_host_metadata_refuses_public_repair_without_writes(self):
        if self.repair_metadata_unavailable() is None:
            self.skipTest("host supports fixture metadata inspection; refusal exercised on unsupported hosts")
        request = self.collected_two_file_proposal()
        before = self.task_path.read_bytes(), self.target_bytes()
        result = self.repair_cli(request, expected=3)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual((self.task_path.read_bytes(), self.target_bytes()), before)

    def test_apply_two_files_public_cli_pause_replay_and_fresh_head(self):
        request = self.collected_two_file_proposal()
        before = self.record()
        self.dispatch(self.request("pause", "pause-before-apply"))
        self.dispatch(self.request("apply-owner-proposal"), expected=3)
        self.dispatch(self.request("resume", "resume-before-apply"))
        request = self.request("apply-owner-proposal")
        revision = self.record()["revision"]
        result = self.repair_cli(request)
        self.assertEqual(result["status"], "APPLIED_UNREVIEWED")
        self.assertEqual(result["resulting_revision"], revision + 2)
        self.assertEqual(self.record()["revision"], revision + 2)
        self.assertEqual(self.target_bytes(), [b"result = 2\n"] * 2)
        self.assertEqual(self.dispatch()["next_action"], "REPAIRED_CANDIDATE_REQUIRES_COMMIT_EXECUTION_AND_REVIEW")
        for name in ("worker", "leases", "state", "head_sha"):
            self.assertEqual(self.record()[name], before[name])
        self.assertEqual(self.record()["foreground_control"]["receipts"] | before["foreground_control"]["receipts"],
                         self.record()["foreground_control"]["receipts"])
        self.dispatch(self.request("pause", "pause-after-apply"))
        saved = self.task_path.read_bytes()
        stats = [(self.worktree / name).stat().st_ino for name in ("source.py", "second.py")]
        self.assertEqual(self.repair_cli(request), result)
        self.assertEqual(self.task_path.read_bytes(), saved)
        self.assertEqual(stats, [(self.worktree / name).stat().st_ino for name in ("source.py", "second.py")])
        reconcile = self.request("reconcile-owner-proposal")
        reconciled = self.repair_cli(reconcile)
        self.assertEqual(reconciled["status"], "APPLIED_UNREVIEWED")
        saved = self.task_path.read_bytes()
        self.assertEqual(self.repair_cli(reconcile), reconciled)
        self.assertEqual(self.repair_cli(request), result)
        self.assertEqual(self.task_path.read_bytes(), saved)
        coordinator = delivery.dependency("orchestrator-state")
        with self.assertRaisesRegex(coordinator.UnknownError, "new committed head"):
            coordinator.require_repair_settled(self.record(), new_review=True, root=self.state_root)
        self.dispatch(self.request("resume", "resume-after-apply"))
        self.cli("state", "transition", "fixture", "Reviewing")
        generation = self.record()["review_protocol"]["generations"][-1]
        path = self.root / "fresh-head-required.json"
        path.write_bytes(c.canonical({"schema_version": 1, "operation_id": "same-head-review",
            "expected_revision": self.record()["revision"], "action": "begin",
            "payload": {name: generation[name] for name in ("base", "head", "packet", "policy", "obligations")}}))
        self.cli("review-evidence", "fixture", "--request", str(path), expected=3)

    def test_apply_exactly_two_persists_link_before_targets_and_final_receipt(self):
        request = self.collected_two_file_proposal()
        replacements, writes, result = self.injected_apply(request)
        self.assertEqual(len(replacements), 2)
        self.assertEqual(len(writes), 2)
        app = writes[0]["foreground_repairs"]["applications"][request["operation_id"]]
        self.assertIsNone(app["final"])
        self.assertEqual(writes[0]["repair_protocol"]["operations"][app["repair_operation_id"]]["phase"], "APPLYING")
        self.assertEqual(writes[1]["foreground_repairs"]["applications"][request["operation_id"]]["final"]["result"], result)
        self.assertEqual(self.repair_cli(request), result)

    def recover_interrupted(self, failure, expected_phase, replaced):
        request = self.collected_two_file_proposal()
        before = self.record()
        replacements, writes, _ = self.injected_apply(request, failure)
        self.assertEqual(len(replacements), replaced)
        self.assertEqual(self.record()["revision"], before["revision"] + 1)
        self.assertEqual(len(writes), 2 if failure == "after-writes" else 1)
        app = self.record()["foreground_repairs"]["applications"][request["operation_id"]]
        self.assertIsNone(app["final"])
        self.assertEqual(self.record()["repair_protocol"]["operations"][app["repair_operation_id"]]["phase"], "APPLYING")
        saved, contents = self.task_path.read_bytes(), self.target_bytes()
        replay = self.repair_cli(request, expected=3)
        self.assertEqual(replay["status"], "REPAIR_RECONCILIATION_REQUIRED")
        self.assertEqual(self.task_path.read_bytes(), saved)
        self.assertEqual(self.target_bytes(), contents)
        # Pending intent must still fence unrelated lifecycle and review mutations.
        self.cli("state", "transition", "fixture", "Reviewing", expected=3)
        self.dispatch(self.request("accept-review", "pending-accept"), expected=3)
        self.dispatch(self.request("pause", "pause-pending"))
        status = self.dispatch()
        self.assertTrue(status["paused"])
        self.assertEqual(status["next_action"], "REPAIR_RECONCILIATION_REQUIRED")
        for name in ("worker", "leases", "state"):
            self.assertEqual(self.record()[name], before[name])
        self.dispatch(self.request("resume", "resume-still-pending"))
        self.assertEqual(self.dispatch()["next_action"], "REPAIR_RECONCILIATION_REQUIRED")
        self.dispatch(self.request("pause", "pause-for-observation"))
        reconciliation = self.request("reconcile-owner-proposal")
        outcome = self.repair_cli(reconciliation, expected=3 if expected_phase == "PARTIAL" else 0)
        self.assertEqual(outcome["status"], expected_phase)
        self.assertEqual(self.target_bytes(), contents)  # observation only; no rollback/completion
        saved = self.task_path.read_bytes()
        self.assertEqual(self.repair_cli(reconciliation, expected=3 if expected_phase == "PARTIAL" else 0), outcome)
        self.assertEqual(self.task_path.read_bytes(), saved)
        final = self.record()["foreground_repairs"]["applications"][request["operation_id"]]["final"]
        if expected_phase == "PARTIAL":
            self.assertIsNone(final)
            self.assertEqual(self.repair_cli(request, expected=3), replay)
            # Explicit operator completion, not controller rollback or automatic retry.
            for name in ("source.py", "second.py"):
                (self.worktree / name).write_bytes(b"result = 2\n")
            next_request = self.request("reconcile-owner-proposal", "observe-completed")
            self.assertEqual(self.repair_cli(next_request)["status"], "APPLIED_UNREVIEWED")
            self.assertEqual(self.repair_cli(reconciliation, expected=3), outcome)
        else:
            self.assertEqual(self.repair_cli(request), final["result"])
        self.dispatch(self.request("resume", "resume-pending"))
        return request

    def test_repair_interruption_before_first_target(self):
        self.recover_interrupted("before-first", "NOT_APPLIED_OBSERVED", 0)

    def test_repair_interruption_between_two_targets(self):
        self.recover_interrupted("between-files", "PARTIAL", 1)

    def test_repair_interruption_after_targets_before_final_persist(self):
        self.recover_interrupted("after-writes", "APPLIED_UNREVIEWED", 2)

    def test_repair_first_persist_failure_has_no_targets_or_receipt(self):
        request = self.collected_two_file_proposal()
        saved = self.task_path.read_bytes()
        replacements, writes, _ = self.injected_apply(request, "first-persist")
        self.assertEqual(replacements, [])
        self.assertEqual(len(writes), 1)
        self.assertEqual(self.task_path.read_bytes(), saved)
        self.assertEqual(self.target_bytes(), [self.source] * 2)
        self.assertEqual(self.repair_cli(request)["status"], "APPLIED_UNREVIEWED")

    def test_repair_unverified_observation_and_external_terminal_need_explicit_link(self):
        request = self.collected_two_file_proposal()
        self.injected_apply(request, "before-first")
        (self.worktree / "source.py").write_bytes(b"unrecognized operator edit\n")
        reconciliation = self.request("reconcile-owner-proposal")
        outcome = self.repair_cli(reconciliation, expected=3)
        self.assertEqual(outcome["status"], "UNVERIFIED")
        self.assertIsNone(self.record()["foreground_repairs"]["applications"][request["operation_id"]]["final"])
        for name in ("source.py", "second.py"):
            (self.worktree / name).write_bytes(self.source)
        op = self.record()["foreground_repairs"]["applications"][request["operation_id"]]["repair_operation_id"]
        self.cli("repair-apply", "fixture", "reconcile", "--operation-id", op)
        self.assertEqual(self.dispatch()["next_action"], "REPAIR_RECONCILIATION_REQUIRED")
        self.assertEqual(self.repair_cli(request, expected=3)["status"], "REPAIR_RECONCILIATION_REQUIRED")
        self.dispatch(self.request("prepare-correction", "cannot-skip-finalization"), expected=3)
        self.dispatch(self.request("pause", "pause-external-terminal"))
        final = self.repair_cli(self.request("reconcile-owner-proposal", "link-external-terminal"))
        self.assertEqual(final["status"], "NOT_APPLIED_OBSERVED")
        self.assertEqual(self.repair_cli(reconciliation, expected=3), outcome)
        self.assertEqual(self.repair_cli(request)["status"], "NOT_APPLIED_OBSERVED")

    def test_repair_failed_reconciliation_persist_keeps_history_and_targets(self):
        request = self.collected_two_file_proposal()
        self.injected_apply(request, "before-first")
        self.dispatch(self.request("pause", "pause-persist-failure"))
        reconciliation = self.request("reconcile-owner-proposal")
        saved = self.task_path.read_bytes()
        replacements, writes, _ = self.injected_apply(reconciliation, "first-persist")
        self.assertEqual(len(writes), 1)
        self.assertEqual(replacements, [])
        self.assertEqual(self.task_path.read_bytes(), saved)
        self.assertEqual(self.target_bytes(), [self.source] * 2)
        self.assertEqual(self.repair_cli(reconciliation)["status"], "NOT_APPLIED_OBSERVED")

    def test_repair_latest_context_source_full_worker_and_namespace_guards(self):
        request = self.collected_two_file_proposal()
        self.dispatch(request, expected=3, bundle=True)
        for patch in ({"expected_revision": 0}, {"operation_id": "begin"},
                      {"operation_id": "fgrepair." + "a" * 64}, {"incarnation": "0" * 64},
                      {"payload": {"admission_id": "0" * 64}}):
            self.dispatch(request | patch, expected=3)
        saved = self.record()
        changed = copy.deepcopy(saved)
        changed["worker"]["created_at"] = "2000-01-01T00:00:00Z"
        self.store_record(changed)
        self.dispatch(request, expected=3)
        self.store_record(saved)
        (self.worktree / "source.py").write_bytes(b"changed\n")
        self.dispatch(request, expected=3)
        (self.worktree / "source.py").write_bytes(self.source)
        later = self.request("admit-owner-proposal", "later-proposal")
        later["payload"]["session"] = "ses_later"
        self.dispatch(later)
        self.dispatch(self.request("apply-owner-proposal"), expected=3)
        self.assertEqual(self.target_bytes(), [self.source] * 2)

    def test_repair_link_loss_substitution_missing_artifacts_and_conflicting_replay(self):
        request = self.collected_two_file_proposal()
        result = self.repair_cli(request)
        saved = self.record()
        for damage in ("ledger", "application", "intent", "final", "request", "revision", "outcome"):
            record = copy.deepcopy(saved)
            app = record["foreground_repairs"]["applications"][request["operation_id"]]
            if damage == "ledger":
                del record["foreground_repairs"]
            elif damage == "application":
                record["foreground_repairs"]["applications"].clear()
            elif damage == "intent":
                record["repair_protocol"]["operations"].clear()
            elif damage == "final":
                app["final"]["result"]["delivery_credit"] = True
            elif damage == "request":
                app["request"]["payload"]["admission_id"] = "0" * 64
                app["request_sha256"] = c.digest(c.canonical(app["request"]))
            elif damage == "revision":
                app["intent_revision"] += 1
            else:
                app["final"]["result"]["status"] = "NOT_APPLIED_OBSERVED"
            self.store_record(record)
            self.dispatch(expected=3)
            self.dispatch(request, expected=3)
        self.store_record(saved)
        # Valid domain/control history must not steal the reserved repair ID.
        record = copy.deepcopy(saved)
        old = record["foreground_control"]["receipts"].pop("collect-owner-proposal")
        op = record["foreground_repairs"]["applications"][request["operation_id"]]["repair_operation_id"]
        collection = record["repair_proposals"][self.proposal_id]["collection"]
        collection["request"]["operation_id"] = op
        collection["request_sha256"] = c.digest(c.canonical(collection["request"]))
        old["request"]["operation_id"] = op
        old["request_sha256"] = c.digest(c.canonical(old["request"]))
        old["result"]["operation_id"] = op
        record["foreground_control"]["receipts"][op] = old
        self.store_record(record)
        self.dispatch(expected=3)
        self.store_record(saved)
        for sha in (result["domain_result"]["bundle_sha256"], c.digest(self.bundle["receipt.json"])):
            artifact = self.state_root / "review-artifacts" / sha
            artifact.rename(artifact.with_suffix(".missing"))
            self.dispatch(expected=3)
            self.dispatch(request, expected=3)
            artifact.with_suffix(".missing").rename(artifact)
        self.dispatch(request | {"expected_revision": self.record()["revision"]}, expected=3)
        self.dispatch(self.request("pause", request["operation_id"]), expected=3)
        self.assertEqual(self.repair_cli(request), result)

    def test_repair_receipt_capacity(self):
        request = self.collected_two_file_proposal()
        record = self.record()
        for index in range(delivery.MAX_RECEIPTS - len(record["foreground_control"]["receipts"])):
            if len(record["foreground_control"]["receipts"]) == 63:
                self.store_record(record)
                self.dispatch(self.request("apply-owner-proposal"), expected=3)
            control = self.request("resume", f"capacity-{index}")
            control["expected_revision"] = record["revision"]
            record, _, _ = delivery.dispatch(record, control, self.state_root)
            record["revision"] += 1
        self.store_record(record)
        self.dispatch(self.request("apply-owner-proposal"), expected=3)
        self.assertEqual(self.target_bytes(), [self.source] * 2)

    def test_completion_budget_valid_record_refuses_before_persist_or_targets(self):
        self.require_repair_metadata()
        request = self.collected_two_file_proposal()
        saved = self.record()
        bridge = delivery.dependency("foreground-repair")
        repair = bridge.load("repair-apply")
        coordinator = bridge.load("orchestrator-state")
        original_load = bridge.load
        # Schema-valid padding does not change the correction's scope, owner,
        # sources, worker or lifecycle. Dense extension metadata is legal under
        # validate_record (unknown top-level fields are retained), and exposes
        # indentation overhead that a single large string cannot demonstrate.
        def padded(width, escaped):
            value = copy.deepcopy(saved)
            text = ("\x01" * width) if escaped else ("x" * width)
            for field in ("dependencies", "findings", "reviewers", "validation"):
                value[field] = [text] * 200
            return value

        for escaped in (False, True):
            with self.subTest(escaped=escaped):
                # Find a schema-valid input fitting both initial limits whose
                # projected completion does not. The disappearing review arrays
                # would shrink intent, so only stable arrays carry the final pad.
                record = padded(1, escaped)
                record["reviewers"], record["validation"] = [], []
                # Extra schema-permitted metadata provides a nested JSON object,
                # accepted by validate_record, to expose compact-vs-pretty sizing.
                record["fixture_budget_metadata"] = ({str(i): ["x"] * 20 for i in range(1000)}
                                                   if escaped else {})
                target = 995_000 if escaped else 898_000
                measure = (lambda v: len((json.dumps(v, sort_keys=True, indent=2) + "\n").encode())) if escaped else (lambda v: len(c.canonical(v)))
                record["fixture_budget_metadata"]["padding"] = "x" * max(0, target - measure(record) - 20)
                coordinator.validate_record(record, "fixture")
                delivery.validate_retained(record, self.state_root, c, e)
                self.assertLessEqual(len(c.canonical(record)), 900_000)
                coordinator.serialized_json(record)
                self.store_record(record)
                before = self.task_path.read_bytes()
                checked = []
                original_budget = bridge.completion_budget
                def budget(value, req, collector, writer):
                    checked.append(True)
                    return original_budget(value, req, collector, writer)
                with mock.patch.object(bridge, "load", side_effect=lambda name:
                        repair if name == "repair-apply" else original_load(name)), \
                        mock.patch.object(bridge, "completion_budget", side_effect=budget), \
                        mock.patch.object(repair, "replace_one") as replace, \
                        mock.patch.object(coordinator, "write_task") as persist:
                    expected_error = "exceed 1 MB" if escaped else "canonical completion budget"
                    with self.assertRaisesRegex(Exception, expected_error):
                        bridge.run(record, request, self.state_root,
                                   lambda value: persist(self.state_root, value), record["foreground_control"])
                    persist.assert_not_called()
                    replace.assert_not_called()
                self.assertEqual(checked, [True])
                self.assertEqual(self.task_path.read_bytes(), before)
                self.assertEqual(self.target_bytes(), [self.source] * 2)
        self.store_record(saved)

    def test_recovery_projection_fits_real_writer_fields_and_reserves_metadata(self):
        request = self.collected_two_file_proposal()
        _, writes, _ = self.injected_apply(request, "first-persist")
        intent = writes[0]  # Real engine intent; first persistence failed, no writes.
        bridge = delivery.dependency("foreground-repair")
        coordinator = bridge.load("orchestrator-state")
        projections = []
        serialize = coordinator.serialized_json
        with mock.patch.object(coordinator, "serialized_json", side_effect=lambda value:
                projections.append(copy.deepcopy(value)) or serialize(value)):
            bridge.completion_budget(intent, request, c, coordinator)
        self.assertEqual(len(projections), 1 + len(bridge.OBSERVED))
        self.assertTrue(all(value["updated_at"] == "9999-12-31T23:59:59.999999Z" for value in projections))
        normal = len(serialize(projections[0]))
        recovery = max(len(serialize(value)) for value in projections[1:])
        self.assertGreater(recovery, normal)
        # Add identical legal metadata to the real record and real engine intent.
        # A dense array makes the durable bound bind first, not the compact one.
        record = self.record()
        for value in (record, intent):
            value["fixture_budget_metadata"] = {str(i): ["x"] * 20 for i in range(1000)}
        projections.clear()
        with mock.patch.object(coordinator, "serialized_json", side_effect=lambda value:
                projections.append(copy.deepcopy(value)) or serialize(value)):
            bridge.completion_budget(intent, request, c, coordinator)
        normal = len(serialize(projections[0]))
        recovery = max(len(serialize(value)) for value in projections[1:])
        padding = 1_000_000 - recovery + (recovery - normal) // 2 - 20
        record["fixture_budget_metadata"]["padding"] = "x" * padding
        intent["fixture_budget_metadata"]["padding"] = "x" * padding
        coordinator.validate_record(record, "fixture")
        delivery.validate_retained(record, self.state_root, c, e)
        coordinator.serialized_json(record)
        bridge.check_write_budget(intent, intent["revision"] + 1, c, coordinator)
        projections.clear()
        with mock.patch.object(coordinator, "serialized_json", side_effect=lambda value:
                projections.append(copy.deepcopy(value)) or serialize(value)):
            with self.assertRaisesRegex(coordinator.InputError, "exceed 1 MB"):
                bridge.completion_budget(intent, request, c, coordinator)
        # The normal completion fits; a concrete recovery outcome does not.
        self.assertLessEqual(len(serialize(projections[0])), 1_000_000)
        self.assertGreater(len(projections), 1)
        self.assertLessEqual(len(c.canonical(projections[-1])), 900_000)
        self.store_record(record)
        before = self.task_path.read_bytes()
        persist = mock.Mock()
        repair = bridge.load("repair-apply")
        original_load = bridge.load
        with mock.patch.object(bridge, "load", side_effect=lambda name:
                repair if name == "repair-apply" else original_load(name)), \
                mock.patch.object(repair, "replace_one") as replace:
            with self.assertRaisesRegex(Exception, "exceed 1 MB"):
                bridge.run(record, request, self.state_root, persist, record["foreground_control"])
            persist.assert_not_called()
            replace.assert_not_called()
        self.assertEqual(self.task_path.read_bytes(), before)
        self.assertEqual(self.target_bytes(), [self.source] * 2)

    def test_last_slot_cannot_reconcile_completed_application_instead_of_pending(self):
        first = self.collected_two_file_proposal()
        self.injected_apply(first, "before-first")
        self.repair_cli(self.request("reconcile-owner-proposal", "settle-first"))
        # Real second review/rework cycle at unchanged head is permitted after
        # NOT_APPLIED_OBSERVED. Domain entrypoints create all history normally.
        self.cli("state", "transition", "fixture", "Reviewing")
        self.domain("review-evidence", "begin", {"base": self.head, "head": self.head,
            "packet": c.digest(self.packet), "policy": "d" * 64,
            "obligations": sorted(e.BASELINE)}, "begin-second")
        self.domain("review-evidence", "assign", {"generation": 2, "run_id": "run-second",
            "reviewer": "reviewer", "profile": "e" * 64, "obligations": sorted(e.BASELINE),
            "adapter": "native-session", "session": "ses_second"}, "assign-second")
        self.domain("review-evidence", "accept", {"generation": 2, "run_id": "run-second",
            "packet": c.digest(self.packet), "policy": "d" * 64, "profile": "e" * 64,
            "session": "ses_second", "coverage": dict.fromkeys(e.BASELINE, "reviewed"),
            "findings": [], "dispositions": [{"finding_id": "F1", "resolution": "persists",
                "counterevidence": "synthetic unchanged source"}], "limitations": ["claims only"]}, "accept-second")
        self.cli("state", "transition", "fixture", "Rework")
        self.correction_id = self.dispatch(self.request("prepare-correction", "prepare-second"))["domain_result"]["correction_id"]
        self.cli("state", "claim", "fixture", "--owner", "writer", "--pid", str(os.getpid()))
        self.cli("state", "transition", "fixture", "Implementing")
        admission = self.request("admit-owner-proposal", "admit-second-owner")
        admission["payload"]["session"] = "ses_owner_second"
        self.proposal_id = self.dispatch(admission)["domain_result"]["admission_id"]
        self.owner_bundle()
        self.dispatch(self.request("collect-owner-proposal", "collect-second-owner"), bundle=True)
        bridge = delivery.dependency("foreground-repair")
        record = self.record()
        while len(record["foreground_control"]["receipts"]) + bridge.count(record) < 62:
            req = self.request("resume", "fill-second-" + str(record["revision"]))
            req["expected_revision"] = record["revision"]
            record, _, _ = delivery.dispatch(record, req, self.state_root)
            record["revision"] += 1
        self.store_record(record)
        second = self.request("apply-owner-proposal", "apply-second")
        self.injected_apply(second, "before-first")
        coordinator = bridge.load("orchestrator-state")
        coordinator.validate_record(self.record(), "fixture")
        delivery.validate_retained(self.record(), self.state_root, c, e)
        before = self.task_path.read_bytes()
        self.assertEqual(self.dispatch()["receipt_count"], 63)
        self.dispatch(self.request("reconcile-owner-proposal", "wrong-terminal-target"), expected=3)
        self.assertEqual(self.task_path.read_bytes(), before)
        observe = self.request("reconcile-owner-proposal", "settle-second")
        observe["payload"]["apply_operation_id"] = "apply-second"
        self.assertEqual(self.repair_cli(observe)["status"], "NOT_APPLIED_OBSERVED")
        self.assertEqual(self.dispatch()["receipt_count"], 64)
        self.assertFalse(bridge.pending(self.record()))
        self.assertEqual(self.target_bytes(), [self.source] * 2)

    def test_pending_repair_keeps_last_slot_for_reconciliation(self):
        request = self.collected_two_file_proposal()
        record = self.record()
        while len(record["foreground_control"]["receipts"]) < 60:
            control = self.request("resume", "fill-" + str(record["revision"]))
            control["expected_revision"] = record["revision"]
            record, _, _ = delivery.dispatch(record, control, self.state_root)
            record["revision"] += 1
        self.store_record(record)
        request = self.request("apply-owner-proposal")
        self.injected_apply(request, "before-first")  # 61 total receipts
        self.assertEqual(self.dispatch()["receipt_count"], 61)
        self.dispatch(self.request("pause", "near-limit-pause"))  # 62
        self.dispatch(self.request("resume", "near-limit-resume"))  # 63
        saved = self.task_path.read_bytes()
        self.dispatch(self.request("pause", "must-preserve-recovery"), expected=3)
        self.dispatch(self.request("resume", "also-preserve-recovery"), expected=3)
        self.assertEqual(self.task_path.read_bytes(), saved)
        self.assertEqual(self.repair_cli(request, expected=3)["status"], "REPAIR_RECONCILIATION_REQUIRED")
        result = self.repair_cli(self.request("reconcile-owner-proposal"))  # 64
        self.assertEqual(result["status"], "NOT_APPLIED_OBSERVED")
        self.assertEqual(self.dispatch()["receipt_count"], 64)
        self.assertEqual(self.repair_cli(request)["status"], "NOT_APPLIED_OBSERVED")
        self.assertIsNotNone(self.record()["foreground_repairs"]["applications"][request["operation_id"]]["final"])
        self.assertEqual(self.target_bytes(), [self.source] * 2)

    def test_unexpected_cli_exit_has_sanitized_same_invocation_diagnostic(self):
        request = self.request("pause")
        request["payload"] = {"private-diagnostic-canary": "must-never-be-printed"}
        path = self.root / "diagnostic-request.json"
        path.write_bytes(c.canonical(request))
        before = self.task_path.read_bytes()
        with self.assertRaises(AssertionError) as caught:
            self.cli("foreground-delivery", "fixture", "--request", str(path))
        message = str(caught.exception)
        self.assertIn('"source": "same-invocation"', message)
        self.assertIn('"exception": "Unverified"', message)
        self.assertIn('"function": "fields"', message)
        self.assertNotIn("private-diagnostic-canary", message)
        self.assertNotIn("must-never-be-printed", message)
        self.assertNotIn(str(self.root), message)
        self.assertLess(len(message), 3200)
        self.assertEqual(self.task_path.read_bytes(), before)


class DiagnosticCompileTests(unittest.TestCase):
    def test_repair_capability_guard_does_not_swallow_unexpected_errors(self):
        # Exercise the capability helper without running the expensive CLI setup.
        fixture = ForegroundTests(methodName="runTest")
        with tempfile.TemporaryDirectory() as directory:
            fixture.worktree = Path(directory).resolve()
            for name in ("source.py", "second.py"):
                (fixture.worktree / name).write_bytes(b"fixture\n")
            with mock.patch.object(os, "listxattr", return_value=[], create=True) as probe:
                self.assertIsNone(fixture.repair_metadata_unavailable())
                self.assertEqual(probe.call_count, 2)
                self.assertTrue(all(type(call.args[0]) is int for call in probe.call_args_list))
            with mock.patch.object(os, "listxattr", return_value=["user.fixture"], create=True):
                self.assertIn("extended metadata", fixture.repair_metadata_unavailable())
            with mock.patch.object(os, "listxattr", side_effect=OSError(errno.ENOTSUP, "unsupported"), create=True):
                self.assertIn("lacks xattr inspection", fixture.repair_metadata_unavailable())
            with mock.patch.object(os, "listxattr", side_effect=OSError(errno.EIO, "unexpected I/O"), create=True):
                with self.assertRaises(OSError):
                    fixture.require_repair_metadata()
            with mock.patch.dict(os.__dict__, {"listxattr": None}):
                del os.listxattr
                with self.assertRaisesRegex(unittest.SkipTest, "host Python lacks"):
                    fixture.require_repair_metadata()

    def test_benchmark_resolves_exact_discovered_method_and_rejects_ambiguity(self):
        benchmark = load(Path(__file__).with_name("foreground-diagnostic-benchmark.py"), "benchmark")

        class Cases(unittest.TestCase):
            def test_example(self):
                pass

            def test_example_extended(self):
                pass

        exact = Cases("test_example")
        suite = unittest.TestSuite([unittest.TestSuite([exact]), Cases("test_example_extended")])
        self.assertIs(benchmark.resolve_case(suite, "test_example"), exact)
        for selector in ("missing", "test_exam", "*example*"):
            with self.subTest(selector=selector), self.assertRaisesRegex(ValueError, "0 matches"):
                benchmark.resolve_case(suite, selector)
        # Duplicate inherited/discovered methods must not be deduplicated away.
        duplicate = unittest.TestSuite([exact, Cases("test_example")])
        with self.assertRaisesRegex(ValueError, "2 matches"):
            benchmark.resolve_case(duplicate, "test_example")

    def test_benchmark_validates_all_selectors_before_samples_or_profiles(self):
        benchmark = load(Path(__file__).with_name("foreground-diagnostic-benchmark.py"), "benchmark")
        test = unittest.FunctionTestCase(lambda: None)
        for mode in ([], ["--profile"]):
            with self.subTest(mode=mode), \
                    mock.patch.object(sys, "argv", ["benchmark", *mode, "--case", "runTest", "--case", "run"]), \
                    mock.patch.object(benchmark, "discover", return_value=(None, unittest.TestSuite([test]))), \
                    mock.patch.object(benchmark, "profile_case") as profile, \
                    mock.patch.object(subprocess, "run") as child, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                benchmark.main()
            self.assertEqual(caught.exception.code, 2)
            profile.assert_not_called()
            child.assert_not_called()

    def test_benchmark_timing_child_reports_actual_count_and_failed_or_skipped_status(self):
        benchmark = load(Path(__file__).with_name("foreground-diagnostic-benchmark.py"), "benchmark")

        class Cases(unittest.TestCase):
            def test_pass(self):
                pass

            def test_fail(self):
                self.fail("expected fixture failure")

            @unittest.skip("expected fixture skip")
            def test_skip(self):
                pass

        for name, code, skipped in (("test_pass", 0, 0), ("test_fail", 1, 0), ("test_skip", 1, 1)):
            output = io.StringIO()
            with self.subTest(name=name), \
                    mock.patch.object(sys, "argv", ["benchmark", "--time-case", name]), \
                    mock.patch.object(benchmark, "discover", return_value=(None, unittest.TestLoader().loadTestsFromTestCase(Cases))), \
                    contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as caught:
                benchmark.main()
            self.assertEqual(caught.exception.code, code)
            report = json.loads(output.getvalue())
            self.assertEqual(report["tests_run"], 1)
            self.assertEqual(report["skipped"], skipped)
            self.assertEqual(benchmark.measured_pass(report), code == 0)
        for report in ({}, {"tests_run": 0, "skipped": 0, "successful": True},
                       {"tests_run": 2, "skipped": 0, "successful": True}):
            self.assertFalse(benchmark.measured_pass(report))

    def test_parent_compile_context_is_per_fixture_and_restored_on_failure(self):
        from importlib.machinery import SourceFileLoader
        original = SourceFileLoader.source_to_code
        contexts = []

        class Fixture(ForegroundTests):
            def git(self, *args):
                if failure == "setup":
                    raise RuntimeError("fixture setup failure")
                return super().git(*args)

            def runTest(self):
                contexts.append(SourceFileLoader.source_to_code)
                self.assertIsNot(contexts[-1], original)
                first = delivery.dependency("candidate-binding")
                first.fixture_mutation = True
                second = delivery.dependency("candidate-binding")
                self.assertIsNot(first, second)
                self.assertFalse(hasattr(second, "fixture_mutation"))
                if failure == "test":
                    self.fail("fixture test failure")

        for failure in (None, "test", "setup"):
            with self.subTest(failure=failure):
                result = unittest.TestResult()
                Fixture().run(result)
                self.assertEqual(result.testsRun, 1)
                self.assertEqual(len(result.errors), int(failure == "setup"))
                self.assertEqual(len(result.failures), int(failure == "test"))
                self.assertIs(SourceFileLoader.source_to_code, original)
        self.assertIsNot(contexts[0], contexts[1])

    def test_diagnostic_profile_launcher_preserves_failed_exit(self):
        with tempfile.TemporaryDirectory(prefix="foreground-profile-exit-") as temporary:
            directory = Path(temporary)
            script, profile = directory / "failed.py", directory / "failed.prof"
            script.write_text("raise SystemExit(3)\n")
            process = subprocess.run([sys.executable, "-I", "-B", str(Path(__file__).with_name("foreground-diagnostic-benchmark.py")),
                                      "--profile-cli", str(profile), str(script)], capture_output=True, timeout=10)
            self.assertEqual(process.returncode, 3)
            self.assertEqual(process.stdout, b"")
            self.assertEqual(process.stderr, b"")
            import pstats
            self.assertGreater(pstats.Stats(str(profile)).total_calls, 0)

    def test_diagnostic_monitoring_and_trace_capture_same_exception_and_restore(self):
        diagnostic = load(Path(__file__).with_name("foreground-cli-diagnostic.py"), "diagnostic")
        namespace = {}
        exec(compile("def helper():\n raise ValueError('private-canary')\ndef main():\n worker = {'process_start': 'start'}\n live, start = 'alive', 'start'\n try:\n  helper()\n except Exception:\n  return 3\n", str(diagnostic.TARGET), "exec"), namespace)
        results = []
        for fallback in (False, True):
            observed = []
            def capture(frame, exception, traceback):
                observed.append((diagnostic.summarize(exception, traceback),
                                 frame.f_locals["live"] == "alive",
                                 frame.f_locals["start"] == frame.f_locals["worker"]["process_start"]))
            original = sys.gettrace()
            manager = mock.patch.object(sys, "monitoring", None, create=True) if fallback else contextlib.nullcontext()
            with manager, diagnostic.exception_observer(capture) as backend:
                self.assertEqual(backend, "trace" if fallback or not hasattr(sys, "monitoring") else "monitoring")
                self.assertEqual(namespace["main"](), 3)
            self.assertIs(sys.gettrace(), original)
            self.assertEqual(len(observed), 1)
            self.assertNotIn("private-canary", repr(observed))
            results.append(observed)
        self.assertEqual(results[0], results[1])
        if hasattr(sys, "monitoring"):
            self.assertIsNone(sys.monitoring.get_tool(5))
            self.assertEqual(sys.monitoring.get_events(5), 0)

    def test_diagnostic_observer_exception_cleanup_and_occupied_slot(self):
        diagnostic = load(Path(__file__).with_name("foreground-cli-diagnostic.py"), "diagnostic")
        original = sys.gettrace()
        with self.assertRaisesRegex(RuntimeError, "observer cleanup"), diagnostic.exception_observer(lambda *args: None):
            raise RuntimeError("observer cleanup")
        self.assertIs(sys.gettrace(), original)
        if hasattr(sys, "monitoring"):
            monitoring = sys.monitoring
            monitoring.use_tool_id(5, "existing-test-observer")
            try:
                with diagnostic.exception_observer(lambda *args: None) as backend:
                    self.assertEqual(backend, "trace")
                    self.assertEqual(monitoring.get_tool(5), "existing-test-observer")
                self.assertEqual(monitoring.get_tool(5), "existing-test-observer")
            finally:
                monitoring.free_tool_id(5)
        self.assertIs(sys.gettrace(), original)

    def test_diagnostic_compile_reuse_reads_edits_and_fresh_globals(self):
        diagnostic = load(Path(__file__).with_name("foreground-cli-diagnostic.py"), "diagnostic")
        from importlib.machinery import SourceFileLoader
        original = SourceFileLoader.source_to_code
        with tempfile.TemporaryDirectory(prefix="foreground-compile-") as temporary:
            directory = Path(temporary)
            path = directory / "helper.py"
            path.write_bytes(b"value = 1\nitems = []\n")
            stamp = path.stat()
            with mock.patch.object(diagnostic, "BIN", directory), \
                    mock.patch.object(SourceFileLoader, "source_to_code", autospec=True, side_effect=original) as compile_source:
                with diagnostic.compiled_installed_sources():
                    first = load(path, "helper_one")
                    first.items.append("mutated")
                    second = load(path, "helper_two")
                    self.assertIsNot(first, second)
                    self.assertEqual(second.items, [])
                    self.assertEqual(compile_source.call_count, 1)
                    path.write_bytes(b"value = 2\nitems = []\n")
                    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                    self.assertEqual(load(path, "helper_changed").value, 2)
                    self.assertEqual(compile_source.call_count, 2)
                    path.rename(directory / "missing.py")
                    with self.assertRaises(FileNotFoundError):
                        load(path, "helper_missing")
                self.assertIs(SourceFileLoader.source_to_code, compile_source)
            self.assertIs(SourceFileLoader.source_to_code, original)

    def test_diagnostic_compile_scope_options_bounds_and_restoration(self):
        diagnostic = load(Path(__file__).with_name("foreground-cli-diagnostic.py"), "diagnostic")
        from importlib.machinery import SourceFileLoader
        original = SourceFileLoader.source_to_code
        source = b"assert False\nvalue = 1\n"
        path = str(diagnostic.BIN / "helper.py")
        loader = SourceFileLoader("helper", path)
        with mock.patch.object(SourceFileLoader, "source_to_code", autospec=True, side_effect=original) as compile_source:
            with self.assertRaisesRegex(RuntimeError, "restore observer"), diagnostic.compiled_installed_sources():
                code = loader.source_to_code(source, path)
                self.assertIs(loader.source_to_code(source, path), code)
                self.assertIsNot(loader.source_to_code(source, path, _optimize=1), code)
                self.assertEqual(compile_source.call_count, 2)
                other = str(diagnostic.BIN.parent / "outside.py")
                self.assertIsNot(loader.source_to_code(source, other), loader.source_to_code(source, other))
                large = b"#" + b"x" * 1_000_000
                self.assertIsNot(loader.source_to_code(large, path), loader.source_to_code(large, path))
                for index in range(30):
                    loader.source_to_code(source, str(diagnostic.BIN / (str(index) + ".py")))
                overflow = str(diagnostic.BIN / "overflow.py")
                self.assertIsNot(loader.source_to_code(source, overflow), loader.source_to_code(source, overflow))
                raise RuntimeError("restore observer")
            self.assertIs(SourceFileLoader.source_to_code, compile_source)
        self.assertIs(SourceFileLoader.source_to_code, original)


def load_tests(loader, tests, pattern):
    cases = load(Path(__file__).with_name("foreground-adopt-cases.py"), "foreground_adopt_cases")
    adoption = cases.install(ForegroundTests, delivery, c)
    tests.addTests(adoption(name) for name in loader.getTestCaseNames(adoption) if name.startswith("test_adopt_"))
    fresh = load(Path(__file__).with_name("foreground-review-cases.py"), "foreground_review_cases").install(adoption, delivery, c)
    tests.addTests(fresh(name) for name in loader.getTestCaseNames(fresh) if name.startswith("test_fresh_"))
    admission = load(Path(__file__).with_name("foreground-admission-cases.py"), "foreground_admission_cases").install(fresh, delivery, c)
    tests.addTests(admission(name) for name in loader.getTestCaseNames(admission) if name.startswith("test_admission_"))
    return tests


if __name__ == "__main__":
    unittest.main()
