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
from typing import Any, cast

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


def unshare_user_network():
    """One Linux syscall, no helper subprocess and no root mapping."""
    flags = 0x10000000 | 0x40000000  # CLONE_NEWUSER | CLONE_NEWNET
    unshare = getattr(os, "unshare", None)
    if unshare is not None:
        unshare(flags)
        return
    # Python builds without os.unshare still use the same libc entry point.
    # CDLL(None) uses this process's libc, not a searched library pathname.
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    call = libc.unshare
    call.argtypes = [ctypes.c_int]
    call.restype = ctypes.c_int
    if call(flags) != 0:
        raise OSError(ctypes.get_errno(), "namespace syscall refused")


def write_namespace_map(name, value):
    # Names are internal constants; procfs mappings affect only this process's
    # new user namespace. Single-ID maps preserve the outside filesystem owner.
    with open("/proc/self/" + name, "w", encoding="ascii") as stream:
        stream.write(value)


def enable_private_loopback():
    """Called only AFTER fresh network namespace and UID/GID checks."""
    import fcntl
    import socket
    import struct

    if [name for _, name in socket.if_nameindex()] != ["lo"]:
        raise Unverified("namespace_interfaces_unexpected")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as control:
        request = bytearray(40)  # Linux ifreq, large enough for 32/64-bit union
        struct.pack_into("16sH", request, 0, b"lo", 0)
        fcntl.ioctl(control.fileno(), 0x8913, request, True)  # SIOCGIFFLAGS
        flags = struct.unpack_from("H", request, 16)[0]
        struct.pack_into("H", request, 16, flags | 1)  # IFF_UP
        fcntl.ioctl(control.fileno(), 0x8914, request, True)  # SIOCSIFFLAGS
        fcntl.ioctl(control.fileno(), 0x8913, request, True)
        if not struct.unpack_from("H", request, 16)[0] & 1:
            raise Unverified("namespace_loopback_not_up")


def setup_private_namespace():
    """Irreversibly isolate this controller and all later children on Linux.

    Requires unprivileged user/net namespace creation under the guest's outer
    policy. Capabilities gained belong to the new user namespace only; UID/GID
    remain the original nonzero IDs. No setns restore; namespace dies on exit.
    Inspect mode never calls this function. IDs are compared, never retained.
    """
    if sys.platform != "linux":
        raise Unverified("namespace_linux_required")
    uid, gid = os.getuid(), os.getgid()
    if uid == 0 or gid == 0 or os.geteuid() != uid or os.getegid() != gid:
        raise Unverified("namespace_nonroot_identity_required")
    try:
        before_net = os.readlink("/proc/self/ns/net")
        before_user = os.readlink("/proc/self/ns/user")
        unshare_user_network()
    except (OSError, AttributeError):
        raise Unverified("namespace_creation_refused") from None
    try:
        after_net = os.readlink("/proc/self/ns/net")
        after_user = os.readlink("/proc/self/ns/user")
        if before_net == after_net or before_user == after_user:
            raise Unverified("namespace_not_fresh")
        write_namespace_map("setgroups", "deny\n")
        write_namespace_map("uid_map", f"{uid} {uid} 1\n")
        write_namespace_map("gid_map", f"{gid} {gid} 1\n")
        if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (uid, uid, gid, gid):
            raise Unverified("namespace_identity_mismatch")
        for name, expected in (("uid_map", [str(uid), str(uid), "1"]),
                               ("gid_map", [str(gid), str(gid), "1"]), ("setgroups", ["deny"])):
            with open("/proc/self/" + name, encoding="ascii") as stream:
                if stream.read(256).split() != expected:
                    raise Unverified("namespace_mapping_mismatch")
        # This is the first socket operation in setup, in the verified new netns.
        enable_private_loopback()
    except OSError:
        raise Unverified("namespace_setup_failed") from None
    return {"status": "VERIFIED", "network_namespace_changed": True,
            "user_namespace_changed": True, "nonroot_identity_preserved": True,
            "interfaces": ["lo"], "loopback_up": True}


def exclude_secrets(value, passwords):
    """Scan decoded keys AND values before any acceptance, logging or retention."""
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 128 or count > 100000:
            raise Unverified("secret_scan_limit")
        if isinstance(item, str):
            if any(password and password in item for password in passwords):
                raise Unverified("secret_in_response")
        elif isinstance(item, dict):
            pending.extend((part, depth + 1) for pair in item.items() for part in pair)
        elif isinstance(item, (list, tuple)):
            pending.extend((part, depth + 1) for part in item)


def serialized_bytes(value, passwords=()):
    exclude_secrets(value, passwords)
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    # Defend the final delivery boundary as well as individual response leaves.
    if any(password.encode() in raw for password in passwords if password):
        raise Unverified("secret_in_response")
    exclude_secrets(parse_json(raw), passwords)
    return raw


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
    def __init__(self, binary, cwd, env, deadline, commands, passwords=None):
        self.binary, self.cwd, self.env = str(binary), cwd, env
        self.deadline, self.commands = deadline, commands
        self.server: subprocess.Popen | None = None
        self.passwords = passwords if passwords is not None else []
        if env.get("OPENCODE_PASSWORD") and env["OPENCODE_PASSWORD"] not in self.passwords:
            self.passwords.append(env["OPENCODE_PASSWORD"])

    def alive(self):
        if self.server is not None and self.server.poll() is not None:
            raise Unverified("owned_server_exited")

    def run(self, args):
        exclude_secrets(args, self.passwords)
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
            if any(password.encode() in output for password in self.passwords):
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
        value = parse_json(raw)
        exclude_secrets(value, self.passwords)
        return value


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


def observe_case(binary, output, case, port, deadline, passwords=None):
    root = output / case
    root.mkdir(mode=0o700)
    env = environment(root)
    env["OPENCODE_PASSWORD"] = secrets.token_hex(32)
    if passwords is None:
        passwords = []
    passwords.append(env["OPENCODE_PASSWORD"])
    nonce = secrets.token_hex(12)
    agent_id, marker = "qualification-" + nonce, "selected-" + nonce
    project, paths, expected = profiles(root, case, agent_id, marker)
    record: dict[str, Any] = {"case": case, "status": "UNVERIFIED", "commands": [], "effects": {},
              "tool_dispatch_enforcement": "UNVERIFIED", "launch_authorized": False}
    runner = Runner(binary, project, env, deadline, record["commands"], passwords)
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
    try:
        exclude_secrets(record, passwords)
    except Unverified:
        return {"case": case, "status": "UNVERIFIED", "reason": "secret_in_response",
                "tool_dispatch_enforcement": "UNVERIFIED", "launch_authorized": False}
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


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def stage_json(output, name, value, passwords):
    """Exclusive staging; partial files stay for diagnosis, never overwritten."""
    raw = serialized_bytes(value, passwords)
    if len(raw) > 1024 * 1024:
        raise Unverified("publication_size_limit")
    stage = output / (name + ".stage")
    fd = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return stage


def publish_output(output, report, passwords):
    """READY is linked exclusively LAST, after staged contents are fsynced.

    A crash can lose the last directory entry; absence then fails closed. The
    marker is a content-completion record, not proof of power-loss durability
    or authenticity. No failed/partial publication is retried or merged.
    """
    observation = report["status"]
    evidence = {**report, "status": "UNVERIFIED", "observation_status": observation,
                "publication": "REQUIRES_VALID_READY", "schema_version": 2}
    report_stage = stage_json(output, "report.json", evidence, passwords)
    report_hash = digest_file(report_stage, 1024 * 1024, time.monotonic() + 1)
    os.link(report_stage, output / "report.json", follow_symlinks=False)
    manifest = {"schema_version": 2, "files": {"report.json": report_hash},
                "raw_streams_retained": False, "runtime_cleanup": report["runtime_cleanup"]}
    manifest_stage = stage_json(output, "manifest.json", manifest, passwords)
    manifest_hash = digest_file(manifest_stage, 1024 * 1024, time.monotonic() + 1)
    os.link(manifest_stage, output / "manifest.json", follow_symlinks=False)
    ready = {"schema_version": 2, "status": observation, "manifest_sha256": manifest_hash,
             "report_sha256": report_hash, "completion": "COMPLETE"}
    ready_stage = stage_json(output, "READY", ready, passwords)
    sync_directory(output)
    # Hard-link creation is atomic and fails if the target exists. Never rename
    # over an existing publication, and never expose partially written READY.
    os.link(ready_stage, output / "READY", follow_symlinks=False)
    return validate_output(output)


def read_evidence(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
            raise Unverified("invalid_evidence_file")
        data = bytearray()
        while len(data) <= 1024 * 1024:
            chunk = os.read(fd, min(65536, 1024 * 1024 + 1 - len(data)))
            if not chunk:
                return bytes(data)
            data.extend(chunk)
        raise Unverified("evidence_size_limit")
    finally:
        os.close(fd)


def require_evidence(condition: bool) -> None:
    if not condition:
        raise Unverified("invalid_success_evidence")


def evidence_object(value: object) -> dict[str, object]:
    require_evidence(type(value) is dict)
    assert isinstance(value, dict)
    require_evidence(all(type(key) is str for key in value))
    return cast(dict[str, object], value)


def evidence_list(value: object) -> list[object]:
    require_evidence(type(value) is list)
    assert isinstance(value, list)
    return cast(list[object], value)


def evidence_string(value: object) -> str:
    require_evidence(type(value) is str)
    assert isinstance(value, str)
    return value


def evidence_integer(value: object) -> int:
    require_evidence(type(value) is int)
    assert isinstance(value, int)
    return value


def valid_sha256(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def validate_returned_command(value: object) -> list[str]:
    command = evidence_object(value)
    require_evidence(type(command) is dict and set(command) == {"argv", "bytes", "exit_code", "status"})
    require_evidence(command["status"] == "RETURNED" and type(command["exit_code"]) is int)
    argv = [evidence_string(arg) for arg in evidence_list(command["argv"])]
    sizes = evidence_object(command["bytes"])
    require_evidence(type(argv) is list and all(type(arg) is str for arg in argv))
    require_evidence(type(sizes) is dict and set(sizes) == {"stdout", "stderr"})
    require_evidence(all(type(size) is int and 0 <= size <= MAX_STREAM for size in sizes.values()))
    if command["exit_code"] == 0:
        require_evidence(evidence_integer(sizes["stdout"]) > 0)
    return argv


def validate_case_commands(row: dict[str, object]) -> str | None:
    """Validate retained request coverage, allowing bounded startup/agent retries.

    No response data is recovered or fabricated from logs. These are internal
    consistency checks on claimed observations, not proof the runtime ran.
    """
    commands = evidence_list(row["commands"])
    require_evidence(type(commands) is list and 3 <= len(commands) <= 16)
    start = evidence_object(commands[0])
    require_evidence(type(start) is dict and set(start) == {"argv", "output", "status"})
    require_evidence(start["status"] == "STARTED" and start["output"] == "discarded; may contain password")
    argv = [evidence_string(arg) for arg in evidence_list(start["argv"])]
    require_evidence(type(argv) is list and len(argv) == 6
                     and argv[:5] == ["<binary>", "serve", "--hostname", "127.0.0.1", "--port"])
    require_evidence(type(argv[5]) is str and re.fullmatch(r"[0-9]{4,5}", argv[5]) is not None
                     and 1024 <= int(argv[5]) <= 65535)
    endpoint = "http://127.0.0.1:" + argv[5]
    successes: list[str] = []
    config_count = agent_count = 0
    agent: str | None = None
    session_path: str | None = None
    actions: set[str] = set()
    for value in commands[1:]:
        command = evidence_object(value)
        args = validate_returned_command(command)
        require_evidence(len(args) in (6, 8) and args[:4] == ["<binary>", "api", "--server", endpoint])
        method, path = args[4:6]
        if method == "GET":
            require_evidence(len(args) == 6)
            if path == "/api/config":
                config_count += 1
                require_evidence(config_count <= READY_ATTEMPTS + 1)
                role = "config"
            else:
                require_evidence(re.fullmatch(r"/api/agent/qualification-[0-9a-f]{24}", path) is not None)
                agent_count += 1
                require_evidence(agent_count <= AGENT_ATTEMPTS)
                current_agent = path.removeprefix("/api/agent/")
                require_evidence(agent is None or current_agent == agent)
                agent = current_agent
                role = "agent"
            # Only config readiness and exact-agent initialization may fail;
            # failures after a successful request of the same role are refused.
            if command["exit_code"] != 0:
                require_evidence(role not in successes)
                continue
        else:
            require_evidence(method == "POST" and len(args) == 8 and args[6] == "--data"
                             and command["exit_code"] == 0 and agent is not None)
            assert agent is not None
            body = parse_json(args[7])
            if path == "/api/session":
                require_evidence(body == {"agent": agent})
                role = "session"
            else:
                require_evidence(re.fullmatch(r"/api/session/ses_[A-Za-z0-9_-]{1,96}/permission", path) is not None)
                require_evidence(session_path is None or session_path == path)
                session_path = path
                require_evidence(type(body) is dict and set(body) == {"id", "action", "resources", "agent"})
                action = body["action"]
                require_evidence(type(action) is str and action in ACTIONS and action not in actions)
                require_evidence(body == {"id": "per_" + agent.removeprefix("qualification-") + "_" + action,
                                          "action": action, "resources": [ACTIONS[action]], "agent": agent})
                actions.add(action)
                role = "permission"
        # Empty-agent retries can be successful CLI exits; count them while
        # preserving the successful config -> agent -> session -> policy order.
        if role != "agent" or not successes or successes[-1] != "agent":
            successes.append(role)
    expected = (["config", "agent", "session", *(["permission"] * 4), "config"]
                if row["case"] in ("clean", "conflict") else ["config", "config"])
    require_evidence(successes == expected)
    return agent


def validate_case_success(value: object) -> None:
    row = evidence_object(value)
    common = {"case", "commands", "effects", "launch_authorized", "profile_contamination_detected",
              "profiles_before", "profiles_after", "server_cleanup", "sources_before", "sources_after",
              "status", "tool_dispatch_enforcement"}
    require_evidence(type(row) is dict and type(row.get("case")) is str and row["case"] in CASES)
    case = evidence_string(row["case"])
    selected = case in ("clean", "conflict")
    require_evidence(set(row) == common | ({"resolved_policy"} if selected else {"reason", "rejection_evidence"}))
    require_evidence(row["launch_authorized"] is False and row["tool_dispatch_enforcement"] == "UNVERIFIED"
                     and row["profile_contamination_detected"] is (case == "conflict")
                     and row["server_cleanup"] == "process_group_killed")
    agent_id = validate_case_commands(row)
    expected_documents = {}
    selected_path, project_path = "config/opencode/opencode.json", "project/opencode.json"
    if selected:
        require_evidence(type(agent_id) is str)
        assert isinstance(agent_id, str)
        nonce = agent_id.removeprefix("qualification-")
        agent = {"mode": "primary", "description": "selected-" + nonce,
                 "system": "Synthetic policy fixture.", "permissions": RULES}
        expected_documents[selected_path] = {"agents": {agent_id: agent}}
        expected_rules = RULES
        if case == "conflict":
            allow = [{"action": "*", "resource": "*", "effect": "allow"}]
            expected_documents[project_path] = {"agents": {agent_id: {**agent,
                                                 "description": agent["description"] + "-project", "permissions": allow}}}
            expected_rules = RULES + allow
        policy = evidence_object(row["resolved_policy"])
        require_evidence(type(policy) is dict and set(policy) == {"defaults", "selected", "suffix"})
        require_evidence(all(type(policy[key]) is list for key in policy))
        # Reuse the runtime's pure ordered rule validator with synthetic binding
        # fields; the retained defaults and suffix must partition identically.
        resolved = {**agent, "description": "policy-check", "id": "policy-check", "name": "policy-check",
                    "request": {"settings": {}, "headers": {}, "body": {}}, "hidden": False,
                    "permissions": evidence_list(policy["defaults"]) + evidence_list(policy["selected"]) + evidence_list(policy["suffix"])}
        checked = parse_agent({"location": {"directory": "/evidence"}, "data": resolved},
                              "policy-check", "policy-check", Path("/evidence"), expected_rules)
        require_evidence(checked == policy)
        require_evidence(row["effects"] == {action: "allow" if case == "conflict" or action == "read" else "deny"
                                            for action in ACTIONS})
    else:
        require_evidence(type(row["effects"]) is dict and not row["effects"]
                         and row["reason"] == "selected_document_not_loaded"
                         and row["rejection_evidence"] == "exact_source_inventory")
    expected_profiles: dict[str, str | None] = {selected_path: None, project_path: None}
    for path, document in expected_documents.items():
        raw = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
        expected_profiles[path] = hashlib.sha256(raw).hexdigest()
    if case == "malformed":
        expected_profiles[selected_path] = hashlib.sha256(b'{"agents":').hexdigest()
    require_evidence(type(row["profiles_before"]) is dict and row["profiles_before"] == expected_profiles
                     and row["profiles_after"] == expected_profiles)
    sources = evidence_list(row["sources_before"])
    require_evidence(type(sources) is list and sources == row["sources_after"] and len(sources) <= 5)
    documents, directories, seen = {}, set(), set()
    for source_value in sources:
        source = evidence_object(source_value)
        require_evidence(type(source) is dict and type(source.get("path")) is str)
        path = evidence_string(source["path"])
        require_evidence(path not in seen)
        seen.add(path)
        if source.get("type") == "document":
            require_evidence(set(source) == {"type", "path", "info_sha256"} and valid_sha256(source["info_sha256"]))
            documents[path] = source["info_sha256"]
        else:
            require_evidence(set(source) == {"type", "path"} and source["type"] == "directory"
                             and path in {"config/opencode", "project", "project/.opencode"})
            directories.add(path)
    require_evidence("config/opencode" in directories)
    require_evidence(documents == {path: hashlib.sha256(json.dumps(document, sort_keys=True,
                                                                  separators=(",", ":")).encode()).hexdigest()
                                   for path, document in expected_documents.items()})


def validate_success_report(value: object) -> None:
    """Pure semantic validation of retained success evidence, not authenticity."""
    report = evidence_object(value)
    require_evidence(type(report) is dict and report.get("version") == VERSION
                     and valid_sha256(report.get("binary_sha256")) and report.get("runtime_cleanup") == "removed")
    namespace = evidence_object(report.get("namespace"))
    require_evidence(type(namespace) is dict and set(namespace) == {"status", "network_namespace_changed",
                     "user_namespace_changed", "nonroot_identity_preserved", "interfaces", "loopback_up"})
    require_evidence(namespace["status"] == "VERIFIED" and type(namespace["interfaces"]) is list
                     and namespace["interfaces"] == ["lo"])
    require_evidence(all(namespace[key] is True for key in ("network_namespace_changed", "user_namespace_changed",
                                                            "nonroot_identity_preserved", "loopback_up")))
    require_evidence(report.get("launch_authorized") is False and report.get("tool_dispatch_enforcement") == "UNVERIFIED")
    commands = evidence_list(report.get("commands"))
    require_evidence(type(commands) is list and len(commands) == 2)
    for command, args in zip(commands, (["<binary>", "--version"], ["<binary>", "api", "--help"]), strict=True):
        require_evidence(validate_returned_command(command) == args and evidence_object(command)["exit_code"] == 0)
    cases = evidence_list(report.get("cases"))
    require_evidence(type(cases) is list and len(cases) == 4)
    for row in cases:
        validate_case_success(row)
    require_evidence(verdict(cases) == "PROFILE_POLICY_OBSERVED")


def validate_output(output):
    """Only this full READY -> manifest -> report check authorizes a status.

    Read-only and offline. Re-read all three files to detect concurrent changes;
    this is a snapshot check, not an atomic filesystem or authenticity guarantee.
    No arbitrary evidence strings are echoed into the inspection result.
    """
    result = {"status": "UNVERIFIED", "publication": "INCOMPLETE_OR_INVALID",
              "tool_dispatch_enforcement": "UNVERIFIED", "launch_authorized": False}
    try:
        output = Path(output)
        if not output.is_absolute() or output.resolve(strict=True) != output:
            raise Unverified("invalid_evidence_path")
        raw = {name: read_evidence(output / name) for name in ("READY", "manifest.json", "report.json")}
        ready, manifest, report = (parse_json(raw[name]) for name in ("READY", "manifest.json", "report.json"))
        if (type(ready) is not dict or set(ready) != {"schema_version", "status", "manifest_sha256",
                                                    "report_sha256", "completion"}
                or ready["schema_version"] != 2 or ready["completion"] != "COMPLETE"
                or ready["status"] not in ("UNVERIFIED", "PROFILE_POLICY_OBSERVED")):
            raise Unverified("invalid_ready")
        if (type(manifest) is not dict or set(manifest) != {"schema_version", "files", "raw_streams_retained",
                                                          "runtime_cleanup"}
                or manifest["schema_version"] != 2 or manifest["raw_streams_retained"] is not False
                or manifest["files"] != {"report.json": ready["report_sha256"]}
                or ready["report_sha256"] != hashlib.sha256(raw["report.json"]).hexdigest()
                or ready["manifest_sha256"] != hashlib.sha256(raw["manifest.json"]).hexdigest()):
            raise Unverified("invalid_manifest_binding")
        if (type(report) is not dict or report.get("schema_version") != 2
                or report.get("status") != "UNVERIFIED" or report.get("publication") != "REQUIRES_VALID_READY"
                or report.get("observation_status") != ready["status"]
                or report.get("launch_authorized") is not False
                or report.get("tool_dispatch_enforcement") != "UNVERIFIED"
                or report.get("runtime_cleanup") != manifest["runtime_cleanup"]
                or type(report.get("cases")) is not list):
            raise Unverified("invalid_report_binding")
        if ready["status"] == "PROFILE_POLICY_OBSERVED":
            validate_success_report(report)
        if any(read_evidence(output / name) != data for name, data in raw.items()):
            raise Unverified("evidence_changed")
        result.update(status=ready["status"], publication="COMPLETE", case_count=len(report["cases"]))
    except (OSError, Unverified, ValueError, KeyError, TypeError, AttributeError, StopIteration):
        pass
    return result


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
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if any(arg == "--inspect-output" or arg.startswith("--inspect-output=") for arg in raw_args):
        parser = argparse.ArgumentParser(description="Validate the complete local READY/manifest/report chain; no runtime launch")
        parser.add_argument("--inspect-output", required=True)
        inspection = parser.parse_args(raw_args)
        result = validate_output(Path(inspection.inspect_output))
        print(json.dumps(result))
        return 0 if result["status"] == "PROFILE_POLICY_OBSERVED" else 3
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
    passwords = []  # All per-case passwords live only in memory, never artifacts.
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
        # Mandatory before version/help, auth generation, server or client work.
        # No production switch bypasses this prerequisite.
        report["namespace"] = setup_private_namespace()
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
            report["cases"].append(observe_case(binary, scratch, case, args.port + index, deadline, passwords))
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
    result = {"status": "UNVERIFIED", "publication": "INCOMPLETE_OR_INVALID",
              "tool_dispatch_enforcement": "UNVERIFIED", "launch_authorized": False,
              "reason": report.get("reason"), "case_count": len(report["cases"])}
    if created:
        try:
            result.update(publish_output(output, report, passwords))
        except (OSError, Unverified, ValueError):
            result.update(status="UNVERIFIED", reason="publication_failed")
    # Paths, response data, stdout, stderr and the synthetic password are omitted.
    try:
        rendered = serialized_bytes(result, passwords)
    except Unverified:
        rendered = b'{"status":"UNVERIFIED","reason":"secret_in_response","launch_authorized":false,"tool_dispatch_enforcement":"UNVERIFIED"}\n'
        result["status"] = "UNVERIFIED"
    print(rendered.decode(), end="")
    return 0 if result["status"] == "PROFILE_POLICY_OBSERVED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
