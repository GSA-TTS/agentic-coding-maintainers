#!/usr/bin/env python3
"""Controller retention positives, corruptions, stale attempts and replay."""

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

SOURCE = Path(__file__).resolve().parents[1] / "bin" / "review-collect.py"
spec = importlib.util.spec_from_file_location("review_collect", SOURCE)
assert spec and spec.loader
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
evidence = collector.load_module("review-evidence")


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state_root = self.root / "state"
        self.state_root.mkdir(mode=0o700)
        self.record = {"task_id": "fixture", "revision": 0, "base_sha": "a" * 40,
                       "head_sha": "b" * 40, "owner": "writer", "state": "Reviewing",
                       "kind": "implementation", "rework_count": 0, "transition_intent": None,
                       "worktree": str(self.root / "candidate")}
        self.source = b"result = 1\n"
        self.path_key = base64.b64encode(b"source.py").decode()
        packet = {"schema_version": 1, "kind": "committed-local-source", "base": "a" * 40,
                  "head": "b" * 40, "policy_sha256": "d" * 64, "changed_inventory": "COMPLETE",
                  "files": [{"path_base64": self.path_key, "after": {
                      "kind": "blob", "encoding": "utf-8", "content": self.source.decode(),
                      "bytes": len(self.source), "sha256": collector.digest(self.source)}}]}
        self.packet = collector.canonical(packet)
        for index, (action, payload) in enumerate((
            ("begin", {"packet": collector.digest(self.packet), "policy": "d" * 64,
                       "base": "a" * 40, "head": "b" * 40, "obligations": sorted(evidence.BASELINE)}),
            ("assign", {"generation": 1, "run_id": "run", "reviewer": "reviewer", "profile": "e" * 64,
                        "obligations": sorted(evidence.BASELINE), "adapter": "native-session", "session": "ses_fixed"}),
        )):
            self.record, _, _ = evidence.apply(self.record, {"schema_version": 1, "operation_id": f"e-{index}",
                                "expected_revision": self.record["revision"], "action": action, "payload": payload})
            self.record["revision"] += 1
        self.admit = self.request("admit", {"generation": 1, "run_id": "run", "binary_sha256": "f" * 64,
            "model": "fixture/model", "agent": "reviewer", "cwd": "/review",
            "sources": {"/candidate/source.py": {"path_base64": self.path_key, "side": "after"}}}, "admit-1")

    def request(self, action, payload, operation):
        return {"schema_version": 1, "operation_id": operation, "expected_revision": self.record["revision"],
                "action": action, "payload": payload}

    def apply(self, request, **kwargs):
        self.record, result, changed = collector.apply(self.record, request, self.state_root, **kwargs)
        if changed:
            self.record["revision"] += 1
        return result

    def bundle(self):
        final = '{"findings":[],"limitations":["static review"]}'
        events = [
            {"type": "tool_use", "sessionID": "ses_fixed", "part": {"tool": "read", "state": {
                "status": "completed", "input": {"path": "/candidate/source.py"},
                "output": "Read file /candidate/source.py, lines 1-1\n1: result = 1"}}},
            {"type": "text", "sessionID": "ses_fixed", "part": {"text": final}},
            {"type": "step_finish", "sessionID": "ses_fixed", "part": {
                "reason": "stop", "tokens": {"input": 100, "output": 10}}},
        ]
        transcript = b"".join(collector.canonical(event) for event in events)
        exported = collector.canonical({"info": {"id": "ses_fixed", "outcome": "succeeded", "agent": "reviewer",
            "model": {"providerID": "fixture", "id": "model"}, "tokens": {"input": 100, "output": 10}},
            "messages": [{"type": "assistant", "finish": "stop", "content": [{"type": "text", "text": final}]}]})
        receipt = {"binary_sha256": "f" * 64, "model": "fixture/model", "agent": "reviewer",
                   "source_sha256": {"/candidate/source.py": collector.digest(self.source)},
                   "sessions": ["ses_fixed"], "transcript_sha256": collector.digest(transcript),
                   "stderr_sha256": collector.digest(b""), "returncode": 0, "status": "REVIEW_OBSERVED",
                   "execution_credit": False, "candidate_ready": False, "source_reads": ["/candidate/source.py"],
                   "final_text": final, "tokens": {"input": 100, "output": 10}}
        return {"receipt.json": collector.canonical(receipt), "transcript.jsonl": transcript,
                "session-export.json": exported, "stderr.txt": b"", "export-stderr.txt": b""}

    def collection(self, admitted, bundle):
        return self.request("collect", {"admission_id": admitted["admission_id"],
                            "artifact_sha256": {name: collector.digest(data) for name, data in bundle.items()}}, "collect-1")

    def test_positive_retention_and_idempotent_replay(self):
        admitted = self.apply(self.admit, packet=self.packet)
        self.assertEqual(self.apply(self.admit), admitted)
        bundle = self.bundle()
        request = self.collection(admitted, bundle)
        result = self.apply(request, artifacts=bundle)
        self.assertEqual(result["status"], "OBSERVATION_COLLECTED")
        self.assertFalse(result["candidate_ready"])
        self.assertFalse(result["execution_credit"])
        saved = copy.deepcopy(self.record)
        self.assertEqual(self.apply(request), result)
        self.assertEqual(self.record, saved)
        for data in bundle.values():
            self.assertEqual((self.state_root / "review-artifacts" / collector.digest(data)).read_bytes(), data)

    def test_substitution_and_cancelled_attempt_refused(self):
        admitted = self.apply(self.admit, packet=self.packet)
        bundle = self.bundle()
        for field, value in (("sessions", ["ses_other"]), ("binary_sha256", "0" * 64), ("model", "other/model")):
            changed = dict(bundle)
            receipt = collector.decode(changed["receipt.json"])
            receipt[field] = value
            changed["receipt.json"] = collector.canonical(receipt)
            with self.subTest(field=field), self.assertRaises(collector.Unverified):
                self.apply(self.collection(admitted, changed), artifacts=changed)
        self.record["state"] = "Cancelled"
        with self.assertRaises(collector.Unverified):
            self.apply(self.collection(admitted, bundle), artifacts=bundle)

    def test_changed_head_epoch_and_request_conflict(self):
        admitted = self.apply(self.admit, packet=self.packet)
        changed = copy.deepcopy(self.admit)
        changed["payload"]["model"] = "other/model"
        with self.assertRaises(collector.Unverified):
            self.apply(changed)
        self.record["review_protocol"]["material_epoch"] += 1
        with self.assertRaisesRegex(Exception, "review comparison is stale"):
            self.apply(self.collection(admitted, self.bundle()), artifacts=self.bundle())

    def test_lost_artifact_and_lost_receipt_fail_closed(self):
        admitted = self.apply(self.admit, packet=self.packet)
        bundle = self.bundle()
        request = self.collection(admitted, bundle)
        self.apply(request, artifacts=bundle)
        saved = copy.deepcopy(self.record)
        del self.record["runtime_collections"]["operations"]["collect-1"]
        with self.assertRaises(collector.Unverified):
            self.apply(request)
        self.record = saved
        artifact = self.state_root / "review-artifacts" / collector.digest(bundle["transcript.jsonl"])
        artifact.chmod(0o600)
        artifact.write_bytes(b"truncated")
        with self.assertRaises(collector.Unverified):
            self.apply(request)

    def test_unreferenced_artifacts_do_not_create_collection(self):
        admitted = self.apply(self.admit, packet=self.packet)
        bundle = self.bundle()
        for data in bundle.values():
            collector.publish(self.state_root / "review-artifacts", data)
        self.assertEqual(self.record["runtime_collections"]["collections"], {})
        result = self.apply(self.collection(admitted, bundle), artifacts=bundle)
        self.assertEqual(result["status"], "OBSERVATION_COLLECTED")

    def test_wrong_packet_missing_bundle_symlink_refused(self):
        with self.assertRaises(collector.Unverified):
            self.apply(self.admit, packet=b"{}")
        admitted = self.apply(self.admit, packet=self.packet)
        bundle = self.bundle()
        del bundle["session-export.json"]
        with self.assertRaises(collector.Unverified):
            self.apply(self.collection(admitted, bundle), artifacts=bundle)
        link = self.root / "link"
        link.symlink_to(self.state_root, target_is_directory=True)
        with self.assertRaises(collector.Unverified):
            collector.read_bytes(link / "missing")

    def test_replaced_summary_and_dangling_collection_receipt(self):
        admitted = self.apply(self.admit, packet=self.packet)
        bundle = self.bundle()
        request = self.collection(admitted, bundle)
        self.apply(request, artifacts=bundle)
        saved = copy.deepcopy(self.record)
        self.record["runtime_collections"]["collections"][admitted["admission_id"]]["summary"]["candidate_ready"] = True
        with self.assertRaises(collector.Unverified):
            self.apply(request)
        self.record = saved
        del self.record["runtime_collections"]["collections"][admitted["admission_id"]]
        with self.assertRaises(collector.Unverified):
            self.apply(request)

    def test_current_request_must_match_bundle_and_packet_selection(self):
        bad = copy.deepcopy(self.admit)
        bad["payload"]["sources"]["/candidate/source.py"]["path_base64"] = "bm90LXByZXNlbnQ="
        with self.assertRaises(collector.Unverified):
            self.apply(bad, packet=self.packet)
        admitted = self.apply(self.admit, packet=self.packet)
        bundle = self.bundle()
        request = self.collection(admitted, bundle)
        bundle["stderr.txt"] = b"changed after request"
        with self.assertRaises(collector.Unverified):
            self.apply(request, artifacts=bundle)

    def test_cli_collects_and_replays_authoritative_task_revision(self):
        Path(self.record["worktree"]).mkdir()
        env = {**os.environ, "ORCHESTRATOR_TEST_MODE": "1", "ORCHESTRATOR_STATE_DIR": str(self.state_root)}
        state = SOURCE.with_name("orchestrator-state.py")

        def command(*args):
            return subprocess.run([sys.executable, "-I", "-B", str(state), *args], env=env,
                                  capture_output=True, text=True, check=False)

        created = command("create", "fixture", "--kind", "review", "--scope", "fixture:collection",
                                 "--head-sha", "b" * 40, "--base-sha", "a" * 40,
                                 "--worktree", self.record["worktree"])
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        self.assertEqual(command("claim", "fixture", "--owner", "writer", "--pid", str(os.getpid())).returncode, 0)
        task_path = self.state_root / "tasks" / "fixture" / "task.json"
        task = json.loads(command("show", "fixture").stdout)
        task.update(revision=self.record["revision"], review_protocol=self.record["review_protocol"])
        task_path.write_bytes(collector.canonical(task))
        request_path = self.root / "request.json"
        packet_path = self.root / "packet.json"
        packet_path.write_bytes(self.packet)
        request_path.write_bytes(collector.canonical(self.admit))
        invoked = subprocess.run([sys.executable, "-I", "-B", str(SOURCE), "fixture", "--request", str(request_path),
                                  "--packet", str(packet_path)], env=env, capture_output=True, text=True, check=False)
        self.assertEqual(invoked.returncode, 0, invoked.stdout + invoked.stderr)
        admitted = json.loads(invoked.stdout)
        self.record = json.loads(command("show", "fixture").stdout)
        bundle = self.bundle()
        staging = self.root / "bundle"
        staging.mkdir()
        for name, data in bundle.items():
            (staging / name).write_bytes(data)
        request_path.write_bytes(collector.canonical(self.collection(admitted, bundle)))
        args = [sys.executable, "-I", "-B", str(SOURCE), "fixture", "--request", str(request_path), "--bundle", str(staging)]
        accepted = subprocess.run(args, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        before = task_path.read_bytes()
        replay = subprocess.run(args, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(replay.returncode, 0, replay.stdout + replay.stderr)
        self.assertEqual(replay.stdout, accepted.stdout)
        self.assertEqual(task_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
