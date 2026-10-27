#!/usr/bin/env python3
"""Pure shadow planner for typed exceptions; never executes a recommendation."""

import sys

if not sys.flags.isolated or not sys.dont_write_bytecode:
    print("exception planner: UNVERIFIED — run with python3 -I -B", file=sys.stderr)
    sys.exit(3)

import argparse
import datetime
import json
import os
import re
import stat
from pathlib import Path

MAX_BYTES = 8192
MAX_ATTEMPT_BYTES = 131072
MAX_ATTEMPTS = 1000
SHA = re.compile(r"^[0-9a-f]{40}$")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
BLOCKERS = {"PARTIAL_WRITE", "STALE_HEAD", "POLICY_DECISION", "CI_OUTAGE", "MISSING_PROVENANCE", "CODE_BUG", "UNKNOWN"}
EVIDENCE = {"complete", "partial", "none"}
MEASUREMENTS = {"check_status", "head_identity", "source_provenance", "worker_liveness"}
FIELDS = {"schema_version", "task_id", "blocker", "task_head_sha", "evidence_head_sha",
          "evidence_coverage", "observed_at", "operation", "measurement",
          "policy_authorization", "independent_work_ready", "write_settlement"}
ATTEMPT_FIELDS = {"schema_version", "attempt_id", "task_id", "head_sha", "measurement", "outcome", "recorded_at"}


class Unverified(Exception):
    pass


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Unverified("duplicate input field")
        result[key] = value
    return result


def validate(value):
    if not isinstance(value, dict) or set(value) != FIELDS or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise Unverified("snapshot fields or schema version are invalid")
    if not isinstance(value["task_id"], str) or not IDENT.fullmatch(value["task_id"]):
        raise Unverified("task identity is invalid")
    if not isinstance(value["blocker"], str) or value["blocker"] not in BLOCKERS:
        raise Unverified("blocker classification is invalid")
    for field in ("task_head_sha", "evidence_head_sha"):
        if value[field] is not None and (not isinstance(value[field], str) or not SHA.fullmatch(value[field])):
            raise Unverified("head binding has an invalid shape")
    if not isinstance(value["evidence_coverage"], str) or value["evidence_coverage"] not in EVIDENCE:
        raise Unverified("evidence coverage is invalid")
    instant(value["observed_at"])
    if not isinstance(value["operation"], str) or value["operation"] not in {"local_read", "remote_read", "remote_write"}:
        raise Unverified("operation type is invalid")
    if value["measurement"] is not None and (not isinstance(value["measurement"], str) or value["measurement"] not in MEASUREMENTS):
        raise Unverified("measurement is not allowlisted")
    if type(value["policy_authorization"]) is not bool or type(value["independent_work_ready"]) is not bool:
        raise Unverified("authorization or independent-work flag is invalid")
    if not isinstance(value["write_settlement"], str) or value["write_settlement"] not in {"not_attempted", "unknown", "confirmed"}:
        raise Unverified("write settlement is invalid")
    if value["write_settlement"] != "not_attempted" and value["operation"] != "remote_write":
        raise Unverified("write settlement is incompatible with a read operation")
    if value["blocker"] == "PARTIAL_WRITE" and (value["operation"] != "remote_write" or value["write_settlement"] != "unknown"):
        raise Unverified("partial-write blocker needs an uncertain remote write")
    if value["blocker"] == "STALE_HEAD" and (
        value["task_head_sha"] is None or value["evidence_head_sha"] is None or
        value["task_head_sha"] == value["evidence_head_sha"]
    ):
        raise Unverified("stale-head classification requires two different measured heads")
    if value["measurement"] is not None and value["task_head_sha"] is None:
        raise Unverified("head-budgeted diagnostic requires a measured task head")
    return value


def instant(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
        raise Unverified("UTC observation/attempt time is invalid")
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Unverified("UTC observation/attempt time is impossible") from exc


def private_attempts(path):
    """Bounded no-follow read; no arbitrary code, symlinks, or outside repo read."""
    if not path.is_absolute() or path.name in ("", ".", ".."):
        raise Unverified("attempt ledger path must be absolute")
    # macOS system /var is a platform symlink, not an operator-chosen path.
    if sys.platform == "darwin" and path.parts[:2] == ("/", "var"):
        path = Path("/private/var", *path.parts[2:])
    fds = []
    try:
        fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fds.append(fd)
        for component in path.parent.parts[1:]:
            if component in (".", ".."):
                raise Unverified("attempt ledger ancestor is unsafe")
            fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            fds.append(fd)
        parent = os.fstat(fd)
        if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
            raise Unverified("attempt ledger directory must be current-user private")
        file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            info = os.fstat(file_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > MAX_ATTEMPT_BYTES:
                raise Unverified("attempt ledger file is unsafe or oversized")
            with os.fdopen(file_fd, "rb") as handle:
                file_fd = -1
                data = handle.read(MAX_ATTEMPT_BYTES + 1)
        finally:
            if file_fd >= 0:
                os.close(file_fd)
    finally:
        for descriptor in reversed(fds):
            os.close(descriptor)
    if len(data) > MAX_ATTEMPT_BYTES or data and not data.endswith(b"\n"):
        raise Unverified("attempt ledger is oversized or has an incomplete final line")
    return data


def attempt_count(data, snapshot):
    lines = data.splitlines()
    if len(lines) > MAX_ATTEMPTS:
        raise Unverified("attempt ledger exceeds the record limit")
    seen = set()
    count = 0
    previous = None
    for line in lines:
        try:
            row = json.loads(line, object_pairs_hook=unique_fields)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise Unverified("attempt ledger has a malformed line") from exc
        if not isinstance(row, dict) or set(row) != ATTEMPT_FIELDS or type(row["schema_version"]) is not int or row["schema_version"] != 1:
            raise Unverified("attempt record fields are invalid")
        if not isinstance(row["attempt_id"], str) or not IDENT.fullmatch(row["attempt_id"]) or row["attempt_id"] in seen:
            raise Unverified("attempt identifier is invalid or duplicated")
        seen.add(row["attempt_id"])
        if not isinstance(row["task_id"], str) or not IDENT.fullmatch(row["task_id"]):
            raise Unverified("attempt task identity is invalid")
        if not isinstance(row["head_sha"], str) or not SHA.fullmatch(row["head_sha"]):
            raise Unverified("attempt head is invalid")
        if not isinstance(row["measurement"], str) or row["measurement"] not in MEASUREMENTS:
            raise Unverified("attempt measurement is not allowlisted")
        if not isinstance(row["outcome"], str) or row["outcome"] not in {"complete", "unverified"}:
            raise Unverified("attempt outcome is invalid")
        at = instant(row["recorded_at"])
        if previous is not None and at < previous:
            raise Unverified("attempt recorded order is inconsistent")
        previous = at
        if at > instant(snapshot["observed_at"]):
            raise Unverified("attempt was recorded after the snapshot")
        if row["task_id"] == snapshot["task_id"] and row["head_sha"] == snapshot["task_head_sha"]:
            count += 1
    return count


def plan(value):
    """One typed advisory action, priority ordered; no IO or hidden clock."""
    if value["write_settlement"] == "unknown" or value["blocker"] == "PARTIAL_WRITE":
        return "RECONCILE_WRITE_READ_ONLY", "write may have occurred; never blind-retry"
    if value["operation"] == "remote_write" and not value["policy_authorization"]:
        return "HUMAN_AUTHORIZATION", "remote write lacks action-specific authorization"
    if value["task_head_sha"] and value["evidence_head_sha"] and value["task_head_sha"] != value["evidence_head_sha"]:
        return "REMEASURE_HEAD_READ_ONLY", "head-dependent evidence applies to another head"
    if value["blocker"] == "POLICY_DECISION":
        return "HUMAN_POLICY_DECISION", "decision is outside the planner's authority"
    if value["blocker"] == "CI_OUTAGE":
        if value["independent_work_ready"]:
            return "REVIEW_INDEPENDENT_WORK", "CI check deferred; unrelated ready work can be reviewed"
        return "DEFER_CI_MEASUREMENT", "CI availability blocks this check, not independent tasks"
    if (value["blocker"] == "CODE_BUG" and value["evidence_coverage"] == "complete" and
            value["task_head_sha"] is not None and value["evidence_head_sha"] == value["task_head_sha"]):
        return "OWNER_REWORK_REVIEW", "reproducible failure is head-bound; owner fix then fixed-head review"
    if value["blocker"] == "MISSING_PROVENANCE" and value["measurement"] == "source_provenance" and value["attempts_for_head"] < 2:
        return "MEASURE_SOURCE_READ_ONLY", "bounded provenance measurement is still available"
    if value["measurement"] and value["attempts_for_head"] < 2:
        return "MEASURE_READ_ONLY", "bounded allowlisted diagnostic is still available"
    if value["independent_work_ready"]:
        return "REVIEW_INDEPENDENT_WORK", "unrelated ready work can progress while this case stays UNVERIFIED"
    return "HUMAN_TRIAGE", "evidence missing or diagnostic budget exhausted"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt-ledger", required=True, type=Path)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        if not raw or len(raw) > MAX_BYTES:
            raise Unverified("bounded snapshot is missing or oversized")
        value = validate(json.loads(raw, object_pairs_hook=unique_fields))
        value["attempts_for_head"] = attempt_count(private_attempts(args.attempt_ledger), value)
        action, reason = plan(value)
    except (Unverified, OSError, ValueError, UnicodeError, RecursionError, TypeError) as exc:
        print(f"exception planner: UNVERIFIED — {exc if isinstance(exc, Unverified) else 'snapshot or attempt ledger unavailable'}", file=sys.stderr)
        return 3
    print(json.dumps({"schema_version": 1, "mode": "SHADOW_ONLY", "task_id": value["task_id"],
                      "current_verdict": "UNVERIFIED", "action": action, "reason": reason,
                      "attempts_for_head_from_private_ledger": value["attempts_for_head"],
                      "execution_performed": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
