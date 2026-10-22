#!/usr/bin/env python3
"""Foreground configured GitHub monitor; no process means no monitoring."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FIELDS = "number,title,author,isDraft,state,headRefOid,updatedAt,reviewDecision,mergeStateStatus,statusCheckRollup"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
OWNER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
TASK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class MonitorError(Exception):
    pass


def workspace_root() -> Path:
    raw = os.environ.get("WORKSPACE_ORCHESTRATOR_ROOT")
    if not raw:
        raise MonitorError("WORKSPACE_ORCHESTRATOR_ROOT must name the consumer workspace")
    supplied = Path(raw).expanduser()
    if supplied.is_symlink():
        raise MonitorError("consumer workspace must not be a symlink")
    root = supplied.resolve()
    if not root.is_dir():
        raise MonitorError("consumer workspace must be a real directory, not a symlink")
    return root


def load_config(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000:
            raise ValueError("not a bounded regular file")
        config = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MonitorError(f"monitor config is unreadable: {safe_text(exc, 300)}") from exc
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise MonitorError("monitor config must be a schema-version 1 object")
    if not set(config).issubset({"schema_version", "repositories", "project"}):
        raise MonitorError("monitor config contains unsupported fields")
    repositories = config.get("repositories")
    if not isinstance(repositories, list) or not 1 <= len(repositories) <= 50:
        raise MonitorError("monitor config repositories must contain 1-50 entries")
    if len(set(repositories)) != len(repositories) or any(not isinstance(r, str) or not REPO_RE.fullmatch(r) for r in repositories):
        raise MonitorError("monitor repositories must be unique owner/name values")
    project = config.get("project")
    if project is not None:
        if not isinstance(project, dict) or not {"owner", "number"} <= set(project):
            raise MonitorError("project must contain owner and number")
        # owner_type is OPTIONAL and defaults to "organization": GraphQL exposes
        # projectV2 under separate organization/user root fields with no neutral
        # one, so a consumer that reads the board needs the type stated rather
        # than probed. Accepting it here (instead of rejecting it as unknown)
        # keeps one config file shared with the cross-repo-epic skill. The
        # monitor itself does not use it.
        if not set(project) <= {"owner", "number", "owner_type"}:
            unknown = sorted(set(project) - {"owner", "number", "owner_type"})
            raise MonitorError(f"project contains unsupported field(s): {', '.join(unknown)}")
        if not isinstance(project["owner"], str) or not OWNER_RE.fullmatch(project["owner"]):
            raise MonitorError("project owner is invalid")
        if type(project["number"]) is not int or project["number"] <= 0:
            raise MonitorError("project number must be positive")
        owner_type = project.get("owner_type", "organization")
        if owner_type not in {"organization", "user"}:
            raise MonitorError("project owner_type must be organization or user")
    return {"schema_version": 1, "repositories": repositories, "project": project}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_text(value: object, limit: int = 200) -> str:
    text = str(value)
    text = "".join("?" if ord(c) < 32 or 127 <= ord(c) <= 159 else c for c in text)
    return text[:limit]


def run(argv: list[str], timeout: int = 90) -> str:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise MonitorError(f"{argv[0]} could not run: {safe_text(exc)}") from exc
    if result.returncode != 0:
        raise MonitorError(f"{' '.join(argv[:3])} failed: {safe_text(result.stderr)}")
    if len(result.stdout) > 5_000_000:
        raise MonitorError("monitor output exceeded 5 MB")
    return result.stdout


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = (json.dumps(data, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if len(encoded) > 5_000_000:
        raise MonitorError("monitor checkpoint would exceed 5 MB")
    fd, tmp = tempfile.mkstemp(prefix=".new-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded.decode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def state_dir() -> Path:
    test_mode = os.environ.get("ORCHESTRATOR_TEST_MODE") == "1"
    raw = os.environ.get("ORCHESTRATOR_STATE_DIR") if test_mode else None
    root = Path(raw) if raw else workspace_root() / ".orchestrator"
    if test_mode:
        try:
            root.resolve().relative_to(Path(tempfile.gettempdir()).resolve())
        except ValueError as exc:
            raise MonitorError("test state root must stay under the system temporary directory") from exc
    if root.exists() and root.is_symlink():
        raise MonitorError("state root is a symlink")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = root.stat()
    if st.st_uid != os.getuid() or st.st_mode & 0o022:
        raise MonitorError("state root must be current-user owned and not group/world writable")
    path = root / "monitor"
    if path.exists() and path.is_symlink():
        raise MonitorError("monitor state directory is a symlink")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    pst = path.stat()
    if not path.is_dir() or pst.st_uid != os.getuid() or pst.st_mode & 0o022:
        raise MonitorError("monitor state directory must be private and current-user owned")
    return path


def acquire(path: Path) -> None:
    try:
        os.mkdir(path, 0o700)
    except FileExistsError as exc:
        raise MonitorError("another monitor run is active; this poll was not performed") from exc


def validate_monitor_task(root: Path, task_id: str) -> None:
    if not TASK_RE.fullmatch(task_id):
        raise ValueError("monitor task id is invalid")
    task_record = root.parent / "tasks" / task_id / "task.json"
    task = read_bounded_json(task_record, "monitor task")
    if task.get("kind") != "monitor" or task.get("state") not in {"Claimed", "Reviewing"} or task.get("worker") is None:
        raise ValueError("monitor task is not actively claimed")
    worker = task["worker"]
    test_mode = os.environ.get("ORCHESTRATOR_TEST_MODE") == "1"
    if not test_mode and worker.get("pid") != os.getpid():
        raise ValueError("monitor task must be claimed by this monitor process")
    process = subprocess.run(
        ["ps", "-p", str(os.getpid()), "-o", "lstart="], capture_output=True,
        text=True, check=False, timeout=3,
    )
    if not test_mode and (process.returncode != 0 or process.stdout.strip() != worker.get("process_start")):
        raise ValueError("monitor process identity does not match the task claim")
    slot = task.get("leases", {}).get("global_slot")
    if type(slot) is not int or not 0 <= slot < 6:
        raise ValueError("monitor task has no valid global slot")
    owner = read_bounded_json(root.parent / "slots" / f"{slot}.lock" / "owner.json", "monitor slot")
    if owner.get("task_id") != task_id or owner.get("token") != worker.get("token"):
        raise ValueError("monitor task does not own its global slot")


def read_bounded_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
        raise ValueError(f"{label} is not a bounded regular file")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{label} is not an object")
    return data


def pr_snapshot(repositories: list[str]) -> list[dict[str, Any]]:
    result = []
    for repo in repositories:
        # gh paginates internally up to --limit. Fetch well beyond normal open
        # counts and refuse at the explicit ceiling instead of checkpointing a
        # silently truncated first page.
        raw = run(["gh", "pr", "list", "-R", repo, "--state", "open", "--limit", "501", "--json", FIELDS])
        try:
            prs = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MonitorError(f"{repo} returned malformed JSON") from exc
        if not isinstance(prs, list):
            raise MonitorError(f"{repo} PR response is not a list")
        if len(prs) >= 501:
            raise MonitorError(f"{repo} open PR coverage reached the 500-item ceiling")
        for pr in prs:
            if not isinstance(pr, dict) or type(pr.get("number")) is not int or not isinstance(pr.get("headRefOid"), str):
                raise MonitorError(f"{repo} PR response has an invalid shape")
            checks = pr.get("statusCheckRollup")
            if not isinstance(checks, list):
                raise MonitorError(f"{repo}#{pr.get('number')} checks are unavailable")
            conclusions = []
            for check in checks:
                if not isinstance(check, dict):
                    raise MonitorError(f"{repo}#{pr['number']} check is malformed")
                conclusions.append(check.get("conclusion") or check.get("state") or "ABSENT")
            result.append({
                "repo": repo, "number": pr["number"], "head": pr["headRefOid"],
                "title": safe_text(pr.get("title", "")), "draft": bool(pr.get("isDraft")),
                "state": pr.get("state"), "review": pr.get("reviewDecision") or "NONE",
                "merge": pr.get("mergeStateStatus") or "UNKNOWN",
                "checks": sorted(conclusions), "updated_at": pr.get("updatedAt"),
            })
    return sorted(result, key=lambda p: (p["repo"], p["number"]))


def project_snapshot(project: dict[str, Any] | None) -> str:
    if project is None:
        return ""
    raw = run([
        "gh", "project", "item-list", str(project["number"]),
        "--owner", project["owner"], "--limit", "2000", "--format", "json",
    ])
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MonitorError("configured GitHub Project returned malformed JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise MonitorError("configured GitHub Project response has an invalid shape")
    total = payload.get("totalCount")
    if type(total) is not int or total < 0:
        raise MonitorError("configured GitHub Project totalCount is unavailable")
    if len(payload["items"]) != total:
        raise MonitorError(f"configured GitHub Project coverage is incomplete ({len(payload['items'])}/{total})")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def poll(root: Path, config: dict[str, Any]) -> tuple[str, dict[str, Any], list[str]]:
    checkpoint = root / "checkpoint.json"
    project = project_snapshot(config["project"])
    prs = pr_snapshot(config["repositories"])
    observed = {
        "schema_version": 1,
        "config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "prs": prs,
        "project_sha256": hashlib.sha256(project.encode()).hexdigest() if config["project"] else None,
    }
    previous = None
    if checkpoint.exists():
        try:
            previous = read_bounded_json(checkpoint, "monitor checkpoint").get("observation")
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            raise MonitorError(f"checkpoint is unreadable: {safe_text(exc)}") from exc
    changed = []
    old_prs = {(p["repo"], p["number"]): p for p in (previous or {}).get("prs", [])}
    current_keys = {(p["repo"], p["number"]) for p in prs}
    for pr in prs:
        old = old_prs.get((pr["repo"], pr["number"]))
        if old != pr:
            changed.append(f"{pr['repo']}#{pr['number']} head={pr['head'][:9]} review={pr['review']} merge={pr['merge']}")
    for key in sorted(set(old_prs) - current_keys):
        changed.append(f"{key[0]}#{key[1]} left the open PR set")
    if previous and previous.get("project_sha256") != observed["project_sha256"]:
        changed.append("configured GitHub Project view changed")
    if previous and previous.get("config_sha256") != observed["config_sha256"]:
        changed.append("monitor configuration changed")
    status = "CHANGED" if changed or previous is None else "CURRENT"
    atomic_json(checkpoint, {
        "schema_version": 1, "last_attempt_at": now(), "last_attempt_status": status,
        "last_success_at": now(), "observation": observed,
    })
    return status, observed, changed


def record_failure(root: Path, reason: str) -> None:
    atomic_json(root / "last-failure.json", {
        "schema_version": 1, "last_attempt_at": now(),
        "last_attempt_status": "UNVERIFIED", "failure_reason": safe_text(reason, 500),
    })


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--loop", action="store_true")
    p.add_argument("--interval", type=int, default=600)
    p.add_argument("--task-id", required=True)
    p.add_argument("--config", type=Path, required=True)
    args = p.parse_args()
    if args.interval < 60:
        print("monitor: interval must be at least 60 seconds", file=sys.stderr)
        return 2
    try:
        root = state_dir()
        config = load_config(args.config)
    except Exception as exc:
        print(f"monitor: UNVERIFIED - {exc}", file=sys.stderr)
        return 3
    try:
        validate_monitor_task(root, args.task_id)
    except Exception as exc:
        print(f"monitor: UNVERIFIED - monitor task evidence is invalid: {safe_text(exc, 500)}", file=sys.stderr)
        return 3
    while True:
        lock = root / "poll.lock"
        try:
            validate_monitor_task(root, args.task_id)
            acquire(lock)
            try:
                # A running monitor must never silently keep watching old
                # repositories after the host-local config changes.
                current_config = load_config(args.config)
                if current_config != config:
                    raise MonitorError("monitor configuration changed; stop, reconcile targets, and restart")
                status, _observation, changed = poll(root, current_config)
                if status == "CHANGED":
                    print(f"monitor: CHANGED at {now()}")
                    for item in changed:
                        print(f"  {item}")
            finally:
                os.rmdir(lock)
        except Exception as exc:
            try:
                record_failure(root, str(exc))
            except Exception as record_exc:
                print(f"monitor: UNVERIFIED - failure state could not be recorded: {safe_text(record_exc, 500)}", file=sys.stderr)
                return 3
            print(f"monitor: UNVERIFIED - {exc}", file=sys.stderr)
            return 3
        if not args.loop:
            return 0
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
