#!/usr/bin/env python3
"""Read-only, local, current-state workflow scorecard; never infer history."""

import argparse
import importlib.util
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


class Unverified(Exception):
    pass


def instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise Unverified("task timestamp is malformed") from exc
    if parsed.tzinfo is None:
        raise Unverified("task timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def snapshot(workspace: Path, as_of: datetime) -> dict:
    root = workspace / ".orchestrator"
    tasks = root / "tasks"
    if root.is_symlink() or tasks.is_symlink() or not tasks.is_dir():
        raise Unverified("private task store is absent or unsafe; no measured task coverage")
    if not tasks.resolve().is_relative_to(workspace.resolve()):
        raise Unverified("task store escapes workspace")
    for directory in (root, tasks):
        status = directory.stat()
        if status.st_uid != os.getuid() or status.st_mode & 0o077:
            raise Unverified("task store is not current-user private")

    # Reuse the canonical state validator rather than inventing a second task
    # schema. Loading it imports functions only; no state operation is called.
    source = workspace / ".agents/skills/workspace-orchestrator/bin/orchestrator-state.py"
    if not source.is_file() or source.is_symlink():
        raise Unverified("canonical task validator is absent or symlinked")
    spec = importlib.util.spec_from_file_location("orchestrator_state_evaluation", source)
    if spec is None or spec.loader is None:
        raise Unverified("canonical task validator could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    results = []
    for directory in sorted(tasks.iterdir()):
        if directory.is_symlink() or not directory.is_dir():
            raise Unverified("task store has an unexpected or symlinked entry")
        path = directory / "task.json"
        if not path.is_file() or path.is_symlink():
            raise Unverified("task record missing or symlinked")
        try:
            record = module.validate_record(module.read_json(path, "evaluation task"), directory.name)
        except (module.InputError, module.UnknownError) as exc:
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
            "recorded_rework_count": record["rework_count"],
            "unresolved_finding_count": len(record["findings"]),
        })
    return {
        "as_of": as_of.isoformat(), "coverage": "measured" if results else "no_evidence",
        "task_count": len(results), "by_state": dict(sorted(Counter(x["state"] for x in results).items())),
        "by_kind": dict(sorted(Counter(x["kind"] for x in results).items())),
        "cases": results,
        "unmeasured": [
            "historical throughput", "time in state", "review turnaround",
            "outcome quality", "continuous monitor uptime", "CI pass rate",
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
    except (Unverified, OSError, ValueError) as exc:
        print(f"evaluation: UNVERIFIED — {exc}", file=sys.stderr)
        return 3
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["coverage"] == "measured" else 3


if __name__ == "__main__":
    sys.exit(main())
