"""Offline fixtures for the proposed codec and raw GitHub issue-comment shape."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/native-claim.py"
SPEC = importlib.util.spec_from_file_location("native_claim", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CODEC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CODEC)

# Public fictitious identifiers; REST field names follow the official schema:
# https://docs.github.com/en/rest/issues/comments#list-issue-comments
CLAIM = {"version": 1, "action": "claim", "repo": "acme/widgets", "issue": 117,
         "claim_id": "0123456789abcdef0123456789abcdef",
         "operation_id": "fedcba9876543210fedcba9876543210", "actor": "octocat",
         "branch": "feat/native-claim", "task_ref": "issue:116", "scope": "implementation"}
EXPECTED_BODY = (
    "Public coordination claim proposal (v1).\n"
    "Operator review of every public field is required before posting.\n"
    "This comment does not grant admission or mutation authority.\n\n"
    '<!-- native-claim:v1 {"action":"claim","actor":"octocat",'
    '"branch":"feat/native-claim","claim_id":"0123456789abcdef0123456789abcdef",'
    '"issue":117,"operation_id":"fedcba9876543210fedcba9876543210",'
    '"repo":"acme/widgets","scope":"implementation","task_ref":"issue:116",'
    '"version":1} -->\n'
)


def comment(body=EXPECTED_BODY, comment_id=101, author="octocat"):
    # Representative raw REST record, including common fields not consumed by
    # this codec. Values are fixture data, not a claim of authentic capture.
    return {"id": comment_id, "node_id": "IC_fixture", "body": body,
            "url": f"https://api.github.com/repos/acme/widgets/issues/comments/{comment_id}",
            "html_url": f"https://github.com/acme/widgets/issues/117#issuecomment-{comment_id}",
            "issue_url": "https://api.github.com/repos/acme/widgets/issues/117",
            "user": {"login": author, "id": 1, "node_id": "U_fixture",
                     "avatar_url": "https://avatars.githubusercontent.com/u/1?v=4",
                     "gravatar_id": "", "url": f"https://api.github.com/users/{author}",
                     "html_url": f"https://github.com/{author}", "type": "User",
                     "site_admin": False},
            "created_at": "2026-11-06T00:00:00Z", "updated_at": "2026-11-06T00:00:00Z",
            "author_association": "NONE", "performed_via_github_app": None,
            "reactions": {"total_count": 0, "+1": 0, "-1": 0}}


class NativeClaimTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-claim-fixture-")
        self.addCleanup(self.temp.cleanup)
        # macOS /var is a symlink; pass the physical temporary directory.
        self.directory = Path(self.temp.name).resolve()
        self.capture = self.directory / "comments.json"

    def run_cli(self, command="reconcile", value=None, extra=(), claim=None, equals=False):
        claim = CLAIM if claim is None else claim
        argv = [sys.executable, "-I", "-B", str(SCRIPT), command]
        for key in ("repo", "issue", "claim_id", "operation_id", "actor", "branch", "task_ref", "scope"):
            option = "--" + key.replace("_", "-")
            argv.extend([option + "=" + str(claim[key])] if equals else [option, str(claim[key])])
        if command == "reconcile":
            data = json.dumps([comment()] if value is None else value).encode("utf-8")
            self.capture.write_bytes(data)
            argv.extend(["--comments=" + str(self.capture)] if equals else ["--comments", str(self.capture)])
        result = subprocess.run(argv + list(extra), capture_output=True, check=False, timeout=5)
        self.assertEqual(result.stderr, b"")
        output = json.loads(result.stdout)
        self.assertIs(output["mutation_authorized"], False)
        self.assertEqual(output["remote_coverage"], "unmeasured")
        return result, output

    def check_status(self, comments, status, reason=None, **kwargs):
        output = CODEC.reconcile(comments, CLAIM, **kwargs)
        self.assertEqual(output["status"], status)
        self.assertIs(output["mutation_authorized"], False)
        self.assertEqual(output["remote_coverage"], "unmeasured")
        if reason is not None:
            self.assertIn(reason, output["conflict_reasons"])
        return output

    def rejected(self, comments, reason):
        with self.assertRaisesRegex(CODEC.Unverified, "^" + reason + "$"):
            CODEC.reconcile(comments, CLAIM)

    def test_exact_deterministic_prepare(self):
        first, output = self.run_cli("prepare")
        second, _ = self.run_cli("prepare")
        self.assertEqual(first.returncode, 0)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(output["comment"], EXPECTED_BODY)
        self.assertEqual(output["comment_sha256"], hashlib.sha256(EXPECTED_BODY.encode()).hexdigest())
        self.assertEqual(output["public_review"], "REQUIRED")
        self.assertEqual(set(output), {"status", "reason", "remote_coverage", "mutation_authorized",
                                       "comment", "comment_sha256", "public_review"})

    def test_exact_marker_roundtrip(self):
        self.assertEqual(CODEC.parse_marker(EXPECTED_BODY), CLAIM)
        self.assertEqual(CODEC.render(dict(reversed(list(CLAIM.items())))), EXPECTED_BODY)

    def test_review_scope_roundtrip(self):
        claim = dict(CLAIM, scope="review")
        body = CODEC.prepare(claim)["comment"]
        self.assertEqual(CODEC.parse_marker(body), claim)
        self.assertEqual(CODEC.reconcile([comment(body)], claim)["status"], "OBSERVED_MATCH")

    def test_real_rest_shape_match_still_exit_three(self):
        result, output = self.run_cli()
        self.assertEqual(result.returncode, 3)
        self.assertEqual(output["status"], "OBSERVED_MATCH")
        self.assertEqual(output["observed_match_ids"], [101])

    def test_only_relevant_rest_fields_required(self):
        raw = comment()
        selected = {key: raw[key] for key in ("id", "user", "body", "issue_url")}
        selected["user"] = {"login": "octocat"}
        self.check_status([selected], "OBSERVED_MATCH")

    def test_unknown_fields_never_echoed(self):
        raw = comment()
        raw["unrelated"] = "DO_NOT_ECHO"
        raw["user"]["email"] = "DO_NOT_ECHO"
        result, output = self.run_cli(value=[raw])
        self.assertEqual(output["status"], "OBSERVED_MATCH")
        self.assertNotIn(b"DO_NOT_ECHO", result.stdout)
        self.assertNotIn(b"octocat", result.stdout)

    def test_empty_is_unverified(self):
        result, output = self.run_cli(value=[])
        self.assertEqual(result.returncode, 3)
        self.assertEqual(output["status"], "UNVERIFIED")
        self.assertEqual(output["reason"], "NO_MATCH_OBSERVED")

    def test_ordinary_partial_capture_is_unverified(self):
        self.check_status([comment("Ordinary discussion, not coordination metadata.")], "UNVERIFIED")

    def test_completeness_envelope_refused(self):
        result, output = self.run_cli(value={"complete": True, "comments": [comment()]})
        self.assertEqual(result.returncode, 3)
        self.assertEqual(output["reason"], "INVALID_CAPTURE")

    def test_other_actor_claim_conflicts(self):
        other = dict(CLAIM, actor="hubot", claim_id="a" * 32, operation_id="b" * 32)
        self.check_status([comment(CODEC.render(other), author="hubot")], "CONFLICT",
                          "OTHER_CLAIM_OR_PAYLOAD")

    def test_same_actor_different_claim_conflicts(self):
        other = dict(CLAIM, claim_id="a" * 32, operation_id="b" * 32)
        result, output = self.run_cli(value=[comment(), comment(CODEC.render(other), 102)])
        self.assertEqual(result.returncode, 4)
        self.assertEqual(output["status"], "CONFLICT")
        self.assertEqual(output["observed_match_ids"], [101])

    def test_author_spoof_conflicts(self):
        self.check_status([comment(author="hubot")], "CONFLICT", "AUTHOR_MISMATCH")
        self.check_status([comment(author="Octocat")], "CONFLICT", "AUTHOR_MISMATCH")

    def test_same_claim_differing_payload_conflicts(self):
        other = dict(CLAIM, branch="fix/other", operation_id="b" * 32)
        self.check_status([comment(), comment(CODEC.render(other), 102)], "CONFLICT",
                          "CLAIM_PAYLOAD_MISMATCH")

    def test_duplicate_operation_conflicts(self):
        self.check_status([comment(), comment(comment_id=102)], "CONFLICT", "DUPLICATE_OPERATION_ID")
        other = dict(CLAIM, claim_id="a" * 32)
        self.check_status([comment(), comment(CODEC.render(other), 102)], "CONFLICT",
                          "DUPLICATE_OPERATION_ID")

    def test_duplicate_comment_ids_refused(self):
        self.rejected([comment(), comment()], "DUPLICATE_COMMENT_ID")

    def test_wrong_rest_identity_refused(self):
        for url in ("https://api.github.com/repos/acme/widgets/issues/116",
                    "https://api.github.com/repos/other/widgets/issues/117",
                    "https://github.com/acme/widgets/issues/117",
                    "https://api.github.example/repos/acme/widgets/issues/117",
                    "https://api.github.com/repos/acme/widgets/issues/117?x=1"):
            with self.subTest(url=url):
                self.rejected([dict(comment(), issue_url=url)], "COMMENT_ISSUE_MISMATCH")

    def test_wrong_marker_identity_conflicts(self):
        other = dict(CLAIM, issue=116)
        self.check_status([comment(CODEC.render(other))], "CONFLICT", "MARKER_ISSUE_MISMATCH")

    def test_malformed_and_foreign_markers_refused(self):
        for body in ("<!-- native-claim:v2 {} -->", "<!-- native-claim:v1 broken -->",
                     EXPECTED_BODY + EXPECTED_BODY, "> " + EXPECTED_BODY,
                     EXPECTED_BODY.replace("native-claim:v1", "NATIVE-CLAIM:v1"),
                     EXPECTED_BODY.replace('"action":"claim"', '"action":"release"')):
            with self.subTest(body=body):
                with self.assertRaises(CODEC.Unverified):
                    CODEC.reconcile([comment(body)], CLAIM)

    def test_raw_summary_and_canonical_edits_refused(self):
        for body in (EXPECTED_BODY.replace("proposal", "admitted"), EXPECTED_BODY.rstrip(),
                     EXPECTED_BODY.replace('"issue":117', '"issue": 117'),
                     EXPECTED_BODY.replace('"version":1', '"version":true')):
            with self.subTest(body=body):
                with self.assertRaises(CODEC.Unverified):
                    CODEC.reconcile([comment(body)], CLAIM)

    def test_known_receipt_matches_without_authority(self):
        self.check_status([comment()], "OBSERVED_MATCH", known_comment_id=101,
                          known_body_sha256=CODEC.digest(EXPECTED_BODY))

    def test_known_receipt_detects_marker_removal(self):
        self.check_status([comment("Edited into ordinary text.")], "CONFLICT", "KNOWN_COMMENT_EDITED",
                          known_comment_id=101, known_body_sha256=CODEC.digest(EXPECTED_BODY))

    def test_known_receipt_missing_is_unverified_even_with_match(self):
        output = self.check_status([comment()], "UNVERIFIED", known_comment_id=102,
                                   known_body_sha256=CODEC.digest(EXPECTED_BODY))
        self.assertEqual(output["reason"], "KNOWN_COMMENT_NOT_OBSERVED")

    def test_receipt_cli_pair_required(self):
        result, output = self.run_cli(extra=("--known-comment-id", "101"))
        self.assertEqual(result.returncode, 3)
        self.assertEqual(output["reason"], "INVALID_RECEIPT")
        result, output = self.run_cli(extra=("--known-comment-id", "101", "--known-body-sha256",
                                            CODEC.digest(EXPECTED_BODY)))
        self.assertEqual(result.returncode, 3)
        self.assertEqual(output["status"], "OBSERVED_MATCH")

    def test_relevant_rest_value_types_and_bounds(self):
        invalid = [("id", True), ("id", 0), ("id", -1), ("id", "101"), ("id", 2**63),
                   ("body", None), ("body", "x" * (CODEC.MAX_BODY_BYTES + 1)),
                    ("user", None), ("user", {"login": "bad[Bot]"})]
        for key, value in invalid:
            with self.subTest(key=key, value_type=type(value)):
                self.rejected([dict(comment(), **{key: value})], "INVALID_COMMENT")
        self.rejected([{}], "INVALID_COMMENT")
        self.rejected([comment()] * (CODEC.MAX_COMMENTS + 1), "INVALID_CAPTURE")

    def test_unsafe_public_fields_refused(self):
        invalid = {"claim_id": ["a" * 31, "A" * 32, "../private", "a" * 33],
                   "operation_id": ["token", "g" * 32],
                   "actor": ["@octocat", "bad--login", "bad[bot]", "a" * 40],
                   "repo": ["acme/widgets/other", "acme/..", "acme/<script>", "acme/a..b"],
                   "branch": ["../private", "-option", "x\n/assign @user", "a//b", "a/",
                              "x<!-- -->", "a.lock", "refs/@{x}", "a" * 129],
                   "scope": ["monitor", "sensitive arbitrary prose"],
                   "task_ref": ["issue116", "https://private.example/task", "issue:0"],
                   "issue": [True, 0, 2**63]}
        for key, values in invalid.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    with self.assertRaises(CODEC.Unverified):
                        CODEC.prepare(dict(CLAIM, **{key: value}))

    def test_private_and_lifecycle_fields_refused(self):
        for key in ("session_id", "pid", "worker", "root", "admitted", "complete"):
            with self.subTest(key=key):
                with self.assertRaises(CODEC.Unverified):
                    CODEC.prepare(dict(CLAIM, **{key: "not-public"}))
        with self.assertRaises(CODEC.Unverified):
            CODEC.prepare(dict(CLAIM, action="release"))

    def test_json_duplicates_utf8_depth_and_byte_bounds(self):
        for data in (b'{"id":1,"id":2}', b'[{"user":{"login":"a","login":"b"}}]',
                     b"\xff", b'"\\ud800"', b"[NaN]", b"[Infinity]", b"[1e999]", b"[",
                     b"[" * 34 + b"0" + b"]" * 34, b"x" * (CODEC.MAX_BYTES + 1), b""):
            with self.subTest(data_prefix=data[:20]):
                with self.assertRaises(CODEC.Unverified):
                    CODEC.parse_json(data)
        duplicate = EXPECTED_BODY.replace('"version":1', '"version":1,"version":1')
        self.rejected([comment(duplicate)], "DUPLICATE_JSON_KEY")

    def test_symlinks_and_hardlinks_refused(self):
        self.capture.write_text("[]", encoding="utf-8")
        leaf = self.directory / "leaf.json"
        leaf.symlink_to(self.capture)
        parent = self.directory / "alias"
        parent.symlink_to(self.directory, target_is_directory=True)
        for path in (leaf, parent / "comments.json"):
            with self.subTest(path=path):
                with self.assertRaises(OSError):
                    CODEC.read_capture(str(path))
        hard = self.directory / "hard.json"
        os.link(self.capture, hard)
        with self.assertRaisesRegex(CODEC.Unverified, "UNSAFE_CAPTURE"):
            CODEC.read_capture(str(self.capture))

    def test_changed_stat_during_read_refused(self):
        self.capture.write_text("[]", encoding="utf-8")
        original = CODEC.os.read

        def changing_read(fd, size):
            data = original(fd, size)
            if data:
                self.capture.write_text("[ ]", encoding="utf-8")
            return data

        with mock.patch.object(CODEC.os, "read", side_effect=changing_read):
            with self.assertRaisesRegex(CODEC.Unverified, "CHANGED_DURING_READ"):
                CODEC.read_capture(str(self.capture))

    def test_paths_regular_files_and_limits(self):
        for path in ("relative.json", "/a/../b", "/a//b", "/", "/a\nb"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(CODEC.Unverified, "INVALID_CAPTURE_PATH"):
                    CODEC.read_capture(path)
        for data in (b"", b" " * (CODEC.MAX_BYTES + 1)):
            self.capture.write_bytes(data)
            with self.assertRaisesRegex(CODEC.Unverified, "UNSAFE_CAPTURE"):
                CODEC.read_capture(str(self.capture))
        with self.assertRaisesRegex(CODEC.Unverified, "UNSAFE_CAPTURE"):
            CODEC.read_capture(str(self.directory))

    def test_errors_do_not_echo_arguments_and_order_is_deterministic(self):
        result, output = self.run_cli("prepare", claim=dict(CLAIM, branch="DO_NOT_ECHO<"))
        self.assertEqual(result.returncode, 3)
        self.assertNotIn(b"DO_NOT_ECHO", result.stdout)
        result, _ = self.run_cli("prepare", extra=("--private-field", "DO_NOT_ECHO"))
        self.assertEqual(result.returncode, 3)
        self.assertNotIn(b"DO_NOT_ECHO", result.stdout)
        other = dict(CLAIM, actor="hubot", claim_id="a" * 32, operation_id="b" * 32)
        records = [comment(), comment(CODEC.render(other), 102, "hubot")]
        self.assertEqual(CODEC.reconcile(records, CLAIM), CODEC.reconcile(list(reversed(records)), CLAIM))

    def test_duplicate_required_cli_options_refused(self):
        for command in ("prepare", "reconcile"):
            for key in ("repo", "issue", "claim_id", "operation_id", "actor", "branch", "task_ref", "scope"):
                option = "--" + key.replace("_", "-")
                for value in (str(CLAIM[key]), "DO_NOT_ECHO<"):
                    for extra in ((option, value), (option + "=" + value,)):
                        with self.subTest(command=command, option=option, extra=extra):
                            result, output = self.run_cli(command, extra=extra)
                            self.assertEqual(result.returncode, 3)
                            self.assertEqual(output["reason"], "DUPLICATE_ARGUMENT")
                            self.assertNotIn(b"DO_NOT_ECHO", result.stdout)
                            self.assertNotIn("comment", output)

    def test_duplicate_capture_and_receipt_cli_options_refused(self):
        values = {"comments": str(self.capture), "known-comment-id": "101",
                  "known-body-sha256": CODEC.digest(EXPECTED_BODY)}
        for name, first in values.items():
            option = "--" + name
            prefix = () if name == "comments" else (option, first)
            for second in (first, "DO_NOT_ECHO<"):
                for duplicate in ((option, second), (option + "=" + second,)):
                    with self.subTest(name=name, duplicate=duplicate):
                        result, output = self.run_cli(extra=prefix + duplicate)
                        self.assertEqual(result.returncode, 3)
                        self.assertEqual(output["reason"], "DUPLICATE_ARGUMENT")
                        self.assertNotIn(b"DO_NOT_ECHO", result.stdout)

    def test_duplicate_equals_first_and_empty_values_refused(self):
        for name, value in (("issue", "117"), ("actor", "octocat"), ("branch", CLAIM["branch"]),
                            ("comments", str(self.capture))):
            for duplicate in (("--" + name, value), ("--" + name + "=" + value,)):
                with self.subTest(name=name, duplicate=duplicate):
                    result, output = self.run_cli(extra=duplicate, equals=True)
                    self.assertEqual(result.returncode, 3)
                    self.assertEqual(output["reason"], "DUPLICATE_ARGUMENT")
        for name in ("known-comment-id", "known-body-sha256"):
            result, output = self.run_cli(extra=("--" + name + "=", "--" + name + "="))
            self.assertEqual(result.returncode, 3)
            self.assertEqual(output["reason"], "DUPLICATE_ARGUMENT")

    def test_ordinary_app_bot_comment_with_valid_claim(self):
        for author in ("github-actions[bot]", "dependabot[bot]", "a" * 39 + "[bot]"):
            with self.subTest(author=author):
                bot = comment("Automated ordinary discussion.", 102, author)
                bot["user"]["type"] = "Bot"
                result, output = self.run_cli(value=[bot, comment()])
                self.assertEqual(result.returncode, 3)
                self.assertEqual(output["status"], "OBSERVED_MATCH")
                self.assertEqual(output["observed_match_ids"], [101])
                self.assertEqual(output["observed_comment_count"], 2)
                self.assertNotIn(author.encode(), result.stdout)
        self.check_status([comment("Ordinary automation.", author="github-actions[bot]")], "UNVERIFIED")

    def test_app_bot_marker_cannot_impersonate_normal_actor(self):
        result, output = self.run_cli(value=[comment(author="octocat[bot]")])
        self.assertEqual(result.returncode, 4)
        self.assertEqual(output["status"], "CONFLICT")
        self.assertIn("AUTHOR_MISMATCH", output["conflict_reasons"])
        self.assertEqual(output["observed_match_ids"], [])
        self.assertNotIn(b"octocat", result.stdout)
        body = EXPECTED_BODY.replace('"actor":"octocat"', '"actor":"octocat[bot]"')
        result, output = self.run_cli(value=[comment(body, author="octocat[bot]")])
        self.assertEqual(result.returncode, 3)
        self.assertEqual(output["reason"], "INVALID_CLAIM")
        self.assertNotIn(b"octocat", result.stdout)

    def test_malicious_app_bot_suffixes_refused_without_echo(self):
        for author in ("[bot]", "bad--login[bot]", "a" * 40 + "[bot]", "octocat[Bot]",
                       "octocat[bot][bot]", "octocat[bot]DO_NOT_ECHO", "octocat[bot]\nDO_NOT_ECHO",
                       "DO_NOT_ECHO<[bot]", "octocat[bot] ", "octocat[other]", "octocat［bot］"):
            with self.subTest(author=author):
                result, output = self.run_cli(value=[comment("Ordinary discussion.", author=author)])
                self.assertEqual(result.returncode, 3)
                self.assertEqual(output["reason"], "INVALID_COMMENT")
                self.assertNotIn(b"DO_NOT_ECHO", result.stdout)
                self.assertNotIn(author.encode(), result.stdout)


if __name__ == "__main__":
    unittest.main()
