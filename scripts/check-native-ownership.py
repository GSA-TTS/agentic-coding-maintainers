#!/usr/bin/env python3
"""Read selected schema-2 coordinator ownership evidence without mutation."""

import argparse
import contextlib
import hashlib
import json
import os
import re
import stat
import sys

MAX_BYTES = 1_000_000  # Same record byte ceiling as orchestrator-state.py.
TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
HEX32 = re.compile(r"[0-9a-f]{32}")
HEX40 = re.compile(r"[0-9a-f]{40}")
STATES = {"Ready", "Claimed", "Implementing", "Reviewing", "Rework",
          "Ready for human review", "Blocked", "Cancelled", "Done"}
TASK_FIELDS = {
    "schema_version", "task_id", "state", "scope", "scope_key", "kind", "owner", "repo",
    "branch", "worktree", "base_sha", "owned_paths", "tracker_type", "tracker_number",
    "head_sha", "reviewed_sha", "restricted_paths", "acceptance_criteria", "dependencies",
    "reviewers", "findings", "validation", "next_action", "worker", "leases",
    "transition_intent", "rework_count", "revision", "created_at", "updated_at"}
WORKER_FIELDS = {"task_id", "owner", "pid", "process_start", "worker_id", "token",
                 "hostname", "created_at"}


class Unverified(Exception):
    """Carries only fixed public reason codes, never input values."""


def result(status, reason):
    return {"status": status, "reason": reason,
            "native_session_authentication": "UNVERIFIED", "mutation_authorized": False}


def require(condition, reason="INVALID_METADATA"):
    if not condition:
        raise Unverified(reason)


def fields(value, expected):
    require(type(value) is dict and set(value) == expected)


def text(value, maximum=2000, nonempty=False):
    require(type(value) is str and len(value) <= maximum and (not nonempty or bool(value)))


def integer(value, minimum=0, maximum=2**63 - 1):
    require(type(value) is int and minimum <= value <= maximum)


def matches(value, pattern):
    require(type(value) is str and pattern.fullmatch(value) is not None)


def unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value)
        value[key] = item
    return value


def bounded(value, depth=0):
    require(depth <= 32)
    if type(value) is str:
        require(len(value.encode("utf-8")) <= 16000)
    elif type(value) is dict:
        require(len(value) <= 2000)
        for key, item in value.items():
            bounded(key, depth + 1)
            bounded(item, depth + 1)
    elif type(value) is list:
        require(len(value) <= 2000)
        for item in value:
            bounded(item, depth + 1)
    else:
        require(value is None or type(value) in (bool, int))


def parse(data):
    require(0 < len(data) <= MAX_BYTES)
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
        bounded(value)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Unverified("INVALID_METADATA") from exc
    require(type(value) is dict)
    return value


def validate_worker(worker):
    fields(worker, WORKER_FIELDS)
    integer(worker["pid"], 1)
    for key in ("worker_id", "token"):
        matches(worker[key], HEX32)
    matches(worker["task_id"], TASK_ID)
    for key in ("owner", "process_start", "hostname", "created_at"):
        text(worker[key], nonempty=True)


def validate_task(task):
    # No prototype upgrade and no imports of the state module or its plugins.
    require(type(task.get("schema_version")) is int and task["schema_version"] == 2,
            "UNSUPPORTED_SCHEMA")
    fields(task, TASK_FIELDS)
    matches(task["task_id"], TASK_ID)
    integer(task["revision"])
    text(task["state"])
    require(task["state"] in STATES)
    text(task["kind"])
    require(task["kind"] in {"implementation", "review", "monitor"})
    text(task["scope"], 500, True)
    require(task["scope"] == task["scope"].strip() and not any(ord(c) < 32 for c in task["scope"]))
    require(task["scope_key"] == hashlib.sha256(task["scope"].encode("utf-8")).hexdigest())
    for key in ("owner", "repo", "branch", "worktree", "base_sha", "head_sha", "reviewed_sha",
                "next_action", "tracker_type", "created_at", "updated_at"):
        text(task[key])
    for key in ("base_sha", "head_sha", "reviewed_sha"):
        if task[key]:
            matches(task[key], HEX40)
    require(task["tracker_type"] in {"none", "issue", "pr"})
    integer(task["tracker_number"])
    require((task["tracker_type"] == "none") == (task["tracker_number"] == 0))
    integer(task["rework_count"], 0, 3)
    if task["transition_intent"] is not None:
        text(task["transition_intent"])
        require(task["transition_intent"] in STATES)
    for key in ("owned_paths", "restricted_paths", "acceptance_criteria", "dependencies",
                "reviewers", "findings", "validation"):
        require(type(task[key]) is list and len(task[key]) <= 200)
        for item in task[key]:
            text(item, 1000)
    fields(task["leases"], {"global_slot", "implementation_lane", "scope_token"})
    matches(task["leases"]["scope_token"], HEX32)
    for key, maximum in (("global_slot", 5), ("implementation_lane", 1)):
        if task["leases"][key] is not None:
            integer(task["leases"][key], 0, maximum)
    if task["worker"] is not None:
        validate_worker(task["worker"])


def parts(path):
    require(type(path) is str and 0 < len(path.encode("utf-8")) <= 4096
            and path.startswith("/") and path != "/" and not any(ord(c) < 32 for c in path),
            "INVALID_ARGUMENTS")
    components = path[1:].split("/")
    require(all(component not in ("", ".", "..") for component in components), "INVALID_ARGUMENTS")
    return components


def directory(parent, name, stack, private=False):
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    stack.callback(os.close, fd)
    if private:
        info = os.fstat(fd)
        require(info.st_uid == os.getuid() and info.st_mode & 0o077 == 0, "UNSAFE_STORE")
    return fd


def physical_root(path, stack):
    fd = directory(None, "/", stack)
    for component in parts(path):
        fd = directory(fd, component, stack)
    return fd


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_mode, info.st_uid, info.st_nlink)


def read_selected(store, components, stack, retained):
    parent = store
    for name in components[:-1]:
        parent = directory(parent, name, stack, private=True)
    fd = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    stack.callback(os.close, fd)
    before = os.fstat(fd)
    require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
            and before.st_mode & 0o077 == 0 and before.st_nlink == 1
            and 0 < before.st_size <= MAX_BYTES, "UNSAFE_STORE")
    retained.append((fd, fingerprint(before)))
    chunks = []
    remaining = MAX_BYTES + 1
    while remaining:
        chunk = os.read(fd, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return parse(b"".join(chunks))


def inspect(args):
    with contextlib.ExitStack() as stack:
        authority = physical_root(args.authority_root, stack)
        invoking = physical_root(args.invoking_root, stack)
        left, right = os.fstat(authority), os.fstat(invoking)
        if (left.st_dev, left.st_ino) != (right.st_dev, right.st_ino):
            return result("CONFLICT", "ROOT_MISMATCH")
        store = directory(authority, ".orchestrator", stack, private=True)
        retained = []
        task = read_selected(store, ["tasks", args.task_id, "task.json"], stack, retained)
        validate_task(task)
        if task["state"] not in {"Claimed", "Implementing", "Reviewing"} or task["transition_intent"] is not None:
            return result("UNVERIFIED", "INACTIVE_OR_TRANSITIONING")
        worker = task["worker"]
        if worker is None or task["leases"]["global_slot"] is None:
            return result("UNVERIFIED", "MISSING_WORKER_OR_SLOT")
        scope = read_selected(store, ["scopes", task["scope_key"] + ".lock", "owner.json"], stack, retained)
        fields(scope, {"schema_version", "task_id", "scope", "token"})
        require(type(scope["schema_version"]) is int and scope["schema_version"] == 2)
        matches(scope["task_id"], TASK_ID)
        text(scope["scope"], 500, True)
        matches(scope["token"], HEX32)
        slot = read_selected(store, ["slots", str(task["leases"]["global_slot"]) + ".lock", "owner.json"], stack, retained)
        validate_worker(slot)
        require(all(fingerprint(os.fstat(fd)) == before for fd, before in retained), "CHANGED_DURING_READ")
        if task["task_id"] != args.task_id or worker["task_id"] != task["task_id"]:
            return result("CONFLICT", "TASK_MISMATCH")
        if task["revision"] != args.expected_revision:
            return result("CONFLICT", "REVISION_MISMATCH")
        if worker["worker_id"] != args.expected_worker_id or worker["owner"] != task["owner"]:
            return result("CONFLICT", "WORKER_MISMATCH")
        if ((args.expected_branch is not None and task["branch"] != args.expected_branch)
                or (args.expected_repo is not None and task["repo"] != args.expected_repo)):
            return result("CONFLICT", "REPOSITORY_OR_BRANCH_MISMATCH")
        if slot != worker or scope != {"schema_version": 2, "task_id": task["task_id"],
                                      "scope": task["scope"], "token": task["leases"]["scope_token"]}:
            return result("CONFLICT", "RETAINED_LEASE_MISMATCH")
        return result("STATIC_MATCH", "RETAINED_WORKER_CONSISTENT")


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Unverified("INVALID_ARGUMENTS")


def main():
    try:
        require(sys.flags.isolated and sys.dont_write_bytecode, "ISOLATED_PYTHON_REQUIRED")
        parser = Parser(description=__doc__, allow_abbrev=False)
        for name in ("authority-root", "invoking-root", "task-id", "expected-revision", "expected-worker-id"):
            parser.add_argument("--" + name, required=True)
        parser.add_argument("--expected-branch")
        parser.add_argument("--expected-repo")
        args = parser.parse_args()
        require(TASK_ID.fullmatch(args.task_id) is not None and HEX32.fullmatch(args.expected_worker_id) is not None,
                "INVALID_ARGUMENTS")
        require(re.fullmatch(r"0|[1-9][0-9]{0,18}", args.expected_revision) is not None, "INVALID_ARGUMENTS")
        args.expected_revision = int(args.expected_revision)
        require(args.expected_revision <= 2**63 - 1, "INVALID_ARGUMENTS")
        for value in (args.expected_branch, args.expected_repo):
            if value is not None:
                require(0 < len(value) <= 2000 and not any(ord(c) < 32 for c in value), "INVALID_ARGUMENTS")
        output = inspect(args)
    except Unverified as exc:
        output = result("UNVERIFIED", str(exc))
    except (OSError, ValueError, UnicodeError, TypeError, RecursionError):
        output = result("UNVERIFIED", "STORE_UNAVAILABLE")
    print(json.dumps(output, sort_keys=True))
    return {"STATIC_MATCH": 0, "UNVERIFIED": 3, "CONFLICT": 4}[output["status"]]


if __name__ == "__main__":
    sys.exit(main())
