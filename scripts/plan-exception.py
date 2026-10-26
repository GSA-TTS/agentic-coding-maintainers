#!/usr/bin/env python3
"""Pure shadow planner for typed exceptions; never executes a recommendation."""

import sys

if not sys.flags.isolated or not sys.dont_write_bytecode:
    print("exception planner: UNVERIFIED — run with python3 -I -B", file=sys.stderr)
    sys.exit(3)

import argparse
import datetime
import json
import re

MAX_BYTES = 8192
SHA = re.compile(r"^[0-9a-f]{40}$")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
BLOCKERS = {"PARTIAL_WRITE", "STALE_HEAD", "POLICY_DECISION", "CI_OUTAGE", "MISSING_PROVENANCE", "CODE_BUG", "UNKNOWN"}
EVIDENCE = {"complete", "partial", "none"}
MEASUREMENTS = {"check_status", "head_identity", "source_provenance", "worker_liveness"}
FIELDS = {"schema_version", "task_id", "blocker", "task_head_sha", "evidence_head_sha",
          "evidence_coverage", "attempts_for_head", "observed_at", "operation", "measurement",
          "policy_authorization", "independent_work_ready", "write_settlement"}


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
    if type(value["attempts_for_head"]) is not int or not 0 <= value["attempts_for_head"] <= 100:
        raise Unverified("attempt budget is invalid")
    if not isinstance(value["observed_at"], str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value["observed_at"]):
        raise Unverified("snapshot time is invalid")
    try:
        datetime.datetime.fromisoformat(value["observed_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise Unverified("snapshot time is impossible") from exc
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
    return value


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
    if value["blocker"] == "CODE_BUG" and value["evidence_coverage"] == "complete" and value["task_head_sha"] == value["evidence_head_sha"]:
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
    parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        if not raw or len(raw) > MAX_BYTES:
            raise Unverified("bounded snapshot is missing or oversized")
        value = validate(json.loads(raw, object_pairs_hook=unique_fields))
        action, reason = plan(value)
    except (Unverified, ValueError, UnicodeError, RecursionError, TypeError) as exc:
        print(f"exception planner: UNVERIFIED — {exc if isinstance(exc, Unverified) else 'invalid snapshot'}", file=sys.stderr)
        return 3
    print(json.dumps({"schema_version": 1, "mode": "SHADOW_ONLY", "task_id": value["task_id"],
                      "current_verdict": "UNVERIFIED", "action": action, "reason": reason,
                      "execution_performed": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
