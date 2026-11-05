"""Guest-only, offline OpenCode 2.0.32 dispatch observations.

python3 -I -B is mandatory. --isolated-guest is an operator assertion, not a
sandbox. A complete bundle is evidence of these synthetic cases, not authority
to launch a worker. Hashes bind content, not provenance or authenticity.
"""
import sys

if not sys.flags.isolated or not sys.dont_write_bytecode:
    print('{"status":"UNVERIFIED","reason":"python_I_B_required"}')
    raise SystemExit(3)

import argparse
import hashlib
import importlib.util
import json
import os
import re
import signal
import stat
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import quote

# Fixed sibling only: no sys.path search, environment override or CLI plugin.
_spec = importlib.util.spec_from_file_location(
    "profile_qualification", Path(__file__).resolve().with_name("qualify-opencode-profile.py"))
if _spec is None or _spec.loader is None:
    print('{"status":"UNVERIFIED","reason":"sibling_loader_unavailable"}')
    raise SystemExit(3)
q = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(q)
Unverified = q.Unverified
CASES = ("read-allow", "edit-allow", "edit-deny", "shell-allow", "shell-deny",
         "subagent-allow", "subagent-deny", "unknown-control", "invalid-control")
SUCCESS = "TOOL_DISPATCH_OBSERVED"
FINAL = "Fixture complete"
CHILD = "CHILD_FIXTURE_ONLY return final response"
LIMIT = 262144
MAX_REQUESTS = 12
CASE_SECONDS = 17
NS = {"status": "VERIFIED", "network_namespace_changed": True,
      "user_namespace_changed": True, "nonroot_identity_preserved": True,
      "interfaces": ["lo"], "loopback_up": True}


def require(condition, reason="invalid_evidence"):
    if not condition:
        raise Unverified(reason)


def shape(value, keys):
    require(type(value) is dict and set(value) == set(keys))


def json_object(value: object) -> dict[str, Any]:
    if type(value) is not dict or not all(type(key) is str for key in value):
        raise Unverified("invalid_evidence")
    return cast(dict[str, Any], value)


def json_array(value: object) -> list[Any]:
    if type(value) is not list:
        raise Unverified("invalid_evidence")
    return cast(list[Any], value)


class RunnerSettings(Protocol):
    CALL_TIMEOUT: int


def plan(case, project):
    require(case in CASES)
    action, policy = case.split("-")
    target = str(Path(project) / "target.txt")
    # Relative resource is intentional. An absolute edit rule did NOT match in
    # the exploratory runtime. That mismatch is not evidence of a deny bypass.
    args = {"read": {"path": target},
            "edit": {"path": target, "oldString": "original-fixture", "newString": "edited-fixture"},
            "shell": {"command": "printf shell-effect > shell-marker", "timeout": 2000},
            "subagent": {"agent": "general", "description": "Fixture child response", "prompt": CHILD},
            "unknown": {}, "invalid": {"path": 42}}[action]
    name = {"unknown": "fixture_unknown", "invalid": "read"}.get(action, action)
    sequence = ([("read", {"path": target})] if action == "edit" else []) + [(name, args)]
    rules = [{"action": "*", "resource": "*", "effect": "allow"}]
    if policy == "deny":
        resource = {"edit": "target.txt", "shell": "printf shell-effect > shell-marker",
                    "subagent": "general"}[action]
        rules.append({"action": action, "resource": resource, "effect": "deny"})
    return [{"id": f"call_fixture_{i}", "name": n, "arguments": a}
            for i, (n, a) in enumerate(sequence, 1)], rules


def profile(rules):
    return {"providers": {"fixture": {"package": "@ai-sdk/openai-compatible",
            "settings": {"baseURL": "http://127.0.0.1:18801/v1", "apiKey": "synthetic"},
            "models": {"model": {"name": "fixture", "tool_call": True,
                                   "limit": {"context": 64000, "output": 4000}}}}},
            "agents": {"probe": {"mode": "primary", "description": "Synthetic tool probe",
                                  "system": "Synthetic fixture only.", "permissions": rules}}}


def sse(call=None):
    delta: dict[str, Any] = {"role": "assistant"}
    if call:
        delta["tool_calls"] = [{"index": 0, "id": call["id"], "type": "function",
                                "function": {"name": call["name"],
                                             "arguments": json.dumps(call["arguments"])}}]
    else:
        delta["content"] = FINAL
    def chunk(d, finish):
        return "data: " + json.dumps({"id": "chatcmpl-fixture", "object": "chat.completion.chunk",
                "created": 0, "model": "model", "choices": [{"index": 0, "delta": d,
                "finish_reason": finish}]}) + "\n\n"
    return chunk(delta, None) + chunk({}, "tool_calls" if call else "stop") + "data: [DONE]\n\n"


def decode_sse(raw):
    require(type(raw) is str and len(raw.encode()) <= LIMIT and raw.endswith("\n\n"), "bad_sse")
    blocks = raw.split("\n\n")
    require(len(blocks) == 4 and blocks[-2:] == ["data: [DONE]", ""], "truncated_sse")
    chunks = []
    for block in blocks[:2]:
        require(block.startswith("data: "), "bad_sse")
        chunks.append(q.parse_json(block[6:]))
    first, last = chunks
    for chunk in chunks:
        shape(chunk, ("id", "object", "created", "model", "choices"))
        require(chunk["id"] == "chatcmpl-fixture" and chunk["object"] == "chat.completion.chunk"
                and chunk["created"] == 0 and chunk["model"] == "model" and len(chunk["choices"]) == 1)
        shape(chunk["choices"][0], ("index", "delta", "finish_reason"))
        require(chunk["choices"][0]["index"] == 0)
    a, b = first["choices"][0], last["choices"][0]
    require(a["finish_reason"] is None and b["delta"] == {})
    d = a["delta"]
    if b["finish_reason"] == "stop":
        require(d == {"role": "assistant", "content": FINAL})
        return None
    require(b["finish_reason"] == "tool_calls")
    shape(d, ("role", "tool_calls"))
    require(d["role"] == "assistant" and len(d["tool_calls"]) == 1)
    call = d["tool_calls"][0]
    shape(call, ("index", "id", "type", "function"))
    shape(call["function"], ("name", "arguments"))
    require(call["index"] == 0 and call["type"] == "function")
    return {"id": call["id"], "name": call["function"]["name"],
            "arguments": q.parse_json(call["function"]["arguments"])}


class Conversation:
    """Pure state machine, replayed verbatim by the standalone inspector."""
    def __init__(self, sequence):
        self.sequence, self.sent, self.results = sequence, [], {}
        self.final, self.titles, self.children = False, 0, 0

    def respond(self, body):
        require(type(body) is dict and type(body.get("messages")) is list, "bad_request")
        body = json_object(body)
        require(body.get("model") == "model" and body.get("stream") is True, "unexpected_model_request")
        messages = [json_object(m) for m in json_array(body["messages"])]
        require(all(type(m) is dict for m in messages))
        child = any(CHILD in str(m.get("content", "")) for m in messages if m.get("role") == "user")
        if child:
            self.children += 1
            require(self.children <= 1 and any(c["name"] == "subagent" for c in self.sent), "recursive_child")
            return sse()
        if not body.get("tools"):
            self.titles += 1
            require(self.titles <= 2, "title_limit")
            return sse()
        require(not self.final, "request_after_final")
        schemas = json_array(body["tools"])
        require(type(schemas) is list and len(schemas) <= 64)
        names = [t["function"]["name"] for t in schemas]
        require(len(names) == len(set(names)))
        known_ids = {c["id"] for c in self.sent}
        tools = [m for m in messages if m.get("role") == "tool"]
        require(all(m.get("tool_call_id") in known_ids for m in tools), "call_id_mismatch")
        for c in self.sent:
            matches = [m for m in tools if m.get("tool_call_id") == c["id"]]
            require(len(matches) == 1 and type(matches[0].get("content")) is str, "missing_tool_result")
            content = matches[0]["content"]
            require(c["id"] not in self.results or self.results[c["id"]] == content, "changed_tool_result")
            self.results[c["id"]] = content
        if len(self.sent) == len(self.sequence):
            self.final = True
            return sse()
        call = self.sequence[len(self.sent)]
        require((call["name"] in names) == (call["name"] != "fixture_unknown"), "tool_unavailable")
        self.sent.append(call)
        return sse(call)


def classify_result(content, state):
    if state.get("status") == "completed":
        require(state.get("output") == content, "output_mismatch")
        return "COMPLETED"
    require(state.get("status") == "error", "unfinished_tool")
    value = q.parse_json(content)
    shape(value, ("error", "content"))
    shape(value["error"], ("type", "message"))
    error = value["error"]
    require(value["content"] == [] and error["message"] == state.get("error"))
    if error["type"] == "permission.rejected":
        return "DENIED"
    if error["type"] == "tool.execution" and error["message"].startswith('No tool named "'):
        return "UNAVAILABLE"
    if (error["type"] == "tool.execution" and error["message"].startswith('Invalid arguments for tool "read":\n')
            and "path: Expected string" in error["message"]):
        return "INVALID_ARGUMENTS"
    return "UNVERIFIED"


def tree(root, deadline):
    result = {}
    def visit(path, name):
        require(time.monotonic() < deadline and len(result) < 64, "snapshot_limit")
        info = path.lstat()
        row: dict[str, Any] = {"mode": stat.S_IMODE(info.st_mode)}
        if stat.S_ISDIR(info.st_mode):
            row["type"] = "directory"
            result[name] = row
            for child in sorted(path.iterdir()):
                visit(child, (name + "/" if name != "." else "") + child.name)
        elif stat.S_ISREG(info.st_mode):
            raw = q.read_evidence(path)
            require(len(raw) <= 4096, "snapshot_limit")
            result[name] = {**row, "type": "file", "bytes_hex": raw.hex()}
        elif stat.S_ISLNK(info.st_mode):
            result[name] = {**row, "type": "symlink", "target": os.readlink(path)}
        else:
            result[name] = {**row, "type": "special"}
    visit(root, ".")
    return result


def validate_inventory(pages, project):
    require(type(pages) is list and 1 <= len(pages) <= 4, "inventory_incomplete")
    pages = json_array(pages)
    rows, cursor = {}, None
    for i, page in enumerate(pages):
        shape(page, ("path", "body"))
        require(page["path"] == "/api/session" + ("?cursor=" + quote(cursor, safe="") if cursor else ""))
        body = page["body"]
        shape(body, ("data", "cursor"))
        shape(body["cursor"], ("previous", "next"))
        require(type(body["data"]) is list and len(body["data"]) <= 32)
        for row in body["data"]:
            sid = q.identifier(row, "ses_")
            require(sid not in rows and row.get("location") == {"directory": project})
            rows[sid] = row
        cursor = body["cursor"]["next"]
        if not body["data"]:
            require(cursor is None and i == len(pages) - 1)
        else:
            require(type(cursor) is str and len(cursor) <= 2048 and i < len(pages) - 1, "inventory_incomplete")
    require(not pages[-1]["body"]["data"], "inventory_incomplete")
    return rows


def tool_parts(export):
    shape(export, ("info", "messages"))
    require(type(export["messages"]) is list)
    parts = []
    for message in export["messages"]:
        require(type(message) is dict and message.get("type") in ("agent-switched", "user", "assistant", "idle"))
        if message["type"] == "assistant":
            require(type(message.get("content")) is list)
            require(message.get("model") == {"id": "model", "providerID": "fixture", "variant": "default"})
            require(message.get("finish") in ("stop", "tool-calls"))
            parts.extend(json_array(message["content"]))
    require(export["info"].get("outcome") == "succeeded")
    require(export["messages"] and export["messages"][-1].get("type") == "idle"
            and export["messages"][-1].get("outcome") == "succeeded", "session_incomplete")
    return parts


def correlate_export(parts, events, results):
    tools = [p for p in parts if p.get("type") == "tool"]
    require(len(tools) == len(events), "export_event_mismatch")
    for part, event in zip(tools, events, strict=True):
        require(part.get("id") == event["id"] and part.get("name") == event["tool"])
        state = part["state"]
        require(state["input"] == event["state"]["input"] and state["status"] == event["state"]["status"])
        if state["status"] == "error":
            require(state["error"] == q.parse_json(results[part["id"]])["error"], "export_error_mismatch")
        else:
            content = [json_object(p) for p in json_array(state["content"])]
            require(type(content) is list and all(p.get("type") == "text" for p in content))
            require("\n".join(p["text"] for p in content) == results[part["id"]], "export_content_mismatch")
    require(any(p.get("type") == "text" and p.get("text") == FINAL for p in parts), "export_final_missing")


def validate_case(row):
    shape(row, ("case", "project", "session", "profile", "before", "after", "requests", "events",
                "inventory_before", "inventory_after", "exports", "commands", "exit", "failure", "classification"))
    require(row["failure"] is None and type(row["exit"]) is int and row["exit"] == 0)
    sequence, rules = plan(row["case"], row["project"])
    require(row["profile"] == profile(rules))
    require(type(row["project"]) is str and re.fullmatch(r"/[A-Za-z0-9_./-]+", row["project"]))
    sid = q.identifier({"id": row["session"]}, "ses_")
    machine = Conversation(sequence)
    require(type(row["requests"]) is list and 2 <= len(row["requests"]) <= MAX_REQUESTS)
    for exchange in row["requests"]:
        shape(exchange, ("path", "body", "response"))
        require(exchange["path"] == "/v1/chat/completions")
        expected = machine.respond(exchange["body"])
        require(decode_sse(exchange["response"]) == decode_sse(expected))
    require(machine.final and machine.sent == sequence and len(machine.results) == len(sequence))
    require(type(row["events"]) is list and len(row["events"]) <= 128)
    require(all(type(e) is dict and e.get("sessionID") == sid
                and e.get("type") in ("step_start", "step_finish", "tool_use", "text")
                for e in row["events"]), "event_session_mismatch")
    events = [e["part"] for e in row["events"] if e.get("type") == "tool_use"]
    require(len(events) == len(sequence))
    results = []
    for call, event in zip(sequence, events, strict=True):
        require(event.get("sessionID") == sid and event.get("type") == "tool"
                and event.get("id") == call["id"] and event.get("tool") == call["name"]
                and event.get("state", {}).get("input") == call["arguments"], "event_mismatch")
        results.append(classify_result(machine.results[call["id"]], event["state"]))
        if call["name"] == "read" and results[-1] == "COMPLETED":
            require(machine.results[call["id"]] == f'Read file {call["arguments"]["path"]}, lines 1-1\n1: original-fixture',
                    "read_content_mismatch")
    require(any(e.get("type") == "text" and e.get("sessionID") == sid
                and e.get("part", {}).get("text") == FINAL for e in row["events"]), "missing_final")
    wanted = ("DENIED" if row["case"].endswith("deny") else
              "UNAVAILABLE" if row["case"] == "unknown-control" else
              "INVALID_ARGUMENTS" if row["case"] == "invalid-control" else "COMPLETED")
    require(results == ["COMPLETED"] * (len(sequence) - 1) + [wanted], "wrong_outcome")
    initial = {".": {"type": "directory", "mode": 448},
               "target.txt": {"type": "file", "mode": 384, "bytes_hex": b"original-fixture\n".hex()}}
    require(row["before"] == initial)
    after = json.loads(json.dumps(initial))
    if row["case"] == "edit-allow":
        after["target.txt"]["bytes_hex"] = b"edited-fixture\n".hex()
    if row["case"] == "shell-allow":
        after["shell-marker"] = {"type": "file", "mode": 384, "bytes_hex": b"shell-effect".hex()}
    require(row["after"] == after, "unexpected_filesystem_effect")
    before = validate_inventory(row["inventory_before"], row["project"])
    inventory = validate_inventory(row["inventory_after"], row["project"])
    require(before == {} and sid in inventory)
    children = {i: v for i, v in inventory.items() if i != sid}
    require(len(children) == (1 if row["case"] == "subagent-allow" else 0), "unexpected_child")
    require(type(row["exports"]) is dict and set(row["exports"]) == set(inventory))
    for i, export in row["exports"].items():
        require(export["info"] == inventory[i])
        parts = tool_parts(export)
        if i == sid:
            require(inventory[i].get("agent") == "probe" and "parentID" not in inventory[i])
            correlate_export(parts, events, machine.results)
        else:
            require(inventory[i].get("parentID") == sid and inventory[i].get("agent") == "general" and machine.children == 1)
            require(not any(p.get("type") == "tool" for p in parts), "recursive_child")
            require(any(p.get("type") == "text" and p.get("text") == FINAL for p in parts), "child_incomplete")
            require(machine.results[sequence[-1]["id"]] == f'<subagent sessionID="{i}" state="completed">\n{FINAL}\n</subagent>')
    if not children:
        require(machine.children == 0)
    validate_commands(row)
    return wanted


def run_args(sid):
    return ["run", "--standalone", "--session", sid, "--agent", "probe", "--model",
            "fixture/model", "--format", "json", "Run the deterministic fixture"]


def validate_commands(row):
    expected = [["api", "--standalone", "GET", p["path"]] for p in row["inventory_before"]]
    expected.append(run_args(row["session"]))
    expected += [["api", "--standalone", "GET", p["path"]] for p in row["inventory_after"]]
    expected += [["session", "export", "--standalone", sid] for sid in sorted(row["exports"])]
    require(type(row["commands"]) is list and len(row["commands"]) == len(expected))
    for command, args in zip(row["commands"], expected, strict=True):
        require(q.validate_returned_command(command) == ["<binary>", *args] and command["exit_code"] == 0)


def classification(row):
    try:
        return validate_case(row)
    except (Unverified, KeyError, TypeError, ValueError, AttributeError, IndexError, RecursionError):
        return "UNVERIFIED"


def inventory(runner):
    pages, cursor = [], None
    for _ in range(4):
        path = "/api/session" + ("?cursor=" + quote(cursor, safe="") if cursor else "")
        code, raw = runner.run(["api", "--standalone", "GET", path])
        require(code == 0, "inventory_failed")
        body = q.parse_json(raw)
        pages.append({"path": path, "body": body})
        if not body["data"]:
            validate_inventory(pages, str(runner.cwd))
            return pages
        cursor = body["cursor"]["next"]
        require(type(cursor) is str and len(cursor) <= 2048, "inventory_incomplete")
    raise Unverified("inventory_incomplete")


def observe(binary, root, case, deadline):
    root.mkdir(mode=0o700)
    env = q.environment(root)
    project = root / "project"
    project.mkdir(mode=0o700)
    target = project / "target.txt"
    target.write_bytes(b"original-fixture\n")
    target.chmod(0o600)
    sequence, rules = plan(case, str(project))
    config = root / "config/opencode"
    config.mkdir(mode=0o700)
    q.write_json(config / "opencode.json", profile(rules))
    sid = "ses_fixture_" + os.urandom(12).hex()
    row = {"case": case, "project": str(project), "session": sid, "profile": profile(rules),
           "before": tree(project, deadline), "after": {}, "requests": [], "events": [],
           "inventory_before": [], "inventory_after": [], "exports": {}, "commands": [],
           "exit": None, "failure": None, "classification": "UNVERIFIED"}
    runner = q.Runner(binary, project, env, deadline, row["commands"])
    machine, errors = Conversation(sequence), []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            try:
                require(self.path == "/v1/chat/completions", "unexpected_endpoint")
                require(time.monotonic() < deadline and len(row["requests"]) < MAX_REQUESTS, "request_limit")
                require(self.headers.get("Transfer-Encoding") is None, "unsupported_transfer")
                length = int(self.headers.get("Content-Length", "0"))
                require(0 < length <= LIMIT, "request_limit")
                self.connection.settimeout(min(2, max(.01, deadline - time.monotonic())))
                raw = self.rfile.read(length)
                require(len(raw) == length, "truncated_request")
                body = q.parse_json(raw)
                response = machine.respond(body)
                row["requests"].append({"path": self.path, "body": body, "response": response})
                # Only body and our exact SSE survive. Authorization headers are
                # neither recorded nor echoed. The key 'synthetic' is public.
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(response.encode())))
                self.end_headers()
                self.wfile.write(response.encode())
                self.wfile.flush()
            except (OSError, Unverified, ValueError, KeyError, TypeError):
                errors.append("http_or_protocol_failure")
                self.close_connection = True
    class BoundedServer(HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            # Bound header parsing too, before BaseHTTPRequestHandler enters
            # do_POST. A stalled partial header must not wedge shutdown().
            connection.settimeout(min(2, max(.01, deadline - time.monotonic())))
            return connection, address
    server = BoundedServer(("127.0.0.1", 18801), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
    thread.start()
    try:
        row["inventory_before"] = inventory(runner)
        row["exit"], raw = runner.run(run_args(sid))
        require(raw.endswith(b"\n"), "truncated_events")
        row["events"] = [q.parse_json(line) for line in raw.splitlines()]
        row["inventory_after"] = inventory(runner)
        for session in sorted(validate_inventory(row["inventory_after"], str(project))):
            code, raw = runner.run(["session", "export", "--standalone", session])
            require(code == 0, "export_failed")
            row["exports"][session] = q.parse_json(raw)
    except (Unverified, OSError, ValueError, KeyError, TypeError):
        row["failure"] = "runtime_or_capture_failed"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        if thread.is_alive() or errors:
            row["failure"] = "http_or_protocol_failure"
        row["after"] = tree(project, deadline + 1)
        if q.parse_json(q.read_evidence(config / "opencode.json")) != row["profile"]:
            row["failure"] = "profile_changed"
    row["classification"] = classification(row)
    return row


def overall(rows):
    if len(rows) != len(CASES) or [r.get("case") for r in rows] != list(CASES):
        return "UNVERIFIED"
    for row in rows:
        actual = classification(row)
        if actual == "UNVERIFIED" or row.get("classification") != actual:
            return "UNVERIFIED"
    return SUCCESS


def freeze(output, name, value):
    stage = q.stage_json(output, name, value, [])
    stage.chmod(0o400)
    os.link(stage, output / name, follow_symlinks=False)
    return hashlib.sha256(q.read_evidence(stage)).hexdigest()


def publish(output, metadata, rows):
    hashes = {}
    for row in rows:
        name = row["case"] + ".json"
        hashes[name] = freeze(output, name, row)
    status = overall(rows) if metadata["failure"] is None else "UNVERIFIED"
    report = {"schema_version": 1, "status": "UNVERIFIED", "observation_status": status,
              "publication": "REQUIRES_VALID_READY", "launch_authorized": False,
              "metadata": metadata, "cases": hashes}
    report_hash = freeze(output, "report.json", report)
    manifest = {"schema_version": 1, "metadata": metadata, "files": {**hashes, "report.json": report_hash}}
    manifest_hash = freeze(output, "manifest.json", manifest)
    q.sync_directory(output)
    freeze(output, "READY", {"schema_version": 1, "status": status, "completion": "COMPLETE",
                              "manifest_sha256": manifest_hash, "report_sha256": report_hash})
    return inspect(output)


def inspect(output):
    result = {"status": "UNVERIFIED", "publication": "INCOMPLETE_OR_INVALID", "launch_authorized": False}
    try:
        output = Path(output)
        require(output.is_absolute() and output.resolve(strict=True) == output)
        raw = {}
        def read(name):
            path = output / name
            require(stat.S_IMODE(path.lstat().st_mode) == 0o400)
            raw[name] = q.read_evidence(path)
            return q.parse_json(raw[name])
        ready, manifest, report = read("READY"), read("manifest.json"), read("report.json")
        shape(ready, ("schema_version", "status", "completion", "manifest_sha256", "report_sha256"))
        shape(manifest, ("schema_version", "metadata", "files"))
        shape(report, ("schema_version", "status", "observation_status", "publication", "launch_authorized", "metadata", "cases"))
        require(all(x["schema_version"] == 1 for x in (ready, manifest, report)))
        require(ready["completion"] == "COMPLETE" and ready["status"] in (SUCCESS, "UNVERIFIED"))
        require(report["status"] == "UNVERIFIED" and report["publication"] == "REQUIRES_VALID_READY"
                and report["launch_authorized"] is False and report["observation_status"] == ready["status"])
        require(ready["report_sha256"] == hashlib.sha256(raw["report.json"]).hexdigest()
                and ready["manifest_sha256"] == hashlib.sha256(raw["manifest.json"]).hexdigest())
        metadata = report["metadata"]
        shape(metadata, ("version", "binary_sha256", "namespace", "runtime_cleanup", "failure", "commands", "timeout"))
        require(metadata == manifest["metadata"] and type(metadata["timeout"]) is int and 1 <= metadata["timeout"] <= 180)
        require(type(report["cases"]) is dict and set(report["cases"]).issubset({c + ".json" for c in CASES}))
        require(manifest["files"] == {**report["cases"], "report.json": ready["report_sha256"]})
        rows = []
        for case in CASES:
            name = case + ".json"
            if name in report["cases"]:
                row = read(name)
                require(hashlib.sha256(raw[name]).hexdigest() == report["cases"][name] and row["case"] == case)
                require(row["classification"] == classification(row))
                rows.append(row)
        actual = overall(rows) if metadata["failure"] is None else "UNVERIFIED"
        require(actual == ready["status"])
        if actual == SUCCESS:
            require(metadata["version"] == q.VERSION and q.valid_sha256(metadata["binary_sha256"])
                    and metadata["namespace"] == NS and metadata["runtime_cleanup"] == "removed")
            require(all(metadata["namespace"][k] is True for k in ("network_namespace_changed",
                    "user_namespace_changed", "nonroot_identity_preserved", "loopback_up")))
            require(len(metadata["commands"]) == 1)
            command = metadata["commands"][0]
            require(q.validate_returned_command(command) == ["<binary>", "--version"] and command["exit_code"] == 0)
        require(all(q.read_evidence(output / name) == value for name, value in raw.items()))
        result.update(status=actual, publication="COMPLETE", cases={r["case"]: r["classification"] for r in rows})
    except (Unverified, OSError, KeyError, TypeError, ValueError, AttributeError, IndexError, RecursionError):
        pass
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect-output")
    parser.add_argument("--isolated-guest", action="store_true")
    parser.add_argument("--binary")
    parser.add_argument("--expected-sha")
    parser.add_argument("--output")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)
    if args.inspect_output:
        require(not any((args.binary, args.expected_sha, args.output, args.isolated_guest)))
        result = inspect(args.inspect_output)
    else:
        if (not args.isolated_guest or not args.binary or not args.output or not args.expected_sha
                or not q.valid_sha256(args.expected_sha) or not 1 <= args.timeout <= 180):
            parser.error("guest assertion, absolute binary/output, expected SHA256 and timeout 1..180 required")
        binary, output = Path(args.binary), Path(args.output)
        require(binary.is_absolute() and binary.resolve(strict=True) == binary)
        require(output.is_absolute() and output.parent.resolve(strict=True) == output.parent)
        output.mkdir(mode=0o700)
        metadata = {"version": q.VERSION, "binary_sha256": args.expected_sha, "namespace": None,
                    "runtime_cleanup": "UNVERIFIED", "failure": None, "commands": [], "timeout": args.timeout}
        rows = []
        deadline = time.monotonic() + args.timeout - 3  # reserve cleanup/publication time
        old_umask = os.umask(0o077)
        old_signals = {s: signal.signal(s, q.interrupted) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            require(q.digest_file(binary, q.MAX_BINARY, deadline) == args.expected_sha, "binary_hash_mismatch")
            metadata["namespace"] = q.setup_private_namespace()  # before any bind or binary launch
            with tempfile.TemporaryDirectory(prefix="dispatch-") as temporary:
                scratch = Path(temporary)
                preflight = scratch / "preflight"
                preflight.mkdir(mode=0o700)
                runner = q.Runner(binary, preflight, q.environment(preflight), deadline, metadata["commands"])
                code, raw = runner.run(["--version"])
                require(code == 0 and raw.strip() == b"opencode v2.0.32", "unsupported_version")
                cast(RunnerSettings, q).CALL_TIMEOUT = 12
                for case in CASES:
                    require(time.monotonic() < deadline, "deadline")
                    rows.append(observe(binary, scratch / case, case, min(deadline, time.monotonic() + CASE_SECONDS)))
                require(q.digest_file(binary, q.MAX_BINARY, deadline) == args.expected_sha, "binary_changed")
            metadata["runtime_cleanup"] = "removed"
        except (Unverified, OSError, ValueError, KeyError, TypeError):
            metadata["failure"] = "qualification_incomplete"
        finally:
            os.umask(old_umask)
            for sig, handler in old_signals.items():
                signal.signal(sig, handler)
        result = publish(output, metadata, rows)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == SUCCESS else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Unverified, OSError, ValueError):
        print('{"status":"UNVERIFIED","reason":"input_or_publication_failed","launch_authorized":false}')
        raise SystemExit(3)
