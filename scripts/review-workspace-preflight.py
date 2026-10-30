#!/usr/bin/env python3
"""Read-only, bounded static package/state observation. Never a readiness gate.

Exit 0: ALIGNED_STATIC; 1: ACTION_REQUIRED; 3: UNVERIFIED (takes precedence).
Only local Git object reads are subprocesses. No controller imports, runtime
queries, recovery, locks, or writes. Run with python3 -I -B.
"""

import argparse
import hashlib
import json
import os
import re
import selectors
import shutil
import stat
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import PurePosixPath

SKILLS = ("cross-repo-epic", "workspace-orchestrator")
SKILL_ROOT = ".agents/skills/"
ORCHESTRATOR = SKILL_ROOT + "workspace-orchestrator"
PACKAGE = tuple(SKILL_ROOT + name for name in SKILLS) + (
    ".opencode/agents", ".opencode/commands",
)
GROUPS = ("tasks", "locks", "scopes", "slots", "implementation")
MANIFEST = ORCHESTRATOR + "/CANONICAL-SHA256SUMS"
MAX_FILE = 1_000_000
MAX_TOTAL = 64_000_000
MAX_ENTRIES = 4096
MAX_DEPTH = 16
STATES = {"Ready", "Claimed", "Implementing", "Reviewing", "Rework",
          "Ready for human review", "Blocked", "Cancelled", "Done"}
TERMINAL = {"Cancelled", "Done"}


class Unverified(Exception):
    """Messages are fixed codes, never input text or OS exception strings."""


@dataclass(frozen=True)
class Entry:
    kind: str
    mode: int
    digest: str
    stamp: tuple
    data: bytes = b""

    def signature(self):
        return self.kind, self.mode, self.digest


def stamp(st):
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def parts(path):
    value = PurePosixPath(path)
    if (not path or value.is_absolute() or any(p in {".", ".."} for p in path.split("/"))
            or "\\" in path or any(ord(c) < 32 for c in path)):
        raise Unverified("unsafe_path")
    return value.parts


@contextmanager
def directory(root, relative=""):
    """Open every component without following links, including root ancestors."""
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        root_parts = parts(os.path.abspath(root).lstrip("/"))
        for name in root_parts + (parts(relative) if relative else ()):
            new = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = new
        yield fd
    finally:
        os.close(fd)


class Reader:
    def __init__(self):
        self.count = 0
        self.total = 0

    def names(self, fd):
        names = []
        with os.scandir(fd) as entries:
            for entry in entries:
                self.count += 1
                if self.count > MAX_ENTRIES:
                    raise Unverified("entry_limit")
                names.append(entry.name)
        return sorted(names)

    def entry(self, fd, name):
        before = os.stat(name, dir_fd=fd, follow_symlinks=False)
        mode = stat.S_IMODE(before.st_mode)
        if stat.S_ISDIR(before.st_mode):
            return Entry("directory", mode, "", stamp(before))
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE:
            raise Unverified("unsafe_or_oversized_file")
        handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            opened = os.fstat(handle)
            if not stat.S_ISREG(opened.st_mode) or stamp(opened) != stamp(before):
                raise Unverified("file_changed")
            data = bytearray()
            while True:
                chunk = os.read(handle, min(65536, MAX_FILE + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                self.total += len(chunk)
                if len(data) > MAX_FILE or self.total > MAX_TOTAL:
                    raise Unverified("byte_limit")
            if stamp(os.fstat(handle)) != stamp(before):
                raise Unverified("file_changed")
        finally:
            os.close(handle)
        if stamp(os.stat(name, dir_fd=fd, follow_symlinks=False)) != stamp(before):
            raise Unverified("file_changed")
        return Entry("file", mode, hashlib.sha256(data).hexdigest(), stamp(before), bytes(data))

    def tree(self, root, relative):
        result = {}

        def walk(fd, prefix, depth):
            if depth > MAX_DEPTH:
                raise Unverified("depth_limit")
            before = os.fstat(fd)
            result[prefix] = Entry("directory", stat.S_IMODE(before.st_mode), "", stamp(before))
            for name in self.names(fd):
                key = prefix + "/" + name
                parts(key)
                item = self.entry(fd, name)
                result[key] = item
                if item.kind == "directory":
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        if stamp(os.fstat(child)) != item.stamp:
                            raise Unverified("directory_changed")
                        walk(child, key, depth + 1)
                    finally:
                        os.close(child)
            if stamp(os.fstat(fd)) != stamp(before):
                raise Unverified("directory_changed")

        with directory(root, relative) as fd:
            walk(fd, relative, 0)
        return result


def package_snapshot(root, installed=False):
    reader, result = Reader(), {}
    for relative in PACKAGE:
        try:
            result.update(reader.tree(root, relative))
        except FileNotFoundError:
            if not installed:
                raise Unverified("source_package_missing") from None
    return result


def state_snapshot(root):
    """Snapshot complete task/reservation trees, including .lock contents.

    Required empty directories are evidence; an absent state root is not an
    empty workspace. Task evidence subdirectories are bounded and not executed.
    """
    reader, result = Reader(), {}
    with directory(root, ".orchestrator") as fd:
        names = reader.names(fd)
        if not set(GROUPS).issubset(names):
            raise Unverified("state_evidence_missing")
        result["state_inventory"] = tuple(names)
    for group in GROUPS:
        result.update(reader.tree(root, ".orchestrator/" + group))
    # Monitor databases may be large and are outside this static check. Inspect
    # its directory inventory and every lock subtree, never open a live DB.
    result["monitor_inventory"] = ()
    if "monitor" in names:
        with directory(root, ".orchestrator/monitor") as fd:
            monitor_names = reader.names(fd)
            result["monitor_inventory"] = tuple(monitor_names)
            for name in monitor_names:
                if name.endswith(".lock"):
                    result.update(reader.tree(root, ".orchestrator/monitor/" + name))
    # Sync stages, previous installs, locks and markers must not disappear into
    # an ignored dot-directory. Only declared skill transaction names are read.
    with directory(root, SKILL_ROOT.rstrip("/")) as fd:
        names = reader.names(fd)
        markers = [name for name in names if any(name.startswith("." + skill + ".") for skill in SKILLS)]
        result["sync_inventory"] = tuple(markers)
        for name in markers:
            key = SKILL_ROOT + name
            item = reader.entry(fd, name)
            result[key] = item
            if item.kind == "directory":
                result.update(reader.tree(root, key))
    return result


def object_json(data):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise Unverified("duplicate_json_key")
            value[key] = item
        return value

    value = json.loads(data, object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(Unverified("invalid_json_number")))
    if not isinstance(value, dict):
        raise Unverified("json_object_required")
    return value


def task_shape(raw, task_id):
    """Observe the schema 1/2 envelope; never migrate or claim compatibility."""
    schema = raw.get("schema_version")
    if type(schema) is not int or schema not in (1, 2):
        raise Unverified("unsupported_task_shape")
    strings = {"task_id", "state", "scope", "scope_key", "kind", "owner", "repo", "branch",
               "worktree", "base_sha", "next_action", "created_at", "updated_at"}
    lists = {"owned_paths", "restricted_paths", "acceptance_criteria", "dependencies",
             "reviewers", "findings", "validation"}
    needed = strings | lists | {"worker", "leases", "revision"}
    if schema == 2:
        strings |= {"tracker_type", "head_sha", "reviewed_sha"}
        needed |= strings | {"tracker_number", "transition_intent", "rework_count"}
    if not needed.issubset(raw):
        raise Unverified("task_fields_missing")
    if any(not isinstance(raw[k], str) or len(raw[k]) > 2000 for k in strings):
        raise Unverified("invalid_task_strings")
    if any(not isinstance(raw[k], list) or len(raw[k]) > 200 or
           any(not isinstance(v, str) or len(v) > 1000 for v in raw[k]) for k in lists):
        raise Unverified("invalid_task_lists")
    if (raw["task_id"] != task_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", task_id)
            or raw["state"] not in STATES or raw["kind"] not in {"implementation", "review", "monitor"}
            or type(raw["revision"]) is not int or raw["revision"] < 0
            or not raw["scope"].strip() or len(raw["scope"]) > 500
            or raw["scope_key"] != hashlib.sha256(raw["scope"].strip().encode()).hexdigest()):
        raise Unverified("invalid_task_identity")
    for field in ("base_sha", "head_sha", "reviewed_sha"):
        if raw.get(field) and not re.fullmatch(r"[0-9a-f]{40}", raw[field]):
            raise Unverified("invalid_task_revision")
    if schema == 2 and (raw["tracker_type"] not in {"none", "issue", "pr"}
                       or type(raw["tracker_number"]) is not int or raw["tracker_number"] < 0
                       or type(raw["rework_count"]) is not int or not 0 <= raw["rework_count"] <= 3):
        raise Unverified("invalid_task_tracking")
    if raw.get("transition_intent") is not None and raw["transition_intent"] not in STATES:
        raise Unverified("invalid_transition")
    leases = raw["leases"]
    if not isinstance(leases, dict) or not {"global_slot", "implementation_lane", "scope_token"}.issubset(leases):
        raise Unverified("invalid_leases")
    if not isinstance(leases["scope_token"], str) or not re.fullmatch(r"[0-9a-f]{32}", leases["scope_token"]):
        raise Unverified("invalid_scope_token")
    for name, maximum in (("global_slot", 6), ("implementation_lane", 2)):
        if leases[name] is not None and (type(leases[name]) is not int or not 0 <= leases[name] < maximum):
            raise Unverified("invalid_lease")
    worker = raw["worker"]
    if worker is not None:
        if not isinstance(worker, dict) or type(worker.get("pid")) is not int or worker["pid"] <= 0:
            raise Unverified("invalid_worker")
        if any(not isinstance(worker.get(k), str) or not worker[k]
               for k in ("task_id", "owner", "process_start", "hostname")):
            raise Unverified("invalid_worker")
        if any(not isinstance(worker.get(k), str) or not re.fullmatch(r"[0-9a-f]{32}", worker[k])
               for k in ("token", "worker_id")) or worker["task_id"] != task_id:
            raise Unverified("invalid_worker")
    active = (raw["state"] not in TERMINAL or worker is not None
              or raw.get("transition_intent") is not None
              or any(leases[k] is not None for k in ("global_slot", "implementation_lane")))
    return schema, active


def inspect_state(snapshot, counts, actions):
    tasks = {}
    prefix = ".orchestrator/tasks/"
    for path, entry in snapshot.items():
        if not isinstance(entry, Entry) or not path.startswith(prefix):
            continue
        tail = path[len(prefix):].split("/")
        if len(tail) == 1:
            if entry.kind != "directory":
                raise Unverified("unexpected_task_layout")
            tasks[tail[0]] = False
        if tail[-1] == "task.json":
            if len(tail) != 2 or entry.kind != "file":
                raise Unverified("nested_task_layout")
            schema, active = task_shape(object_json(entry.data), tail[0])
            counts["schema_" + str(schema) + "_observed"] += 1
            tasks[tail[0]] = True
            if active:
                actions.add("task_activity_recorded")
    if not all(tasks.values()):
        raise Unverified("task_record_missing")
    counts["tasks"] = len(tasks)
    for group in GROUPS[1:]:
        prefix = ".orchestrator/" + group + "/"
        for path, entry in snapshot.items():
            if not path.startswith(prefix):
                continue
            actions.add("reservations_or_locks_present")
            counts["reservation_entries"] += 1
            tail = path[len(prefix):].split("/")
            if len(tail) == 1:
                if entry.kind != "directory" or not tail[0].endswith(".lock"):
                    raise Unverified("unexpected_reservation_layout")
                owner = snapshot.get(path + "/owner.json")
                if not isinstance(owner, Entry) or owner.kind != "file":
                    raise Unverified("reservation_owner_missing")
                raw = object_json(owner.data)
                if not isinstance(raw.get("token"), str) or not re.fullmatch(r"[0-9a-f]{32}", raw["token"]):
                    raise Unverified("reservation_owner_malformed")
                if group in {"slots", "implementation"}:
                    # Worker reservations deliberately have no schema_version.
                    if (type(raw.get("pid")) is not int or raw["pid"] <= 0
                            or any(not isinstance(raw.get(k), str) or not raw[k] for k in
                                   ("task_id", "owner", "process_start", "worker_id", "hostname", "created_at"))):
                        raise Unverified("worker_reservation_malformed")
                elif (type(raw.get("schema_version")) is not int or raw["schema_version"] not in (1, 2)
                      or (group == "scopes" and any(not isinstance(raw.get(k), str) or not raw[k]
                                                   for k in ("task_id", "scope")))
                      or (group == "locks" and (type(raw.get("pid")) is not int or raw["pid"] <= 0
                          or any(not isinstance(raw.get(k), str) or not raw[k] for k in ("hostname", "created_at"))))):
                    raise Unverified("reservation_owner_malformed")
            if entry.kind == "file" and path.endswith(".json"):
                object_json(entry.data)
    counts["sync_markers"] = len(snapshot["sync_inventory"])
    if counts["sync_markers"]:
        actions.add("sync_transaction_present")
    if any(name.endswith(".lock") for name in snapshot["monitor_inventory"]):
        actions.add("monitor_lock_present")
    for path, entry in snapshot.items():
        if path.startswith(".orchestrator/monitor/") and isinstance(entry, Entry) and entry.kind == "file" and path.endswith(".json"):
            object_json(entry.data)
    if set(snapshot["state_inventory"]) - set(GROUPS) - {"monitor"}:
        raise Unverified("unrecognized_state_inventory")


def verify_manifest(source):
    entry = source.get(MANIFEST)
    if entry is None or entry.kind != "file" or not entry.data:
        raise Unverified("manifest_missing_or_empty")
    declared = {}
    for line in entry.data.decode("utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  \./(.+)", line)
        if not match:
            raise Unverified("manifest_malformed")
        name = ORCHESTRATOR + "/" + "/".join(parts(match[2]))
        if name in declared or name == MANIFEST:
            raise Unverified("manifest_duplicate_or_self")
        declared[name] = match[1]
    actual = {name: item.digest for name, item in source.items()
              if name.startswith(ORCHESTRATOR + "/") and item.kind == "file" and name != MANIFEST}
    if not declared or declared != actual:
        raise Unverified("manifest_inventory_mismatch")
    for skill in SKILLS:
        item = source.get(SKILL_ROOT + skill + "/SKILL.md")
        if item is None or item.kind != "file" or not item.data:
            raise Unverified("skill_missing_or_empty")
    for src_prefix, dest_prefix in ((ORCHESTRATOR + "/profiles/opencode-v1/", ".opencode/agents/"),
                                    (ORCHESTRATOR + "/examples/commands/", ".opencode/commands/")):
        items = [(name, item) for name, item in source.items() if name.startswith(src_prefix) and item.kind == "file"]
        if not items:
            raise Unverified("source_install_surface_missing")
        for name, item in items:
            installed = source.get(dest_prefix + name[len(src_prefix):])
            if installed is None or installed.signature() != item.signature():
                raise Unverified("source_install_surface_mismatch")


def git_read(root, *args):
    """Hermetic, bounded local object queries; never status, hooks or filters."""
    binary = shutil.which("git", path="/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin")
    if not binary:
        raise Unverified("git_unavailable")
    env = {"PATH": "/usr/bin:/bin", "HOME": "/dev/null", "LC_ALL": "C",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1"}
    command = [binary, "--no-pager", "--no-replace-objects", "-c", "core.fsmonitor=false",
               "-c", "core.hooksPath=/dev/null", "-C", os.path.abspath(root), *args]
    with subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        assert process.stdout is not None
        data, deadline = bytearray(), time.monotonic() + 15
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    if time.monotonic() >= deadline:
                        raise Unverified("git_timeout")
                    if not selector.select(min(0.2, max(0, deadline - time.monotonic()))):
                        continue
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > MAX_TOTAL:
                        raise Unverified("git_output_limit")
            if process.wait(timeout=max(0.01, deadline - time.monotonic())):
                raise Unverified("git_query_failed")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    return bytes(data)


def verify_source(root, expected, source):
    if git_read(root, "rev-parse", "--verify", "HEAD").decode().strip() != expected:
        raise Unverified("source_revision_mismatch")
    tree = git_read(root, "ls-tree", "-rz", "--full-tree", expected, "--", *PACKAGE)
    tracked = {}
    for row in tree.split(b"\0"):
        if not row:
            continue
        metadata, name = row.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        name = name.decode("utf-8")
        parts(name)
        if kind != "blob" or mode not in {"100644", "100755"} or name in tracked:
            raise Unverified("source_tree_unsupported")
        item = source.get(name)
        if item is None or item.kind != "file" or item.mode != int(mode, 8) & 0o777:
            raise Unverified("source_package_dirty")
        # Git blob identity is the hash of the raw file plus its object header;
        # this avoids filters/textconv and executing anything from the package.
        algorithm = hashlib.sha1 if len(oid) == 40 else hashlib.sha256
        if algorithm(b"blob " + str(len(item.data)).encode() + b"\0" + item.data).hexdigest() != oid:
            raise Unverified("source_package_dirty")
        tracked[name] = True
    actual = {name for name, item in source.items() if item.kind == "file"}
    if not tracked or set(tracked) != actual:
        raise Unverified("source_inventory_dirty")


def preflight(source_root, consumer_root, expected):
    counts = {key: 0 for key in ("source_files", "installed_files", "package_differences", "tasks",
                               "schema_1_observed", "schema_2_observed", "reservation_entries", "sync_markers")}
    actions, errors = set(), set()
    try:
        if not re.fullmatch(r"[0-9a-f]{40}", expected):
            raise Unverified("expected_source_requires_full_sha")
        source = package_snapshot(source_root)
        verify_manifest(source)
        verify_source(source_root, expected, source)
        counts["source_files"] = sum(e.kind == "file" for e in source.values())
        installed = package_snapshot(consumer_root, installed=True)
        counts["installed_files"] = sum(e.kind == "file" for e in installed.values())
        differences = [name for name in source.keys() | installed.keys()
                       if name not in source or name not in installed
                       or source[name].signature() != installed[name].signature()]
        counts["package_differences"] = len(differences)
        if differences:
            actions.add("installed_package_differs")
        before = state_snapshot(consumer_root)
        after = state_snapshot(consumer_root)
        if before != after:
            raise Unverified("state_changed_between_passes")
        inspect_state(before, counts, actions)
        if source != package_snapshot(source_root) or installed != package_snapshot(consumer_root, installed=True):
            raise Unverified("package_changed_between_passes")
        verify_source(source_root, expected, source)
    except Unverified as exc:
        errors.add(str(exc))
    except (OSError, ValueError, TypeError, KeyError, RecursionError, subprocess.SubprocessError):
        errors.add("evidence_unreadable_or_malformed")
    status = "UNVERIFIED" if errors else "ACTION_REQUIRED" if actions else "ALIGNED_STATIC"
    return {"status": status, "counts": counts, "action_codes": sorted(actions), "unverified_codes": sorted(errors),
            "scope": "static_files_only", "state_schema": "observed_shape_only",
            "limitations": ["not_runtime_compatibility", "not_readiness", "not_a_lock_or_atomic_snapshot",
                            "no_process_or_network_observation"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--consumer", required=True)
    parser.add_argument("--expected-source", required=True)
    args = parser.parse_args(argv)
    report = preflight(args.source, args.consumer, args.expected_source)
    print(json.dumps(report, sort_keys=True, indent=2))
    return {"ALIGNED_STATIC": 0, "ACTION_REQUIRED": 1, "UNVERIFIED": 3}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
