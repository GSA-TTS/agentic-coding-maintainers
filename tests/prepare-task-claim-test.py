#!/usr/bin/env python3
"""Real core CLI schema-3 fixtures; run only in an independently isolated guest."""

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1]
SCRIPT = SOURCE / "scripts/prepare-task-claim.py"
SESSION = "private-session-canary"
CLAIM = "c" * 32
OPERATION = "d" * 32


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PreparationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="task-claim-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.state = self.root / ".orchestrator"
        self.skill = self.root / "core"
        shutil.copytree(SOURCE / ".agents/skills/workspace-orchestrator/bin", self.skill,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        self.core = self.skill / "orchestrator-state.py"
        self.env = {"PATH": os.defpath, "HOME": str(self.root), "TMPDIR": str(self.root),
                    "PYTHONDONTWRITEBYTECODE": "1", "ORCHESTRATOR_TEST_MODE": "1",
                    "ORCHESTRATOR_STATE_DIR": str(self.state)}
        checkout = self.root / "checkout"
        checkout.mkdir()
        self.core_cli("create", "private-task-canary", "--scope", "private-domain:scope-canary",
                      "--kind", "implementation", "--repo", "example/project",
                      "--branch", "feat/public", "--worktree", str(checkout),
                      "--base-sha", "a" * 40, "--head-sha", "a" * 40,
                      "--tracker-type", "issue", "--tracker-number", "117")
        self.task = self.core_cli("claim", "private-task-canary", "--owner", "private-human-label",
                                  "--pid", str(os.getpid()), "--session-id", SESSION,
                                  "--expected-generation", "0", "--expected-revision", "0")
        self.task = self.core_cli("transition", self.task["task_id"], "Implementing", *self.owned())
        self.original_worker = copy.deepcopy(self.task["worker"])
        self.task_path = self.state / "tasks" / self.task["task_id"] / "task.json"
        self.module = load("fixture_task_claim", SCRIPT)

    def core_cli(self, *args):
        outcome = subprocess.run([sys.executable, "-I", "-B", str(self.core), *args],
                                 cwd=self.root, env=self.env, capture_output=True,
                                 text=True, check=False, timeout=15)
        self.assertEqual(outcome.returncode, 0, (outcome.stdout, outcome.stderr))
        return json.loads(outcome.stdout)

    def owned(self):
        return ["--expected-worker-id", self.task["worker"]["worker_id"],
                "--expected-session-id", self.task["cooperative_binding"]["session_id"],
                "--expected-generation", str(self.task["cooperative_binding"]["generation"]),
                "--expected-revision", str(self.task["revision"])]

    def options(self):
        return {"authority-root": str(self.root), "invoking-root": str(self.root),
                "task-id": self.task["task_id"], "expected-revision": str(self.task["revision"]),
                "expected-worker-id": self.task["worker"]["worker_id"],
                "expected-session-id": self.task["cooperative_binding"]["session_id"],
                "expected-generation": str(self.task["cooperative_binding"]["generation"]),
                "repo": "example/project", "branch": "feat/public", "issue": "117",
                "actor": "octocat", "claim-id": CLAIM, "operation-id": OPERATION,
                "scope": "implementation"}

    def argv(self, overrides=None, extra=()):
        options = self.options()
        options.update(overrides or {})
        return [str(SCRIPT), *[item for key, value in options.items() if value is not None
                              for item in ("--" + key, value)], *extra]

    def snapshot(self):
        return {str(path.relative_to(self.state)): (path.lstat().st_ino, path.lstat().st_mode,
                                                    path.lstat().st_mtime_ns,
                                                    path.read_bytes() if path.is_file() else None)
                for path in self.state.rglob("*")}

    def invoke(self, overrides=None, extra=()):
        before = self.snapshot()
        outcome = subprocess.run([sys.executable, "-I", "-B", *self.argv(overrides, extra)],
                                 cwd=self.root, env=self.env, capture_output=True,
                                 text=True, check=False, timeout=15)
        self.assertEqual(outcome.stderr, "")
        self.assertEqual(self.snapshot(), before)
        output = json.loads(outcome.stdout)
        self.assertIs(output["mutation_authorized"], False)
        self.assertEqual(output["native_session_authentication"], "UNVERIFIED")
        self.assertEqual(output["current_actor_authentication"], "UNVERIFIED")
        worker = self.task["worker"] or self.original_worker
        for private in (str(self.root), self.task["task_id"], self.task["scope"], SESSION,
                        "private-human-label", worker["worker_id"],
                        worker["token"], self.task["leases"]["scope_token"]):
            self.assertNotIn(private, outcome.stdout)
        if output["status"] != "PREPARED_RETAINED_MATCH":
            self.assertNotIn("comment", output)
            self.assertIs(output["bound_retained_snapshot"], False)
        return outcome.returncode, output

    def write(self, path, value):
        path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    def assert_result(self, expected, overrides=None, extra=()):
        code, output = self.invoke(overrides, extra)
        self.assertEqual((code, output["status"], output["reason"]), expected)

    def test_actual_schema3_fixed_public_payload(self):
        code, output = self.invoke()
        self.assertEqual(code, 3)
        self.assertEqual(output["status"], "PREPARED_RETAINED_MATCH")
        self.assertIs(output["bound_retained_snapshot"], True)
        claim = {"version": 1, "action": "claim", "repo": "example/project", "issue": 117,
                 "branch": "feat/public", "actor": "octocat", "claim_id": CLAIM,
                 "operation_id": OPERATION, "task_ref": "issue:117", "scope": "implementation"}
        expected = self.module.codec.prepare(claim)
        expected.update(status="PREPARED_RETAINED_MATCH", bound_retained_snapshot=True,
                        native_session_authentication="UNVERIFIED", current_actor_authentication="UNVERIFIED")
        self.assertEqual(output, expected)
        self.assertEqual(output["comment"],
                         'Public coordination claim proposal (v1).\n'
                         'Operator review of every public field is required before posting.\n'
                         'This comment does not grant admission or mutation authority.\n\n'
                         '<!-- native-claim:v1 {"action":"claim","actor":"octocat",'
                         '"branch":"feat/public","claim_id":"cccccccccccccccccccccccccccccccc",'
                         '"issue":117,"operation_id":"dddddddddddddddddddddddddddddddd",'
                         '"repo":"example/project","scope":"implementation",'
                         '"task_ref":"issue:117","version":1} -->\n')

    def test_tracker_type_and_number_are_actual_task_metadata(self):
        original = copy.deepcopy(self.task)
        for tracker, number in (("pr", 117), ("none", 0), ("issue", 118)):
            self.task = dict(original, tracker_type=tracker, tracker_number=number)
            self.write(self.task_path, self.task)
            self.assert_result((4, "CONFLICT", "TRACKER_ISSUE_MISMATCH"))

    def test_inconsistent_selection_cannot_prepare_a_public_claim(self):
        with mock.patch.object(sys, "argv", self.argv()):
            args, claim = self.module.arguments()
        # A real successful preflight cannot coexist with a missing task. If an
        # internal composition violates that contract, retain the CLI refusal.
        for evidence, expected in (({"status": "CONFLICT", "reason": "REVISION_MISMATCH"},
                                     ("CONFLICT", "REVISION_MISMATCH")),
                                    ({"status": "STATIC_MATCH"},
                                     ("UNVERIFIED", "STORE_UNAVAILABLE"))):
            with self.subTest(evidence=evidence), \
                    mock.patch.object(self.module, "arguments", return_value=(args, claim)), \
                    mock.patch.object(self.module, "selected", return_value=(None, (1, 2))), \
                    mock.patch.object(self.module, "unchanged"), \
                    mock.patch.object(self.module.preflight, "inspect", return_value=evidence), \
                    mock.patch.object(self.module.codec, "prepare") as render, \
                    mock.patch("builtins.print") as printed:
                code = self.module.main()
                output = json.loads(printed.call_args.args[0])
                self.assertEqual((output["status"], output["reason"]), expected)
                self.assertEqual(code, 4 if expected[0] == "CONFLICT" else 3)
                self.assertNotIn("comment", output)
                render.assert_not_called()

    def test_explicit_repository_branch_kind_expectations(self):
        for overrides, reason in (({"repo": "other/project"}, "REPOSITORY_OR_BRANCH_MISMATCH"),
                                  ({"branch": "feat/other"}, "REPOSITORY_OR_BRANCH_MISMATCH"),
                                  ({"scope": "review"}, "TASK_KIND_SCOPE_MISMATCH")):
            self.assert_result((4, "CONFLICT", reason), overrides)

    def test_stale_revision_worker_session_and_generation(self):
        for overrides, reason in (({"expected-revision": "1"}, "REVISION_MISMATCH"),
                                  ({"expected-worker-id": "e" * 32}, "WORKER_MISMATCH"),
                                  ({"expected-session-id": "another-session"}, "SESSION_OR_GENERATION_MISMATCH"),
                                  ({"expected-generation": "2"}, "SESSION_OR_GENERATION_MISMATCH")):
            self.assert_result((4, "CONFLICT", reason), overrides)

    def test_wrong_root_and_borrowed_alias(self):
        other = self.root / "other"
        other.mkdir()
        self.assert_result((4, "CONFLICT", "ROOT_MISMATCH"), {"invoking-root": str(other)})
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        code, output = self.invoke({"authority-root": str(alias), "invoking-root": str(alias)})
        self.assertEqual((code, output["status"]), (3, "UNVERIFIED"))

    def test_owner_string_is_not_an_authenticated_actor(self):
        self.task["owner"] = "another-private-owner"
        self.write(self.task_path, self.task)
        self.assert_result((4, "CONFLICT", "WORKER_MISMATCH"))
        self.task["worker"]["owner"] = self.task["owner"]
        self.write(self.task_path, self.task)
        for group, lease in (("slots", "global_slot"), ("implementation", "implementation_lane")):
            self.write(self.state / group / f'{self.task["leases"][lease]}.lock/owner.json', self.task["worker"])
        # A consistent human owner label may differ from the explicitly entered public login.
        self.assertEqual(self.invoke()[1]["status"], "PREPARED_RETAINED_MATCH")

    def test_missing_global_and_implementation_slot(self):
        for group, lease in (("slots", "global_slot"), ("implementation", "implementation_lane")):
            path = self.state / group / f'{self.task["leases"][lease]}.lock/owner.json'
            raw = path.read_bytes()
            path.unlink()
            self.assert_result((3, "UNVERIFIED", "STORE_UNAVAILABLE"))
            path.write_bytes(raw)
            path.chmod(0o600)

    def test_swapped_retained_lane_and_global_tokens(self):
        for group, lease in (("slots", "global_slot"), ("implementation", "implementation_lane")):
            path = self.state / group / f'{self.task["leases"][lease]}.lock/owner.json'
            self.write(path, dict(self.task["worker"], token="e" * 32))
            self.assert_result((4, "CONFLICT", "RETAINED_LEASE_MISMATCH"))
            self.write(path, self.task["worker"])

    def test_public_identifiers_cannot_reuse_known_private_identifiers(self):
        tokens = (self.task["worker"]["worker_id"], self.task["worker"]["token"],
                  self.task["leases"]["scope_token"])
        for option in ("claim-id", "operation-id"):
            for token in tokens:
                self.assert_result((3, "UNVERIFIED", "PRIVATE_IDENTIFIER_REUSE"), {option: token})
        # A valid public-ID-shaped cooperative session must also be excluded.
        self.task["cooperative_binding"]["session_id"] = "f" * 32
        self.task["worker"]["session_id"] = "f" * 32
        self.write(self.task_path, self.task)
        for group, lease in (("slots", "global_slot"), ("implementation", "implementation_lane")):
            self.write(self.state / group / f'{self.task["leases"][lease]}.lock/owner.json', self.task["worker"])
        self.assert_result((3, "UNVERIFIED", "PRIVATE_IDENTIFIER_REUSE"), {"claim-id": "f" * 32})

    def test_schema2_and_unsupported_schema_refusals(self):
        original = copy.deepcopy(self.task)
        legacy = copy.deepcopy(original)
        legacy["schema_version"] = 2
        del legacy["cooperative_binding"]
        for key in ("session_id", "generation"):
            del legacy["worker"][key]
        self.write(self.task_path, legacy)
        self.assert_result((3, "UNVERIFIED", "UNEXPECTED_BOUND_EXPECTATIONS"))
        self.write(self.task_path, dict(original, schema_version=4))
        self.assert_result((3, "UNVERIFIED", "UNSUPPORTED_SCHEMA"))

    def test_idle_and_transitioning_tasks(self):
        options = self.options()
        self.task["transition_intent"] = "Reviewing"
        self.write(self.task_path, self.task)
        self.assert_result((3, "UNVERIFIED", "INACTIVE_OR_TRANSITIONING"))
        self.task.update(state="Blocked", transition_intent=None, worker=None)
        self.task["leases"].update(global_slot=None, implementation_lane=None)
        self.write(self.task_path, self.task)
        # Keep invocation expectations from the original actual claim.
        with mock.patch.object(self, "options", return_value=options):
            self.assert_result((3, "UNVERIFIED", "INACTIVE_OR_TRANSITIONING"))

    def test_pending_recovery_receipt_and_prior_retained_identifiers(self):
        fixtures = load("fixture_ownership_shapes", SOURCE / "tests/check-native-ownership-test.py")
        options = self.options()
        pending = fixtures.attach_recovery_receipt(self.task, phase="pending")
        self.write(self.task_path, pending)
        self.assert_result((3, "UNVERIFIED", "INACTIVE_OR_TRANSITIONING"))
        # A settled receipt can retain private identifiers from an older worker.
        self.task["revision"] = 7
        self.task["cooperative_binding"]["generation"] = 2
        self.task["worker"]["generation"] = 2
        settled = fixtures.attach_recovery_receipt(self.task)
        self.write(self.task_path, settled)
        for group, lease in (("slots", "global_slot"), ("implementation", "implementation_lane")):
            self.write(self.state / group / f'{self.task["leases"][lease]}.lock/owner.json', self.task["worker"])
        with mock.patch.object(self, "options", return_value=options):
            self.assert_result((4, "CONFLICT", "REVISION_MISMATCH"))
        self.assertEqual(self.invoke()[1]["status"], "PREPARED_RETAINED_MATCH")
        prior = settled["transition_recovery"]["worker"]["worker_id"]
        self.assert_result((3, "UNVERIFIED", "PRIVATE_IDENTIFIER_REUSE"), {"operation-id": prior})

    def test_real_phase_change_and_stale_handoff_expectations(self):
        options = self.options()
        self.task = self.core_cli("transition", self.task["task_id"], "Reviewing", *self.owned())
        with mock.patch.object(self, "options", return_value=options):
            self.assert_result((4, "CONFLICT", "REVISION_MISMATCH"))
        self.assertEqual(self.invoke()[1]["status"], "PREPARED_RETAINED_MATCH")
        self.task["cooperative_binding"].update(session_id="handoff-session", generation=2)
        self.task["worker"].update(self.task["cooperative_binding"])
        self.task["revision"] += 2
        self.write(self.task_path, self.task)
        self.write(self.state / "slots" / f'{self.task["leases"]["global_slot"]}.lock/owner.json', self.task["worker"])
        self.assert_result((4, "CONFLICT", "SESSION_OR_GENERATION_MISMATCH"),
                           {"expected-session-id": SESSION})

    def test_review_kind_uses_only_bounded_public_review_scope(self):
        self.task = self.core_cli("transition", self.task["task_id"], "Reviewing", *self.owned())
        self.task["kind"] = "review"
        self.write(self.task_path, self.task)
        code, output = self.invoke({"scope": "review"})
        self.assertEqual((code, output["status"]), (3, "PREPARED_RETAINED_MATCH"))
        self.assertEqual(self.module.codec.parse_marker(output["comment"])["scope"], "review")

    def test_unsafe_and_malformed_task_metadata_no_echo(self):
        original = self.task_path.read_bytes()
        for raw in (b'{"private-canary":', b'{}', b'\xff',
                    original.replace(b'"revision":', b'"revision": 3, "revision":')):
            self.task_path.write_bytes(raw)
            code, output = self.invoke()
            self.assertEqual((code, output["status"]), (3, "UNVERIFIED"))
        self.task_path.write_bytes(original)
        self.task_path.chmod(0o644)
        self.assert_result((3, "UNVERIFIED", "UNSAFE_STORE"))

    def test_duplicate_options_and_invalid_arguments_no_echo(self):
        for option, value in self.options().items():
            self.assert_result((3, "UNVERIFIED", "DUPLICATE_ARGUMENT"), extra=(f"--{option}={value}",))
        for overrides in ({"expected-revision": "01"}, {"expected-generation": "0"},
                          {"expected-session-id": None}, {"task-id": "../private"},
                          {"actor": "bad[bot]"}, {"scope": "private-domain"}):
            code, output = self.invoke(overrides)
            self.assertEqual((code, output["status"]), (3, "UNVERIFIED"))

    def test_change_between_preread_preflight_and_render_is_refused(self):
        args, claim = None, None
        with mock.patch.object(sys, "argv", self.argv()):
            args, claim = self.module.arguments()
        original = self.task_path.read_bytes()
        for component, attribute in ((self.module.preflight, "inspect"), (self.module.codec, "prepare")):
            real = getattr(component, attribute)

            def change(*values):
                output = real(*values)
                self.write(self.task_path, dict(self.task, next_action="concurrent change"))
                return output

            with mock.patch.object(component, attribute, side_effect=change):
                with self.assertRaisesRegex(self.module.preflight.Unverified, "CHANGED_DURING_READ"):
                    self.module.prepare(args, claim)
            self.task_path.write_bytes(original)

    def test_change_during_initial_safe_read_is_refused(self):
        with mock.patch.object(sys, "argv", self.argv()):
            args, claim = self.module.arguments()
        real = self.module.preflight.read_selected

        def change(*values):
            task = real(*values)
            self.write(self.task_path, dict(self.task, next_action="concurrent preread change"))
            return task

        with mock.patch.object(self.module.preflight, "read_selected", side_effect=change):
            with self.assertRaisesRegex(self.module.preflight.Unverified, "CHANGED_DURING_READ"):
                self.module.prepare(args, claim)


if __name__ == "__main__":
    unittest.main()
