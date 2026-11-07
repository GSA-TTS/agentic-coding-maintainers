#!/usr/bin/env python3
"""Read selected schema-2 or schema-3 coordinator ownership evidence without mutation."""

import argparse
import contextlib
import copy
import hashlib
import json
import os
import re
import stat
import sys

MAX_BYTES = 1_000_000  # Same record byte ceiling as orchestrator-state.py.
MAX_INT64 = 2**63 - 1
TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", re.ASCII)
HEX32 = re.compile(r"[0-9a-f]{32}")
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
STATES = {"Ready", "Claimed", "Implementing", "Reviewing", "Rework",
          "Ready for human review", "Blocked", "Cancelled", "Done"}
ACTIVE = {"Claimed", "Implementing", "Reviewing"}
TRANSITIONS = {
    "Ready": {"Blocked", "Cancelled"},
    "Claimed": {"Implementing", "Reviewing", "Blocked", "Cancelled"},
    "Implementing": {"Reviewing", "Blocked", "Cancelled"},
    "Reviewing": {"Rework", "Ready for human review", "Blocked", "Cancelled"},
    "Rework": {"Blocked", "Cancelled"},
    "Ready for human review": {"Rework", "Done", "Blocked", "Cancelled"},
    "Blocked": {"Ready", "Rework", "Cancelled"},
    "Cancelled": set(),
    "Done": set(),
}
TASK_FIELDS = {
    "schema_version", "task_id", "state", "scope", "scope_key", "kind", "owner", "repo",
    "branch", "worktree", "base_sha", "owned_paths", "tracker_type", "tracker_number",
    "head_sha", "reviewed_sha", "restricted_paths", "acceptance_criteria", "dependencies",
    "reviewers", "findings", "validation", "next_action", "worker", "leases",
    "transition_intent", "rework_count", "revision", "created_at", "updated_at"}
BOUND_OPTIONAL_FIELDS = {"legacy_finding_dispositions", "transition_recovery"}
WORKER_FIELDS = {"task_id", "owner", "pid", "process_start", "worker_id", "token",
                 "hostname", "created_at"}
BOUND_WORKER_FIELDS = WORKER_FIELDS | {"session_id", "generation"}
RECOVERY_FIELDS = {
    "phase", "source", "intent", "generation", "base_revision", "pending_revision",
    "worker", "leases", "capacity_observed", "operator_reason", "task_sha256", "correlation_sha256"}
DISPOSITION_FIELDS = {
    "finding_index", "finding_sha256", "head_sha", "epoch", "disposition",
    "reviewer", "implementation_owner", "evidence", "revision"}


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


def single_line(value, maximum=500):
    text(value, maximum, True)
    require(value == value.strip() and not any(ord(c) < 32 for c in value))


def integer(value, minimum=0, maximum=MAX_INT64):
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


def recovery_digest(value):
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    require(len(encoded) <= MAX_BYTES)
    return hashlib.sha256(encoded).hexdigest()


def validate_worker(worker, bound=False):
    fields(worker, BOUND_WORKER_FIELDS if bound else WORKER_FIELDS)
    integer(worker["pid"], 1)
    for key in ("worker_id", "token"):
        matches(worker[key], HEX32)
    matches(worker["task_id"], TASK_ID)
    for key in ("owner", "process_start", "hostname", "created_at"):
        text(worker[key], nonempty=True)
    if bound:
        matches(worker["session_id"], SESSION_ID)
        integer(worker["generation"], 1)


def validate_base_task(task, bound=False):
    matches(task["task_id"], TASK_ID)
    integer(task["revision"])
    text(task["state"])
    require(task["state"] in STATES)
    text(task["kind"])
    require(task["kind"] in {"implementation", "review", "monitor"})
    single_line(task["scope"], 500)
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
        validate_worker(task["worker"], bound=bound)


def validate_cooperative_binding(task, check_worker_task=True):
    binding = task.get("cooperative_binding")
    fields(binding, {"session_id", "generation"})
    matches(binding["session_id"], SESSION_ID)
    integer(binding["generation"], 1, min(MAX_INT64, task["revision"]))
    worker = task["worker"]
    if worker is not None:
        if check_worker_task:
            require(worker["task_id"] == task["task_id"] and worker["owner"] == task["owner"])
        require(worker["session_id"] == binding["session_id"]
                and worker["generation"] == binding["generation"])
    if task["state"] in ACTIVE:
        require(worker is not None and task["leases"]["global_slot"] is not None)
    else:
        require(worker is None and task["leases"]["global_slot"] is None
                and task["leases"]["implementation_lane"] is None)


def validate_interrupted_snapshot(snapshot, observed):
    validate_base_task(snapshot, bound=True)
    validate_cooperative_binding(snapshot, check_worker_task=True)
    source, target = snapshot["state"], snapshot["transition_intent"]
    require(type(target) is str and target in TRANSITIONS[source])
    lane = snapshot["leases"]["implementation_lane"]
    needs_lane = source == "Implementing" or target == "Implementing"
    if needs_lane:
        require(snapshot["kind"] == "implementation")
    require((lane is not None) == needs_lane)
    fields(observed, {"slots", "implementation"})
    require(all(type(val) is bool for val in observed.values()))
    for group, field in (("slots", "global_slot"), ("implementation", "implementation_lane")):
        if snapshot["leases"][field] is None:
            require(not observed[group])
        elif not observed[group]:
            releases = target not in ACTIVE or (group == "implementation" and target == "Reviewing")
            require(releases)
    require(not (snapshot["leases"]["global_slot"] is not None
                 and snapshot["leases"]["implementation_lane"] is not None
                 and target not in ACTIVE
                 and observed["slots"] and not observed["implementation"]))


def validate_transition_recovery(task):
    if "transition_recovery" not in task:
        return
    receipt = task["transition_recovery"]
    fields(receipt, RECOVERY_FIELDS)
    require(receipt["phase"] in {"pending", "settled"})
    require(receipt["source"] in STATES and receipt["intent"] in STATES)
    for key in ("generation", "base_revision", "pending_revision"):
        integer(receipt[key], 1)
    require(receipt["pending_revision"] == receipt["base_revision"] + 1)
    single_line(receipt["operator_reason"], 500)
    for key in ("task_sha256", "correlation_sha256"):
        matches(receipt[key], HEX64)
    correlation = {k: v for k, v in receipt.items() if k not in {"phase", "correlation_sha256"}}
    require(receipt["correlation_sha256"] == recovery_digest(correlation))
    snapshot = copy.deepcopy(task)
    snapshot.pop("transition_recovery")
    snapshot.pop("legacy_finding_dispositions", None)
    worker = receipt["worker"]
    snapshot.update(
        state=receipt["source"],
        transition_intent=receipt["intent"],
        worker=worker,
        leases=receipt["leases"],
        revision=receipt["base_revision"],
        cooperative_binding={
            "session_id": worker.get("session_id") if type(worker) is dict else task["cooperative_binding"]["session_id"],
            "generation": receipt["generation"],
        },
    )
    if type(worker) is dict and type(worker.get("owner")) is str:
        snapshot["owner"] = worker["owner"]
    fields(snapshot, TASK_FIELDS | {"cooperative_binding"})
    validate_interrupted_snapshot(snapshot, receipt["capacity_observed"])
    if receipt["phase"] == "pending":
        require(task["revision"] == receipt["pending_revision"]
                and task["cooperative_binding"]["generation"] == receipt["generation"]
                and all(task[k] == receipt[f] for k, f in (
                    ("state", "source"), ("transition_intent", "intent"),
                    ("worker", "worker"), ("leases", "leases"))))
        retained = {k: v for k, v in task.items() if k not in {"transition_recovery", "revision", "updated_at"}}
        require(recovery_digest(retained) == receipt["task_sha256"])
    else:
        require(task["revision"] > receipt["pending_revision"]
                and task["cooperative_binding"]["generation"] >= receipt["generation"]
                and task["leases"]["scope_token"] == receipt["leases"]["scope_token"])
        if task["revision"] == receipt["pending_revision"] + 1:
            require(task["state"] == "Blocked" and task["transition_intent"] is None
                    and task["worker"] is None and task["next_action"] == receipt["operator_reason"]
                    and task["cooperative_binding"]["generation"] == receipt["generation"])


def validate_legacy_dispositions(task):
    if "legacy_finding_dispositions" not in task:
        return
    ledger = task["legacy_finding_dispositions"]
    fields(ledger, {"epoch", "history"})
    integer(ledger["epoch"], 0, task["revision"])
    require(type(ledger["history"]) is list and len(ledger["history"]) <= 1000)
    latest = {}
    bindings = {}
    previous_revision, previous_epoch = -1, -1
    for item in ledger["history"]:
        fields(item, DISPOSITION_FIELDS)
        index, epoch, revision = item["finding_index"], item["epoch"], item["revision"]
        integer(index, 0, len(task["findings"]) - 1)
        integer(epoch, max(0, previous_epoch), ledger["epoch"])
        integer(revision, max(1, previous_revision + 1), task["revision"])
        require(item["finding_sha256"] == hashlib.sha256(task["findings"][index].encode("utf-8")).hexdigest())
        matches(item["head_sha"], HEX40)
        require(item["disposition"] in {"fixed", "refuted", "persists"})
        prior = latest.get((epoch, index))
        if prior is not None:
            require((prior == "persists") != (item["disposition"] == "persists"))
        for field in ("reviewer", "implementation_owner", "evidence"):
            single_line(item[field], 500)
        require(item["reviewer"] != item["implementation_owner"])
        binding = (item["head_sha"], item["implementation_owner"])
        if epoch in bindings:
            require(bindings[epoch] == binding)
        if epoch == ledger["epoch"]:
            require(item["head_sha"] == task["head_sha"] and item["implementation_owner"] == task["owner"])
        bindings[epoch] = binding
        latest[(epoch, index)] = item["disposition"]
        previous_revision, previous_epoch = revision, epoch


def validate_task(task):
    # No prototype upgrade and no imports of the state module or its plugins.
    schema = task.get("schema_version")
    require(type(schema) is int and schema in {2, 3}, "UNSUPPORTED_SCHEMA")
    if schema == 2:
        fields(task, TASK_FIELDS)
        validate_base_task(task, bound=False)
        return
    required = TASK_FIELDS | {"cooperative_binding"}
    require(type(task) is dict and required <= set(task) and set(task) - required <= BOUND_OPTIONAL_FIELDS)
    validate_base_task(task, bound=True)
    validate_cooperative_binding(task, check_worker_task=False)
    validate_transition_recovery(task)
    validate_legacy_dispositions(task)


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
        bound = task["schema_version"] == 3
        has_bound_args = args.expected_session_id is not None
        if not bound and has_bound_args:
            return result("UNVERIFIED", "UNEXPECTED_BOUND_EXPECTATIONS")
        if bound and not has_bound_args:
            return result("UNVERIFIED", "MISSING_BOUND_EXPECTATIONS")
        if (task["state"] not in ACTIVE or task["transition_intent"] is not None
                or task.get("transition_recovery", {}).get("phase") == "pending"):
            return result("UNVERIFIED", "INACTIVE_OR_TRANSITIONING")
        worker = task["worker"]
        if worker is None or task["leases"]["global_slot"] is None:
            return result("UNVERIFIED", "MISSING_WORKER_OR_SLOT")
        lane = task["leases"]["implementation_lane"]
        lane_owner = None
        if bound:
            if task["state"] == "Implementing":
                require(task["kind"] == "implementation" and lane is not None)
            else:
                require(lane is None)
        scope = read_selected(store, ["scopes", task["scope_key"] + ".lock", "owner.json"], stack, retained)
        fields(scope, {"schema_version", "task_id", "scope", "token"})
        require(type(scope["schema_version"]) is int and scope["schema_version"] == 2)
        matches(scope["task_id"], TASK_ID)
        text(scope["scope"], 500, True)
        matches(scope["token"], HEX32)
        slot = read_selected(store, ["slots", str(task["leases"]["global_slot"]) + ".lock", "owner.json"], stack, retained)
        validate_worker(slot, bound=bound)
        if bound and lane is not None:
            lane_owner = read_selected(store, ["implementation", str(lane) + ".lock", "owner.json"], stack, retained)
            validate_worker(lane_owner, bound=True)
        require(all(fingerprint(os.fstat(fd)) == before for fd, before in retained), "CHANGED_DURING_READ")
        if task["task_id"] != args.task_id or worker["task_id"] != task["task_id"]:
            return result("CONFLICT", "TASK_MISMATCH")
        if task["revision"] != args.expected_revision:
            return result("CONFLICT", "REVISION_MISMATCH")
        if worker["worker_id"] != args.expected_worker_id or worker["owner"] != task["owner"]:
            return result("CONFLICT", "WORKER_MISMATCH")
        if bound and (task["cooperative_binding"]["session_id"] != args.expected_session_id
                      or task["cooperative_binding"]["generation"] != args.expected_generation):
            return result("CONFLICT", "SESSION_OR_GENERATION_MISMATCH")
        if ((args.expected_branch is not None and task["branch"] != args.expected_branch)
                or (args.expected_repo is not None and task["repo"] != args.expected_repo)):
            return result("CONFLICT", "REPOSITORY_OR_BRANCH_MISMATCH")
        if (slot != worker
                or (lane_owner is not None and lane_owner != worker)
                or scope != {"schema_version": 2, "task_id": task["task_id"],
                             "scope": task["scope"], "token": task["leases"]["scope_token"]}):
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
        parser.add_argument("--expected-session-id")
        parser.add_argument("--expected-generation")
        args = parser.parse_args()
        require(TASK_ID.fullmatch(args.task_id) is not None and HEX32.fullmatch(args.expected_worker_id) is not None,
                "INVALID_ARGUMENTS")
        require(re.fullmatch(r"0|[1-9][0-9]{0,18}", args.expected_revision) is not None, "INVALID_ARGUMENTS")
        args.expected_revision = int(args.expected_revision)
        require(args.expected_revision <= MAX_INT64, "INVALID_ARGUMENTS")
        require((args.expected_session_id is None) == (args.expected_generation is None), "INVALID_ARGUMENTS")
        if args.expected_session_id is not None:
            require(SESSION_ID.fullmatch(args.expected_session_id) is not None, "INVALID_ARGUMENTS")
            require(re.fullmatch(r"[1-9][0-9]{0,18}", args.expected_generation) is not None, "INVALID_ARGUMENTS")
            args.expected_generation = int(args.expected_generation)
            require(1 <= args.expected_generation <= MAX_INT64, "INVALID_ARGUMENTS")
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
