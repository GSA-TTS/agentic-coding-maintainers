#!/usr/bin/env python3
"""Actual schema-3 core and fixed GET fixtures; isolated guest execution only."""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import importlib.util

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


local = load("approval_task_fixtures", ROOT / "tests/prepare-task-claim-test.py")
remote = load("approval_remote_fixtures", ROOT / "tests/observe-github-claims-test.py")
approval = load("approval_cli", ROOT / "scripts/prepare-approved-claim.py")


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.local = local.PreparationTest()
        self.local.setUp()
        self.addCleanup(self.local.doCleanups)
        self.remote = remote.ObservationTests()
        self.remote.setUp()
        self.addCleanup(self.remote.doCleanups)
        self.options = self.local.options()
        claim = dict(version=1, action="claim", repo="example/project", issue=117,
                     branch="feat/public", actor="octocat", claim_id=local.CLAIM,
                     operation_id=local.OPERATION, task_ref="issue:117", scope="implementation")
        self.options.update({"expected-actor-id": "7", "expected-repo-id": "400",
                             "expected-issue-id": "500", "reviewer": "public-reviewer",
                             "approved-body-sha256": remote.codec.digest(remote.codec.render(claim))})
        repo_url = remote.observer.API + "/repos/example/project"
        self.records = [{"id": 7, "node_id": "U_fixture", "login": "octocat", "type": "User"},
                        {"id": 400, "node_id": "R_fixture", "full_name": "example/project",
                         "url": repo_url, "updated_at": remote.ISSUE["updated_at"]},
                        dict(remote.ISSUE, node_id="I_fixture", url=repo_url + "/issues/117",
                             repository_url=repo_url, html_url="https://github.com/example/project/issues/117")]
        self.urls = [remote.observer.API + "/user", repo_url, repo_url + "/issues/117"] * 2
        self.env = dict(self.local.env, **self.remote.environment)
        self.env.update(HOME=str(self.local.root), TMPDIR=str(self.local.root))

    def argv(self, overrides=None, extra=()):
        options = dict(self.options, **(overrides or {}))
        return [str(ROOT / "scripts/prepare-approved-claim.py"),
                *[item for key, value in options.items() if value is not None
                  for item in ("--" + key, value)], "--approve-public-text", *extra]

    def steps(self):
        return [{"url": url, "raw": remote.http(record), "stderr": "secret-diagnostic-canary"}
                for url, record in zip(self.urls, self.records * 2)]

    def invoke(self, steps=None, overrides=None, extra=(), approved=True, isolated=True):
        if self.remote.calls.exists():
            self.remote.calls.unlink()
        self.remote.fixture.write_text(json.dumps(self.steps() if steps is None else steps))
        before = self.local.snapshot()
        argv = self.argv(overrides, extra)
        if not approved:
            argv.remove("--approve-public-text")
        outcome = subprocess.run([sys.executable, *(["-I"] if isolated else []), "-B", *argv],
                                 env=self.env, cwd=self.local.root, capture_output=True, timeout=10)
        self.assertFalse(outcome.stderr)
        self.assertEqual(before, self.local.snapshot())
        result = json.loads(outcome.stdout)
        self.assertIs(result["mutation_authorized"], False)
        for value in (local.SESSION, self.local.task["worker"]["worker_id"],
                      self.local.task["worker"]["token"], "private-task-canary", "feat/public",
                      "octocat", "public-reviewer", "example/project", "secret", str(self.local.root)):
            self.assertNotIn(value.encode(), outcome.stdout)
        calls = json.loads(self.remote.calls.read_text()) if self.remote.calls.exists() else []
        return outcome.returncode, result, calls

    def test_canonical_private_contract_and_exact_six_gets(self):
        code, result, calls = self.invoke()
        self.assertEqual((code, result["status"], calls), (3, "IDENTITY_BOUND_DECLARATION", self.urls))
        self.assertEqual((result["actor_id"], result["repository_id"], result["issue_id"]), (7, 400, 500))
        self.assertEqual(result["comment_sha256"], self.options["approved-body-sha256"])
        self.assertEqual(result["get_counts"], {"user": 2, "repository": 2, "issue": 2})
        for key in ("atomic_snapshot", "remote_effects_enabled", "persisted", "absence_authorizing"):
            self.assertIs(result[key], False)
        self.assertTrue(result["private_correlatable"])
        self.assertEqual(result["publisher_authority"], "UNVERIFIED")
        self.assertEqual(result["issuance_identity"], "UNVERIFIED")
        self.assertEqual(result["public_text_approval"], "DECLARED_UNAUTHENTICATED")
        self.assertNotIn("comment", result)

    def test_wrong_digest_stale_fences_and_roots_have_no_get(self):
        other = self.local.root / "other"
        other.mkdir()
        for overrides in ({"approved-body-sha256": "0" * 64}, {"expected-revision": "1"},
                          {"expected-worker-id": "e" * 32}, {"expected-generation": "2"},
                          {"expected-session-id": "stale-session"}, {"invoking-root": str(other)}):
            code, result, calls = self.invoke(overrides=overrides)
            self.assertIn(code, (3, 4))
            self.assertNotEqual(result["status"], "IDENTITY_BOUND_DECLARATION")
            self.assertEqual(calls, [])

    def test_all_required_options_and_duplicates_refused_before_get(self):
        for key, value in self.options.items():
            for overrides, extra in (({key: None}, ()), ({}, (f"--{key}={value}",))):
                code, result, calls = self.invoke(overrides=overrides, extra=extra)
                self.assertEqual((code, result["status"], calls), (3, "UNVERIFIED", []))
        self.assertEqual(self.invoke(approved=False)[2], [])
        self.assertEqual(self.invoke(extra=("--approve-public-text",))[1]["reason"], "DUPLICATE_ARGUMENT")
        for flag in ("--current-credentials", "--capture", "--ready", "--url"):
            self.assertEqual(self.invoke(extra=(flag, "secret"))[2], [])

    def test_forwarded_help_is_sanitized_even_with_missing_preparation_arguments(self):
        wrapper_flags = {"expected-actor-id", "expected-repo-id", "expected-issue-id",
                         "reviewer", "approved-body-sha256"}
        missing_preparation = {key: None for key in self.options if key not in wrapper_flags}
        for help_flag in ("--help", "-h"):
            for overrides in ({}, missing_preparation):
                code, result, calls = self.invoke(overrides=overrides, extra=(help_flag,))
                self.assertEqual((code, result["status"], result["reason"], calls),
                                 (3, "UNVERIFIED", "INVALID_ARGUMENTS", []))

    def test_id_fences_are_strict_positive_integers(self):
        for key in ("expected-actor-id", "expected-repo-id", "expected-issue-id"):
            for value in ("0", "-1", "true", "7.0", "07", str(2**63)):
                self.assertEqual(self.invoke(overrides={key: value})[2], [])
        for index in range(3):
            for identifier in (True, 7.0, "7", 0):
                steps = self.steps()
                steps[index]["raw"] = remote.http(dict(self.records[index], id=identifier))
                self.assertEqual(self.invoke(steps)[1]["reason"], "IMMUTABLE_IDENTITY_INVALID")

    def test_observed_identity_and_target_fences(self):
        changes = [(0, {"id": 8}), (0, {"login": "other"}), (0, {"type": "Bot"}),
                   (1, {"id": 401}), (1, {"full_name": "other/project"}),
                   (2, {"id": 501}), (2, {"pull_request": {}}), (2, {"number": True}),
                   (2, {"repository_url": "https://evil.invalid"})]
        for index, change in changes:
            steps = self.steps()
            steps[index]["raw"] = remote.http(dict(self.records[index], **change))
            self.assertEqual(self.invoke(steps)[1]["status"], "UNVERIFIED")

    def test_repeated_immutable_and_relevant_anchors(self):
        for index, key, value in ((0, "id", 8), (0, "node_id", "U_changed"),
                                 (1, "id", 401), (1, "node_id", "R_changed"),
                                 (1, "updated_at", "2026-11-01T00:00:01Z"),
                                 (2, "id", 501), (2, "node_id", "I_changed"),
                                 (2, "updated_at", "2026-11-01T00:00:01Z"),
                                 (2, "comments", 1), (2, "state", "closed"), (2, "locked", True)):
            steps = self.steps()
            steps[index + 3]["raw"] = remote.http(dict(self.records[index], **{key: value}))
            self.assertEqual(self.invoke(steps)[1]["status"], "UNVERIFIED")

    def test_closed_locked_observation_grants_no_readiness(self):
        self.records[2].update(state="closed", locked=True)
        _, result, _ = self.invoke()
        self.assertEqual(result["status"], "IDENTITY_BOUND_DECLARATION")
        self.assertTrue(result["issue_closed"] and result["issue_locked"])
        self.assertNotIn("ready", result)

    def test_task_changed_by_network_response_is_refused(self):
        # Fixture-only side effect at the actual fake-gh boundary, not a supplied summary.
        gh = self.remote.directory / "gh"
        gh.write_text(f"#!{sys.executable}\n" + remote.FAKE.replace(
            'calls.append(step["url"])',
            'p = Path(os.environ["TASK_FILE"]); t = json.loads(p.read_text()); '
            't["next_action"] = "concurrent-change"; p.write_text(json.dumps(t))\n'
            'calls.append(step["url"])'))
        self.env["TASK_FILE"] = str(self.local.task_path)
        with patch.object(self.local, "snapshot", return_value={}):
            code, result, calls = self.invoke()
        self.assertEqual((code, result["reason"]), (3, "LOCAL_SNAPSHOT_CHANGED"))
        self.assertEqual(len(calls), 3)

    def test_transport_failures_are_sanitized_and_bounded(self):
        for change, reason in (({"exit": 1, "raw": "secret-body"}, "API_READ_UNAVAILABLE"),
                               ({"stderr": "x" * (remote.observer.MAX_BYTES + 1)}, "OUTPUT_BYTE_BOUND"),
                               ({"raw": remote.http(self.records[0], "Link: secret\r\n")},
                                "IDENTITY_PAGINATION_REFUSED")):
            steps = self.steps()
            steps[0].update(change)
            self.assertEqual(self.invoke(steps)[1]["reason"], reason)

    def test_actual_transport_shared_deadline_and_environment(self):
        prepare = self.local.module
        observer = remote.observer
        with patch.object(sys, "argv", self.argv()):
            args, claim = approval.arguments(prepare)
        self.remote.fixture.write_text(json.dumps(self.steps()))
        original = observer.Transport
        original_parse = observer.parse_http
        deadlines = []
        parsed = []
        clock = [100.0]
        fixture_time = SimpleNamespace(monotonic=lambda: clock[0])

        def bounded(repo, issue, deadline):
            deadlines.append(deadline)
            return original(repo, issue, deadline)

        def parse_then_expire(*values, **kwargs):
            result = original_parse(*values, **kwargs)
            parsed.append(result)
            if len(parsed) == 2:
                # Both real subprocess responses completed and parsed. Expire the
                # original shared deadline before the third GET can launch.
                clock[0] = 131.0
            return result

        # Replace only these modules' clock references, not the global time module
        # used by subprocess/selector internals or the fake-gh child processes.
        with patch.object(approval, "time", fixture_time), \
                patch.object(observer, "time", fixture_time), \
                patch.object(observer, "Transport", side_effect=bounded), \
                patch.object(observer, "parse_http", side_effect=parse_then_expire):
            with self.assertRaisesRegex(observer.Unverified, "DEADLINE_EXCEEDED"):
                approval.collect(args, claim, prepare, observer)
        self.assertEqual(deadlines, [130.0])
        self.assertEqual(len(parsed), 2)
        self.assertEqual(json.loads(self.remote.calls.read_text()), self.urls[:2])
        # Normal gh credential/config fallback remains available, never certified secure.
        env = observer.environment()
        self.assertEqual(env["GH_TOKEN"], "fixture-credential")
        self.assertNotIn("GH_DEBUG", env)

    def test_nonisolated_has_no_get(self):
        self.assertEqual(self.invoke(isolated=False)[2], [])


if __name__ == "__main__":
    unittest.main()
