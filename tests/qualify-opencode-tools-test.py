"""Offline semantic/stub tests. Fake observations are never runtime evidence."""
import copy
import importlib.util
import json
import pathlib
import tempfile
import time
import unittest
import urllib.request
from unittest.mock import patch

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts/qualify-opencode-tools.py"
spec = importlib.util.spec_from_file_location("tools_qualification", SCRIPT)
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)


def returned(args):
    return {"argv": ["<binary>", *args], "status": "RETURNED", "exit_code": 0,
            "bytes": {"stdout": 100, "stderr": 0}}


def pages(rows):
    empty = {"path": "/api/session", "body": {"data": [], "cursor": {"previous": None, "next": None}}}
    if not rows:
        return [empty]
    return [{"path": "/api/session", "body": {"data": rows, "cursor": {"previous": "prev", "next": "next"}}},
            {**empty, "path": "/api/session?cursor=next"}]


def fixture(case):
    project, sid = "/fixture/project", "ses_fixture_parent"
    sequence, rules = t.plan(case, project)
    machine, messages, requests, events = t.Conversation(sequence), [], [], []
    before = {".": {"type": "directory", "mode": 448},
              "target.txt": {"type": "file", "mode": 384, "bytes_hex": b"original-fixture\n".hex()}}
    after = copy.deepcopy(before)
    schemas = [{"type": "function", "function": {"name": n, "parameters": {"type": "object"}}}
               for n in ("read", "edit", "shell", "subagent")]
    def request(body):
        body.update(model="model", stream=True)
        requests.append({"path": "/v1/chat/completions", "body": copy.deepcopy(body),
                         "response": machine.respond(body)})
    request({"messages": [{"role": "user", "content": "title"}]})
    for i, call in enumerate(sequence):
        request({"tools": schemas, "messages": messages})
        outcome = ("DENIED" if case.endswith("deny") and i == len(sequence) - 1 else
                   "UNAVAILABLE" if case == "unknown-control" else
                   "INVALID_ARGUMENTS" if case == "invalid-control" else "COMPLETED")
        content = "Read file /fixture/project/target.txt, lines 1-1\n1: original-fixture" if call["name"] == "read" else "Fixture tool completed"
        state = {"status": "completed", "input": call["arguments"], "output": content}
        if outcome != "COMPLETED":
            kind, text = {"DENIED": ("permission.rejected", "Permission denied: " + call["name"]),
                          "UNAVAILABLE": ("tool.execution", 'No tool named "fixture_unknown" is currently available.'),
                          "INVALID_ARGUMENTS": ("tool.execution", 'Invalid arguments for tool "read":\n- path: Expected string')}[outcome]
            content = json.dumps({"error": {"type": kind, "message": text}, "content": []})
            state = {"status": "error", "input": call["arguments"], "error": text}
        event = {"type": "tool", "id": call["id"], "tool": call["name"], "sessionID": sid, "state": state}
        events.append({"type": "tool_use", "sessionID": sid, "part": event})
        messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
    if case == "subagent-allow":
        request({"tools": schemas, "messages": [{"role": "user", "content": t.CHILD}]})
    request({"tools": schemas, "messages": messages})
    events.append({"type": "text", "sessionID": sid, "part": {"type": "text", "text": t.FINAL}})
    if case == "edit-allow":
        after["target.txt"]["bytes_hex"] = b"edited-fixture\n".hex()
    if case == "shell-allow":
        after["shell-marker"] = {"type": "file", "mode": 384, "bytes_hex": b"shell-effect".hex()}
    parent = {"id": sid, "location": {"directory": project}, "agent": "probe", "outcome": "succeeded"}
    rows = [parent]
    def assistant(content):
        return {"type": "assistant", "content": content, "finish": "stop",
                "model": {"id": "model", "providerID": "fixture", "variant": "default"}}
    idle = {"type": "idle", "outcome": "succeeded"}
    exported = []
    for event in events[:-1]:
        part = event["part"]
        state = part["state"]
        wire = {"status": state["status"], "input": state["input"]}
        if state["status"] == "completed":
            wire["content"] = [{"type": "text", "text": state["output"]}]
        else:
            wire["error"] = json.loads(machine.results[part["id"]])["error"]
        exported.append({"type": "tool", "id": part["id"], "name": part["tool"], "state": wire})
    exported.append({"type": "text", "text": t.FINAL})
    exports = {sid: {"info": parent, "messages": [assistant(exported), idle]}}
    if case == "subagent-allow":
        child = {"id": "ses_fixture_child", "parentID": sid, "location": {"directory": project},
                 "agent": "general", "outcome": "succeeded"}
        rows.append(child)
        exports[child["id"]] = {"info": child, "messages": [assistant([{"type": "text", "text": t.FINAL}]), idle]}
        content = f'<subagent sessionID="{child["id"]}" state="completed">\n{t.FINAL}\n</subagent>'
        requests[-1]["body"]["messages"][0]["content"] = content
        events[0]["part"]["state"]["output"] = content
        exported[0]["state"]["content"][0]["text"] = content
    row = {"case": case, "project": project, "session": sid, "profile": t.profile(rules),
           "before": before, "after": after, "requests": requests, "events": events,
           "inventory_before": pages([]), "inventory_after": pages(rows), "exports": exports,
           "commands": [], "exit": 0, "failure": None, "classification": "UNVERIFIED"}
    args = [["api", "--standalone", "GET", p["path"]] for p in row["inventory_before"]]
    args += [t.run_args(sid)]
    args += [["api", "--standalone", "GET", p["path"]] for p in row["inventory_after"]]
    args += [["session", "export", "--standalone", s] for s in sorted(exports)]
    row["commands"] = [returned(a) for a in args]
    row["classification"] = t.classification(row)
    return row


def metadata():
    return {"version": "2.0.32", "binary_sha256": "a" * 64, "namespace": t.NS,
            "runtime_cleanup": "removed", "failure": None, "commands": [returned(["--version"])], "timeout": 180}


class SemanticTests(unittest.TestCase):
    def test_fake_runtime_end_to_end(self):
        """Drive real HTTP/SSE capture through observe with a fully fake CLI."""
        class FakeRunner:
            def __init__(self, binary, cwd, env, deadline, commands):
                self.cwd, self.commands, self.row = cwd, commands, None

            def run(self, args):
                self.commands.append(returned(args))
                if args[0] == "run":
                    case, sid = self.cwd.parent.name, args[args.index("--session") + 1]
                    row = fixture(case)
                    encoded = json.dumps(row).replace("/fixture/project", str(self.cwd)).replace("ses_fixture_parent", sid)
                    self.row = json.loads(encoded)
                    for exchange in self.row["requests"]:
                        request = urllib.request.Request("http://127.0.0.1:18801/v1/chat/completions",
                            data=json.dumps(exchange["body"]).encode(), headers={"Content-Type": "application/json"})
                        with urllib.request.urlopen(request, timeout=2) as response:
                            actual = t.decode_sse(response.read().decode())
                            expected = t.decode_sse(exchange["response"])
                            # Arguments embedded in the fixture SSE are escaped;
                            # compare independently reconstructed dispatch plans.
                            if expected:
                                expected = next(c for c in t.plan(case, str(self.cwd))[0] if c["id"] == expected["id"])
                            self.assert_call(actual, expected)
                    for name, entry in self.row["after"].items():
                        if entry["type"] == "file":
                            (self.cwd / name).write_bytes(bytes.fromhex(entry["bytes_hex"]))
                            (self.cwd / name).chmod(entry["mode"])
                    return 0, ("\n".join(json.dumps(e) for e in self.row["events"]) + "\n").encode()
                if args[0] == "api":
                    response = (pages([])[0] if self.row is None else
                                self.row["inventory_after"][1 if "cursor=" in args[-1] else 0])
                    return 0, json.dumps(response["body"]).encode()
                if args[:2] == ["session", "export"]:
                    return 0, json.dumps(self.row["exports"][args[-1]]).encode()
                raise AssertionError(args)

            @staticmethod
            def assert_call(actual, expected):
                if actual != expected:
                    raise AssertionError((actual, expected))

        with tempfile.TemporaryDirectory() as d, patch.object(t.q, "Runner", FakeRunner):
            for case in t.CASES:
                with self.subTest(case=case):
                    row = t.observe("unused", pathlib.Path(d) / case, case, time.monotonic() + 5)
                    self.assertNotEqual(row["classification"], "UNVERIFIED")

    def test_positive_controls_and_deny_pairs(self):
        rows = [fixture(c) for c in t.CASES]
        self.assertEqual([r["classification"] for r in rows],
                         ["COMPLETED", "COMPLETED", "DENIED", "COMPLETED", "DENIED",
                          "COMPLETED", "DENIED", "UNAVAILABLE", "INVALID_ARGUMENTS"])
        self.assertEqual(t.overall(rows), t.SUCCESS)

    def test_bad_observations_never_qualify(self):
        mutations = {
            "missing_tool_result": lambda r: r["requests"][-1]["body"].update(messages=[]),
            "call_id_mixup": lambda r: r["events"][0]["part"].update(id="call_wrong"),
            "event_session_mixup": lambda r: r["events"][0].update(sessionID="ses_wrong"),
            "shell_marker_unexpected": lambda r: r["after"].update({"shell-marker": {"type": "file", "mode": 384, "bytes_hex": "00"}}),
            "mode_change": lambda r: r["after"]["target.txt"].update(mode=511),
            "symlink": lambda r: r["after"].update({"link": {"type": "symlink", "mode": 511, "target": "target.txt"}}),
            "timed_out": lambda r: r.update(failure="command_timeout"),
            "overflow": lambda r: r["commands"][0]["bytes"].update(stdout=t.LIMIT + 1),
            "nonzero": lambda r: r.update(exit=1),
            "truncated_sse": lambda r: r["requests"][-1].update(response=t.sse()[:-10]),
            "malformed_sse": lambda r: r["requests"][-1].update(response="data: {\n\n"),
            "inventory_incomplete": lambda r: r["inventory_after"].pop(),
            "missing_export": lambda r: r["exports"].clear(),
            "wrong_profile": lambda r: r["profile"]["agents"]["probe"].update(permissions=[]),
            "unknown_field": lambda r: r.update(approved=True),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                row = fixture("shell-deny")
                mutate(row)
                self.assertEqual(t.classification(row), "UNVERIFIED")

    def test_bad_positive_effects(self):
        for case in ("edit-allow", "shell-allow"):
            row = fixture(case)
            row["after"] = row["before"]
            self.assertEqual(t.classification(row), "UNVERIFIED")

    def test_claimed_read_success_without_contents(self):
        row = fixture("read-allow")
        row["events"][0]["part"]["state"]["output"] = "done"
        row["requests"][-1]["body"]["messages"][0]["content"] = "done"
        self.assertEqual(t.classification(row), "UNVERIFIED")

    def test_classifier_claim_cannot_override_evidence(self):
        rows = [fixture(c) for c in t.CASES]
        rows[0]["classification"] = "DENIED"
        self.assertEqual(t.overall(rows), "UNVERIFIED")

    def test_sse_call_mixup(self):
        row = fixture("edit-deny")
        row["requests"][1]["response"] = t.sse({"id": "call_other", "name": "read", "arguments": {}})
        self.assertEqual(t.classification(row), "UNVERIFIED")

    def test_early_next_call_without_result(self):
        sequence = t.plan("edit-deny", "/fixture")[0]
        machine = t.Conversation(sequence)
        body = {"model": "model", "stream": True, "messages": [],
                "tools": [{"function": {"name": "read"}}, {"function": {"name": "edit"}}]}
        machine.respond(body)
        with self.assertRaises(t.Unverified):
            machine.respond(body)

    def test_invalid_arguments_never_denial(self):
        row = fixture("edit-deny")
        tool = row["events"][1]["part"]
        text = 'Invalid arguments for tool "read":\n- path: Expected string'
        tool["state"]["error"] = text
        row["requests"][-1]["body"]["messages"][-1]["content"] = json.dumps(
            {"error": {"type": "tool.execution", "message": text}, "content": []})
        self.assertEqual(t.classification(row), "UNVERIFIED")

    def test_metadata_disagreement_and_incomplete_cleanup(self):
        for key, value in (("namespace", None), ("runtime_cleanup", "failed"), ("version", "2.0.31")):
            with tempfile.TemporaryDirectory() as d:
                meta = metadata()
                meta[key] = value
                self.assertEqual(t.publish(pathlib.Path(d), meta, [fixture(c) for c in t.CASES])["status"], "UNVERIFIED")

    def test_malformed_nested_values_fail_closed(self):
        for key in ("requests", "events", "inventory_after", "exports", "commands"):
            for value in (None, 1, "invalid", {}, [None]):
                row = fixture("read-allow")
                row[key] = value
                self.assertEqual(t.classification(row), "UNVERIFIED", (key, value))

    def test_child_created_under_deny(self):
        row = fixture("subagent-deny")
        row["inventory_after"] = fixture("subagent-allow")["inventory_after"]
        self.assertEqual(t.classification(row), "UNVERIFIED")

    def test_child_missing_completion_or_recursive(self):
        for parts in ([], [{"type": "tool"}], [{"type": "text", "text": "not complete"}]):
            row = fixture("subagent-allow")
            row["exports"]["ses_fixture_child"]["messages"][0]["content"] = parts
            self.assertEqual(t.classification(row), "UNVERIFIED")

    def test_unavailable_not_permission_denial(self):
        row = fixture("shell-deny")
        event = row["events"][0]["part"]
        text = 'No tool named "shell" is currently available.'
        event["state"]["error"] = text
        row["requests"][-1]["body"]["messages"][0]["content"] = json.dumps(
            {"error": {"type": "tool.execution", "message": text}, "content": []})
        self.assertEqual(t.classification(row), "UNVERIFIED")

    def test_filtered_schema_fails_before_dispatch(self):
        machine = t.Conversation(t.plan("shell-deny", "/fixture")[0])
        with self.assertRaises(t.Unverified):
            machine.respond({"model": "model", "stream": True, "tools": [{"function": {"name": "read"}}], "messages": []})

    def test_relative_edit_resource(self):
        _, rules = t.plan("edit-deny", "/fixture")
        self.assertEqual(rules[-1]["resource"], "target.txt")

    def test_json_duplicate_and_nonfinite_rejected(self):
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', '{'):
            with self.assertRaises(t.Unverified):
                t.q.parse_json(raw)

    def test_no_child_dispatch_recursion(self):
        m = t.Conversation(t.plan("subagent-allow", "/fixture")[0])
        m.respond({"model": "model", "stream": True, "tools": [{"function": {"name": "subagent"}}], "messages": []})
        body = {"model": "model", "stream": True, "tools": [{}], "messages": [{"role": "user", "content": t.CHILD}]}
        self.assertIsNone(t.decode_sse(m.respond(body)))
        with self.assertRaises(t.Unverified):
            m.respond(body)

    def test_bound_sse_and_titles(self):
        with self.assertRaises(t.Unverified):
            t.decode_sse("x" * (t.LIMIT + 1))
        m = t.Conversation([])
        for _ in range(2):
            m.respond({"model": "model", "stream": True, "messages": []})
        with self.assertRaises(t.Unverified):
            m.respond({"model": "model", "stream": True, "messages": []})

    def test_bundle_roundtrip_standalone_unverified(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d)
            result = t.publish(path, metadata(), [fixture(c) for c in t.CASES])
            self.assertEqual(result["status"], t.SUCCESS)
            self.assertEqual(json.loads((path / "report.json").read_text())["status"], "UNVERIFIED")
            self.assertEqual(t.inspect(path)["status"], t.SUCCESS)
            self.assertEqual((path / "READY").stat().st_mode & 0o777, 0o400)

    def test_rehashed_bad_semantics_not_self_authorizing(self):
        for case, mutate in (("shell-deny", lambda r: r.update(exit=1)),
                             ("edit-allow", lambda r: r.update(after=r["before"]))):
            with tempfile.TemporaryDirectory() as d:
                rows = [fixture(c) for c in t.CASES]
                mutate(rows[t.CASES.index(case)])
                self.assertEqual(t.publish(pathlib.Path(d), metadata(), rows)["status"], "UNVERIFIED")

    def test_missing_ready_and_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d)
            t.publish(path, metadata(), [fixture(c) for c in t.CASES])
            (path / "READY").rename(path / "missing")
            self.assertEqual(t.inspect(path)["status"], "UNVERIFIED")
            (path / "missing").rename(path / "READY")
            (path / "shell-deny.json").chmod(0o600)
            (path / "shell-deny.json").write_text('{}')
            (path / "shell-deny.json").chmod(0o400)
            self.assertEqual(t.inspect(path)["status"], "UNVERIFIED")

    def test_namespace_mandatory_before_runtime(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(t.q, "setup_private_namespace", side_effect=t.Unverified("refused")), \
                    patch.object(t.q.Runner, "run", side_effect=AssertionError("must not launch")):
                binary = SCRIPT
                sha = t.q.digest_file(binary, t.q.MAX_BINARY, time.monotonic() + 2)
                self.assertEqual(t.main(["--isolated-guest", "--binary", str(binary), "--expected-sha", sha,
                                         "--output", d + "/result"]), 3)


if __name__ == "__main__":
    unittest.main()
