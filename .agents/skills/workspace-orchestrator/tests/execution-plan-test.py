#!/usr/bin/env python3
"""Frozen execution selection and current packet-bound obligation evidence."""

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"
spec = importlib.util.spec_from_file_location("execution_plan", BIN / "execution-plan.py")
assert spec and spec.loader
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)
c, e, observer, packet_module = [plan.load(name) for name in ("review-collect", "review-evidence", "execution-observe", "review-packet")]


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "source"
        self.repo.mkdir()
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        self.git("init", "-q")
        (self.repo / "baseline").write_text("baseline\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        base = self.git("rev-parse", "HEAD")
        (self.repo / "probe.py").write_text("print(6)\n")
        self.git("add", ".")
        self.git("commit", "-qm", "probe")
        head = self.git("rev-parse", "HEAD")
        packet = packet_module.capture(self.repo, "fixture/project", base, head, "direct")
        self.packet = packet_module.canonical(packet)
        self.record = {"task_id": "task", "repo": "fixture/project", "owner": "owner", "kind": "implementation",
                       "revision": 0, "state": "Reviewing", "worker": {}, "leases": {"global_slot": 0},
                       "head_sha": head, "base_sha": base, "worktree": str(self.repo), "transition_intent": None, "rework_count": 0}
        self.record, _, _ = e.apply(self.record, {"schema_version": 1, "operation_id": "begin", "expected_revision": 0,
            "action": "begin", "payload": {"packet": plan.digest(self.packet), "policy": packet["policy_sha256"],
                "head": head, "base": base, "obligations": sorted(e.BASELINE)}})
        self.record["revision"] += 1
        self.definition = {"schema_version": 1, "docker_binary": "/bin/docker", "docker_sha256": "a" * 64,
            "endpoint": "unix:///fixture.sock", "container_id": "b" * 64, "created": "date", "image_id": "sha256:" + "c" * 64,
            "environment": [], "mounts": [{"Source": str(self.repo), "Destination": "/candidate", "Type": "bind", "RW": False}],
            "cases": [{"id": "positive", "argv": ["/bin/python", "/candidate/probe.py"], "expected_stdout": "6\n", "expected_exit": 0, "timeout": 10}],
            "head": head, "base": base, "source_sha256": {"probe.py": plan.digest(b"print(6)\n")}}
        self.raw = plan.canonical(self.definition)
        self.sha = plan.digest(self.raw)
        obligations = {name: [] for name in e.BASELINE}
        obligations["correctness"] = [{"operation_id": "execution", "definition_sha256": self.sha, "cases": ["positive"]}]
        self.request = {"schema_version": 1, "operation_id": "plan", "expected_revision": 1, "action": "plan-execution",
                        "payload": {"generation": 1, "obligations": obligations}}

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                                        "-c", "commit.gpgsign=false", *args]).decode().strip()

    def admit(self):
        self.record, result, changed = plan.admit(self.record, self.request, self.state, self.packet, {self.sha: self.raw})
        if changed:
            self.record["revision"] += 1
        return result

    def execution(self, output=b"6\n"):
        self.plan_id = self.admit()["plan_id"]
        store = self.state / "review-artifacts"
        c.publish(store, output)
        c.publish(store, b"")
        attempt = {"request": {"operation_id": "execution", "definition_sha256": self.sha, "expected_revision": self.record["revision"]},
            "definition": self.definition, "phase": "SETTLED", "termination": "STOPPED_OBSERVED", "owner": "owner",
            "head": self.record["head_sha"], "base": self.record["base_sha"], "controller_sha256": plan.controller_manifest()["execution-observe.py"],
            "execution_plan": self.plan_id, "cases": [observer.evaluate(self.definition["cases"][0], output, b"", 0, None)],
            "launchers": [{"case": "positive", "pid": 123, "process_start": "start", "process_status": "alive", "identity": "actual Docker CLI child, not guest PID"}],
            "stop_observation": {"container_id": "b" * 64, "created": "date", "running": False},
            "result": {"oracle_verdict": "PASS" if output == b"6\n" else "FAIL", "applicable": True, "candidate_ready": False}}
        self.record["execution_observations"] = {"execution": attempt}
        self.record["revision"] += 3

    def test_positive_and_released_capacity_have_narrow_credit(self):
        self.execution()
        self.record.update(state="Ready for human review", worker=None, leases={"global_slot": None})
        before = copy.deepcopy(self.record)
        result = plan.assess(self.record, self.state)
        self.assertEqual(result["execution"]["correctness"]["status"], "PASS")
        self.assertEqual(result["execution"]["test-adequacy"]["status"], "NOT_REQUIRED")
        self.assertFalse(result["candidate_ready"])
        self.assertEqual(self.record, before)

    def test_failure_and_missing_evidence(self):
        self.execution(b"7\n")
        self.assertEqual(plan.assess(self.record, self.state)["status"], "FAIL")
        artifact = self.state / "review-artifacts" / plan.digest(b"7\n")
        artifact.chmod(0o600)
        artifact.write_bytes(b"corrupt")
        self.assertEqual(plan.assess(self.record, self.state)["status"], "UNVERIFIED")

    def test_plan_replay_and_no_posthoc_selection(self):
        result = self.admit()
        saved = copy.deepcopy(self.record)
        self.assertEqual(self.admit(), result)
        self.assertEqual(self.record, saved)
        changed = copy.deepcopy(self.request)
        changed["payload"]["obligations"]["correctness"] = []
        with self.assertRaises(Exception):
            plan.admit(self.record, changed, self.state, self.packet, {})
        self.record.pop("execution_plans")
        self.record["execution_observations"] = {"old": {"request": {"expected_revision": 1}}}
        changed["expected_revision"] = self.record["revision"]
        with self.assertRaisesRegex(Exception, "after execution"):
            plan.admit(self.record, changed, self.state, self.packet, {})

    def test_stale_epoch_owner_task_and_controller_refused(self):
        self.execution()
        saved = copy.deepcopy(self.record)
        for field, value in (("owner", "other"), ("task_id", "other"), ("repo", "other/project"), ("state", "Cancelled")):
            self.record = copy.deepcopy(saved)
            self.record[field] = value
            self.assertEqual(plan.assess(self.record, self.state)["status"], "UNVERIFIED", field)
        self.record = copy.deepcopy(saved)
        self.record["review_protocol"]["material_epoch"] += 2
        self.assertEqual(plan.assess(self.record, self.state)["status"], "UNVERIFIED")
        self.record = saved
        self.record["execution_observations"]["execution"]["controller_sha256"] = "f" * 64
        self.assertEqual(plan.assess(self.record, self.state)["status"], "UNVERIFIED")

    def test_no_empty_evidence_pass_or_invented_cases(self):
        self.request["payload"]["obligations"]["correctness"] = []
        self.record, _, _ = plan.admit(self.record, self.request, self.state, self.packet, {})
        self.record["revision"] += 1
        self.assertEqual(plan.assess(self.record, self.state)["status"], "UNVERIFIED")
        self.assertTrue(all(item["status"] == "NOT_REQUIRED" for item in plan.assess(self.record, self.state)["execution"].values()))

    def test_loss_marker_cannot_be_hidden_by_phase(self):
        self.execution()
        self.record["execution_observations"]["execution"]["evidence_loss"] = "previous loss"
        self.assertEqual(plan.assess(self.record, self.state)["status"], "UNVERIFIED")

    def test_definition_sources_must_match_committed_packet(self):
        (self.repo / "probe.py").write_text("print(7)\n")
        altered = copy.deepcopy(self.definition)
        altered["source_sha256"]["probe.py"] = plan.digest(b"print(7)\n")
        raw = plan.canonical(altered)
        sha = plan.digest(raw)
        self.request["payload"]["obligations"]["correctness"][0]["definition_sha256"] = sha
        with self.assertRaisesRegex(Exception, "packet contents"):
            plan.admit(self.record, self.request, self.state, self.packet, {sha: raw})

    def test_dispatch_requires_current_selected_definition(self):
        result = self.admit()
        self.assertEqual(plan.dispatch_plan(self.record, self.state, "execution", self.sha), result["plan_id"])
        with self.assertRaises(Exception):
            plan.dispatch_plan(self.record, self.state, "unselected", self.sha)
        with self.assertRaises(Exception):
            plan.dispatch_plan(self.record, self.state, "execution", "f" * 64)

    def test_deleted_plan_and_new_generation_cannot_reuse_execution(self):
        self.execution()
        saved = copy.deepcopy(self.record)
        self.record.pop("execution_plans")
        self.assertEqual(plan.assess(self.record, self.state)["status"], "UNVERIFIED")
        with self.assertRaisesRegex(Exception, "ledger is missing"):
            plan.dispatch_plan(self.record, self.state, "other", self.sha)
        self.record = saved
        generation = self.record["review_protocol"]["generations"][0]
        self.record, _, _ = e.apply(self.record, {"schema_version": 1, "operation_id": "begin-again", "expected_revision": self.record["revision"],
            "action": "begin", "payload": {name: generation[name] for name in ("packet", "policy", "base", "head", "obligations")}})
        self.record["revision"] += 1
        self.assertEqual(plan.assess(self.record, self.state)["status"], "UNVERIFIED")

    def test_actual_source_drift_cannot_keep_current_pass(self):
        self.execution()
        (self.repo / "probe.py").write_text("print(7)\n")
        self.assertEqual(plan.assess(self.record, self.state)["status"], "UNVERIFIED")

    def test_public_assessment_is_read_only_after_worker_release(self):
        self.execution()
        env = {**os.environ, "ORCHESTRATOR_TEST_MODE": "1", "ORCHESTRATOR_STATE_DIR": str(self.state)}
        command = [sys.executable, "-I", "-B", str(BIN / "orchestrator-state.py")]
        created = subprocess.run(command + ["create", "task", "--scope", "plan:fixture", "--kind", "review", "--repo", "fixture/project",
            "--worktree", str(self.repo), "--base-sha", self.record["base_sha"], "--head-sha", self.record["head_sha"]], env=env, capture_output=True, text=True)
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        task = json.loads(created.stdout)
        task.update(self.record)
        task.update(state="Ready for human review", worker=None, leases={"global_slot": None, "implementation_lane": None, "scope_token": "f" * 32})
        path = self.state / "tasks" / "task" / "task.json"
        path.write_bytes(plan.canonical(task))
        before = {str(file.relative_to(self.state)): file.read_bytes() for file in self.state.rglob("*") if file.is_file()}
        result = subprocess.run([sys.executable, "-I", "-B", str(BIN / "execution-plan.py"), "task"], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["execution"]["correctness"]["status"], "PASS")
        after = {str(file.relative_to(self.state)): file.read_bytes() for file in self.state.rglob("*") if file.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
