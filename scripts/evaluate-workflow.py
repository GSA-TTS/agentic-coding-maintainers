#!/usr/bin/env python3
"""Read-only, local, current-state workflow scorecard; never infer history."""

import sys

# Must run before ANY non-built-in import. Without -I, a caller-controlled
# PYTHONPATH could supply a module imported below and execute it on the host.
if not sys.flags.isolated or not sys.dont_write_bytecode:
    print("evaluation: UNVERIFIED — run with python3 -I -B", file=sys.stderr)
    sys.exit(3)

import argparse
import importlib.util
import json
import os
import stat
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path


class Unverified(Exception):
    pass


MAX_CASES = 500
MAX_RECORD_BYTES = 100_000
MAX_TOTAL_BYTES = 5_000_000


def instant(value: str) -> datetime:
    if not isinstance(value, str):
        raise Unverified("task timestamp is not a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise Unverified("task timestamp is malformed") from exc
    if parsed.tzinfo is None:
        raise Unverified("task timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def snapshot(workspace: Path, as_of: datetime) -> dict:
    # The validator is code from THIS trusted installation, never the selected
    # workspace. An import executes top-level Python, even when no function is
    # called: deriving its path from --workspace was a host-execution bug.
    source = Path(__file__).resolve().parent.parent / ".agents/skills/workspace-orchestrator/bin/orchestrator-state.py"
    if not source.is_file() or source.is_symlink():
        raise Unverified("canonical task validator is absent or symlinked")
    spec = importlib.util.spec_from_file_location("orchestrator_state_evaluation", source)
    if spec is None or spec.loader is None:
        raise Unverified("canonical task validator could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)

    results = []
    total_bytes = 0
    # Walk each component by descriptor; O_NOFOLLOW on the final tasks path
    # alone cannot prevent a concurrent swap of its .orchestrator parent.
    with ExitStack() as stack:
        workspace_fd = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, workspace_fd)
        root_fd = os.open(".orchestrator", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=workspace_fd)
        stack.callback(os.close, root_fd)
        tasks_fd = os.open("tasks", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        stack.callback(os.close, tasks_fd)
        for fd in (root_fd, tasks_fd):
            status = os.fstat(fd)
            if status.st_uid != os.getuid() or status.st_mode & 0o077:
                raise Unverified("task store is not current-user private")
        # Stop enumeration at the limit BEFORE sorting/materializing.
        with os.scandir(tasks_fd) as entries:
            names = []
            for entry in entries:
                names.append(entry.name)
                if len(names) > MAX_CASES:
                    raise Unverified("task count exceeds the evaluation limit")
        for name in sorted(names):
            if name in (".", ".."):
                raise Unverified("task directory name is invalid")
            directory_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=tasks_fd)
            try:
                record_fd = os.open("task.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
                try:
                    info = os.fstat(record_fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RECORD_BYTES:
                        raise Unverified("task record is not a bounded regular file")
                    with os.fdopen(record_fd, "rb") as handle:
                        record_fd = -1
                        data = handle.read(MAX_RECORD_BYTES + 1)
                    if len(data) > MAX_RECORD_BYTES:
                        raise Unverified("task record exceeds the evaluation limit")
                    total_bytes += len(data)
                    if total_bytes > MAX_TOTAL_BYTES:
                        raise Unverified("task record bytes exceed the evaluation limit")
                    raw = json.loads(data)
                finally:
                    if record_fd >= 0:
                        os.close(record_fd)
            finally:
                os.close(directory_fd)
            try:
                source_schema = raw.get("schema_version") if isinstance(raw, dict) else None
                record = module.validate_record(raw, name)
            except Exception as exc:  # malformed field types may raise TypeError in the canonical validator
                raise Unverified("a task record could not be validated") from exc
            if record["transition_intent"] is not None:
                raise Unverified("task transition is incomplete; reconcile first")
            created, updated = instant(record["created_at"]), instant(record["updated_at"])
            if created > updated or updated > as_of:
                raise Unverified("task timestamps are inconsistent or in the future")
            results.append({
                "id": record["task_id"], "kind": record["kind"], "state": record["state"],
                "age_days": round((as_of - created).total_seconds() / 86400, 2),
                "since_last_write_days": round((as_of - updated).total_seconds() / 86400, 2),
                # Schema 1 may have been upgraded and persisted as schema 2
                # with a *default* zero. Without provenance, a zero cannot
                # distinguish no rework from unknown pre-upgrade history.
                "recorded_rework_count": record["rework_count"] if source_schema != 1 and record["rework_count"] > 0 else None,
                "unresolved_finding_count": len(record["findings"]),
            })
    return {
        "as_of": as_of.isoformat(), "coverage": "parsed_task_records" if results else "no_evidence",
        "task_count": len(results), "by_state": dict(sorted(Counter(x["state"] for x in results).items())),
        "by_kind": dict(sorted(Counter(x["kind"] for x in results).items())),
        "cases": results,
        "unmeasured": [
            "reservation/lease consistency", "live worker ownership", "historical throughput",
            "time in state", "review turnaround", "outcome quality",
            "continuous monitor uptime", "CI pass rate",
        ],
        "recommendations": (
            ["Reconcile task records with current issues and PRs before claiming an outcome."]
            if results else ["Admit a case before estimating throughput; zero records is not zero work."]
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    try:
        workspace = args.workspace.expanduser()
        if workspace.is_symlink() or not workspace.is_dir():
            raise Unverified("workspace is not a real directory")
        report = snapshot(workspace.resolve(), datetime.now(timezone.utc))
    except (Unverified, OSError, ValueError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        if not isinstance(exc, Unverified):
            exc = Unverified("task store could not be read consistently")
        print(f"evaluation: UNVERIFIED — {exc}", file=sys.stderr)
        return 3
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["coverage"] == "parsed_task_records" else 3


if __name__ == "__main__":
    sys.exit(main())
