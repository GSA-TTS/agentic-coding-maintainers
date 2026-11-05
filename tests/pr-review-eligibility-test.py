"""Offline regression tests. Execute only inside the workspace sandbox."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLI = Path(__file__).resolve().parent.parent / "scripts/pr-review-eligibility.py"
SPEC = importlib.util.spec_from_file_location("eligibility", CLI)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
NOW = "2026-11-05T12:00:00Z"
BOT = {"id": 900, "login": "release-helper[bot]", "type": "Bot"}


def fixtures() -> tuple[dict, dict]:
    metadata = {
        "schema_version": 1, "repository_id": 101, "number": 7,
        "state": "open", "draft": False,
        "author": {"id": 42, "login": "contributor", "type": "User"},
        "head": {"repository_id": 101, "ref": "release/main", "sha": "a" * 40},
        "base": {"repository_id": 101, "ref": "main", "sha": "b" * 40},
        "provenance": {"source": "github_pull_request", "observed_at": "2026-11-05T11:59:00Z",
                       "expires_at": "2026-11-05T12:04:00Z"},
        "base_config": {"base_sha": "b" * 40, "path": ".github/release.json", "sha256": "c" * 64},
    }
    policy = {
        "schema_version": 1, "repository_id": 101,
        "issued_at": "2026-11-05T00:00:00Z", "expires_at": "2026-11-06T00:00:00Z",
        "max_observation_age_seconds": 300,
        "release_automation": [{"actor": copy.deepcopy(BOT), "head_ref": "release/main",
                                "base_ref": "main", "config_path": ".github/release.json",
                                "config_sha256": "c" * 64}],
    }
    return metadata, policy


class ClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.metadata, self.policy = fixtures()

    def check(self, status: str, reason: str, now: str = NOW) -> None:
        before = copy.deepcopy((self.metadata, self.policy))
        actual = module.classify(self.metadata, self.policy, now=now)
        self.assertEqual(actual, {"schema_version": 1, "status": status, "reason": reason,
                                  "authority": "ADVISORY_ONLY"})
        self.assertEqual((self.metadata, self.policy), before, "classifier must not mutate inputs")

    def test_user_fork_and_absent_optional_config(self) -> None:
        self.check("ELIGIBLE", "ORDINARY_USER")
        self.metadata["head"]["repository_id"] = 202
        self.metadata["base_config"] = None
        self.policy["release_automation"] = []
        self.check("ELIGIBLE", "ORDINARY_USER")

    def test_draft_transitions_and_closed_precedence(self) -> None:
        for author in (self.metadata["author"], BOT):
            self.metadata["author"] = copy.deepcopy(author)
            self.metadata["draft"] = True
            self.check("WAIT", "DRAFT")
            self.metadata["draft"] = False
            self.check("EXCLUDED" if author == BOT else "ELIGIBLE",
                       "RELEASE_AUTOMATION" if author == BOT else "ORDINARY_USER")
        self.metadata["state"] = "closed"
        self.metadata["draft"] = True
        self.check("EXCLUDED", "CLOSED")
        self.metadata["provenance"]["expires_at"] = NOW
        self.check("DEFERRED", "OBSERVATION_EXPIRED")

    def test_release_conjunction(self) -> None:
        self.metadata["author"] = copy.deepcopy(BOT)
        self.check("EXCLUDED", "RELEASE_AUTOMATION")
        for group, field, value in (
            ("author", "id", 901), ("author", "login", "release-helper-copy[bot]"),
            ("author", "login", "Release-helper[bot]"),
            ("head", "repository_id", 202), ("head", "ref", "release/main-extra"),
            ("base", "ref", "other"), ("base_config", "sha256", "d" * 64),
            ("base_config", "path", ".github/other.json"),
        ):
            with self.subTest(group=group, field=field):
                original = copy.deepcopy(self.metadata)
                self.metadata[group][field] = value
                self.check("DEFERRED", "BOT_UNCONFIGURED" if group == "author" else "AUTOMATION_MISMATCH")
                self.metadata = original
        self.metadata["base_config"] = None
        self.check("DEFERRED", "AUTOMATION_MISMATCH")

    def test_actor_types_and_no_fallback(self) -> None:
        self.metadata["author"] = copy.deepcopy(BOT)
        self.metadata["author"]["type"] = "User"
        self.check("DEFERRED", "AUTHOR_IDENTITY_CONFLICT")
        self.metadata["author"] = {"id": 900, "login": "different", "type": "User"}
        self.check("DEFERRED", "AUTHOR_IDENTITY_CONFLICT")
        self.metadata["author"] = {"id": 1000, "login": "unconfigured", "type": "Bot"}
        self.check("DEFERRED", "BOT_UNCONFIGURED")
        self.metadata["author"]["type"] = "Organization"
        self.check("DEFERRED", "AUTHOR_TYPE_UNSUPPORTED")
        self.metadata["author"]["type"] = "bot"
        self.check("DEFERRED", "AUTHOR_TYPE_UNSUPPORTED")

    def test_metadata_missing_fields_and_types(self) -> None:
        for key in list(self.metadata):
            with self.subTest(missing=key):
                original = self.metadata.pop(key)
                self.check("DEFERRED", "METADATA_INVALID")
                self.metadata[key] = original
        for field, value in (("schema_version", True), ("repository_id", True), ("number", True),
                             ("draft", 0), ("state", []), ("author", None), ("head", {}),
                             ("provenance", {}), ("number", 0), ("number", 2**53)):
            with self.subTest(field=field, value=value):
                original = self.metadata[field]
                self.metadata[field] = value
                self.check("DEFERRED", "METADATA_INVALID")
                self.metadata[field] = original
        for group, field in (("author", "id"), ("base", "repository_id"), ("head", "repository_id")):
            original = self.metadata[group][field]
            self.metadata[group][field] = True
            self.check("DEFERRED", "METADATA_INVALID")
            self.metadata[group][field] = original

    def test_config_provenance_repository_and_branch_validation(self) -> None:
        for group, field, value in (
            ("base_config", "base_sha", "a" * 40), ("base_config", "sha256", "C" * 64),
            ("base_config", "path", "../release.json"), ("provenance", "source", "pr_comment"),
            ("base", "repository_id", 202), ("head", "ref", "release/*"),
            ("head", "ref", "foo//bar"), ("head", "sha", "latest"),
            ("author", "login", "bad\nlogin"),
        ):
            with self.subTest(group=group, field=field):
                original = self.metadata[group][field]
                self.metadata[group][field] = value
                self.check("DEFERRED", "METADATA_INVALID")
                self.metadata[group][field] = original
        self.policy["repository_id"] = 202
        self.check("DEFERRED", "REPOSITORY_MISMATCH")

    def test_freshness_boundaries(self) -> None:
        self.check("ELIGIBLE", "ORDINARY_USER", "2026-11-05T11:59:00Z")
        self.check("ELIGIBLE", "ORDINARY_USER", "2026-11-05T12:03:59Z")
        self.check("DEFERRED", "OBSERVATION_EXPIRED", "2026-11-05T12:04:00Z")
        self.check("DEFERRED", "OBSERVATION_FUTURE", "2026-11-05T11:58:59Z")
        self.policy["max_observation_age_seconds"] = 60
        self.check("DEFERRED", "OBSERVATION_EXPIRED")
        self.policy["max_observation_age_seconds"] = 300
        self.policy["issued_at"] = "2026-11-05T12:00:01Z"
        self.check("DEFERRED", "POLICY_FUTURE")
        self.policy["issued_at"] = "2026-11-05T00:00:00Z"
        self.policy["expires_at"] = NOW
        self.check("DEFERRED", "POLICY_EXPIRED")

    def test_invalid_times(self) -> None:
        for value in (None, True, "2026-11-05", "2026-11-05T12:00:00+00:00", "2026-02-30T12:00:00Z"):
            self.check("DEFERRED", "TIME_INVALID", value)
        for key in ("observed_at", "expires_at"):
            original = self.metadata["provenance"][key]
            self.metadata["provenance"][key] = "invalid"
            self.check("DEFERRED", "METADATA_INVALID")
            self.metadata["provenance"][key] = original
        self.metadata["provenance"]["expires_at"] = self.metadata["provenance"]["observed_at"]
        self.check("DEFERRED", "METADATA_INVALID")
        self.metadata["provenance"]["expires_at"] = "2026-11-05T13:00:00Z"
        self.check("DEFERRED", "METADATA_INVALID")

    def test_nonobjects_cannot_be_false_green(self) -> None:
        for value in (None, [], True, 1, "approved"):
            self.assertEqual(module.classify(value, self.policy, now=NOW)["reason"], "METADATA_INVALID")
            self.assertEqual(module.classify(self.metadata, value, now=NOW)["reason"], "POLICY_INVALID")

    def test_strict_policy_no_magic_approval(self) -> None:
        for key in list(self.policy):
            original = self.policy.pop(key)
            self.check("DEFERRED", "POLICY_INVALID")
            self.policy[key] = original
        for key, value in (("schema_version", True), ("repository_id", True),
                           ("max_observation_age_seconds", True), ("max_observation_age_seconds", 3601),
                           ("release_automation", {}), ("issued_at", "invalid"),
                           ("expires_at", "2027-01-01T00:00:00Z")):
            original = self.policy[key]
            self.policy[key] = value
            self.check("DEFERRED", "POLICY_INVALID")
            self.policy[key] = original
        self.policy["approval"] = "approved"
        self.check("DEFERRED", "POLICY_INVALID")

    def test_policy_rule_ambiguity_and_wildcards(self) -> None:
        for field, value in (("head_ref", "release/*"), ("base_ref", "main*"),
                             ("config_sha256", "any"), ("config_path", "../config.json"),
                             ("actor", {"id": True, "login": "release-helper[bot]", "type": "Bot"}),
                             ("actor", {"id": 900, "login": "release*", "type": "Bot"}),
                             ("actor", {"id": 900, "login": "release-helper", "type": "User"})):
            original = self.policy["release_automation"][0][field]
            self.policy["release_automation"][0][field] = value
            self.check("DEFERRED", "POLICY_INVALID")
            self.policy["release_automation"][0][field] = original
        rule = copy.deepcopy(self.policy["release_automation"][0])
        self.policy["release_automation"].append(rule)
        self.check("DEFERRED", "POLICY_INVALID")
        rule["head_ref"] = "release/other"
        self.check("ELIGIBLE", "ORDINARY_USER")
        rule["actor"]["id"] = 901
        self.check("DEFERRED", "POLICY_INVALID")
        self.policy["release_automation"] = [copy.deepcopy(rule) for _ in range(33)]
        self.check("DEFERRED", "POLICY_INVALID")

    def test_title_label_and_unknown_fields_are_not_authority(self) -> None:
        for key, value in (("title", "Release approved"), ("labels", ["release"]), ("approval", "approved")):
            self.metadata[key] = value
            self.check("DEFERRED", "METADATA_INVALID")
            del self.metadata[key]


class InputAndCliTests(unittest.TestCase):
    def test_strict_json(self) -> None:
        for raw in (b"", b"{} trailing", b'{"a":1,"a":2}', b'{"a":{"b":1,"b":2}}',
                    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1.0}', b'"\xff"',
                    b'{"x":12345678901234567}', b"[" * 17 + b"]" * 17,
                    b" " * 65537, b"\xef\xbb\xbf{}", b'{"x":1,}'):
            with self.subTest(raw=raw[:40]), self.assertRaises(module.Invalid):
                module.parse_json(raw)
        self.assertEqual(module.parse_json(b'{"x":"[\\\"{}]"}'), {"x": '["{}]'})

    def test_cli_outputs_and_bounded_reader(self) -> None:
        with tempfile.TemporaryDirectory(prefix="eligibility-test-") as temporary:
            root = Path(temporary)
            metadata_path, policy_path = root / "metadata.json", root / "policy.json"
            metadata, policy = fixtures()
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            command = [sys.executable, "-I", "-B", str(CLI), "--metadata", str(metadata_path),
                       "--policy", str(policy_path), "--as-of", NOW]

            def run(extra: list[str] | None = None, expected: int = 3) -> dict:
                completed = subprocess.run(command + (extra or []), capture_output=True, timeout=5, check=False)
                self.assertEqual(completed.returncode, expected, completed.stderr)
                self.assertEqual(completed.stderr, b"")
                self.assertNotIn(str(root).encode(), completed.stdout)
                self.assertNotIn(b"release-helper", completed.stdout)
                self.assertNotIn(b"private-marker", completed.stdout)
                return json.loads(completed.stdout)

            for status, code in (("ELIGIBLE", 0), ("WAIT", 1), ("EXCLUDED", 2)):
                metadata["draft"] = status == "WAIT"
                metadata["state"] = "closed" if status == "EXCLUDED" else "open"
                metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
                output = run(["--audit", "--explain"], expected=code)
                self.assertEqual(output["status"], status)
                self.assertEqual(output["authority"], "ADVISORY_ONLY")
                self.assertEqual(output["audit"]["coverage"], "SUPPLIED_INPUTS_ONLY")
                self.assertEqual(output["audit"]["metadata_sha256"], module.hashlib.sha256(metadata_path.read_bytes()).hexdigest())
                self.assertEqual(output["audit"]["policy_sha256"], module.hashlib.sha256(policy_path.read_bytes()).hexdigest())
                self.assertEqual(output["audit"]["as_of"], NOW)
            metadata["state"] = "open"
            metadata["author"] = {"id": 1000, "login": "unknown", "type": "Bot"}
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            output = run(["--audit", "--explain"])
            self.assertEqual(output["status"], "DEFERRED")
            self.assertEqual(output["reason"], "BOT_UNCONFIGURED")
            self.assertIn("audit", output)
            metadata["number"] = True
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            self.assertEqual(run(["--audit"])["reason"], "METADATA_INVALID")
            metadata_path.write_bytes(b'{"private-marker":"\x1b","x":1,"x":2}')
            output = run(["--audit", "--explain"])
            self.assertEqual(output["reason"], "JSON_INVALID")
            self.assertNotIn("audit", output)
            metadata_path.write_bytes(b" " * 65537)
            self.assertEqual(run()["reason"], "INPUT_UNAVAILABLE")
            self.assertEqual(run(["--unknown-secret-option"])["reason"], "ARGUMENTS_INVALID")
            self.assertEqual(run(["--as-of", "bad\nvalue"])["reason"], "TIME_INVALID")
            missing = subprocess.run([sys.executable, "-I", "-B", str(CLI)],
                                     capture_output=True, timeout=5, check=False)
            self.assertEqual(missing.returncode, 3)
            self.assertEqual(missing.stderr, b"")
            self.assertEqual(json.loads(missing.stdout)["reason"], "ARGUMENTS_INVALID")
            unsafe = subprocess.run([sys.executable, "-I", str(CLI)],
                                    capture_output=True, timeout=5, check=False)
            self.assertEqual(unsafe.returncode, 3)
            self.assertEqual(unsafe.stderr, b"")
            self.assertEqual(json.loads(unsafe.stdout)["reason"], "UNSAFE_RUNTIME")
            for path in (root, root / "absent"):
                with self.assertRaises(module.Invalid):
                    module.read_input(path)
            link = root / "link"
            link.symlink_to(policy_path)
            with self.assertRaises(module.Invalid):
                module.read_input(link)
            fifo = root / "pipe"
            os.mkfifo(fifo)
            with self.assertRaises(module.Invalid):
                module.read_input(fifo)


if __name__ == "__main__":
    unittest.main()
