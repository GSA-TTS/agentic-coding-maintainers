#!/usr/bin/env python3
"""Bounded guest-only policy observation for OpenCode 2.0.32.

Run with python3 -I -B inside an independently isolated, network-none guest.
The flag is an operator assertion, NOT a sandbox. No inference or tool dispatch
is attempted. Exit 0 means PROFILE_POLICY_OBSERVED; 3 means UNVERIFIED.
Unknown API schemas fail closed; the fake CLI tests are not runtime evidence.
"""

import sys

if not sys.flags.isolated or not sys.dont_write_bytecode:
    sys.stdout.write('{"status":"UNVERIFIED","reason":"python_I_B_required",'
                     '"launch_authorized":false,"tool_dispatch_enforcement":"UNVERIFIED"}\n')
    raise SystemExit(3)

import argparse
import hashlib
import json
import os
import re
import secrets
import selectors
import signal
import stat
import subprocess
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any

VERSION = "2.0.32"
MAX_STREAM = 262144
MAX_BINARY = 512 * 1024 * 1024
MAX_SOURCE = 65536
CALL_TIMEOUT = 8
READY_ATTEMPTS = 5
AGENT_ATTEMPTS = 3
CASES = ("clean", "conflict", "missing", "malformed")
RULES = [{"action": "*", "resource": "*", "effect": "deny"},
         {"action": "read", "resource": "*", "effect": "allow"}]
ACTIONS = {"read": "/candidate/sample.py", "edit": "/candidate/sample.py",
           "shell": "printf fixture", "subagent": "fixture-agent"}


class Unverified(Exception):
    """Only fixed reason codes may cross into retained reports."""


def digest_file(path, limit, deadline):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise Unverified("unsafe_or_oversized_file")
        value, count = hashlib.sha256(), 0
        while True:
            if time.monotonic() >= deadline:
                raise Unverified("deadline")
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            count += len(chunk)
            if count > limit:
                raise Unverified("file_limit")
            value.update(chunk)
        after = os.fstat(fd)
        def stamp(s):
            return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns
        if stamp(before) != stamp(after) or stamp(after) != stamp(os.stat(path, follow_symlinks=False)):
            raise Unverified("file_changed")
        return value.hexdigest()
    finally:
        os.close(fd)


def stop(process):
    """Kill the owned group even if its leader exited leaving inherited pipes."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        raise Unverified("cleanup_timeout") from None


def interrupted(*_):
    raise Unverified("interrupted")


class Runner:
    def __init__(self, binary, cwd, env, deadline, commands):
        self.binary, self.cwd, self.env = str(binary), cwd, env
        self.deadline, self.commands = deadline, commands
        self.server: subprocess.Popen | None = None

    def alive(self):
        if self.server is not None and self.server.poll() is not None:
            raise Unverified("owned_server_exited")

    def run(self, args):
        self.alive()
        end = min(self.deadline, time.monotonic() + CALL_TIMEOUT)
        if end <= time.monotonic():
            raise Unverified("deadline")
        # All arguments are generated here. No raw output or environment is logged.
        record: dict[str, Any] = {"argv": ["<binary>", *args], "status": "UNVERIFIED"}
        self.commands.append(record)
        process = subprocess.Popen([self.binary, *args], cwd=self.cwd, env=self.env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        assert process.stdout is not None and process.stderr is not None
        output, sizes = bytearray(), {"stdout": 0, "stderr": 0}
        try:
            with selectors.DefaultSelector() as selector:
                for stream, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, name)
                while selector.get_map():
                    self.alive()
                    remaining = end - time.monotonic()
                    if remaining <= 0:
                        raise Unverified("command_timeout")
                    for key, _ in selector.select(min(remaining, 0.05)):
                        chunk = os.read(key.fd, 16384)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        sizes[key.data] += len(chunk)
                        if sizes[key.data] > MAX_STREAM:
                            raise Unverified("stream_limit")
                        if key.data == "stdout":
                            output.extend(chunk)
                try:
                    code = process.wait(timeout=max(0.001, end - time.monotonic()))
                except subprocess.TimeoutExpired:
                    raise Unverified("command_timeout") from None
            self.alive()
            record.update(status="RETURNED", exit_code=code, bytes=sizes)
            # Never return secret-bearing output, including an accidental echo.
            if self.env.get("OPENCODE_PASSWORD", "\x00").encode() in output:
                raise Unverified("secret_in_response")
            return code, bytes(output)
        except Unverified as exc:
            record.update(status="UNVERIFIED", reason=str(exc), bytes=sizes)
            raise
        finally:
            stop(process)
            process.stdout.close()
            process.stderr.close()

    def start(self, port):
        if time.monotonic() >= self.deadline:
            raise Unverified("deadline")
        args = ["serve", "--hostname", "127.0.0.1", "--port", str(port)]
        self.commands.append({"argv": ["<binary>", *args], "status": "STARTED",
                              "output": "discarded; may contain password"})
        # /dev/null is deliberately used rather than a raw server log on disk.
        self.server = subprocess.Popen([self.binary, *args], cwd=self.cwd, env=self.env,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, start_new_session=True)

    def api(self, port, method, path, body=None):
        args = ["api", "--server", f"http://127.0.0.1:{port}", method, path]
        if body is not None:
            args.extend(["--data", json.dumps(body, separators=(",", ":"))])
        code, raw = self.run(args)
        if code != 0:
            raise Unverified("api_cli_failed")
        return parse_json(raw)


def parse_json(raw):
    """Decode JSON only; each endpoint has its own measured wire schema."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Unverified("duplicate_json_key")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(Unverified("json_constant")))
    except (ValueError, UnicodeError, RecursionError):
        raise Unverified("invalid_json") from None
    return value


def parse_config(value):
    """GET /api/config is a RAW ARRAY of document/directory source records."""
    if type(value) is not list or len(value) > 64:
        raise Unverified("unsupported_config_schema")
    seen = set()
    for row in value:
        if type(row) is not dict:
            raise Unverified("unsupported_source_schema")
        kind, path = row.get("type"), row.get("path")
        if kind not in ("document", "directory"):
            raise Unverified("unsupported_source_schema")
        if (set(row) != ({"type", "path", "info"} if kind == "document" else {"type", "path"})
                or type(path) is not str or not path.startswith("/") or len(path) > 4096
                or any(ord(c) < 32 for c in path) or path in seen):
            raise Unverified("unsupported_source_schema")
        if kind == "document" and type(row["info"]) is not dict:
            raise Unverified("unsupported_source_schema")
        seen.add(path)
    return value


def parse_agent(value, agent_id, marker, cwd, selected_rules):
    """Bind the resolved agent to the exact location and ordered policy layers."""
    if (type(value) is not dict or set(value) != {"location", "data"}
            or value["location"] != {"directory": str(cwd)}):
        raise Unverified("unsupported_agent_envelope")
    data = value["data"]
    fields = {"id", "name", "request", "system", "description", "mode", "hidden", "permissions"}
    if (type(data) is not dict or set(data) != fields or data.get("id") != agent_id
            or data.get("name") != agent_id or data.get("description") != marker
            or data.get("request") != {"settings": {}, "headers": {}, "body": {}}
            or data.get("system") != "Synthetic policy fixture."
            or data.get("mode") != "primary" or data.get("hidden") is not False
            or type(data.get("permissions")) is not list or not data["permissions"]
            or len(data["permissions"]) > 128):
        raise Unverified("unsupported_or_unselected_agent")
    for rule in data["permissions"]:
        if (type(rule) is not dict or set(rule) != {"action", "resource", "effect"}
                or any(type(rule[k]) is not str or len(rule[k]) > 4096 for k in rule)
                or rule["effect"] not in {"allow", "deny", "ask"}):
            raise Unverified("unsupported_permission_schema")
    rules = data["permissions"]
    # Observed default categories only; an unknown prefix rule is not silently
    # trusted simply because the selected deny happens to follow it.
    default_allow = {"action": "*", "resource": "*", "effect": "allow"}
    browser_deny = {"action": "browser", "resource": "*", "effect": "deny"}
    suffix = [browser_deny] if rules[-1] == browser_deny else []
    index = len(rules) - len(suffix) - len(selected_rules)
    if index < 0 or rules[index:index + len(selected_rules)] != selected_rules:
        raise Unverified("selected_rules_mismatch")
    prefix = rules[:index]
    for rule in prefix:
        env_ask = (rule["action"] == "read" and rule["effect"] == "ask"
                    and rule["resource"] in {".env", ".env.*", "*.env", "*.env.*", "**/.env", "**/.env.*"})
        env_example = rule == {"action":"read", "resource":"*.env.example", "effect":"allow"}
        if rule != default_allow and not env_ask and not env_example:
            raise Unverified("unknown_default_permission")
    return {"defaults": prefix, "selected": selected_rules, "suffix": suffix}


def identifier(data, prefix):
    if type(data) is not dict or type(data.get("id")) is not str:
        raise Unverified("unsupported_identifier_schema")
    value = data["id"]
    if re.fullmatch(prefix + r"[A-Za-z0-9_-]{1,96}", value) is None:
        raise Unverified("invalid_identifier")
    return value


def parse_session(value, agent_id, cwd):
    if type(value) is not dict or set(value) != {"data"}:
        raise Unverified("unsupported_session_envelope")
    data = value["data"]
    if (type(data) is not dict or data.get("agent") != agent_id
            or data.get("location") != {"directory": str(cwd)}):
        raise Unverified("session_binding_mismatch")
    # Session metadata beyond these measured binding fields is not retained.
    return identifier(data, "ses_")


def parse_permission(value, request_id):
    if type(value) is not dict or set(value) != {"data"}:
        raise Unverified("unsupported_permission_envelope")
    data = value["data"]
    if (type(data) is not dict or set(data) != {"id", "effect"}
            or data["id"] != request_id or type(data["effect"]) is not str
            or data["effect"] not in {"allow", "deny"}):
        raise Unverified("unsupported_effect_schema")
    return data["effect"]


def environment(root):
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    for name, part in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"),
                       ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache"),
                       ("XDG_STATE_HOME", "state"), ("XDG_RUNTIME_DIR", "run"),
                       ("TMPDIR", "tmp")):
        path = root / part
        path.mkdir(mode=0o700)
        env[name] = str(path)
    return env


def write_json(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")


def profiles(root, case, agent_id, marker):
    config, project = root / "config/opencode", root / "project"
    config.mkdir(mode=0o700)
    project.mkdir(mode=0o700)
    # A fabricated empty .git directory is not a valid project boundary. The
    # entire ancestor layout belongs to this disposable fixture instead.
    selected, competitor = config / "opencode.json", project / "opencode.json"
    agent = {"mode": "primary", "description": marker, "system": "Synthetic policy fixture.",
             "permissions": RULES}
    if case == "malformed":
        selected.write_text('{"agents":', encoding="utf-8")
    elif case != "missing":
        write_json(selected, {"agents": {agent_id: agent}})
    if case == "conflict":
        write_json(competitor, {"agents": {agent_id: {**agent, "description": marker + "-project",
                                                       "permissions": [{"action": "*", "resource": "*",
                                                                        "effect": "allow"}]}}})
    expected = {}
    for path in (selected, competitor):
        if path.exists() and not (case == "malformed" and path == selected):
            expected[str(path)] = parse_json(path.read_bytes())
    return project, (selected, competitor), expected


def snapshot(paths, root, deadline):
    result = {}
    for path in paths:
        key = str(path.relative_to(root))
        try:
            result[key] = digest_file(path, MAX_SOURCE, deadline)
        except FileNotFoundError:
            result[key] = None
    return result


def check_sources(value, expected, root):
    sources = parse_config(value)
    docs = {row["path"]: row["info"] for row in sources if row["type"] == "document"}
    dirs = [row["path"] for row in sources if row["type"] == "directory"]
    if set(docs) != set(expected):
        raise Unverified("source_inventory_mismatch")
    if docs != expected:
        raise Unverified("source_content_mismatch")
    # Resolve no external path from an API response. Only compare known strings.
    allowed_dirs = {str(root / p) for p in ("config/opencode", "project", "project/.opencode")}
    if (str(root / "config/opencode") not in dirs or not set(dirs).issubset(allowed_dirs)):
        raise Unverified("source_directory_mismatch")
    return [{"type": row["type"], "path": str(Path(row["path"]).relative_to(root)),
             **({"info_sha256": hashlib.sha256(json.dumps(row["info"], sort_keys=True,
                                                           separators=(",", ":")).encode()).hexdigest()}
                if row["type"] == "document" else {})} for row in sources]


def observe_case(binary, output, case, port, deadline):
    root = output / case
    root.mkdir(mode=0o700)
    env = environment(root)
    env["OPENCODE_PASSWORD"] = secrets.token_hex(32)
    nonce = secrets.token_hex(12)
    agent_id, marker = "qualification-" + nonce, "selected-" + nonce
    project, paths, expected = profiles(root, case, agent_id, marker)
    record: dict[str, Any] = {"case": case, "status": "UNVERIFIED", "commands": [], "effects": {},
              "tool_dispatch_enforcement": "UNVERIFIED", "launch_authorized": False}
    runner = Runner(binary, project, env, deadline, record["commands"])
    record["profiles_before"] = snapshot(paths, root, deadline)
    try:
        runner.start(port)
        config = None
        for attempt in range(READY_ATTEMPTS):
            try:
                config = runner.api(port, "GET", "/api/config")
                break
            except Unverified as exc:
                if str(exc) != "api_cli_failed" or attempt == READY_ATTEMPTS - 1:
                    raise
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        record["sources_before"] = check_sources(config, expected, root)
        record["profile_contamination_detected"] = case == "conflict"
        # A random agent marker and exact source paths bind replies to this case,
        # alongside an alive owned server and its per-case authentication secret.
        if case in ("missing", "malformed"):
            # Successful exact source inventory proves no selected document was
            # loaded. The known missing/invalid input cannot qualify. A crash or
            # unrecognized error does not reach this branch.
            record.update(status="CANNOT_QUALIFY", reason="selected_document_not_loaded",
                          rejection_evidence="exact_source_inventory")
        else:
            expected_marker = marker + "-project" if case == "conflict" else marker
            expected_rules = (RULES + [{"action": "*", "resource": "*", "effect": "allow"}]
                              if case == "conflict" else RULES)
            agent = None
            for attempt in range(AGENT_ATTEMPTS):
                try:
                    agent = runner.api(port, "GET", "/api/agent/" + agent_id)
                except Unverified as exc:
                    if str(exc) != "api_cli_failed" or attempt == AGENT_ATTEMPTS - 1:
                        raise
                    time.sleep(min(0.1, max(0, deadline - time.monotonic())))
                    continue
                if (type(agent) is dict and agent.get("data") not in (None, {})):
                    break
                if attempt < AGENT_ATTEMPTS - 1:
                    time.sleep(min(0.1, max(0, deadline - time.monotonic())))
            record["resolved_policy"] = parse_agent(agent, agent_id, expected_marker, project, expected_rules)
            session = parse_session(runner.api(port, "POST", "/api/session", {"agent": agent_id}),
                                    agent_id, project)
            for action, resource in ACTIONS.items():
                request_id = "per_" + nonce + "_" + action
                reply = runner.api(port, "POST", f"/api/session/{session}/permission",
                                   {"id": request_id, "action": action, "resources": [resource],
                                    "agent": agent_id})
                record["effects"][action] = parse_permission(reply, request_id)
            wanted = {action: "allow" if action == "read" or case == "conflict" else "deny"
                      for action in ACTIONS}
            if record["effects"] != wanted:
                raise Unverified("policy_positive_control_failed")
            record["status"] = ("PROFILE_CONTAMINATION_DETECTED" if case == "conflict"
                                else "PROFILE_POLICY_OBSERVED")
        record["sources_after"] = check_sources(runner.api(port, "GET", "/api/config"), expected, root)
        if record["sources_before"] != record["sources_after"]:
            raise Unverified("source_inventory_changed")
    except Unverified as exc:
        record.update(status="UNVERIFIED", reason=str(exc))
    except (OSError, ValueError):
        record.update(status="UNVERIFIED", reason="filesystem_or_process_error")
    finally:
        try:
            if runner.server is not None:
                stop(runner.server)
                record["server_cleanup"] = "process_group_killed"
            else:
                record["server_cleanup"] = "not_started"
            record["profiles_after"] = snapshot(paths, root, time.monotonic() + 1)
            if record["profiles_before"] != record["profiles_after"]:
                record.update(status="UNVERIFIED", reason="profile_changed")
        except (OSError, Unverified):
            record.update(status="UNVERIFIED", reason="cleanup_or_snapshot_failed")
    return record


def verdict(cases):
    wanted = {"clean": "PROFILE_POLICY_OBSERVED", "conflict": "PROFILE_CONTAMINATION_DETECTED",
              "missing": "CANNOT_QUALIFY", "malformed": "CANNOT_QUALIFY"}
    if len(cases) != len(wanted) or {r["case"] for r in cases} != set(wanted):
        return "UNVERIFIED"
    return ("PROFILE_POLICY_OBSERVED" if all(r["status"] == wanted[r["case"]] for r in cases)
            else "UNVERIFIED")


def positive_int(value):
    if not re.fullmatch(r"[0-9]+", value):
        raise argparse.ArgumentTypeError("positive integer required")
    return int(value)


def arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolated-guest", action="store_true", required=True)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--output", required=True, help="new absolute directory in the isolated guest")
    parser.add_argument("--port", type=positive_int, default=18763)
    parser.add_argument("--timeout", type=positive_int, default=120)
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 180 or not 1024 <= args.port <= 65532:
        parser.error("timeout must be 1..180; starting port must be 1024..65532 (four owned servers)")
    if not re.fullmatch(r"[0-9a-f]{64}", args.expected_sha):
        parser.error("expected-sha must be a full lowercase SHA256")
    if not Path(args.binary).is_absolute() or not Path(args.output).is_absolute():
        parser.error("binary and output must be absolute guest paths")
    return args


def main(argv=None):
    args = arguments(argv)
    report: dict[str, Any] = {"schema_version": 1, "status": "UNVERIFIED", "launch_authorized": False,
              "tool_dispatch_enforcement": "UNVERIFIED", "cases": [], "commands": [],
              "limits": {"deadline_seconds": args.timeout, "call_seconds": CALL_TIMEOUT,
                         "bytes_per_cli_stream": MAX_STREAM, "readiness_attempts": READY_ATTEMPTS,
                         "agent_attempts": AGENT_ATTEMPTS, "cleanup_wait_seconds_per_group": 1,
                         "max_binary_bytes": MAX_BINARY, "max_profile_bytes": MAX_SOURCE},
              "compatibility": {"version": VERSION, "wire_schema": "endpoint_specific_observed_shapes",
                                "malformed_error_schema": "unknown errors UNVERIFIED; exact source omission rejects selection"},
              "isolation": "operator_asserted_guest_network_none; not independently verified"}
    deadline = time.monotonic() + args.timeout
    output = Path(args.output)
    created = False
    previous_umask = os.umask(0o077)
    previous_signals = {}
    runtime = ExitStack()
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous_signals[sig] = signal.signal(sig, interrupted)
        # Resolve ancestors before creating anything; refuse links and reuse.
        if output.parent.resolve(strict=True) != output.parent or output.name in ("", ".", ".."):
            raise Unverified("unsafe_output_path")
        output.mkdir(mode=0o700)
        created = True
        # Runtime databases/caches are not evidence and could contain credentials.
        # Only normalized observations survive this guest-local temporary tree.
        scratch = Path(runtime.enter_context(tempfile.TemporaryDirectory(prefix="runtime-", dir=output)))
        binary = Path(args.binary)
        if binary.resolve(strict=True) != binary:
            raise Unverified("binary_symlink")
        observed = digest_file(binary, MAX_BINARY, deadline)
        report["binary_sha256"] = observed
        if observed != args.expected_sha:
            raise Unverified("binary_hash_mismatch")
        preflight = scratch / "preflight"
        preflight.mkdir(mode=0o700)
        runner = Runner(binary, preflight, environment(preflight), deadline, report["commands"])
        code, raw = runner.run(["--version"])
        if code or raw.strip() != ("opencode v" + VERSION).encode():
            raise Unverified("unsupported_version")
        report["version"] = VERSION
        code, raw = runner.run(["api", "--help"])
        if code or b"--server" not in raw or b"--standalone" not in raw:
            raise Unverified("unsupported_api_cli")
        for index, case in enumerate(CASES):
            if digest_file(binary, MAX_BINARY, deadline) != observed:
                raise Unverified("binary_changed")
            report["cases"].append(observe_case(binary, scratch, case, args.port + index, deadline))
        if digest_file(binary, MAX_BINARY, deadline) != observed:
            raise Unverified("binary_changed")
        report["status"] = verdict(report["cases"])
    except Unverified as exc:
        report.update(status="UNVERIFIED", reason=str(exc))
    except (OSError, ValueError):
        report.update(status="UNVERIFIED", reason="filesystem_or_process_error")
    finally:
        try:
            runtime.close()
            report["runtime_cleanup"] = "removed"
        except OSError:
            report.update(status="UNVERIFIED", reason="runtime_cleanup_failed", runtime_cleanup="failed")
        for sig, handler in previous_signals.items():
            signal.signal(sig, handler)
        os.umask(previous_umask)
    if created:
        try:
            write_json(output / "report.json", report)
            report_hash = digest_file(output / "report.json", 1024 * 1024, time.monotonic() + 1)
            write_json(output / "manifest.json", {"schema_version": 1, "files": {"report.json": report_hash},
                                                  "runtime_cleanup": report["runtime_cleanup"],
                                                  "raw_streams_retained": False})
        except (OSError, Unverified):
            report.update(status="UNVERIFIED", reason="report_write_failed")
    # Paths, response data, stdout, stderr and the synthetic password are omitted.
    print(json.dumps({k: report[k] for k in ("status", "tool_dispatch_enforcement", "launch_authorized")}
                     | {"reason": report.get("reason"), "case_count": len(report["cases"])}))
    return 0 if report["status"] == "PROFILE_POLICY_OBSERVED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
