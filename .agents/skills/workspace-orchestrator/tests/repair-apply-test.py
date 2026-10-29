#!/usr/bin/env python3
"""Owner replacement, retained intent and conservative recovery tests."""

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

BIN = Path(__file__).resolve().parents[1] / "bin"
spec = importlib.util.spec_from_file_location("repair_apply", BIN / "repair-apply.py")
assert spec and spec.loader
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)
e = repair.load("review-evidence")


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "candidate"
        self.repo.mkdir()
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        self.git("init", "-q", "-b", "task")
        (self.repo / "source.py").write_bytes(b"result = 1\n")
        (self.repo / "test.py").write_bytes(b"expected = 1\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        head = self.git("rev-parse", "HEAD")
        self.record = dict(task_id="task", repo="fixture/project", owner="owner", kind="implementation", branch="task", worktree=str(self.repo),
            state="Reviewing", revision=0, head_sha=head, base_sha=head, worker=None, leases={}, rework_count=0, transition_intent=None,
            owned_paths=["source.py", "test.py"], restricted_paths=[], acceptance_criteria=["result must be 2"], reviewed_sha=head, reviewers=["qa"], validation=["old pass"])
        begin = dict(packet="a" * 64, policy="b" * 64, head=head, base=head, obligations=sorted(e.BASELINE))
        assign = dict(generation=1, run_id="review", reviewer="qa", profile="c" * 64, session="ses_review", adapter="native-session", obligations=sorted(e.BASELINE))
        report = dict(generation=1, run_id="review", packet="a" * 64, policy="b" * 64, profile="c" * 64, session="ses_review",
            coverage=dict.fromkeys(e.BASELINE, "reviewed"), findings=[dict(id="F1", invariant="result is 2", trigger="call", path="source.py:1", impact="wrong result", evidence="returns1")],
            dispositions=[], limitations=[])
        for index, (action, payload) in enumerate((("begin", begin), ("assign", assign), ("accept", report))):
            self.record, _, _ = e.apply(self.record, dict(schema_version=1, operation_id=f"e-{index}", expected_revision=self.record["revision"], action=action, payload=payload))
            self.record["revision"] += 1
        self.record.update(state="Rework", rework_count=1)
        self.record, prepared = repair.prepare(self.record, self.state, self.record["revision"])
        self.correction_id = prepared["correction_id"]
        self.record["revision"] += 1
        self.record.update(state="Implementing", worker={"owner": "owner", "token": "f" * 32}, leases={"global_slot": 0, "implementation_lane": 0})
        self.persisted = copy.deepcopy(self.record)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                                        "-c", "commit.gpgsign=false", *args]).decode().strip()

    def request(self, two=False):
        replacements = [dict(path="source.py", before_sha256=repair.digest(b"result = 1\n"), after_base64=base64.b64encode(b"result = 2\n").decode())]
        if two:
            replacements.append(dict(path="test.py", before_sha256=repair.digest(b"expected = 1\n"), after_base64=base64.b64encode(b"expected = 2\n").decode()))
        raw = repair.canonical(dict(schema_version=1, correction_id=self.correction_id, replacements=replacements))
        return dict(schema_version=1, operation_id="repair", expected_revision=self.record["revision"], correction_id=self.correction_id, bundle_sha256=repair.digest(raw)), raw

    def persist(self, value):
        value["revision"] += 1
        self.persisted = copy.deepcopy(value)

    def test_positive_two_files_invalidate_and_require_new_head(self):
        request, raw = self.request(two=True)
        epoch = self.record["review_protocol"]["material_epoch"]
        result = repair.apply_repair(self.record, self.state, request, raw, self.persist)
        self.assertEqual(result["status"], "APPLIED_UNREVIEWED")
        self.assertFalse(result["candidate_ready"])
        self.assertEqual((self.repo / "source.py").read_bytes(), b"result = 2\n")
        self.assertEqual((self.repo / "test.py").read_bytes(), b"expected = 2\n")
        self.assertEqual(self.record["review_protocol"]["material_epoch"], epoch + 1)
        self.assertEqual(e.assess(self.record)["status"], "UNVERIFIED")
        self.assertEqual(self.record["reviewers"], [])
        with self.assertRaises(Exception):
            e.apply(self.record, dict(schema_version=1, operation_id="begin2", expected_revision=self.record["revision"], action="begin", payload={}))
        with mock.patch.object(repair, "replace_one", side_effect=AssertionError("must not rewrite")):
            self.assertEqual(repair.apply_repair(self.record, self.state, request, raw, self.persist), result)

    def test_all_preconditions_checked_before_any_write(self):
        request, raw = self.request(two=True)
        value = json.loads(raw)
        value["replacements"][1]["before_sha256"] = "0" * 64
        raw = repair.canonical(value)
        request["bundle_sha256"] = repair.digest(raw)
        with self.assertRaises(repair.Unverified):
            repair.apply_repair(self.record, self.state, request, raw, self.persist)
        self.assertEqual((self.repo / "source.py").read_bytes(), b"result = 1\n")
        self.assertEqual(self.record["repair_protocol"]["operations"], {})

    def test_interruption_after_first_write_is_partial_and_never_reapplied(self):
        request, raw = self.request(two=True)
        original = repair.replace_one
        def fail_second(root, entry, mode):
            if entry["path"] == "test.py":
                raise OSError("interrupted")
            original(root, entry, mode)
        with mock.patch.object(repair, "replace_one", side_effect=fail_second):
            with self.assertRaises(OSError):
                repair.apply_repair(self.record, self.state, request, raw, self.persist)
        self.record = self.persisted
        self.assertEqual(self.record["repair_protocol"]["operations"]["repair"]["phase"], "APPLYING")
        with mock.patch.object(repair, "replace_one", side_effect=AssertionError("no retry writes")):
            self.assertEqual(repair.apply_repair(self.record, self.state, request, raw, self.persist)["status"], "APPLYING")
        self.assertEqual(repair.reconcile(self.record, self.state, "repair", self.persist)["status"], "PARTIAL")
        with self.assertRaises(Exception):
            repair.load("orchestrator-state").require_repair_settled(self.record)

    def test_intent_persistence_failure_writes_nothing(self):
        request, raw = self.request()
        with self.assertRaises(OSError):
            repair.apply_repair(self.record, self.state, request, raw, lambda _: (_ for _ in ()).throw(OSError("disk")))
        self.assertEqual((self.repo / "source.py").read_bytes(), b"result = 1\n")

    def test_paths_links_scope_and_metadata_refused(self):
        for path in ("../source.py", "/source.py", "a//b", ".git/config", "src/AGENTS.md", "a\\b", "a/../b"):
            with self.subTest(path=path), self.assertRaises(repair.Unverified):
                repair.relative_path(path)
        os.link(self.repo / "source.py", self.root / "alias")
        with self.assertRaises(repair.Unverified):
            repair.inspect_targets(self.repo, [dict(path="source.py")])
        (self.repo / "linked").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            repair.inspect_targets(self.repo, [dict(path="linked/alias")])

    def test_changed_owner_or_scope_refused(self):
        request, raw = self.request()
        for field, value in (("owner", "other"), ("owned_paths", ["test.py"]), ("rework_count", 2), ("state", "Rework")):
            changed = copy.deepcopy(self.record)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(repair.Unverified):
                repair.apply_repair(changed, self.state, request, raw, self.persist)

    def test_all_after_reconciliation_does_not_resolve_findings(self):
        request, raw = self.request()
        calls = 0
        def persist(value):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("lost final receipt")
            self.persist(value)
        with self.assertRaises(OSError):
            repair.apply_repair(self.record, self.state, request, raw, persist)
        self.record = self.persisted
        self.assertEqual(repair.reconcile(self.record, self.state, "repair", self.persist)["status"], "APPLIED_UNREVIEWED")
        self.assertIn("F1", e.finding_history(self.record))

    def test_public_rework_lifecycle_repair_and_new_head(self):
        env = {**os.environ, "ORCHESTRATOR_TEST_MODE": "1", "ORCHESTRATOR_STATE_DIR": str(self.state)}
        def command(tool, *args):
            return subprocess.run([sys.executable, "-I", "-B", str(BIN / tool), *args], env=env, capture_output=True, text=True)
        def state(*args):
            return command("orchestrator-state.py", *args)
        created = state("create", "task", "--scope", "repair:fixture", "--kind", "implementation", "--repo", "fixture/project",
                        "--worktree", str(self.repo), "--branch", "task", "--base-sha", self.record["base_sha"],
                        "--head-sha", self.record["head_sha"], "--owned-path", "source.py", "--owned-path", "test.py", "--acceptance", "result must be 2")
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(state("claim", "task", "--owner", "owner", "--pid", str(os.getpid())).returncode, 0)
        self.assertEqual(state("transition", "task", "Implementing").returncode, 0)
        self.assertEqual(state("transition", "task", "Reviewing").returncode, 0)
        record = json.loads(state("show", "task").stdout)
        record["review_protocol"] = self.record["review_protocol"]
        task_path = self.state / "tasks" / "task" / "task.json"
        task_path.write_bytes(repair.canonical(record))
        self.assertEqual(state("transition", "task", "Rework").returncode, 0)
        record = json.loads(state("show", "task").stdout)
        prepared = command("repair-apply.py", "task", "prepare", "--expected-revision", str(record["revision"]))
        self.assertEqual(prepared.returncode, 0, prepared.stdout)
        self.assertEqual(state("claim", "task", "--owner", "other", "--pid", str(os.getpid())).returncode, 4)
        self.assertEqual(state("claim", "task", "--owner", "owner", "--pid", str(os.getpid())).returncode, 0)
        self.assertEqual(state("transition", "task", "Implementing").returncode, 0)
        self.record = json.loads(state("show", "task").stdout)
        self.correction_id = json.loads(prepared.stdout)["correction_id"]
        request, raw = self.request(two=True)
        request_path, bundle_path = self.root / "request.json", self.root / "bundle.json"
        request_path.write_bytes(repair.canonical(request))
        bundle_path.write_bytes(raw)
        applied = command("repair-apply.py", "task", "apply", "--request", str(request_path), "--bundle", str(bundle_path))
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        before = task_path.read_bytes()
        replay = command("repair-apply.py", "task", "apply", "--request", str(request_path), "--bundle", str(bundle_path))
        self.assertEqual(replay.returncode, 0, replay.stdout)
        self.assertEqual(task_path.read_bytes(), before)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.record["head_sha"])
        self.git("add", ".")
        self.git("commit", "-qm", "owner repair")
        updated = state("update-head", "task", self.git("rev-parse", "HEAD"))
        self.assertEqual(updated.returncode, 0, updated.stderr)
        self.assertIn("F1", e.finding_history(json.loads(updated.stdout)))

    def test_third_admitted_repair_can_be_reviewed(self):
        record = copy.deepcopy(self.record)
        record.pop("repair_protocol")
        record["rework_count"] = 3
        generation = record["review_protocol"]["generations"][0]
        updated, _, _ = e.apply(record, dict(schema_version=1, operation_id="final-review", expected_revision=record["revision"], action="begin",
            payload={name:generation[name] for name in ("packet", "policy", "head", "base", "obligations")}))
        self.assertEqual(len(updated["review_protocol"]["generations"]), 2)


if __name__ == "__main__":
    unittest.main()
