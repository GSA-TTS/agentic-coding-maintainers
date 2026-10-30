#!/usr/bin/env python3
"""Strict, local coordination state for bounded multi-agent work."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXIT_INPUT = 2
EXIT_UNKNOWN = 3
EXIT_BUSY = 4
SCHEMA = 2
MAX_WORKERS = 6
MAX_IMPLEMENTATION = 2
TASK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
STATES = {
    "Ready", "Claimed", "Implementing", "Reviewing", "Rework",
    "Ready for human review", "Blocked", "Cancelled", "Done",
}
ACTIVE = {"Claimed", "Implementing", "Reviewing"}
TERMINAL = {"Cancelled", "Done"}
TRANSITIONS = {
    # `Claimed` is entered only by command_claim(), which atomically records the
    # worker identity and reserves a global slot. A generic transition cannot
    # establish those ownership invariants.
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


class InputError(Exception):
    pass


class UnknownError(Exception):
    pass


class AmbiguousWriteError(UnknownError):
    pass


class BusyError(Exception):
    pass


def git_probe(worktree: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Inspect a checkout without repository-configured execution or lazy fetch.

    These probes only inspect identity, ancestry, or cleanliness. A partial
    clone missing an object is UNVERIFIED, not a reason to fetch it using the
    checkout's configured remote or credential helper on the host.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_NO_LAZY_FETCH="1", GIT_OPTIONAL_LOCKS="0")
    return subprocess.run(
        ["git", "-c", "protocol.allow=never", "-c", "core.fsmonitor=false",
         "-c", "core.untrackedCache=false", "-c", f"core.hooksPath={os.devnull}",
         "-C", worktree, *args],
        capture_output=True, text=True, check=False, timeout=5, env=env,
    )


def verify_clean_checkout(worktree: str) -> None:
    """Fail closed without Git status/diff's checkout-defined clean filters.

    Compare raw worktree bytes to indexed blobs. Attributes with conversions
    can produce a false dirty result, never a false clean result. Untracked or
    staged changes are refused. Neither cat-file nor ls-files transforms files.
    """
    root = Path(worktree).resolve()
    staged = git_probe(worktree, "diff-index", "--cached", "--quiet", "HEAD", "--")
    if staged.returncode == 1:
        raise BusyError("worktree has staged changes")
    if staged.returncode != 0:
        raise UnknownError("cannot establish staged checkout cleanliness")
    # Include ignored files too: a build/test may consume an ignored config,
    # and a fixed-SHA review cannot claim a clean checkout with those present.
    unknown = git_probe(worktree, "ls-files", "--others", "-z")
    if unknown.returncode != 0:
        raise UnknownError("cannot enumerate untracked checkout files")
    if unknown.stdout:
        raise BusyError("worktree has untracked files")
    tracked = git_probe(worktree, "ls-files", "--stage", "-z")
    if tracked.returncode != 0:
        raise UnknownError("cannot enumerate tracked checkout files")
    for item in tracked.stdout.split("\0"):
        if not item:
            continue
        try:
            metadata, name = item.split("\t", 1)
            mode, oid, stage = metadata.split(" ")
        except ValueError as exc:
            raise UnknownError("tracked checkout index is malformed") from exc
        if stage != "0" or mode not in {"100644", "100755", "120000", "160000"} or not re.fullmatch(r"[0-9a-f]{40,64}", oid):
            raise UnknownError("cannot compare non-regular or conflicted checkout entry")
        file = root / name
        if not file.parent.resolve().is_relative_to(root):
            raise UnknownError("tracked checkout path escapes worktree")
        if mode == "160000":
            # An uninitialized gitlink is safe to inspect without invoking the
            # nested repository's configuration or fetching its commit.
            try:
                if file.is_symlink() or (file.exists() and not file.is_dir()):
                    raise BusyError("tracked gitlink changed type")
                if file.is_dir() and any(file.iterdir()):
                    raise BusyError("tracked gitlink is initialized or modified")
            except OSError as exc:
                raise UnknownError("cannot read tracked gitlink") from exc
            continue
        # `git hash-object --no-filters` reads the bytes directly. Do not use
        # Git's normal diff/status comparisons, which may invoke filters.
        try:
            if mode == "120000":
                actual = os.readlink(file).encode("utf-8", errors="surrogateescape")
            else:
                if file.is_symlink() or not file.is_file():
                    raise BusyError("tracked checkout entry changed type")
                actual = file.read_bytes()
                executable = bool(file.stat().st_mode & 0o111)
                if executable != (mode == "100755"):
                    raise BusyError("tracked checkout entry changed mode")
        except OSError as exc:
            raise UnknownError("cannot read tracked checkout entry") from exc
        # An object ID over raw bytes is sufficient: no filters, no text-mode
        # decoding of arbitrary binary objects, and no remote object lookup.
        if len(oid) == 40:
            digest = hashlib.sha1(b"blob " + str(len(actual)).encode() + b"\0" + actual, usedforsecurity=False)
        else:
            digest = hashlib.sha256(b"blob " + str(len(actual)).encode() + b"\0" + actual)
        if digest.hexdigest() != oid:
            raise BusyError("tracked checkout bytes differ from indexed object")


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def workspace_root() -> Path:
    raw = os.environ.get("WORKSPACE_ORCHESTRATOR_ROOT")
    if not raw:
        raise InputError("WORKSPACE_ORCHESTRATOR_ROOT must name the consumer workspace")
    supplied = Path(raw).expanduser()
    if supplied.is_symlink():
        raise InputError("consumer workspace must not be a symlink")
    root = supplied.resolve()
    if not root.is_dir():
        raise InputError("consumer workspace must be a real directory, not a symlink")
    return root


def state_root(create: bool = True) -> Path:
    test_mode = os.environ.get("ORCHESTRATOR_TEST_MODE") == "1"
    raw = os.environ.get("ORCHESTRATOR_STATE_DIR") if test_mode else None
    root = Path(raw).expanduser() if raw else workspace_root() / ".orchestrator"
    if test_mode:
        try:
            root.resolve().relative_to(Path(tempfile.gettempdir()).resolve())
        except ValueError as exc:
            raise UnknownError("test state root must stay under the system temporary directory") from exc
    if root.exists() and root.is_symlink():
        raise UnknownError("state root is a symlink")
    if create:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    elif not root.is_dir():
        raise UnknownError("coordinator state is not initialized")
    st = root.stat()
    if st.st_uid != os.getuid() or st.st_mode & 0o022:
        raise UnknownError("state root must be current-user owned and not group/world writable")
    for name in ("tasks", "locks", "scopes", "slots", "implementation"):
        path = root / name
        if path.exists() and path.is_symlink():
            raise UnknownError(f"state component {name!r} is a symlink")
        if create:
            path.mkdir(mode=0o700, exist_ok=True)
        elif not path.is_dir():
            raise UnknownError(f"state component {name!r} is missing")
        pst = path.stat()
        if not path.is_dir() or pst.st_uid != os.getuid() or pst.st_mode & 0o022:
            raise UnknownError(f"state component {name!r} must be a private current-user directory")
    return root


def validate_task_id(value: str) -> str:
    if not TASK_RE.fullmatch(value):
        raise InputError("task id must be a flat 1-80 character token")
    return value


def task_path(root: Path, task_id: str) -> Path:
    directory = root / "tasks" / validate_task_id(task_id)
    if directory.exists() and directory.is_symlink():
        raise UnknownError("task directory is a symlink")
    return directory / "task.json"


def safe_scope(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 500 or any(ord(c) < 32 for c in value):
        raise InputError("scope must be a non-empty, single-line value <= 500 characters")
    return value


def resource_path(value: str) -> str:
    value = value.strip().replace("\\", "/")
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or any(ord(c) < 32 for c in value):
        raise InputError("owned/restricted paths must be relative, non-traversing paths")
    normalized = path.as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized or len(normalized) > 500:
        raise InputError("owned/restricted path is empty or too long")
    return normalized


def scope_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = (json.dumps(data, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if len(encoded) > 1_000_000:
        raise InputError("record would exceed 1 MB")
    fd, tmp = tempfile.mkstemp(prefix=".new-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded.decode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        try:
            dfd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError as exc:
            raise AmbiguousWriteError(f"record replacement durability is unknown: {exc}") from exc
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError("not a bounded regular file")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise UnknownError(f"{label} unreadable or malformed: {exc}") from exc
    if not isinstance(raw, dict):
        raise UnknownError(f"{label} is not an object")
    return raw


def validate_record(raw: dict[str, Any], expected: str | None = None) -> dict[str, Any]:
    # Schema 1 was emitted by the first in-session prototype before tracker/head
    # binding and transition intents were added. It is persisted host state, so
    # make the upgrade explicit and lossless instead of requiring a reset.
    if raw.get("schema_version") == 1:
        raw = dict(raw)
        raw.update({
            "schema_version": SCHEMA,
            "tracker_type": "none",
            "tracker_number": 0,
            "head_sha": "",
            "reviewed_sha": "",
            "transition_intent": None,
            "rework_count": 0,
        })
    required = {
        "schema_version", "task_id", "state", "scope", "scope_key", "kind",
        "owner", "repo", "branch", "worktree", "base_sha", "owned_paths",
        "tracker_type", "tracker_number", "head_sha", "reviewed_sha",
        "restricted_paths", "acceptance_criteria", "dependencies", "reviewers",
        "findings", "validation", "next_action", "worker", "leases",
        "transition_intent", "rework_count", "revision", "created_at", "updated_at",
    }
    missing = required - raw.keys()
    if missing:
        raise UnknownError(f"task record missing fields: {', '.join(sorted(missing))}")
    if raw["schema_version"] != SCHEMA or type(raw["revision"]) is not int or raw["revision"] < 0:
        raise UnknownError("task schema or revision is invalid")
    validate_task_id(str(raw["task_id"]))
    if expected and raw["task_id"] != expected:
        raise UnknownError("task record id does not match its directory")
    if raw["state"] not in STATES:
        raise UnknownError(f"task state is invalid: {raw['state']!r}")
    if raw["scope_key"] != scope_key(safe_scope(str(raw["scope"]))):
        raise UnknownError("task scope hash does not match scope")
    if raw["kind"] not in {"implementation", "review", "monitor"}:
        raise UnknownError("task kind is invalid")
    for field in ("owned_paths", "restricted_paths", "acceptance_criteria", "dependencies", "reviewers", "findings", "validation"):
        if not isinstance(raw[field], list) or len(raw[field]) > 200 or any(not isinstance(v, str) or len(v) > 1000 for v in raw[field]):
            raise UnknownError(f"task field {field!r} is invalid or oversized")
    for field in ("owner", "repo", "branch", "worktree", "base_sha", "head_sha", "reviewed_sha", "next_action", "tracker_type"):
        if not isinstance(raw[field], str) or len(raw[field]) > 2000:
            raise UnknownError(f"task field {field!r} is invalid")
    for field in ("base_sha", "head_sha", "reviewed_sha"):
        if raw[field] and not re.fullmatch(r"[0-9a-f]{40}", raw[field]):
            raise UnknownError(f"task {field} must be full lowercase 40-hex")
    if raw["tracker_type"] not in {"none", "issue", "pr"} or type(raw["tracker_number"]) is not int or raw["tracker_number"] < 0:
        raise UnknownError("task tracker identity is invalid")
    if type(raw["rework_count"]) is not int or not 0 <= raw["rework_count"] <= 3:
        raise UnknownError("task rework count is invalid")
    if raw["transition_intent"] is not None and raw["transition_intent"] not in STATES:
        raise UnknownError("task transition intent is invalid")
    if not isinstance(raw["worker"], (dict, type(None))) or not isinstance(raw["leases"], dict):
        raise UnknownError("task worker or leases shape is invalid")
    for name, maximum in (("global_slot", MAX_WORKERS), ("implementation_lane", MAX_IMPLEMENTATION)):
        value = raw["leases"].get(name)
        if value is not None and (type(value) is not int or not 0 <= value < maximum):
            raise UnknownError(f"task lease {name!r} is invalid")
    if not isinstance(raw["leases"].get("scope_token"), str) or not re.fullmatch(r"[0-9a-f]{32}", raw["leases"]["scope_token"]):
        raise UnknownError("task scope token is invalid")
    if raw["worker"] is not None:
        worker = raw["worker"]
        if type(worker.get("pid")) is not int or worker["pid"] <= 0:
            raise UnknownError("task worker pid is invalid")
        for field in ("worker_id", "token"):
            if not isinstance(worker.get(field), str) or not re.fullmatch(r"[0-9a-f]{32}", worker[field]):
                raise UnknownError(f"task worker {field} is invalid")
        for field in ("task_id", "owner", "process_start", "hostname"):
            if not isinstance(worker.get(field), str) or not worker[field]:
                raise UnknownError(f"task worker {field} is invalid")
        if worker["task_id"] != raw["task_id"]:
            raise UnknownError("task worker id does not match task")
    if "candidate_binding" in raw:
        path = Path(__file__).resolve().with_name("candidate-binding.py")
        spec = importlib.util.spec_from_file_location("installed_candidate_binding", path)
        if spec is None or spec.loader is None:
            raise UnknownError("candidate binding validator unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            module.validate_binding(raw)
        except Exception as exc:
            raise UnknownError("task candidate binding is invalid") from exc
    validate_legacy_dispositions(raw)
    return raw


def validate_legacy_dispositions(record: dict[str, Any]) -> None:
    """Validate optional local claims, including retained, no-longer-current history."""
    if "legacy_finding_dispositions" not in record:
        return
    ledger = record["legacy_finding_dispositions"]
    if (not isinstance(ledger, dict) or set(ledger) != {"epoch", "history"}
            or type(ledger["epoch"]) is not int or not 0 <= ledger["epoch"] <= record["revision"]
            or not isinstance(ledger["history"], list) or len(ledger["history"]) > 1000):
        raise UnknownError("legacy finding dispositions are malformed")
    latest: dict[tuple[int, int], str] = {}
    bindings: dict[int, tuple[str, str]] = {}
    previous_revision, previous_epoch = -1, -1
    for item in ledger["history"]:
        if not isinstance(item, dict) or set(item) != {
            "finding_index", "finding_sha256", "head_sha", "epoch", "disposition",
            "reviewer", "implementation_owner", "evidence", "revision",
        }:
            raise UnknownError("legacy finding disposition entry is malformed")
        index, epoch, revision = item["finding_index"], item["epoch"], item["revision"]
        if (type(index) is not int or not 0 <= index < len(record["findings"])
                or type(epoch) is not int or not previous_epoch <= epoch <= ledger["epoch"] or epoch < 0
                or type(revision) is not int or revision < 1 or not previous_revision < revision <= record["revision"]):
            raise UnknownError("legacy finding disposition identity/order is invalid or duplicated")
        if item["finding_sha256"] != scope_key(record["findings"][index]):
            raise UnknownError("legacy finding text digest changed")
        if (not isinstance(item["head_sha"], str) or not re.fullmatch(r"[0-9a-f]{40}", item["head_sha"])
                or item["disposition"] not in ("fixed", "refuted", "persists")):
            raise UnknownError("legacy finding disposition head/outcome is invalid")
        prior = latest.get((epoch, index))
        if prior is not None and (prior == "persists") == (item["disposition"] == "persists"):
            raise UnknownError("legacy finding disposition duplicates an outcome without reopening/resolution")
        for field in ("reviewer", "implementation_owner", "evidence"):
            value = item[field]
            if (not isinstance(value, str) or not value or value != value.strip()
                    or len(value) > 500 or any(ord(c) < 32 for c in value)):
                raise UnknownError("legacy finding disposition identity/evidence is missing or invalid")
        if item["reviewer"] == item["implementation_owner"]:
            raise UnknownError("legacy finding disposition reviewer is the implementation owner")
        binding = (item["head_sha"], item["implementation_owner"])
        if epoch in bindings and bindings[epoch] != binding:
            raise UnknownError("legacy finding disposition epoch has conflicting head/owner bindings")
        if epoch == ledger["epoch"] and (item["head_sha"] != record["head_sha"]
                or item["implementation_owner"] != record["owner"]):
            raise UnknownError("current legacy finding disposition binding changed")
        bindings[epoch] = binding
        latest[(epoch, index)] = item["disposition"]
        previous_revision, previous_epoch = revision, epoch


def unresolved_legacy_finding_indices(record: dict[str, Any]) -> list[int]:
    """Return unresolved indices from a validated task; validate claims before counting."""
    validate_legacy_dispositions(record)
    ledger = record.get("legacy_finding_dispositions", {"epoch": 0, "history": []})
    latest = {item["finding_index"]: item["disposition"] for item in ledger["history"]
              if item["epoch"] == ledger["epoch"]}
    return [index for index in range(len(record["findings"]))
            if latest.get(index) not in ("fixed", "refuted")]


def unresolved_legacy_findings(record: dict[str, Any]) -> bool:
    return bool(unresolved_legacy_finding_indices(record))


class CoordinatorLock:
    def __init__(self, root: Path):
        self.path = root / "locks" / "coordinator.lock"
        self.token = uuid.uuid4().hex

    def __enter__(self) -> "CoordinatorLock":
        try:
            os.mkdir(self.path, 0o700)
        except FileExistsError as exc:
            raise BusyError("coordinator lock is held; no state was changed") from exc
        atomic_json(self.path / "owner.json", {
            "schema_version": SCHEMA, "token": self.token, "pid": os.getpid(),
            "hostname": socket.gethostname(), "created_at": now(),
        })
        return self

    def __exit__(self, *_: object) -> None:
        owner = read_json(self.path / "owner.json", "coordinator owner")
        if owner.get("token") != self.token:
            raise UnknownError("coordinator lock fencing token changed")
        os.unlink(self.path / "owner.json")
        os.rmdir(self.path)


def read_task(root: Path, task_id: str) -> dict[str, Any]:
    path = task_path(root, task_id)
    if not path.exists():
        raise UnknownError(f"task {task_id!r} record is missing")
    return validate_record(read_json(path, f"task {task_id}"), task_id)


def write_task(root: Path, record: dict[str, Any]) -> None:
    record["revision"] += 1
    record["updated_at"] = now()
    validate_record(record, record["task_id"])
    atomic_json(task_path(root, record["task_id"]), record)


def acquire_dir(path: Path, metadata: dict[str, Any]) -> None:
    try:
        os.mkdir(path, 0o700)
    except FileExistsError as exc:
        raise BusyError(f"reservation already held: {path.name}") from exc
    try:
        atomic_json(path / "owner.json", metadata)
    except Exception:
        # The empty directory remains deliberately ambiguous; reconciliation must
        # report UNKNOWN instead of treating it as available.
        raise


def release_dir(path: Path, token: str) -> None:
    if not path.exists():
        return
    owner = read_json(path / "owner.json", f"reservation {path.name}")
    if owner.get("token") != token:
        raise UnknownError(f"reservation fencing token changed: {path.name}")
    os.unlink(path / "owner.json")
    os.rmdir(path)


def reserve_first(root: Path, group: str, count: int, metadata: dict[str, Any]) -> int:
    # Validate EVERY existing reservation before admitting a worker. An empty
    # slot after a corrupt lock does not make capacity measurable again.
    for idx in range(count):
        path = root / group / f"{idx}.lock"
        if path.exists() or path.is_symlink():
            read_json(path / "owner.json", f"{group} {idx} owner")
    for idx in range(count):
        path = root / group / f"{idx}.lock"
        try:
            acquire_dir(path, metadata)
            return idx
        except BusyError:
            read_json(path / "owner.json", f"{group} {idx} owner")
    raise BusyError(f"no {group} capacity available")


def process_identity(pid: int) -> tuple[str, str | None]:
    try:
        value = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="], check=False,
            capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown", None
    if value.returncode == 1 and value.stderr.strip():
        return "unknown", None
    if value.returncode not in (0, 1):
        return "unknown", None
    text = value.stdout.strip()
    return ("alive", text) if text else ("absent", None)


def worker_metadata(task_id: str, owner: str, pid: int) -> dict[str, Any]:
    status, start = process_identity(pid)
    if status != "alive" or not start:
        raise UnknownError(f"cannot establish process identity for pid {pid}")
    return {
        "task_id": task_id, "owner": owner, "pid": pid,
        "process_start": start, "worker_id": uuid.uuid4().hex,
        "token": uuid.uuid4().hex, "hostname": socket.gethostname(),
        "created_at": now(),
    }


def command_create(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    task_id = validate_task_id(args.task_id)
    scope = safe_scope(args.scope)
    worktree = str(Path(args.worktree).expanduser().resolve()) if args.worktree else ""
    if worktree and not Path(worktree).is_dir():
        raise InputError("worktree must exist when supplied")
    if args.kind == "implementation" and os.environ.get("ORCHESTRATOR_TEST_MODE") != "1":
        expected_root = (workspace_root() / "work").resolve()
        actual = Path(worktree)
        try:
            actual.relative_to(expected_root)
        except (ValueError, TypeError) as exc:
            raise InputError("implementation worktree must resolve inside work/") from exc
        if not args.branch or not args.base_sha:
            raise InputError("implementation tasks require branch and base SHA")
        probe = git_probe(worktree, "rev-parse", "--is-inside-work-tree")
        if probe.returncode != 0 or probe.stdout.strip() != "true":
            raise InputError("implementation path is not a git worktree")
        top = git_probe(worktree, "rev-parse", "--show-toplevel")
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != Path(worktree):
            raise InputError("implementation path is not the worktree root")
        branch = git_probe(worktree, "symbolic-ref", "--quiet", "--short", "HEAD")
        if branch.returncode != 0 or branch.stdout.strip() != args.branch:
            raise InputError("implementation worktree branch does not match --branch")
        base = git_probe(worktree, "cat-file", "-e", f"{args.base_sha}^{{commit}}")
        if base.returncode != 0:
            raise InputError("base SHA is not a commit in the implementation repository")
        head = git_probe(worktree, "rev-parse", "HEAD")
        if head.returncode != 0 or (args.head_sha and head.stdout.strip() != args.head_sha):
            raise InputError("implementation worktree HEAD does not match --head-sha")
        if not args.head_sha:
            args.head_sha = head.stdout.strip()
        ancestry = git_probe(worktree, "merge-base", "--is-ancestor", args.base_sha, args.head_sha)
        if ancestry.returncode != 0:
            raise InputError("implementation head does not descend from base SHA")
    if args.kind == "review" and not args.head_sha:
        raise InputError("review tasks require a full head SHA")
    if args.kind == "review" and os.environ.get("ORCHESTRATOR_TEST_MODE") != "1":
        if not worktree or not args.repo:
            raise InputError("review tasks require repository and worktree identity")
        top = git_probe(worktree, "rev-parse", "--show-toplevel")
        commit = git_probe(worktree, "cat-file", "-e", f"{args.head_sha}^{{commit}}")
        head = git_probe(worktree, "rev-parse", "HEAD")
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != Path(worktree):
            raise InputError("review path is not the worktree root")
        if commit.returncode != 0 or head.returncode != 0 or head.stdout.strip() != args.head_sha:
            raise InputError("review head is not the assigned worktree HEAD")
    owned_paths = [resource_path(p) for p in args.owned_path]
    restricted_paths = [resource_path(p) for p in args.restricted_path]
    if args.tracker_type == "none" and args.tracker_number != 0:
        raise InputError("tracker type none requires tracker number 0")
    if args.tracker_type in {"issue", "pr"} and args.tracker_number <= 0:
        raise InputError("issue/pr tracker number must be positive")
    scope_dir = root / "scopes" / f"{scope_key(scope)}.lock"
    with CoordinatorLock(root):
        validate_admission_reservations(root)
        if task_path(root, task_id).exists():
            raise BusyError(f"task {task_id!r} already exists")
        incoming_paths = owned_paths + restricted_paths
        for existing in command_list(root):
            if existing["state"] in TERMINAL:
                continue
            if worktree and existing["worktree"] == worktree:
                raise BusyError(f"worktree is already assigned to {existing['task_id']}")
            if args.branch and existing["repo"] == args.repo and existing["branch"] == args.branch:
                raise BusyError(f"branch is already assigned to {existing['task_id']}")
            current_paths = [str(Path(p)) for p in existing["owned_paths"] + existing["restricted_paths"]]
            if existing["repo"] == args.repo:
                for left in incoming_paths:
                    for right in current_paths:
                        if left == "." or right == "." or left == right or left.startswith(right.rstrip("/") + "/") or right.startswith(left.rstrip("/") + "/"):
                            raise BusyError(f"path resource overlaps task {existing['task_id']}: {left!r} / {right!r}")
        metadata = {"schema_version": SCHEMA, "task_id": task_id, "scope": scope, "token": uuid.uuid4().hex}
        stamp = now()
        record = {
            "schema_version": SCHEMA, "task_id": task_id, "state": "Ready",
            "scope": scope, "scope_key": scope_key(scope), "kind": args.kind,
            "owner": "", "repo": args.repo, "branch": args.branch,
            "worktree": worktree, "base_sha": args.base_sha,
            "tracker_type": args.tracker_type, "tracker_number": args.tracker_number,
            "head_sha": args.head_sha, "reviewed_sha": "",
            "owned_paths": owned_paths, "restricted_paths": restricted_paths,
            "acceptance_criteria": args.acceptance, "dependencies": args.dependency,
            "reviewers": [], "findings": [], "validation": [],
            "next_action": args.next_action, "worker": None,
            "leases": {"global_slot": None, "implementation_lane": None, "scope_token": metadata["token"]},
            "transition_intent": None,
            "rework_count": 0,
            "revision": 0, "created_at": stamp, "updated_at": stamp,
        }
        validate_record(record, task_id)
        acquire_dir(scope_dir, metadata)
        atomic_json(task_path(root, task_id), record)
    return record


def require_execution_stopped(record: dict[str, Any]) -> None:
    attempts = record.get("execution_observations", {})
    if not isinstance(attempts, dict):
        raise UnknownError("malformed execution observations")
    for attempt in attempts.values():
        if (not isinstance(attempt, dict) or attempt.get("termination") != "STOPPED_OBSERVED"
                or attempt.get("phase") not in {"SETTLED", "UNKNOWN_STOPPED", "EVIDENCE_LOST_STOPPED"}):
            raise UnknownError("execution may still be active; reconcile exact sandbox stop before lifecycle changes")
        definition = attempt.get("definition")
        stop = attempt.get("stop_observation")
        if (not isinstance(definition, dict) or not isinstance(stop, dict)
                or not isinstance(definition.get("container_id"), str) or not re.fullmatch(r"[0-9a-f]{64}", definition["container_id"])
                or not definition.get("created")
                or stop != {"container_id": definition["container_id"], "created": definition["created"], "running": False}):
            raise UnknownError("execution stop observation is missing or malformed")


def require_repair_settled(record: dict[str, Any], new_review: bool = False, root: Path | None = None) -> None:
    ledger = record.get("repair_protocol")
    if ledger is None:
        return
    if root is not None:
        import importlib.util
        source = Path(__file__).resolve().with_name("repair-apply.py")
        spec = importlib.util.spec_from_file_location("installed_repair", source)
        if spec is None or spec.loader is None:
            raise UnknownError("repair validator unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            module.validate_retained(record, root)
            if "repair_proposals" in record:
                proposal_spec = importlib.util.spec_from_file_location("installed_proposal", Path(__file__).resolve().with_name("repair-proposal.py"))
                if proposal_spec is None or proposal_spec.loader is None:
                    raise UnknownError("proposal validator unavailable")
                proposal_module = importlib.util.module_from_spec(proposal_spec)
                proposal_spec.loader.exec_module(proposal_module)
                proposal_module.validate(record, root)
        except Exception as exc:
            raise UnknownError("retained repair evidence unavailable") from exc
    if not isinstance(ledger, dict) or not isinstance(ledger.get("operations"), dict):
        raise UnknownError("repair ledger malformed")
    for item in ledger["operations"].values():
        if not isinstance(item, dict) or item.get("phase") not in {"APPLIED_UNREVIEWED", "NOT_APPLIED_OBSERVED"}:
            raise UnknownError("repair is unsettled; reconcile before lifecycle/head changes")
        if new_review and item["phase"] == "APPLIED_UNREVIEWED" and item.get("head") == record["head_sha"]:
            raise UnknownError("repaired bytes require a new committed head before review")


def command_claim(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    with CoordinatorLock(root):
        validate_admission_reservations(root)
        record = read_task(root, args.task_id)
        if record["state"] not in {"Ready", "Rework"}:
            raise BusyError(f"task is not claimable from state {record['state']!r}")
        require_execution_stopped(record)
        require_repair_settled(record, root=root)
        ledger = record.get("repair_protocol", {})
        prepared = [item for item in ledger.get("corrections", {}).values() if item.get("cycle") == record["rework_count"]]
        if prepared and args.owner != prepared[0]["owner"]:
            raise BusyError("prepared repair belongs to original owner")
        owner = safe_scope(args.owner)
        worker = worker_metadata(record["task_id"], owner, args.pid)
        slot = reserve_first(root, "slots", MAX_WORKERS, worker)
        try:
            if os.environ.get("ORCHESTRATOR_TEST_MODE") == "1" and os.environ.get("ORCHESTRATOR_TEST_FAIL_CLAIM_WRITE") == "1":
                raise OSError("injected claim persistence failure")
            record["state"] = "Claimed"
            if record["owner"] != owner and "legacy_finding_dispositions" in record:
                record["legacy_finding_dispositions"]["epoch"] += 1
            record["owner"] = owner
            record["worker"] = worker
            record["leases"]["global_slot"] = slot
            record["leases"]["implementation_lane"] = None
            write_task(root, record)
        except AmbiguousWriteError:
            raise
        except Exception:
            release_dir(root / "slots" / f"{slot}.lock", worker["token"])
            raise
    return record


def release_capacity(root: Path, record: dict[str, Any]) -> None:
    worker = record.get("worker") or {}
    token = worker.get("token")
    if not token:
        return
    slot = record["leases"].get("global_slot")
    lane = record["leases"].get("implementation_lane")
    if slot is not None:
        release_dir(root / "slots" / f"{slot}.lock", token)
    if lane is not None:
        release_dir(root / "implementation" / f"{lane}.lock", token)
    record["leases"]["global_slot"] = None
    record["leases"]["implementation_lane"] = None
    record["worker"] = None


def release_implementation_lane(root: Path, record: dict[str, Any]) -> None:
    worker = record.get("worker") or {}
    token = worker.get("token")
    lane = record["leases"].get("implementation_lane")
    if token and lane is not None:
        release_dir(root / "implementation" / f"{lane}.lock", token)
        record["leases"]["implementation_lane"] = None


def command_transition(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    if args.state == "Unknown" or args.state not in STATES:
        raise InputError("target state is invalid; Unknown is derived only")
    with CoordinatorLock(root):
        record = read_task(root, args.task_id)
        verify_reservations(root, record)
        if args.state not in TRANSITIONS[record["state"]]:
            raise InputError(f"transition {record['state']!r} -> {args.state!r} is not allowed")
        require_execution_stopped(record)
        require_repair_settled(record, root=root)
        if args.state == "Implementing" and (record["kind"] != "implementation" or not record.get("worker")):
            raise InputError("only a claimed implementation task can enter Implementing")
        if args.state == "Implementing" and os.environ.get("ORCHESTRATOR_TEST_MODE") != "1":
            verify_worktree_identity(record, require_head=True)
        if args.state == "Reviewing" and record["kind"] == "review" and os.environ.get("ORCHESTRATOR_TEST_MODE") != "1":
            verify_review_identity(record)
        if args.reason:
            safe_scope(args.reason)
        if args.state == "Ready for human review":
            if "review_protocol" in record:
                raise BusyError("review protocol claims require corroborated runtime evidence; readiness is UNVERIFIED")
            if not record["head_sha"]:
                raise BusyError("readiness requires a fixed head SHA")
            if record["kind"] == "implementation" and os.environ.get("ORCHESTRATOR_TEST_MODE") != "1":
                verify_worktree_identity(record, require_head=True)
            if not record["reviewers"] or not record["validation"] or not record["reviewed_sha"]:
                raise BusyError("readiness requires a reviewer, validation evidence, and reviewed SHA")
            if record["reviewed_sha"] != record["head_sha"]:
                raise BusyError("reviewed SHA does not match task head SHA")
            if record["kind"] == "review" and os.environ.get("ORCHESTRATOR_TEST_MODE") != "1":
                verify_review_identity(record)
            if unresolved_legacy_findings(record):
                raise BusyError("readiness is blocked by unresolved findings")
            if record["kind"] == "implementation" and os.environ.get("ORCHESTRATOR_TEST_MODE") != "1":
                verify_clean_checkout(record["worktree"])
        if args.state == "Rework":
            if record["rework_count"] >= 3:
                raise BusyError("three rework cycles reached; checkpoint and escalate")
            record["rework_count"] += 1
            record["reviewers"] = []
            record["validation"] = []
            record["reviewed_sha"] = ""
        if args.state == "Implementing":
            lane = reserve_first(root, "implementation", MAX_IMPLEMENTATION, record["worker"])
            record["leases"]["implementation_lane"] = lane
        record["transition_intent"] = args.state
        write_task(root, record)
        if args.reason:
            record["next_action"] = args.reason
        if args.state == "Reviewing":
            release_implementation_lane(root, record)
        elif args.state not in ACTIVE:
            release_capacity(root, record)
        if args.state in TERMINAL:
            release_dir(
                root / "scopes" / f"{record['scope_key']}.lock",
                record["leases"]["scope_token"],
            )
        record["state"] = args.state
        record["transition_intent"] = None
        write_task(root, record)
    return record


def verify_worktree_identity(record: dict[str, Any], require_head: bool) -> None:
    worktree = record["worktree"]
    top = git_probe(worktree, "rev-parse", "--show-toplevel")
    branch = git_probe(worktree, "symbolic-ref", "--quiet", "--short", "HEAD")
    head = git_probe(worktree, "rev-parse", "HEAD")
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != Path(worktree):
        raise UnknownError("assigned worktree identity changed")
    if branch.returncode != 0 or branch.stdout.strip() != record["branch"]:
        raise UnknownError("assigned branch changed")
    if require_head and (head.returncode != 0 or head.stdout.strip() != record["head_sha"]):
        raise UnknownError("assigned worktree HEAD differs from recorded head")


def verify_review_identity(record: dict[str, Any]) -> None:
    worktree = record["worktree"]
    top = git_probe(worktree, "rev-parse", "--show-toplevel")
    head = git_probe(worktree, "rev-parse", "HEAD")
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != Path(worktree):
        raise UnknownError("review worktree identity changed")
    if head.returncode != 0 or head.stdout.strip() != record["head_sha"]:
        raise UnknownError("review worktree HEAD differs from recorded head")
    verify_clean_checkout(worktree)


def revoke_legacy_readiness(record: dict[str, Any]) -> None:
    if record["state"] != "Ready for human review":
        return
    if record["rework_count"] >= 3:
        record["state"] = "Blocked"
        record["next_action"] = "three rework cycles reached; escalate new or persisting finding"
    else:
        record["state"] = "Rework"
        record["rework_count"] += 1
        record["next_action"] = "address new or persisting finding"
    record["reviewers"] = []
    record["validation"] = []
    record["reviewed_sha"] = ""


def command_record(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    if args.category == "resolution":
        raise InputError("record resolution would erase history; use resolve-finding with exact binding and evidence")
    field = {
        "reviewer": "reviewers",
        "finding": "findings",
        "validation": "validation",
        "dependency": "dependencies",
    }[args.category]
    value = safe_scope(args.value)
    with CoordinatorLock(root):
        record = read_task(root, args.task_id)
        if record["state"] in TERMINAL:
            raise BusyError("terminal task evidence is immutable")
        if args.category == "finding" and value in record[field]:
            raise BusyError("finding is already recorded; use resolve-finding --disposition persists to reopen")
        if args.category == "finding":
            revoke_legacy_readiness(record)
        if value not in record[field]:
            if len(record[field]) >= 200:
                raise InputError(f"task field {field!r} is full")
            record[field].append(value)
        if args.next_action:
            record["next_action"] = safe_scope(args.next_action)
        if args.reviewed_sha:
            if not re.fullmatch(r"[0-9a-f]{40}", args.reviewed_sha):
                raise InputError("reviewed SHA must be full lowercase 40-hex")
            record["reviewed_sha"] = args.reviewed_sha
        write_task(root, record)
    return record


def command_resolve_finding(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    reviewer, evidence = safe_scope(args.reviewer), safe_scope(args.evidence)
    if (args.finding_index < 0 or args.expected_revision < 0
            or not re.fullmatch(r"[0-9a-f]{64}", args.finding_sha256)
            or not re.fullmatch(r"[0-9a-f]{40}", args.head_sha)):
        raise InputError("resolution requires a nonnegative index/revision and full lowercase digests")
    with CoordinatorLock(root):
        record = read_task(root, args.task_id)
        verify_reservations(root, record)
        if record["transition_intent"]:
            raise UnknownError("reconcile unfinished transition before resolving findings")
        if "review_protocol" in record:
            raise BusyError("legacy resolution cannot supply review protocol evidence")
        allowed_states = {"Reviewing"}
        if args.disposition == "persists":
            allowed_states.add("Ready for human review")
        if record["kind"] not in {"implementation", "review"} or record["state"] not in allowed_states:
            raise BusyError("legacy disposition requires an implementation/review task in Reviewing (or ready for persists)")
        if args.expected_revision != record["revision"] or args.head_sha != record["head_sha"]:
            raise BusyError("resolution revision/head is stale")
        if not record["owner"].strip() or reviewer == record["owner"].strip():
            raise BusyError("resolution requires an owner and a distinct reviewer label")
        if (args.finding_index >= len(record["findings"])
                or scope_key(record["findings"][args.finding_index]) != args.finding_sha256):
            raise BusyError("resolution finding index/text digest does not match")
        require_execution_stopped(record)
        require_repair_settled(record, root=root)
        if os.environ.get("ORCHESTRATOR_TEST_MODE") != "1":
            if record["kind"] == "review":
                verify_review_identity(record)
            else:
                verify_worktree_identity(record, require_head=True)
                verify_clean_checkout(record["worktree"])
        ledger = record.setdefault("legacy_finding_dispositions", {"epoch": 0, "history": []})
        prior = next((item["disposition"] for item in reversed(ledger["history"])
                      if item["epoch"] == ledger["epoch"] and item["finding_index"] == args.finding_index), None)
        if prior is not None and (prior == "persists") == (args.disposition == "persists"):
            raise BusyError("finding already has this outcome; requires an intervening reopening/resolution")
        if len(ledger["history"]) >= 1000:
            raise BusyError("legacy disposition history is full; checkpoint and escalate")
        ledger["history"].append({
            "finding_index": args.finding_index, "finding_sha256": args.finding_sha256,
            "head_sha": args.head_sha, "epoch": ledger["epoch"], "disposition": args.disposition,
            "reviewer": reviewer, "implementation_owner": record["owner"], "evidence": evidence,
            "revision": record["revision"] + 1,
        })
        if args.disposition == "persists":
            revoke_legacy_readiness(record)
        write_task(root, record)
    return record


def command_update_head(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", args.head_sha):
        raise InputError("head SHA must be full lowercase 40-hex")
    with CoordinatorLock(root):
        record = read_task(root, args.task_id)
        require_repair_settled(record, root=root)
        if record["kind"] != "implementation" or record["state"] not in {"Implementing", "Rework", "Claimed"}:
            raise BusyError("head can be updated only for an active/rework implementation task")
        worktree = record["worktree"]
        if not worktree:
            raise UnknownError("implementation task has no worktree")
        top = git_probe(worktree, "rev-parse", "--show-toplevel")
        branch = git_probe(worktree, "symbolic-ref", "--quiet", "--short", "HEAD")
        head = git_probe(worktree, "rev-parse", "HEAD")
        ancestor = git_probe(worktree, "merge-base", "--is-ancestor", record["base_sha"], args.head_sha)
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != Path(worktree):
            raise UnknownError("assigned worktree identity changed")
        if branch.returncode != 0 or branch.stdout.strip() != record["branch"]:
            raise UnknownError("assigned branch changed")
        if head.returncode != 0 or head.stdout.strip() != args.head_sha:
            raise BusyError("requested head is not the assigned worktree HEAD")
        if ancestor.returncode != 0:
            raise BusyError("requested head does not descend from the recorded base")
        if record["head_sha"] != args.head_sha and "review_protocol" in record:
            protocol = record["review_protocol"]
            if not isinstance(protocol, dict) or type(protocol.get("material_epoch")) is not int:
                raise UnknownError("review protocol material epoch is malformed")
            protocol["material_epoch"] += 1
        if record["head_sha"] != args.head_sha and "legacy_finding_dispositions" in record:
            record["legacy_finding_dispositions"]["epoch"] += 1
        record["head_sha"] = args.head_sha
        record["reviewed_sha"] = ""
        record["reviewers"] = []
        record["validation"] = []
        record["next_action"] = args.next_action or "independent review at updated head"
        write_task(root, record)
    return record


def reservation_owner(root: Path, group: str, index: int | str) -> dict[str, Any]:
    return read_json(root / group / f"{index}.lock" / "owner.json", f"{group} reservation {index}")


def verify_reservations(root: Path, record: dict[str, Any]) -> None:
    expected: list[tuple[str, int | str, str]] = []
    if record["state"] not in TERMINAL:
        expected.append(("scopes", record["scope_key"], record["leases"]["scope_token"]))
    worker = record.get("worker")
    if record["state"] not in ACTIVE:
        if worker is not None or record["leases"]["global_slot"] is not None or record["leases"]["implementation_lane"] is not None:
            raise UnknownError(f"task {record['task_id']} retains active ownership outside an active state")
    if record["state"] in ACTIVE:
        if not worker:
            raise UnknownError(f"task {record['task_id']} is active without a worker")
        slot = record["leases"]["global_slot"]
        if slot is None:
            raise UnknownError(f"task {record['task_id']} is active without a global slot")
        expected.append(("slots", slot, worker["token"]))
        lane = record["leases"]["implementation_lane"]
        if record["state"] == "Implementing" and record["kind"] == "implementation":
            if lane is None:
                raise UnknownError(f"task {record['task_id']} is implementing without a lane")
            expected.append(("implementation", lane, worker["token"]))
        elif lane is not None:
            raise UnknownError(f"task {record['task_id']} holds an unexpected implementation lane")
    for group, index, token in expected:
        owner = reservation_owner(root, group, index)
        if owner.get("task_id") != record["task_id"] or owner.get("token") != token:
            raise UnknownError(f"task {record['task_id']} does not own its {group} reservation")


def validate_admission_reservations(root: Path) -> None:
    """Refuse new work if either side of any reservation is unmeasured.

    Run under CoordinatorLock before create/claim. Readable JSON alone does
    not establish ownership: a lock may name a missing task, or a task may
    claim a different slot. An interrupted transition must be reconciled
    explicitly before admission rather than guessed into a healthy state.
    """
    records: dict[str, dict[str, Any]] = {}
    for path in (root / "tasks").glob("*/task.json"):
        record = validate_record(read_json(path, f"task {path.parent.name}"), path.parent.name)
        if record["transition_intent"]:
            raise UnknownError(f"task {record['task_id']} has an unfinished transition; reconcile first")
        records[record["task_id"]] = record
        verify_reservations(root, record)
    for group in ("scopes", "slots", "implementation"):
        for lock in (root / group).glob("*.lock"):
            owner = read_json(lock / "owner.json", f"{group} reservation {lock.name}")
            task_id = owner.get("task_id")
            record = records.get(task_id) if isinstance(task_id, str) else None
            if record is None:
                raise UnknownError(f"{group} reservation {lock.name} has no task record")
            if group == "scopes":
                expected_slot = record["scope_key"]
                expected_token = record["leases"]["scope_token"]
                valid_state = record["state"] not in TERMINAL
            elif group == "slots":
                expected_slot = record["leases"]["global_slot"]
                expected_token = (record.get("worker") or {}).get("token")
                valid_state = record["state"] in ACTIVE
            else:
                expected_slot = record["leases"]["implementation_lane"]
                expected_token = (record.get("worker") or {}).get("token")
                valid_state = record["state"] == "Implementing" and record["kind"] == "implementation"
            if not valid_state or lock.name != f"{expected_slot}.lock" or owner.get("token") != expected_token:
                raise UnknownError(f"{group} reservation {lock.name} disagrees with task {task_id}")


def finish_intent(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    target = record["transition_intent"]
    if not target:
        return record
    require_execution_stopped(record)
    require_repair_settled(record, root=root)
    if target == "Ready for human review":
        if "review_protocol" in record:
            raise UnknownError("cannot recover readiness from uncorroborated review protocol claims")
        # The earlier readiness check was performed before writing intent.
        # The worktree may have changed during a crash: never publish ready
        # solely by replaying the intent.
        if (not record["head_sha"] or record["reviewed_sha"] != record["head_sha"]
                or not record["reviewers"] or not record["validation"] or unresolved_legacy_findings(record)):
            raise UnknownError("cannot recover readiness: review evidence changed")
        if record["kind"] == "implementation" and os.environ.get("ORCHESTRATOR_TEST_MODE") != "1":
            verify_worktree_identity(record, require_head=True)
            verify_clean_checkout(record["worktree"])
        if record["kind"] == "review" and os.environ.get("ORCHESTRATOR_TEST_MODE") != "1":
            verify_review_identity(record)
    if target in {"Reviewing", "Implementing"} and os.environ.get("ORCHESTRATOR_TEST_MODE") != "1":
        if record["kind"] == "implementation":
            verify_worktree_identity(record, require_head=True)
        elif record["kind"] == "review":
            verify_review_identity(record)
    if target == "Implementing" and record["leases"]["implementation_lane"] is None:
        if record["kind"] != "implementation" or not record.get("worker"):
            raise UnknownError(f"task {record['task_id']} cannot complete Implementing intent")
        matches = []
        for lock in (root / "implementation").glob("*.lock"):
            owner = read_json(lock / "owner.json", f"implementation reservation {lock.name}")
            if owner.get("task_id") == record["task_id"] and owner.get("token") == record["worker"]["token"]:
                matches.append(int(lock.stem))
        if len(matches) > 1:
            raise UnknownError(f"task {record['task_id']} owns multiple implementation lanes")
        record["leases"]["implementation_lane"] = matches[0] if matches else reserve_first(
            root, "implementation", MAX_IMPLEMENTATION, record["worker"]
        )
    elif target == "Reviewing":
        release_implementation_lane(root, record)
    elif target not in ACTIVE:
        release_capacity(root, record)
    if target in TERMINAL:
        release_dir(root / "scopes" / f"{record['scope_key']}.lock", record["leases"]["scope_token"])
    record["state"] = target
    record["transition_intent"] = None
    write_task(root, record)
    return record


def reconcile_one(root: Path, record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if record["transition_intent"]:
        record = finish_intent(root, record)
        verify_reservations(root, record)
        return record, True
    verify_reservations(root, record)
    if record["state"] not in ACTIVE:
        return record, False
    worker = record.get("worker")
    if not worker or type(worker.get("pid")) is not int or not worker.get("process_start"):
        raise UnknownError(f"task {record['task_id']} has ambiguous active ownership")
    if worker["hostname"] != socket.gethostname():
        raise UnknownError(f"task {record['task_id']} belongs to another host")
    status, actual_start = process_identity(worker["pid"])
    if status == "unknown":
        raise UnknownError(f"cannot establish process state for task {record['task_id']}")
    if status == "alive" and actual_start != worker["process_start"]:
        raise UnknownError(f"task {record['task_id']} pid was reused or ownership changed")
    worktree = record.get("worktree")
    interrupted = status == "absent"
    missing_worktree = bool(worktree) and not Path(worktree).exists()
    if not interrupted and not missing_worktree:
        return record, False
    require_execution_stopped(record)
    require_repair_settled(record, root=root)
    release_capacity(root, record)
    record["state"] = "Blocked"
    record["next_action"] = "interrupted worker" if interrupted else "worktree missing"
    write_task(root, record)
    return record, True


def command_reconcile(args: argparse.Namespace, root: Path) -> list[dict[str, Any]]:
    changed = []
    with CoordinatorLock(root):
        paths = [task_path(root, args.task_id)] if args.task_id else sorted((root / "tasks").glob("*/task.json"))
        records: dict[str, dict[str, Any]] = {}
        for path in paths:
            if not path.exists():
                raise UnknownError("task record missing")
            record = validate_record(read_json(path, f"task {path.parent.name}"), path.parent.name)
            records[record["task_id"]] = record
            record, did_change = reconcile_one(root, record)
            if did_change:
                changed.append(record)
        # Every reservation must be readable and agree with the task's recorded
        # lease and fencing token. Existence alone is not ownership evidence.
        for group in ("scopes", "slots", "implementation"):
            for lock in (root / group).glob("*.lock"):
                owner = read_json(lock / "owner.json", f"{group} reservation {lock.name}")
                task_id = owner.get("task_id")
                if not isinstance(task_id, str) or not task_path(root, task_id).exists():
                    raise UnknownError(f"{group} reservation {lock.name} has no task record")
                record = records.get(task_id) or read_task(root, task_id)
                if group == "scopes" and record["state"] in TERMINAL:
                    raise UnknownError(f"terminal task {task_id} retains a scope reservation")
                if group == "slots" and record["state"] not in ACTIVE:
                    raise UnknownError(f"inactive task {task_id} retains a global slot")
                if group == "implementation" and not (record["state"] == "Implementing" and record["kind"] == "implementation"):
                    raise UnknownError(f"task {task_id} retains an invalid implementation lane")
                expected_token = record["leases"]["scope_token"] if group == "scopes" else (record.get("worker") or {}).get("token")
                expected_name = (
                    f"{record['scope_key']}.lock" if group == "scopes" else
                    f"{record['leases']['global_slot']}.lock" if group == "slots" else
                    f"{record['leases']['implementation_lane']}.lock"
                )
                if owner.get("token") != expected_token or lock.name != expected_name:
                    raise UnknownError(f"{group} reservation {lock.name} disagrees with task {task_id}")
    return changed


def command_list(root: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted((root / "tasks").glob("*/task.json")):
        records.append(validate_record(read_json(path, f"task {path.parent.name}"), path.parent.name))
    return records


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("task_id")
    create.add_argument("--scope", required=True)
    create.add_argument("--kind", choices=("implementation", "review", "monitor"), required=True)
    create.add_argument("--repo", default="")
    create.add_argument("--branch", default="")
    create.add_argument("--worktree", default="")
    create.add_argument("--base-sha", default="")
    create.add_argument("--head-sha", default="")
    create.add_argument("--tracker-type", choices=("none", "issue", "pr"), default="none")
    create.add_argument("--tracker-number", type=int, default=0)
    create.add_argument("--owned-path", action="append", default=[])
    create.add_argument("--restricted-path", action="append", default=[])
    create.add_argument("--acceptance", action="append", default=[])
    create.add_argument("--dependency", action="append", default=[])
    create.add_argument("--next-action", default="")
    claim = sub.add_parser("claim")
    claim.add_argument("task_id")
    claim.add_argument("--owner", required=True)
    claim.add_argument("--pid", type=int, default=os.getppid())
    transition = sub.add_parser("transition")
    transition.add_argument("task_id")
    transition.add_argument("state")
    transition.add_argument("--reason", default="")
    show = sub.add_parser("show")
    show.add_argument("task_id")
    sub.add_parser("list")
    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("task_id", nargs="?")
    update = sub.add_parser("update-head")
    update.add_argument("task_id")
    update.add_argument("head_sha")
    update.add_argument("--next-action", default="")
    record = sub.add_parser("record")
    record.add_argument("task_id")
    record.add_argument("category", choices=("reviewer", "finding", "resolution", "validation", "dependency"))
    record.add_argument("value")
    record.add_argument("--next-action", default="")
    record.add_argument("--reviewed-sha", default="")
    resolve = sub.add_parser("resolve-finding")
    resolve.add_argument("task_id")
    resolve.add_argument("--finding-index", type=int, required=True)
    resolve.add_argument("--finding-sha256", required=True)
    resolve.add_argument("--head-sha", required=True)
    resolve.add_argument("--disposition", choices=("fixed", "refuted", "persists"), required=True)
    resolve.add_argument("--reviewer", required=True)
    resolve.add_argument("--evidence", required=True)
    resolve.add_argument("--expected-revision", type=int, required=True)
    return p


def emit(value: Any) -> None:
    print(json.dumps(value, sort_keys=True, indent=2))


def main() -> int:
    try:
        args = parser().parse_args()
        root = state_root()
        if args.command == "create":
            emit(command_create(args, root))
        elif args.command == "claim":
            emit(command_claim(args, root))
        elif args.command == "transition":
            emit(command_transition(args, root))
        elif args.command == "show":
            emit(read_task(root, args.task_id))
        elif args.command == "list":
            emit(command_list(root))
        elif args.command == "reconcile":
            emit({"state": "CURRENT", "changed": command_reconcile(args, root)})
        elif args.command == "record":
            emit(command_record(args, root))
        elif args.command == "update-head":
            emit(command_update_head(args, root))
        elif args.command == "resolve-finding":
            emit(command_resolve_finding(args, root))
        return 0
    except InputError as exc:
        print(f"orchestrator: invalid input: {exc}", file=sys.stderr)
        return EXIT_INPUT
    except UnknownError as exc:
        emit({"state": "Unknown", "reason": str(exc)})
        print(f"orchestrator: UNVERIFIED - {exc}", file=sys.stderr)
        return EXIT_UNKNOWN
    except BusyError as exc:
        print(f"orchestrator: refused - {exc}", file=sys.stderr)
        return EXIT_BUSY
    except Exception as exc:
        # Operational failures must not fall through to an ambiguous traceback
        # or an invented healthy state. Keep the diagnostic bounded and typed.
        reason = str(exc).replace("\n", " ")[:500]
        emit({"state": "Unknown", "reason": reason})
        print(f"orchestrator: UNVERIFIED - {reason}", file=sys.stderr)
        return EXIT_UNKNOWN


if __name__ == "__main__":
    raise SystemExit(main())
