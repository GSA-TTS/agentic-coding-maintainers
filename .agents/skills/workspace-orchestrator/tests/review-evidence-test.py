#!/usr/bin/env python3
"""Protocol faults and useful review/repair claims without invented runtime credit."""

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "bin" / "review-evidence.py"
spec = importlib.util.spec_from_file_location("review_evidence", SOURCE)
assert spec and spec.loader
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.record = {"revision": 0, "base_sha": "a" * 40, "head_sha": "b" * 40,
                       "state": "Reviewing", "owner": "writer", "kind": "implementation",
                       "rework_count": 0, "transition_intent": None}
        self.counter = 0
        self.begin()

    def request(self, action, payload, operation=None):
        self.counter += 1
        return {"schema_version": 1, "operation_id": operation or f"op-{self.counter}",
                "expected_revision": self.record["revision"], "action": action, "payload": payload}

    def execute(self, request):
        self.record, result, changed = evidence.apply(self.record, request)
        if changed:
            self.record["revision"] += 1
        return result

    def begin(self):
        self.execute(self.request("begin", {"packet": "c" * 64, "policy": "d" * 64,
                     "base": self.record["base_sha"], "head": self.record["head_sha"],
                     "obligations": sorted(evidence.BASELINE)}))

    def assign(self, run_id):
        self.execute(self.request("assign", {"generation": len(self.record["review_protocol"]["generations"]),
                     "run_id": run_id, "reviewer": "reviewer", "profile": "e" * 64,
                     "obligations": sorted(evidence.BASELINE), "adapter": "fake", "session": f"session-{run_id}"}))

    def report(self, run_id):
        return {"generation": len(self.record["review_protocol"]["generations"]), "run_id": run_id,
                "packet": "c" * 64, "policy": "d" * 64, "profile": "e" * 64,
                "session": f"session-{run_id}", "coverage": dict.fromkeys(evidence.BASELINE, "reviewed"),
                "findings": [], "dispositions": [], "limitations": []}

    def test_clean_claims_complete_without_execution_credit(self):
        self.assign("clean")
        self.execute(self.request("accept", self.report("clean")))
        assessment = evidence.assess(self.record)
        self.assertEqual(assessment["review_process"], "CLAIMS_COMPLETE")
        self.assertEqual(assessment["unresolved_findings"], [])
        self.assertFalse(assessment["candidate_ready"])
        self.assertFalse(assessment["execution_credit"])

    def test_two_assignments_survive_nonmaterial_revision_change(self):
        self.assign("first")
        self.assign("second")
        self.execute(self.request("accept", self.report("first")))
        self.execute(self.request("accept", self.report("second")))
        self.assertEqual(len(self.record["review_protocol"]["generations"][0]["reports"]), 2)

    def test_crash_replay_returns_original_receipt(self):
        self.assign("clean")
        request = self.request("accept", self.report("clean"))
        original = self.execute(request)
        saved = copy.deepcopy(self.record)
        self.assertEqual(self.execute(request), original)
        self.assertEqual(self.record, saved)
        changed = copy.deepcopy(request)
        changed["payload"]["limitations"] = ["different"]
        with self.assertRaises(evidence.Unverified):
            self.execute(changed)

    def test_new_head_requires_new_generation_and_retains_finding(self):
        self.assign("z-original")
        report = self.report("z-original")
        report["findings"] = [{"id": "F1", "invariant": "only current revisions qualify",
                                "trigger": "head advances", "path": "src/check.py:12",
                                "impact": "stale approval", "evidence": "observed old-head acceptance"}]
        self.execute(self.request("accept", report))
        self.assertEqual(evidence.assess(self.record)["status"], "HOLD")
        old = self.report("late")
        self.record["head_sha"] = "f" * 40
        self.record["revision"] += 1
        self.assertEqual(evidence.assess(self.record)["status"], "UNVERIFIED")
        self.begin()
        self.assign("a-fix")
        with self.assertRaises(evidence.Unverified):
            self.execute(self.request("accept", old))
        fixed = self.report("a-fix")
        fixed["dispositions"] = [{"finding_id": "F1", "resolution": "fixed",
                                   "counterevidence": "new-head comparison rejects old evidence"}]
        self.execute(self.request("accept", fixed))
        self.record = json.loads(json.dumps(self.record, sort_keys=True))
        history = evidence.finding_history(self.record)
        self.assertEqual(history["F1"]["finding"], report["findings"][0])
        self.assertEqual(evidence.assess(self.record)["unresolved_findings"], [])
        self.assertFalse(evidence.assess(self.record)["candidate_ready"])

    def test_refutation_is_retained_in_separate_run(self):
        self.assign("z-finding")
        report = self.report("z-finding")
        report["findings"] = [{"id": "F1", "invariant": "limit", "trigger": "input", "path": "x:1",
                                "impact": "overflow", "evidence": "initial claim"}]
        self.execute(self.request("accept", report))
        self.assign("a-counter")
        counter = self.report("a-counter")
        counter["dispositions"] = [{"finding_id": "F1", "resolution": "refuted", "counterevidence": "bound precedes read"}]
        self.execute(self.request("accept", counter))
        self.record = json.loads(json.dumps(self.record, sort_keys=True))
        self.assertEqual(evidence.finding_history(self.record)["F1"]["dispositions"][0]["resolution"], "refuted")

    def test_substitution_missing_coverage_and_unknown_run(self):
        self.assign("review")
        for name in ("packet", "policy", "profile", "session", "run_id"):
            report = self.report("review")
            report[name] = "substituted"
            with self.subTest(name=name), self.assertRaises(evidence.Unverified):
                self.execute(self.request("accept", report))
        report = self.report("review")
        report["coverage"].pop("baseline-security")
        with self.assertRaises(evidence.Unverified):
            self.execute(self.request("accept", report))

    def test_stale_revision_and_cancelled_task_refused(self):
        request = self.request("assign", {})
        self.record["revision"] += 1
        with self.assertRaises(evidence.Unverified):
            self.execute(request)
        self.record["state"] = "Cancelled"
        with self.assertRaises(evidence.Unverified):
            self.execute(self.request("accept", {}))

    def test_strict_parser_and_boolean_revision(self):
        for data in (b'{"a":1,"a":2}', b'{"a":NaN}', b'[]', b''):
            with self.assertRaises(evidence.Unverified):
                evidence.parse(data)
        request = self.request("accept", {})
        request["expected_revision"] = True
        with self.assertRaises(evidence.Unverified):
            self.execute(request)

    def test_corrupt_persisted_claims_never_appear_complete(self):
        self.assign("review")
        self.execute(self.request("accept", self.report("review")))
        saved = copy.deepcopy(self.record)
        for field, value in (("acceptance_order", []), ("obligations", []), ("number", True)):
            with self.subTest(field=field):
                self.record = copy.deepcopy(saved)
                self.record["review_protocol"]["generations"][0][field] = value
                self.assertEqual(evidence.assess(self.record)["review_process"], "UNVERIFIED")
                with self.assertRaises(evidence.Unverified):
                    self.execute(self.request("accept", self.report("review")))

    def test_material_epoch_prevents_head_return_revival(self):
        self.assign("review")
        self.execute(self.request("accept", self.report("review")))
        self.record["review_protocol"]["material_epoch"] += 2
        self.record["revision"] += 2
        self.assertEqual(evidence.assess(self.record)["review_process"], "UNVERIFIED")
        self.begin()
        self.assertEqual(evidence.assess(self.record)["missing_obligations"], sorted(evidence.BASELINE))

    def test_receipts_bind_retained_reports_and_requests(self):
        self.assign("review")
        request = self.request("accept", self.report("review"))
        self.execute(request)
        saved = copy.deepcopy(self.record)
        generation = self.record["review_protocol"]["generations"][0]
        generation["reports"] = {}
        generation["acceptance_order"] = []
        with self.assertRaises(evidence.Unverified):
            self.execute(request)
        self.record = copy.deepcopy(saved)
        self.record["review_protocol"]["operations"][request["operation_id"]]["result"]["report_sha256"] = "f" * 64
        with self.assertRaises(evidence.Unverified):
            self.execute(request)
        self.record = copy.deepcopy(saved)
        del self.record["review_protocol"]["operations"][request["operation_id"]]
        self.assertEqual(evidence.assess(self.record)["review_process"], "UNVERIFIED")

    def test_empty_base_refused_without_mutation(self):
        self.record = {"revision": 0, "base_sha": "", "head_sha": "b" * 40, "state": "Reviewing",
                       "owner": "writer", "kind": "review", "rework_count": 0, "transition_intent": None}
        saved = copy.deepcopy(self.record)
        with self.assertRaises(evidence.Unverified):
            self.begin()
        self.assertEqual(self.record, saved)

    def test_reordered_dispositions_fail_receipt_chronology(self):
        self.assign("original")
        report = self.report("original")
        report["findings"] = [{"id": "F1", "invariant": "bound", "trigger": "input", "path": "x:1",
                                "impact": "overflow", "evidence": "observed"}]
        self.execute(self.request("accept", report))
        for run_id, resolution in (("fixed", "fixed"), ("persists", "persists")):
            self.assign(run_id)
            report = self.report(run_id)
            report["dispositions"] = [{"finding_id": "F1", "resolution": resolution, "counterevidence": "independent claim"}]
            self.execute(self.request("accept", report))
        self.assertEqual(evidence.assess(self.record)["status"], "HOLD")
        self.record["review_protocol"]["generations"][0]["acceptance_order"] = ["original", "persists", "fixed"]
        self.assertEqual(evidence.assess(self.record)["review_process"], "UNVERIFIED")

    def test_empty_generation_still_requires_chronological_begin(self):
        self.begin()
        self.assign("review")
        self.execute(self.request("accept", self.report("review")))
        self.record["revision"] = 10
        protocol = self.record["review_protocol"]
        protocol["generations"][0]["admission_revision"] = 7
        receipt = protocol["operations"]["op-1"]
        receipt["request"]["expected_revision"] = 7
        receipt["request_sha256"] = hashlib.sha256(evidence.canonical(receipt["request"])).hexdigest()
        receipt["result"]["resulting_revision"] = 8
        self.assertEqual(evidence.assess(self.record)["review_process"], "UNVERIFIED")

    def test_cross_generation_run_identity_can_dispose_finding(self):
        self.assign("review")
        report = self.report("review")
        report["findings"] = [{"id": "F1", "invariant": "bound", "trigger": "input", "path": "x:1",
                                "impact": "overflow", "evidence": "observed"}]
        self.execute(self.request("accept", report))
        self.record["head_sha"] = "f" * 40
        self.record["revision"] += 1
        self.record["review_protocol"]["material_epoch"] += 1
        self.begin()
        self.assign("review")
        report = self.report("review")
        report["dispositions"] = [{"finding_id": "F1", "resolution": "fixed", "counterevidence": "new generation"}]
        self.execute(self.request("accept", report))
        self.assertEqual(evidence.assess(self.record)["unresolved_findings"], [])

    def test_correction_targets_original_owner_without_write_authority(self):
        self.record.update(task_id="task", repo="fixture/project", branch="task-branch", worktree="/work/task",
                           owned_paths=["src"], restricted_paths=["policy"], acceptance_criteria=["reject stale evidence"])
        self.assign("review")
        report = self.report("review")
        report["findings"] = [{"id": "F1", "invariant": "bound", "trigger": "input", "path": "src/x:1",
                                "impact": "overflow", "evidence": "observed"}]
        self.execute(self.request("accept", report))
        before = copy.deepcopy(self.record)
        request = evidence.correction_request(self.record)
        self.assertEqual(request["owner"], "writer")
        self.assertEqual(request["head"], self.record["head_sha"])
        self.assertEqual(request["findings"][0]["finding"]["id"], "F1")
        self.assertEqual(request["owned_paths"], ["src"])
        self.assertFalse(request["write_authority"])
        self.assertEqual(self.record, before)
        self.record["owner"] = "replacement"
        with self.assertRaises(evidence.Unverified):
            evidence.correction_request(self.record)
        self.record = before
        self.record["rework_count"] = 3
        with self.assertRaises(evidence.Unverified):
            evidence.correction_request(self.record)
        self.record["state"] = "Rework"
        self.assertEqual(evidence.correction_request(self.record)["remaining_rework_cycles"], 1)
        self.record["rework_count"] = 1
        self.record["owner"] = "replacement"
        self.begin()
        with self.assertRaises(evidence.Unverified):
            evidence.correction_request(self.record)

    def test_correction_cli_does_not_initialize_missing_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "missing-state"
            env = {**os.environ, "ORCHESTRATOR_TEST_MODE": "1", "ORCHESTRATOR_STATE_DIR": str(root)}
            for extra in ([], ["--request", str(Path(directory) / "request.json")]):
                result = subprocess.run([sys.executable, "-I", "-B", str(SOURCE), "absent", "--correction", *extra],
                                        env=env, capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 3)
                self.assertFalse(root.exists())

    def test_authoritative_cli_receipt_replay_and_readiness_guard(self):
        coordinator = evidence.load_coordinator()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {**os.environ, "ORCHESTRATOR_TEST_MODE": "1", "ORCHESTRATOR_STATE_DIR": str(root / "state")}
            state_script = SOURCE.with_name("orchestrator-state.py")

            def state(*args):
                return subprocess.run([sys.executable, "-I", "-B", str(state_script), *args],
                                      env=env, capture_output=True, text=True, check=False)

            self.assertEqual(state("create", "fixture", "--scope", "fixture:review", "--kind", "review",
                                   "--head-sha", "b" * 40, "--base-sha", "a" * 40).returncode, 0)
            self.assertEqual(state("claim", "fixture", "--owner", "writer", "--pid", str(os.getpid())).returncode, 0)
            self.assertEqual(state("transition", "fixture", "Reviewing").returncode, 0)
            self.record = json.loads(state("show", "fixture").stdout)
            request = self.request("begin", {"packet": "c" * 64, "policy": "d" * 64,
                                            "base": "a" * 40, "head": "b" * 40,
                                            "obligations": sorted(evidence.BASELINE)})
            staging = root / "request.json"
            staging.write_bytes(evidence.canonical(request))

            def submit():
                return subprocess.run([sys.executable, "-I", "-B", str(SOURCE), "fixture", "--request", str(staging)],
                                      env=env, capture_output=True, text=True, check=False)

            first = submit()
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            persisted = json.loads(state("show", "fixture").stdout)
            replay = submit()
            self.assertEqual(replay.returncode, 0, replay.stdout + replay.stderr)
            self.assertEqual(json.loads(first.stdout), json.loads(replay.stdout))
            self.assertEqual(persisted, json.loads(state("show", "fixture").stdout))
            self.assertEqual(state("record", "fixture", "reviewer", "qa", "--reviewed-sha", "b" * 40).returncode, 0)
            self.assertEqual(state("record", "fixture", "validation", "claimed pass").returncode, 0)
            self.assertEqual(state("transition", "fixture", "Ready for human review").returncode, 4)
            persisted["transition_intent"] = "Ready for human review"
            with self.assertRaises(coordinator.UnknownError):
                coordinator.finish_intent(root / "state", persisted)


if __name__ == "__main__":
    unittest.main()
