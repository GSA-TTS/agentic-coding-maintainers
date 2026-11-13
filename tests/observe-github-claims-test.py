#!/usr/bin/env python3
"""Offline adversarial REST fixtures. Run only in an independently isolated guest."""

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/observe-github-claims.py"
spec = importlib.util.spec_from_file_location("observer", SCRIPT)
assert spec and spec.loader
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)
codec = observer.codec
REPO = "acme/widgets"
REPO_URL = observer.API + "/repos/" + REPO
ISSUE_URL = REPO_URL + "/issues/117"
COMMENTS = ISSUE_URL + "/comments"
CLAIM = {"version": 1, "action": "claim", "repo": REPO, "issue": 117,
         "claim_id": "0" * 32, "operation_id": "1" * 32, "actor": "octocat",
         "branch": "feat/private-fixture", "task_ref": "issue:116", "scope": "implementation"}
ISSUE = {"id": 500, "number": 117, "url": ISSUE_URL, "repository_url": REPO_URL,
         "html_url": "https://github.com/acme/widgets/issues/117",
         "updated_at": "2026-11-01T00:00:00Z", "comments": 0, "state": "open", "locked": False}

# This executable validates every argv before providing a deterministic reply.
# No shell, network, imports from the repository, or real gh fallback is used.
# A followed redirect fixture exposes only the final response, as gh can do;
# it does not simulate or certify intermediate network/credential handling.
FAKE = r'''
import json, os, subprocess, sys, time
from pathlib import Path
steps = json.loads(Path(os.environ["FIXTURE"]).read_text())
log = Path(os.environ["CALLS"])
calls = json.loads(log.read_text()) if log.exists() else []
index = len(calls)
assert index < len(steps)
step = steps[index]
if step.get("followed_redirect"):
    # Model gh exposing only a valid final response after following a redirect.
    assert step["raw"].startswith("HTTP/2.0 200 OK\r\n") and "Location:" not in step["raw"]
assert sys.argv[1:] == ["api", "--hostname", "github.com", "--method", "GET", "--include",
    "-H", "Accept: application/vnd.github.raw+json", "-H", "X-GitHub-Api-Version: 2022-11-28", step["url"]]
assert os.environ["GH_HOST"] == "github.com"
assert not any(key.startswith("GIT_") for key in os.environ)
assert "GITHUB_HOST" not in os.environ and "GH_DEBUG" not in os.environ
assert os.environ["GH_TOKEN"] == "fixture-credential"
calls.append(step["url"])
log.write_text(json.dumps(calls))
if step.get("child"):
    child = subprocess.Popen([sys.executable, "-c",
        "import sys,time; from pathlib import Path; time.sleep(1); Path(sys.argv[1]).write_text('survived'); time.sleep(30)",
        os.environ["CHILD_SENTINEL"]])
    Path(os.environ["CHILD_PID"]).write_text(str(child.pid))
time.sleep(step.get("delay", 0))
sys.stderr.write(step.get("stderr", ""))
sys.stderr.flush()
sys.stdout.write(step.get("raw", ""))
sys.stdout.flush()
sys.exit(step.get("exit", 0))
'''


def http(value, headers="", newline="\r\n"):
    return "HTTP/2.0 200 OK" + newline + headers + newline + json.dumps(value)


def comment(identifier=1, body="ordinary confidential fixture discussion", login="octocat", actor_id=7):
    return {"id": identifier, "user": {"id": actor_id, "login": login}, "body": body,
            "issue_url": ISSUE_URL, "created_at": "2026-10-01T00:00:00Z",
            "updated_at": "2026-10-01T00:00:00Z", "unknown_private_field": "do-not-echo"}


def steps_for(pages, links=None, issue=None):
    issue = copy.deepcopy(ISSUE if issue is None else issue)
    issue["comments"] = sum(len(page) for page in pages)
    steps = [{"url": observer.API + "/user", "raw": http({"id": 7, "login": "octocat", "type": "User"})},
             {"url": REPO_URL, "raw": http({"id": 400, "full_name": REPO, "url": REPO_URL})},
             {"url": ISSUE_URL, "raw": http(issue)}]
    for index, records in enumerate(pages, 1):
        header = (links or {}).get(index, "")
        steps.append({"url": f"{COMMENTS}?per_page=100&page={index}", "raw": http(records, header)})
    steps.append({"url": ISSUE_URL, "raw": http(issue)})
    return steps


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        gh = self.directory / "gh"
        gh.write_text(f"#!{sys.executable}\n" + FAKE)
        gh.chmod(0o700)
        self.fixture = self.directory / "answers.json"
        self.calls = self.directory / "calls.json"
        env = dict(os.environ)
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            env.pop(key, None)
        env.update(PATH=str(self.directory), FIXTURE=str(self.fixture), CALLS=str(self.calls),
                   CHILD_PID=str(self.directory / "child.pid"), GH_TOKEN="fixture-credential",
                   CHILD_SENTINEL=str(self.directory / "child-survived"),
                   GH_HOST="evil.invalid", GITHUB_HOST="evil.invalid", GH_DEBUG="api",
                   GIT_DIR="/invalid", GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="credential.helper",
                   GIT_CONFIG_VALUE_0="invalid")
        self.environment = env
        self.env_patch = patch.dict(os.environ, env, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def run_observation(self, steps, deadline=3, **kwargs):
        self.fixture.write_text(json.dumps(steps))
        transport = observer.Transport(REPO, 117, time.monotonic() + deadline)
        return observer.observe(REPO, 117, transport, **kwargs)

    def refused(self, steps, reason=None, deadline=3):
        with self.assertRaises(observer.Unverified) as caught:
            self.run_observation(steps, deadline)
        if reason:
            self.assertEqual(str(caught.exception), reason)
        self.assertNotIn("confidential", str(caught.exception))

    def test_empty_and_closed_locked_are_observed_without_authority(self):
        issue = dict(ISSUE, state="closed", locked=True)
        result = self.run_observation(steps_for([[]], issue=issue))
        self.assertEqual(result["status"], "OBSERVED")
        self.assertEqual(result["remote_coverage"], "complete_pagination")
        self.assertTrue(result["issue_closed"] and result["issue_locked"])
        self.assertFalse(result["atomic_snapshot"] or result["mutation_authorized"] or result["absence_authorizing"])
        self.assertEqual(len(json.loads(self.calls.read_text())), 5)

    def test_claim_summaries_and_bots_do_not_echo_private_fields(self):
        records = [comment(body=codec.render(CLAIM)), comment(2, login="github-actions[bot]", actor_id=8)]
        result = self.run_observation(steps_for([records]))
        self.assertEqual(result["recognized_claim_count"], 1)
        self.assertTrue(result["claims"][0]["actor_is_current_user"])
        self.assertEqual(result["claims"][0]["body_sha256"], codec.digest(codec.render(CLAIM)))
        for private in ("octocat", "acme/widgets", CLAIM["branch"], CLAIM["operation_id"],
                        "do-not-echo", "confidential", "github-actions"):
            self.assertNotIn(private, json.dumps(result))

    def test_full_terminal_page_and_monotonic_pagination(self):
        pages = [[comment(i) for i in range(1, 101)], [comment(101)]]
        links = {1: f'Link: <{COMMENTS}?page=2&per_page=100>; rel="next", '
                    f'<{COMMENTS}?per_page=100&page=2>; rel="last"\r\n',
                 2: f'Link: <{COMMENTS}?per_page=100&page=1>; rel="prev"\r\n'}
        result = self.run_observation(steps_for(pages, links))
        self.assertEqual((result["page_count"], result["comment_count"]), (2, 101))
        self.calls.unlink()
        self.assertEqual(self.run_observation(steps_for([pages[0]]))["comment_count"], 100)

    def test_verified_numeric_links_keep_outgoing_requests_named(self):
        numeric = observer.API + "/repositories/400/issues/117/comments"
        links = {1: f'Link: <{numeric}?per_page=100&page=2>; rel="next", '
                    f'<{numeric}?page=2&per_page=100>; rel="last"\r\n',
                 2: f'Link: <{numeric}?per_page=100&page=1>; rel="prev", '
                    f'<{numeric}?per_page=100&page=1>; rel="first"\r\n'}
        result = self.run_observation(steps_for([[comment()], [comment(2)]], links))
        self.assertEqual(result["status"], "OBSERVED")
        self.assertEqual(result["repository_id"], 400)
        self.assertEqual(result["page_count"], 2)
        calls = json.loads(self.calls.read_text())
        self.assertEqual(calls[3:5], [f"{COMMENTS}?per_page=100&page=1",
                                      f"{COMMENTS}?per_page=100&page=2"])
        self.assertFalse(any("/repositories/" in url for url in calls))

    def test_foreign_numeric_repository_or_issue_links_refused(self):
        for path in ("/repositories/401/issues/117/comments", "/repositories/400/issues/118/comments",
                     "/repositories/0400/issues/117/comments"):
            with self.subTest(path=path):
                if self.calls.exists():
                    self.calls.unlink()
                links = {1: f'Link: <{observer.API}{path}?per_page=100&page=2>; rel="next"\r\n'}
                self.refused(steps_for([[comment()]], links), "LINK_ENDPOINT_MISMATCH")
                self.assertEqual(len(json.loads(self.calls.read_text())), 4)

    def test_followed_redirect_final_200_observes_valid_identity(self):
        # Only final metadata is available; no claim that a redirect was blocked.
        steps = steps_for([[comment(body=codec.render(CLAIM))]])
        steps[1]["followed_redirect"] = "fixture intermediate 301 not exposed by gh"
        result = self.run_observation(steps)
        self.assertEqual(result["status"], "OBSERVED")
        self.assertEqual((result["repository_id"], result["issue_id"]), (400, 500))
        self.assertFalse(result["mutation_authorized"] or result["absence_authorizing"])
        self.assertFalse(any("redirect" in key for key in result))

    def test_nested_duplicate_identity_and_marker_json_keys_refused(self):
        steps = steps_for([[]])
        steps[1]["raw"] = http({"id": 400, "full_name": REPO, "url": REPO_URL,
                               "owner": {"id": 7}}).replace('"owner": {"id": 7}',
                                                           '"owner": {"id": 7, "id": 8}')
        self.refused(steps, "DUPLICATE_JSON_KEY")
        self.calls.unlink()
        body = codec.render(CLAIM).replace('"actor":"octocat"',
                                          '"actor":"octocat","actor":"other"')
        self.refused(steps_for([[comment(body=body)]]), "DUPLICATE_JSON_KEY")
        self.calls.unlink()
        body = codec.render(CLAIM).replace('"scope":"implementation"',
                                          '"scope":{"nested":1,"nested":2}')
        self.refused(steps_for([[comment(body=body)]]), "DUPLICATE_JSON_KEY")
        self.calls.unlink()
        steps = steps_for([[comment()]])
        steps[3]["raw"] = steps[3]["raw"].replace('"user": {"id": 7,', '"user": {"id": 7, "id": 8,')
        self.refused(steps, "DUPLICATE_JSON_KEY")

    def test_malformed_link_urls_produce_fixed_json_without_stderr(self):
        targets = ["https://[invalid/comments?per_page=100&page=2",
                   f"{COMMENTS}?per_page=100&page"]
        for target in targets:
            with self.subTest(target=target):
                if self.calls.exists():
                    self.calls.unlink()
                steps = steps_for([[comment()]], {1: f'Link: <{target}>; rel="next"\r\n'})
                self.fixture.write_text(json.dumps(steps))
                completed = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--repo", REPO,
                                            "--issue", "117"], env=self.environment, capture_output=True, timeout=5)
                self.assertEqual(completed.returncode, 3)
                self.assertFalse(completed.stderr)
                self.assertEqual(json.loads(completed.stdout), observer.report("UNVERIFIED", "LINK_URL_INVALID"))

    def test_nonisolated_output_has_uniform_schema(self):
        completed = subprocess.run([sys.executable, "-B", str(SCRIPT), "--repo", REPO, "--issue", "117"],
                                   env=self.environment, capture_output=True, timeout=5)
        self.assertEqual(completed.returncode, 3)
        self.assertFalse(completed.stderr)
        self.assertFalse(self.calls.exists())
        self.assertEqual(json.loads(completed.stdout), observer.report("UNVERIFIED", "ISOLATED_PYTHON_REQUIRED"))

    def test_cross_call_deadline_is_not_reset(self):
        steps = steps_for([[]])
        # Each call fits the total budget individually; together they exceed it.
        steps[0]["delay"] = 0.3
        steps[1]["delay"] = 0.8
        started = time.monotonic()
        self.refused(steps, "DEADLINE_EXCEEDED", deadline=1)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(json.loads(self.calls.read_text()), [observer.API + "/user", REPO_URL])

    def test_link_adversaries_never_follow_unapproved_url(self):
        links = [f'<https://evil.invalid/comments?per_page=100&page=2>; rel="next"',
                 f'<{COMMENTS}?per_page=100&page=3>; rel="next"',
                 f'<{COMMENTS}?per_page=100&page=2&secret=x>; rel="next"',
                 f'<{COMMENTS}?per_page=100&page=2&page=2>; rel="next"',
                 f'<{COMMENTS}?per_page=100&page=2>; rel="next", <https://evil.invalid/>; rel="last"',
                 f'<{COMMENTS}?per_page=100&page=2>; rel="next", trailing',
                 f'<{COMMENTS}?per_page=100&page=2#fragment>; rel="next"',
                 f'<{COMMENTS}?per_page=100&page=11>; rel="last"',
                 f'<{COMMENTS}?per_page=100&page=2>; rel="last"',
                 f'<{COMMENTS}?per_page=100&page=2>; rel="next", <{COMMENTS}?per_page=100&page=2>; rel="next"']
        for link in links:
            with self.subTest(link=link):
                if self.calls.exists():
                    self.calls.unlink()
                self.refused(steps_for([[comment()]], {1: "Link: " + link + "\r\n"}))
                self.assertEqual(len(json.loads(self.calls.read_text())), 4)

    def test_http_and_json_adversaries(self):
        for raw in ('HTTP/1.1 302 Found\r\nLocation: https://evil.invalid\r\n\r\n[]',
                    http([], 'Link: x\r\nLink: x\r\n'),
                    http([], 'Location: https://evil.invalid\r\n'),
                    'HTTP/2.0 200 OK\r\n\r\n[{"id":1,"id":2}]',
                    'HTTP/2.0 200 OK\r\n\r\n[NaN]',
                    'HTTP/2.0 200 OK\r\n\r\nHTTP/2.0 200 OK\r\n\r\n[]'):
            with self.subTest(raw=raw):
                if self.calls.exists():
                    self.calls.unlink()
                steps = steps_for([[]])
                steps[3]["raw"] = raw
                self.refused(steps)

    def test_identity_and_anchor_changes(self):
        changes = [(0, {"id": 7, "login": "octocat", "type": "Bot"}),
                   (1, {"id": 400, "full_name": "foreign/widgets", "url": REPO_URL}),
                   (2, dict(ISSUE, pull_request={})),
                   (2, dict(ISSUE, number=True)),
                   (2, dict(ISSUE, url="https://evil.invalid")),
                   (4, dict(ISSUE, id=501)), (4, dict(ISSUE, comments=1)),
                   (4, dict(ISSUE, updated_at="2026-11-01T00:00:01Z"))]
        for index, value in changes:
            with self.subTest(index=index, value=value):
                if self.calls.exists():
                    self.calls.unlink()
                steps = steps_for([[]])
                steps[index]["raw"] = http(value)
                self.refused(steps)

    def test_all_comments_count_and_identity_checked(self):
        for records in ([comment(), comment()], [comment(2), comment(1)],
                        [dict(comment(), issue_url=REPO_URL + "/issues/118")],
                        [dict(comment(), body=None)], [dict(comment(), user=None)]):
            if self.calls.exists():
                self.calls.unlink()
            self.refused(steps_for([records]))
        self.calls.unlink()
        steps = steps_for([[comment()]])
        issue = dict(ISSUE, comments=0)
        steps[2]["raw"] = steps[-1]["raw"] = http(issue)
        self.refused(steps, "ISSUE_CHANGED_OR_COUNT_MISMATCH")

    def test_future_mixed_edited_and_unknown_action_markers_refused(self):
        body = codec.render(CLAIM)
        for changed in (body.replace("native-claim:v1", "native-claim:v2"),
                        body + "<!-- native-claim:v2 {} -->", body.replace('"claim"', '"release"'),
                        body.replace('"version":1', '"version":2'), "quoted native-claim", body + "edited"):
            if self.calls.exists():
                self.calls.unlink()
            self.refused(steps_for([[comment(body=changed)]]))

    def test_conflicts_and_current_actor_id_binding(self):
        cases = [([comment(body=codec.render(CLAIM), login="octocat[bot]")], "AUTHOR_MISMATCH"),
                 ([comment(body=codec.render(dict(CLAIM, issue=118)))], "MARKER_ISSUE_MISMATCH"),
                 ([comment(body=codec.render(CLAIM)), comment(2, codec.render(CLAIM))], "DUPLICATE_OPERATION_ID"),
                 ([comment(body=codec.render(CLAIM)), comment(2, codec.render(dict(CLAIM, branch="other")))], "CLAIM_PAYLOAD_MISMATCH"),
                 ([comment(body=codec.render(CLAIM)), comment(2, codec.render(dict(CLAIM, claim_id="2" * 32, operation_id="3" * 32)))], "MULTIPLE_CLAIMS")]
        for records, reason in cases:
            if self.calls.exists():
                self.calls.unlink()
            result = self.run_observation(steps_for([records]))
            self.assertEqual(result["status"], "CONFLICT")
            self.assertIn(reason, result["conflict_reasons"])
        self.calls.unlink()
        result = self.run_observation(steps_for([[comment(body=codec.render(CLAIM), actor_id=99)]]))
        self.assertFalse(result["claims"][0]["actor_is_current_user"])

    def test_byte_budget_includes_stderr_and_all_requests(self):
        steps = steps_for([[]])
        steps[0]["stderr"] = "x" * (observer.MAX_BYTES + 1)
        self.refused(steps, "OUTPUT_BYTE_BOUND")
        self.calls.unlink()
        steps = steps_for([[]])
        steps[0]["stderr"] = "x" * (observer.MAX_BYTES // 2)
        steps[1]["stderr"] = "x" * (observer.MAX_BYTES // 2)
        self.refused(steps, "OUTPUT_BYTE_BOUND")

    def test_deadline_kills_pipe_holding_child(self):
        steps = steps_for([[]])
        steps[0].update(delay=30, child=True)
        start = time.monotonic()
        self.refused(steps, "DEADLINE_EXCEEDED", deadline=0.5)
        self.assertLess(time.monotonic() - start, 2)
        self.assertTrue((self.directory / "child.pid").exists())
        time.sleep(1.1)
        self.assertFalse((self.directory / "child-survived").exists())

    def test_page_and_comment_limits_and_cross_page_duplicates(self):
        pages = [[comment(i) for i in range(start, start + 100)] for start in range(1, 1001, 100)]
        links = {page: f'Link: <{COMMENTS}?per_page=100&page={page + 1}>; rel="next"\r\n'
                 for page in range(1, 10)}
        result = self.run_observation(steps_for(pages, links), deadline=5)
        self.assertEqual((result["page_count"], result["comment_count"]), (10, 1000))
        self.calls.unlink()
        links[10] = f'Link: <{COMMENTS}?per_page=100&page=11>; rel="next"\r\n'
        self.refused(steps_for(pages, links), "PAGE_BOUND", deadline=5)
        self.calls.unlink()
        self.refused(steps_for([[comment()], [comment()]],
                              {1: f'Link: <{COMMENTS}?per_page=100&page=2>; rel="next"\r\n'}),
                     "DUPLICATE_COMMENT_ID")
        self.calls.unlink()
        self.refused(steps_for([[comment(i) for i in range(1, 102)]]), "COMMENT_PAGE_INVALID")

    def test_stdout_overflow_and_lf_headers(self):
        steps = steps_for([[]])
        steps[0]["raw"] = "x" * (observer.MAX_BYTES + 1)
        self.refused(steps, "OUTPUT_BYTE_BOUND")
        records, successor = observer.parse_http(http([], newline="\n").encode(), COMMENTS, 1)
        self.assertEqual(records, [])
        self.assertIsNone(successor)

    def test_empty_continuing_page_and_missing_http_metadata(self):
        self.refused(steps_for([[]],
                              {1: f'Link: <{COMMENTS}?per_page=100&page=2>; rel="next"\r\n'}),
                     "COMMENT_PAGE_INVALID")
        self.calls.unlink()
        steps = steps_for([[]])
        steps[3]["raw"] = "[]"
        self.refused(steps, "HTTP_METADATA_MISSING")

    def test_link_order_requires_current_page_for_relative_relations(self):
        # Internal callers must provide a current page for comparisons. Keep
        # earlier metadata/URL validation and the page-independent first link.
        for relation in ("next", "prev", "last"):
            with self.subTest(relation=relation):
                raw = http([comment()], f'Link: <{COMMENTS}?per_page=100&page=2>; rel="{relation}"\r\n')
                with self.assertRaisesRegex(observer.Unverified, "^LINK_ORDER_INVALID$"):
                    observer.parse_http(raw.encode(), COMMENTS)
        for header, reason in (("Link: malformed\r\n", "LINK_INVALID"),
                ('Link: <https://evil.invalid/?per_page=100&page=2>; rel="next"\r\n',
                 "LINK_ENDPOINT_MISMATCH")):
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(observer.Unverified, "^" + reason + "$"):
                    observer.parse_http(http([comment()], header).encode(), COMMENTS)
        raw = http([comment()], f'Link: <{COMMENTS}?per_page=100&page=1>; rel="first"\r\n')
        self.assertEqual(observer.parse_http(raw.encode(), COMMENTS), ([comment()], None))
        with self.assertRaisesRegex(observer.Unverified, "^IDENTITY_PAGINATION_REFUSED$"):
            observer.parse_http(raw.encode())
        self.assertFalse(self.calls.exists())

    def test_proxy_is_refused_before_process_launch(self):
        with patch.dict(os.environ, {"HTTPS_PROXY": "https://evil.invalid"}):
            with self.assertRaises(observer.Unverified) as caught:
                observer.Transport(REPO, 117, time.monotonic() + 1)
        self.assertEqual(str(caught.exception), "PROXY_ROUTING_UNVERIFIED")
        self.assertFalse(self.calls.exists())

    def test_internal_exact_body_match_is_current_immutable_actor_bound(self):
        body = codec.render(CLAIM)
        result = self.run_observation(steps_for([[comment(body=body)]]), expected_body=body)
        self.assertEqual(result["exact_match_comment_id"], 1)
        self.assertEqual(result["expected_body_sha256"], codec.digest(body))
        self.assertNotIn(body, json.dumps(result))
        for record in (comment(body=body, actor_id=99), comment(body=body, login="other"),
                       comment(body=codec.render(dict(CLAIM, branch="changed")))):
            self.calls.unlink()
            result = self.run_observation(steps_for([[record]]), expected_body=body)
            self.assertEqual(result["status"], "CONFLICT")
            self.assertIsNone(result["exact_match_comment_id"])

    def test_internal_malformed_body_is_not_attributed_by_operation_substring(self):
        body = codec.render(CLAIM)
        operation = CLAIM["operation_id"]
        for malformed in (f"Discussion of native-claim operation {operation}.",
                          "```text\n" + body + "```\n",
                          '<!-- native-claim:v1 {"operation_id":"' + operation + '"',
                          "<!-- native-claim:v1 {} -->\nOperation outside payload: " + operation,
                          body + "edited",
                          body.replace("Operator review", "Human review")):
            with self.subTest(body=malformed):
                if self.calls.exists():
                    self.calls.unlink()
                self.fixture.write_text(json.dumps(steps_for([[comment(body=malformed)]])))
                transport = observer.Transport(REPO, 117, time.monotonic() + 3)
                with self.assertRaises(observer.Unverified):
                    observer.observe(REPO, 117, transport, expected_body=body)

    def test_internal_match_absence_competition_and_duplicate_precedence(self):
        body = codec.render(CLAIM)
        for records, status, identifier in (([], "OBSERVED", None),
                ([comment(body=body), comment(2, body)], "CONFLICT", None),
                ([comment(body=body), comment(2, codec.render(dict(CLAIM, claim_id="2" * 32,
                                                                  operation_id="3" * 32)))], "CONFLICT", None)):
            if self.calls.exists():
                self.calls.unlink()
            result = self.run_observation(steps_for([records]), expected_body=body)
            self.assertEqual(result["status"], status)
            self.assertIs(result["exact_match_comment_id"], identifier)

    def test_cli_codes_and_sanitized_auth_error(self):
        for records, expected in (([], 0), ([comment(body=codec.render(CLAIM), login="other")], 4)):
            if self.calls.exists():
                self.calls.unlink()
            self.fixture.write_text(json.dumps(steps_for([records])))
            completed = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--repo", REPO,
                                        "--issue", "117"], env=self.environment, capture_output=True, timeout=5)
            self.assertEqual(completed.returncode, expected, completed.stderr)
            self.assertFalse(completed.stderr)
        self.calls.unlink()
        steps = steps_for([[]])
        steps[0].update(exit=1, stderr="confidential credential fixture secret", raw="private body")
        self.fixture.write_text(json.dumps(steps))
        completed = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--repo", REPO,
                                    "--issue", "117"], env=self.environment, capture_output=True, timeout=5)
        self.assertEqual(completed.returncode, 3)
        self.assertFalse(completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["reason"], "API_READ_UNAVAILABLE")
        self.assertNotIn(b"secret", completed.stdout)

    def test_invalid_duplicate_arguments_and_arbitrary_endpoints(self):
        for args in (["--repo", REPO, "--issue", "117", "--repo=" + REPO],
                     ["--repo", "acme/../widgets", "--issue", "117"],
                     ["--repo", REPO, "--issue", "117", "--url", "https://evil.invalid"]):
            completed = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), *args],
                                       env=self.environment, capture_output=True, timeout=5)
            self.assertEqual(completed.returncode, 3)
            self.assertFalse(self.calls.exists())
            self.assertNotIn(b"evil", completed.stdout + completed.stderr)
        transport = observer.Transport(REPO, 117, time.monotonic() + 1)
        with self.assertRaises(observer.Unverified):
            transport.get("https://evil.invalid")
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
