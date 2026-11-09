#!/usr/bin/env python3
"""Offline assignment primitives; run only inside the workspace validation sandbox.

PTY fixtures exercise the actual collector; they are not human approval evidence.
No sockets or credentials are used. The vertical fixture separately covers dispatch.
"""

import copy
import hashlib
import importlib.util
import io
import json
import os
import pty
import re
import select
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SOURCE / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


publisher = load("assignment_publisher_fixture", "publish-github-assignment.py")
transport = load("assignment_transport_fixture", "github-assignment-transport.py")


def binding():
    body = '{"assignees":["operator"]}'
    return {"schema_version": 1, "action": "add-assignee", "intent_operation_id": "1" * 32,
            "operation_id": "2" * 32, "attempt_id": "3" * 32, "store_id": "4" * 32,
            "intent_sha256": "5" * 64, "payload": body,
            "payload_sha256": hashlib.sha256(body.encode("ascii")).hexdigest(),
            "implementation_head": "6" * 40, "prior_assignee_ids": [8],
            "publisher": {"id": 9, "node_id": "U_actor", "login": "operator"},
            "target": {"repository": "example/fixture", "repository_id": 10,
                       "repository_node_id": "R_repo", "issue": 12, "issue_id": 11,
                       "issue_node_id": "I_issue"},
            "task_binding": {"task_id": "fixture", "created_at": "2026-11-09T00:00:00Z",
                             "task_sha256": "7" * 64, "revision": 2, "generation": 1,
                             "session_id": "fixture-session", "worker": {"pid": 1}}}


class ApprovalTest(unittest.TestCase):
    def interaction(self, answer="approve", after=None, short_deadline=False, terminal_change=None):
        """Child has a real controlling PTY, parent responds only after full prompt."""
        child, fd = pty.fork()
        if child == 0:
            try:
                if short_deadline:
                    publisher.MAX_APPROVAL_SECONDS = 0.08
                value = binding()
                actual_attributes = publisher.termios.tcgetattr
                attribute_reads = 0

                def observed_attributes(terminal):
                    nonlocal attribute_reads
                    attributes = copy.deepcopy(actual_attributes(terminal))
                    attribute_reads += 1
                    if terminal_change == "pendin":
                        if attribute_reads == 1:
                            attributes[3] |= publisher.termios.PENDIN
                        else:
                            attributes[3] &= ~publisher.termios.PENDIN
                    elif terminal_change is not None and attribute_reads > 1:
                        if terminal_change == "canonical":
                            attributes[3] &= ~publisher.termios.ICANON
                        elif terminal_change == "echo":
                            attributes[3] ^= publisher.termios.ECHO
                        elif terminal_change == "input":
                            attributes[0] ^= publisher.termios.ICRNL
                        elif terminal_change == "control-character":
                            attributes[6][publisher.termios.VERASE] = b"\x01"
                    return attributes

                # Real PTY/challenge, deterministic kernel-observation changes.
                with mock.patch.object(publisher.termios, "tcgetattr", side_effect=observed_attributes):
                    approval = publisher.collect_approval(value)
                if after == "expiry":
                    with mock.patch.object(publisher.time, "monotonic",
                                           return_value=approval._started + 120):
                        approval.validate(value)
                elif after == "clock-backwards":
                    with mock.patch.object(publisher.time, "monotonic",
                                           return_value=approval._started - 1):
                        approval.validate(value)
                elif after == "unmeasurable":
                    with mock.patch.object(publisher.time, "monotonic", return_value=float("nan")):
                        approval.validate(value)
                elif after == "changed":
                    value["attempt_id"] = "9" * 32
                    approval.validate(value)
                elif after == "forked":
                    with mock.patch.object(publisher.os, "getpid", return_value=approval._pid + 1):
                        approval.validate(value)
                else:
                    receipt = approval.validate(value)
                    assert receipt["binding_sha256"] == publisher.binding_digest(value)
                os.write(1, b"\nRESULT:APPROVED\n")
                os._exit(0)
            except publisher.Refusal as exc:
                os.write(1, ("\nRESULT:" + str(exc) + "\n").encode("ascii"))
                os._exit(0)
            except BaseException:
                os.write(1, b"\nRESULT:UNEXPECTED\n")
                os._exit(2)
        output = bytearray()
        sent = False
        limit = time.monotonic() + 5
        status = None
        try:
            while time.monotonic() < limit:
                readable, _, _ = select.select([fd], [], [], 0.05)
                if readable:
                    try:
                        chunk = os.read(fd, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output.extend(chunk)
                    if not sent and b"anything else to decline:" in output:
                        sent = True
                        if answer == "approve":
                            match = re.search(rb"Type exactly (APPROVE [0-9a-f]{64})", output)
                            self.assertIsNotNone(match)
                            os.write(fd, match[1] + b"\n")
                        elif answer == "decline":
                            os.write(fd, b"no\n")
                        elif answer == "wrong-digest":
                            os.write(fd, b"APPROVE " + b"0" * 64 + b"\n")
                done, observed = os.waitpid(child, os.WNOHANG)
                if done:
                    status = observed
                    # A final readable chunk can still remain after process exit.
                    try:
                        while select.select([fd], [], [], 0)[0]:
                            chunk = os.read(fd, 65536)
                            if not chunk:
                                break
                            output.extend(chunk)
                    except OSError:
                        pass
                    break
            if status is None:
                done, observed = os.waitpid(child, os.WNOHANG)
                if done:
                    status = observed
        finally:
            if status is None:
                try:
                    os.kill(child, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                _, status = os.waitpid(child, 0)
            os.close(fd)
        self.assertEqual(status, 0, output.decode("ascii", errors="replace"))
        match = re.search(rb"RESULT:([A-Z_]+)", output)
        self.assertIsNotNone(match, output)
        return match[1].decode("ascii"), bytes(output)

    def test_actual_terminal_challenge(self):
        result, output = self.interaction()
        self.assertEqual(result, "APPROVED")
        self.assertIn(publisher.canonical(binding()).encode("ascii"), output)

    @unittest.skipUnless(hasattr(publisher.termios, "PENDIN"), "platform has no PENDIN")
    def test_pending_input_flag_clears_during_actual_interaction(self):
        self.assertEqual(self.interaction(terminal_change="pendin")[0], "APPROVED")
        self.assertEqual(self.interaction(answer="wrong-digest", terminal_change="pendin")[0],
                         "APPROVAL_DECLINED")

    def test_other_terminal_changes_still_refuse(self):
        for change in ("canonical", "echo", "input", "control-character"):
            with self.subTest(change=change):
                self.assertEqual(self.interaction(terminal_change=change)[0], "TTY_CHANGED_DURING_INTERACTION")

    def test_platform_without_pendin_keeps_exact_settings(self):
        attributes = [1, 2, 3, 4, 5, 6, [b"x"]]
        with mock.patch.object(publisher, "termios", object()):
            self.assertEqual(publisher.terminal_settings(attributes), attributes)

    def test_decline_and_wrong_digest(self):
        for answer in ("decline", "wrong-digest"):
            with self.subTest(answer=answer):
                self.assertEqual(self.interaction(answer)[0], "APPROVAL_DECLINED")

    def test_bounded_silent_operator(self):
        self.assertEqual(self.interaction("silent", short_deadline=True)[0], "APPROVAL_EXPIRED")

    def test_age_revalidated_after_interaction(self):
        for after in ("expiry", "clock-backwards", "unmeasurable"):
            with self.subTest(after=after):
                self.assertEqual(self.interaction(after=after)[0], "APPROVAL_EXPIRED")

    def test_changed_attempt_invalidates_approval(self):
        self.assertEqual(self.interaction(after="changed")[0], "APPROVAL_BINDING_CHANGED")

    def test_inherited_approval_cannot_launch(self):
        self.assertEqual(self.interaction(after="forked")[0], "INTERACTION_REQUIRED")

    def test_invalid_payload_and_colliding_ids(self):
        for key, value in (("payload", '{"assignees":[]}'), ("attempt_id", "2" * 32),
                           ("action", "comment"), ("prior_assignee_ids", [8, 8])):
            with self.subTest(key=key), self.assertRaises(publisher.Refusal):
                changed = binding()
                changed[key] = value
                publisher.validate_binding(changed)

    def test_pipe_is_not_an_approval_terminal(self):
        read_fd, write_fd = os.pipe()
        try:
            with mock.patch.object(publisher.os, "open", return_value=os.dup(read_fd)):
                with self.assertRaisesRegex(publisher.Refusal, "FOREGROUND_CONTROLLING_TTY_REQUIRED"):
                    publisher.collect_approval(binding())
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_no_file_or_readiness_override(self):
        with self.assertRaisesRegex(publisher.Refusal, "INTERACTION_REQUIRED"):
            publisher._Approval(binding(), time.monotonic(), object())


class FakeResponse:
    def __init__(self, status, value=None, headers=None):
        self.status = status
        self.raw = b"" if value is None else json.dumps(value).encode("ascii")
        self.headers = headers if headers is not None else [("Content-Type", "application/json")]
        if not any(key.lower() in {"content-length", "transfer-encoding"} for key, _ in self.headers):
            self.headers = [*self.headers, ("Content-Length", str(len(self.raw)))]

    def getheaders(self):
        return self.headers

    def read(self, count):
        return self.raw[:count]


class TransportTest(unittest.TestCase):
    def setUp(self):
        self.observed = {"actor_id": 9, "actor_node_id": "U_actor", "actor_login": "operator",
                         "repository_id": 10, "repository_node_id": "R_repo",
                         "issue_id": 11, "issue_node_id": "I_issue"}
        self.user = {"id": 9, "node_id": "U_actor", "login": "operator", "type": "User"}
        self.repo = {"id": 10, "node_id": "R_repo", "full_name": "example/fixture",
                     "url": transport.API + "/repos/example/fixture", "private": False,
                     "archived": False, "disabled": False, "permissions": {"push": True}}
        self.issue = {"id": 11, "node_id": "I_issue", "number": 12,
                      "url": transport.API + "/repos/example/fixture/issues/12",
                      "repository_url": transport.API + "/repos/example/fixture",
                      "state": "open", "locked": False, "assignees": [{"id": 8}]}
        self.responses = []
        self.calls = []
        fixture = self

        class Connection:
            def __init__(self, host, port, *, context, timeout):
                fixture.assertEqual((host, port), ("api.github.com", 443))
                fixture.assertTrue(context.check_hostname)
                fixture.assertGreater(timeout, 0)

            def request(self, method, path, *, body, headers):
                fixture.calls.append((method, path, body, headers))

            def getresponse(self):
                item = fixture.responses.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item

            def close(self):
                pass

        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(os.environ, {}, clear=True).start()
        mock.patch.object(transport, "BoundedHTTPSConnection", Connection).start()
        self.client = transport.Transport("example/fixture", 12, "ghp_" + "x" * 36)
        self.addCleanup(self.client.close)

    def identity_responses(self, scopes="public_repo"):
        self.responses += [FakeResponse(200, self.user, [("Content-Type", "application/json"),
                                                       ("X-OAuth-Scopes", scopes)]),
                           FakeResponse(200, self.repo), FakeResponse(204), FakeResponse(200, self.issue)]

    def test_fresh_permissions_capacity_and_additive_payload(self):
        self.identity_responses()
        self.assertEqual(self.client.fresh(self.observed), [8])
        self.issue["assignees"].append({"id": 9})
        self.responses += [FakeResponse(201, self.issue), FakeResponse(200, self.issue)]
        self.client.assign(self.observed)
        self.assertEqual(self.client.issue(self.observed), [8, 9])
        posts = [call for call in self.calls if call[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][1:3], ("/repos/example/fixture/issues/12/assignees",
                                        b'{"assignees":["operator"]}'))
        self.assertEqual(posts[0][3]["X-GitHub-Api-Version"], "2022-11-28")

    def test_no_post_retry_after_lost_response(self):
        self.responses.append(OSError("fixture lost response"))
        with self.assertRaisesRegex(transport.Refusal, "TRANSPORT_UNVERIFIED"):
            self.client.assign(self.observed)
        with self.assertRaisesRegex(transport.Refusal, "POST_REPLAY_REFUSED"):
            self.client.assign(self.observed)
        self.assertEqual(len(self.calls), 1)

    def test_redirect_rate_limit_and_missing_scope(self):
        cases = [FakeResponse(302, {}, [("Location", "https://example.invalid")]),
                 FakeResponse(403, {}, [("Retry-After", "60")]),
                 FakeResponse(200, self.user)]
        for response in cases:
            with self.subTest(status=response.status):
                self.responses = [response, FakeResponse(200, self.repo)]
                with self.assertRaises(transport.Refusal):
                    self.client.fresh(self.observed)
                self.assertFalse(any(call[0] == "POST" for call in self.calls))

    def test_target_drift_and_permission_denial(self):
        for target, key, value in ((self.user, "id", 99), (self.user, "type", "Bot"),
                                   (self.repo, "permissions", {"push": False}),
                                   (self.issue, "locked", True), (self.issue, "state", "closed"),
                                   (self.issue, "pull_request", {})):
            with self.subTest(key=key):
                before = copy.deepcopy(target)
                target[key] = value
                self.responses = []
                self.identity_responses()
                with self.assertRaises(transport.Refusal):
                    self.client.fresh(self.observed)
                target.clear()
                target.update(before)

    def test_assignee_capacity_and_incomplete_ids(self):
        for ids in (None, [{"id": 8}, {"id": 8}], [{"login": "other"}],
                    [{"id": value} for value in range(20, 30)], [{"id": True}]):
            with self.subTest(ids=ids):
                self.issue["assignees"] = ids
                self.responses = []
                self.identity_responses()
                with self.assertRaises(transport.Refusal):
                    self.client.fresh(self.observed)

    def test_unsupported_credentials_and_endpoint(self):
        for prefix in ("github_pat_", "ghs_", "ghu_", ""):
            with self.subTest(prefix=prefix), self.assertRaises(transport.Refusal):
                transport.Transport("example/fixture", 12, prefix + "x" * 36)
        with self.assertRaisesRegex(transport.Refusal, "ENDPOINT_REFUSED"):
            self.client._request("POST", self.client.issue_path + "/comments", b"{}")
        self.assertFalse(self.calls)

    def test_scope_does_not_authorize_private_repo(self):
        self.repo["private"] = True
        self.identity_responses("public_repo")
        with self.assertRaisesRegex(transport.Refusal, "CREDENTIAL_SCOPE_UNPROVEN"):
            self.client.fresh(self.observed)

    def test_actual_results_never_assert_provenance(self):
        self.assertEqual(transport.actual_result([8], [8, 9, 10], 9),
                         ("PRESERVED_ACTOR_PRESENT", True))
        self.assertEqual(transport.actual_result([8], [9], 9), ("DRIFT", False))
        self.assertEqual(transport.actual_result([8], [8], 9), ("FAILED_ACTUAL_RESULT", False))

    def test_duplicate_json_and_bool_ids_refused(self):
        with self.assertRaisesRegex(transport.Refusal, "DUPLICATE_JSON_KEY"):
            transport.decode(b'{"id":9,"id":10}')
        with self.assertRaises(transport.Refusal):
            transport.actual_result([True], [1, 9], 9)

    def test_real_http_response_framing(self):
        class Socket:
            def __init__(self, wire):
                self.wire = wire

            def makefile(self, mode):
                return io.BytesIO(self.wire)

        body = json.dumps(self.issue).encode("ascii")
        cases = [
            (b"Content-Length: " + str(len(body) + 10).encode(), body, False),
            (b"Content-Length: -1", body, False),
            (b"Content-Length: xyz", body, False),
            (b"Content-Length: 1, 1", body, False),
            (b"Content-Length: " + str(len(body)).encode() + b"\r\nTransfer-Encoding: chunked", body, False),
            (b"Transfer-Encoding: gzip", body, False),
            (b"Transfer-Encoding: chunked", hex(len(body))[2:].encode() + b"\r\n" + body + b"\r\n", False),
            (b"Transfer-Encoding: chunked", hex(len(body))[2:].encode() + b"\r\n" + body + b"\r\n0\r\n", False),
            (b"Transfer-Encoding: chunked", hex(len(body))[2:].encode() + b"\r\n" + body + b"xx0\r\n\r\n", False),
            (b"Content-Length: " + str(len(body)).encode(), body, True),
            (b"Transfer-Encoding: chunked", hex(len(body))[2:].encode() + b"\r\n" + body + b"\r\n0\r\n\r\n", True),
        ]
        for method in ("GET", "POST"):
            for framing, encoded, valid in cases:
                with self.subTest(method=method, framing=framing, valid=valid):
                    status = b"201 Created" if method == "POST" else b"200 OK"
                    response = transport.http.client.HTTPResponse(Socket(
                        b"HTTP/1.1 " + status + b"\r\nContent-Type: application/json\r\n" + framing + b"\r\n\r\n" + encoded))
                    response.begin()
                    self.responses = [response]
                    client = transport.Transport("example/fixture", 12, "ghp_" + "x" * 36)
                    try:
                        call = client.assign if method == "POST" else client.issue
                        if valid:
                            call(self.observed)
                        else:
                            with self.assertRaises(transport.Refusal):
                                call(self.observed)
                    finally:
                        client.close()

    def test_dns_timeout_is_killed_reaped_and_credential_free(self):
        # Actual subprocess.run timeout cleanup with a deliberately sleeping
        # resolver replacement; only its internal argv is injected. No DNS/socket.
        run = subprocess.run
        reaped = []

        def delayed(argv, **kwargs):
            self.assertEqual(kwargs["env"], {})
            self.assertTrue(kwargs["close_fds"])
            self.assertNotIn("ghp_", " ".join(argv))
            command = [sys.executable, "-I", "-B", "-c", "import os,time; print(os.getpid(),flush=True); time.sleep(30)"]
            try:
                return run(command, **kwargs)
            except subprocess.TimeoutExpired as exc:
                pid = int(exc.stdout.strip())
                with self.assertRaises(ChildProcessError):
                    os.waitpid(pid, os.WNOHANG)
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
                reaped.append(pid)
                raise

        # setUp replaced only the class name; load a fresh copy for this actual
        # resolver boundary (not a production override).
        fresh = load("bounded_dns_fixture", "github-assignment-transport.py")
        connection = fresh.BoundedHTTPSConnection("api.github.com", timeout=0.2)
        started = time.monotonic()
        with mock.patch.object(fresh.subprocess, "run", side_effect=delayed):
            with self.assertRaisesRegex(fresh.Refusal, "DNS_OR_CONNECT_UNVERIFIED"):
                connection.connect()
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(len(reaped), 1)


if __name__ == "__main__":
    unittest.main()
