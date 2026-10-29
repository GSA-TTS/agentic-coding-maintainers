#!/usr/bin/env python3
"""Structured final-review acceptance atop collected fixture observations."""

import copy
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
fixtures = load(Path(__file__).with_name("review-collect-test.py"), "collection_fixture")
acceptance = load(ROOT / "bin" / "review-accept.py", "review_acceptance")
c = fixtures.collector
e = fixtures.evidence


class AcceptanceTests(fixtures.CollectionTests):
    # Reuse collection setup/helpers and retain the existing collection cases.
    def structured(self, findings=None, coverage=None):
        return {"schema_version": 1, "coverage": coverage or dict.fromkeys(e.BASELINE, "reviewed"),
                "findings": findings or [], "dispositions": [], "limitations": ["claims only"]}

    def collect_final(self, content):
        admitted = self.apply(self.admit, packet=self.packet)
        bundle = self.bundle()
        final = content if isinstance(content, str) else json.dumps(content)
        receipt = c.decode(bundle["receipt.json"])
        receipt["final_text"] = final
        events = [json.loads(line) for line in bundle["transcript.jsonl"].splitlines()]
        for event in events:
            if event["type"] == "text":
                event["part"]["text"] = final
        bundle["transcript.jsonl"] = b"".join(c.canonical(event) for event in events)
        receipt["transcript_sha256"] = c.digest(bundle["transcript.jsonl"])
        exported = c.decode(bundle["session-export.json"])
        exported["messages"][0]["content"][0]["text"] = final
        bundle["session-export.json"] = c.canonical(exported)
        bundle["receipt.json"] = c.canonical(receipt)
        self.apply(self.collection(admitted, bundle), artifacts=bundle)
        return self.request("accept-collected", {"admission_id": admitted["admission_id"]}, "accept-final")

    def accept_final(self, request):
        self.record, result, changed = acceptance.apply(self.record, request, self.state_root)
        if changed:
            self.record["revision"] += 1
        return result

    def test_clean_review_accepted_and_replayed_without_readiness(self):
        request = self.collect_final(self.structured())
        result = self.accept_final(request)
        self.assertEqual(result["status"], "CLAIM_ACCEPTED")
        self.assertEqual(e.assess(self.record)["review_process"], "CLAIMS_COMPLETE")
        self.assertFalse(e.assess(self.record)["candidate_ready"])
        saved = copy.deepcopy(self.record)
        self.assertEqual(self.accept_final(request), result)
        self.assertEqual(saved, self.record)

    def test_defect_enters_history_and_original_owner_correction(self):
        finding = {"id": "F1", "invariant": "limit", "trigger": "oversized input", "path": "source.py:1",
                   "impact": "unbounded allocation", "evidence": "length checked after allocation"}
        request = self.collect_final(self.structured([finding]))
        self.accept_final(request)
        self.record.update(repo="fixture/project", branch="fixture", owned_paths=["source.py"], restricted_paths=[], acceptance_criteria=["bounded input"])
        self.assertEqual(e.assess(self.record)["status"], "HOLD")
        correction = e.correction_request(self.record)
        self.assertEqual(correction["owner"], "writer")
        self.assertEqual(correction["findings"][0]["finding"], finding)
        self.assertFalse(correction["write_authority"])

    def test_malformed_final_is_retained_but_not_accepted(self):
        request = self.collect_final('```json\n{"findings":[]}\n```')
        saved = copy.deepcopy(self.record)
        with self.assertRaises(Exception):
            self.accept_final(request)
        self.assertEqual(self.record, saved)
        self.assertEqual(len(self.record["runtime_collections"]["collections"]), 1)
        self.assertEqual(self.record["review_protocol"]["generations"][0]["reports"], {})

    def test_missing_coverage_and_extra_authority_refused(self):
        content = self.structured()
        del content["coverage"]["baseline-security"]
        content["candidate_ready"] = True
        request = self.collect_final(content)
        with self.assertRaises(Exception):
            self.accept_final(request)

    def test_stale_cancelled_and_conflicting_replay_refused(self):
        request = self.collect_final(self.structured())
        saved = copy.deepcopy(self.record)
        self.record["review_protocol"]["material_epoch"] += 1
        with self.assertRaises(Exception):
            self.accept_final(request)
        self.record = copy.deepcopy(saved)
        self.record["state"] = "Cancelled"
        with self.assertRaises(Exception):
            self.accept_final(request)
        self.record = saved
        self.accept_final(request)
        altered = copy.deepcopy(request)
        altered["payload"]["admission_id"] = "f" * 64
        with self.assertRaises(Exception):
            self.accept_final(altered)

    def test_missing_artifact_refuses_historical_acknowledgement(self):
        request = self.collect_final(self.structured())
        self.accept_final(request)
        collected = next(iter(self.record["runtime_collections"]["collections"].values()))
        path = self.state_root / "review-artifacts" / collected["artifacts"]["receipt.json"]
        path.chmod(0o600)
        path.write_bytes(b"corrupt")
        with self.assertRaises(Exception):
            self.accept_final(request)

    def test_detached_claim_and_tampered_link_refused(self):
        request = self.collect_final(self.structured())
        report = acceptance.final_report(self.record, request["payload"]["admission_id"], self.state_root / "review-artifacts", c, e)
        self.record, _, _ = e.apply(self.record, {**request, "action": "accept", "payload": report})
        self.record["revision"] += 1
        with self.assertRaises(Exception):
            self.accept_final(request)

    def test_public_cli_atomic_write_and_retry(self):
        request = self.collect_final(self.structured())
        env = {**os.environ, "ORCHESTRATOR_TEST_MODE": "1", "ORCHESTRATOR_STATE_DIR": str(self.state_root)}
        state_script = ROOT / "bin" / "orchestrator-state.py"
        def state(*args):
            return subprocess.run([sys.executable, "-I", "-B", str(state_script), *args], env=env, capture_output=True, text=True)
        self.assertEqual(state("create", "fixture", "--scope", "fixture:accept", "--kind", "review", "--head-sha", "b" * 40, "--base-sha", "a" * 40).returncode, 0)
        self.assertEqual(state("claim", "fixture", "--owner", "writer", "--pid", str(os.getpid())).returncode, 0)
        task = json.loads(state("show", "fixture").stdout)
        task.update(self.record)
        task["kind"] = "review"
        task["state"] = "Claimed"
        path = self.state_root / "tasks" / "fixture" / "task.json"
        path.write_bytes(c.canonical(task))
        request_path = self.root / "accept.json"
        request_path.write_bytes(c.canonical(request))
        command = [sys.executable, "-I", "-B", str(ROOT / "bin" / "review-accept.py"), "fixture", "--request", str(request_path)]
        first = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        before = path.read_bytes()
        replay = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertEqual(replay.returncode, 0, replay.stdout + replay.stderr)
        self.assertEqual(replay.stdout, first.stdout)
        self.assertEqual(path.read_bytes(), before)
        task = json.loads(path.read_bytes())
        collected = next(iter(task["runtime_collections"]["collections"].values()))
        artifact = self.state_root / "review-artifacts" / collected["artifacts"]["receipt.json"]
        artifact.chmod(0o600)
        artifact.write_bytes(b"lost evidence")
        assessment = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "bin" / "review-evidence.py"), "fixture"],
                                    env=env, capture_output=True, text=True)
        self.assertEqual(assessment.returncode, 3)
        self.assertEqual(json.loads(assessment.stdout)["status"], "UNVERIFIED")
        self.assertNotIn("CLAIMS_COMPLETE", assessment.stdout)


if __name__ == "__main__":
    unittest.main()
