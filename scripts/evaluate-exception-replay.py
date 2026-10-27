#!/usr/bin/env python3
"""Offline shadow evaluation of supplied planner recommendations and labels."""

import sys

if not sys.flags.isolated or not sys.dont_write_bytecode:
    print("exception replay: UNVERIFIED — run with python3 -I -B", file=sys.stderr)
    sys.exit(3)

import argparse
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 65536
MAX_CASES = 500
MAX_MANIFEST_BYTES = 65536
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
ACTIONS = {
    "RECONCILE_WRITE_READ_ONLY", "HUMAN_AUTHORIZATION", "REMEASURE_HEAD_READ_ONLY",
    "HUMAN_POLICY_DECISION", "DEFER_CI_MEASUREMENT", "OWNER_REWORK_REVIEW",
    "MEASURE_SOURCE_READ_ONLY", "MEASURE_READ_ONLY", "REVIEW_INDEPENDENT_WORK", "HUMAN_TRIAGE",
}
WRITES = {"APPROVE", "MERGE", "POST", "PUSH", "EXECUTE_WRITE"}


class Unverified(Exception):
    pass


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Unverified("duplicate JSON field")
        result[key] = value
    return result


def private_manifest(path: Path):
    if not path.is_absolute() or path.name in ("", ".", ".."):
        raise Unverified("manifest path must be absolute")
    if sys.platform == "darwin" and path.parts[:2] == ("/", "var"):
        path = Path("/private/var", *path.parts[2:])
    fds = []
    try:
        fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fds.append(fd)
        for component in path.parent.parts[1:]:
            if component in (".", ".."):
                raise Unverified("manifest path has a relative component")
            fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            fds.append(fd)
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Unverified("manifest directory is not current-user private")
        file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            info = os.fstat(file_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > MAX_MANIFEST_BYTES:
                raise Unverified("manifest file is unsafe or oversized")
            with os.fdopen(file_fd, "rb") as handle:
                file_fd = -1
                data = handle.read(MAX_MANIFEST_BYTES + 1)
        finally:
            if file_fd >= 0:
                os.close(file_fd)
    finally:
        for descriptor in reversed(fds):
            os.close(descriptor)
    if not data or len(data) > MAX_MANIFEST_BYTES:
        raise Unverified("manifest is empty or oversized")
    return data


def manifest(data):
    try:
        value = json.loads(data, object_pairs_hook=unique_fields)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Unverified("invalid manifest") from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "frozen_at", "cases"} or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise Unverified("manifest fields or version are invalid")
    frozen = value["frozen_at"]
    if not isinstance(frozen, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", frozen):
        raise Unverified("manifest freeze time is invalid")
    try:
        at = datetime.fromisoformat(frozen.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Unverified("manifest freeze time is impossible") from exc
    if at > datetime.now(timezone.utc):
        raise Unverified("manifest freeze time is in the future")
    cases = value["cases"]
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise Unverified("manifest cohort is empty or oversized")
    labelled = {}
    for row in cases:
        if not isinstance(row, dict) or set(row) != {"case_id", "maintainer_action", "independent_label"}:
            raise Unverified("manifest case fields are invalid")
        cid = row["case_id"]
        if not isinstance(cid, str) or not ID.fullmatch(cid) or cid in labelled:
            raise Unverified("manifest case ID is invalid or duplicated")
        if row["maintainer_action"] is not None and (not isinstance(row["maintainer_action"], str) or row["maintainer_action"] not in ACTIONS):
            raise Unverified("manifest maintainer label is invalid")
        if type(row["independent_label"]) is not bool:
            raise Unverified("manifest independence flag is invalid")
        labelled[cid] = row
    return labelled


def validate(data, labelled):
    try:
        value = json.loads(data, object_pairs_hook=unique_fields)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Unverified("invalid replay input") from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "cases"} or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise Unverified("replay schema is invalid")
    cases = value["cases"]
    if not isinstance(cases, list) or len(cases) > MAX_CASES:
        raise Unverified("replay rows exceed limit")
    seen = set()
    for row in cases:
        if not isinstance(row, dict) or set(row) != {"case_id", "planner_action", "planner_verdict"}:
            raise Unverified("case fields are invalid")
        cid = row["case_id"]
        if not isinstance(cid, str) or cid not in labelled or cid in seen:
            raise Unverified("case identity is outside cohort or duplicated")
        seen.add(cid)
        if row["planner_action"] is not None and (not isinstance(row["planner_action"], str) or row["planner_action"] not in ACTIONS | WRITES | {"PASS"}):
            raise Unverified("planner action is not in the bounded vocabulary")
        if row["planner_verdict"] is not None and (not isinstance(row["planner_verdict"], str) or row["planner_verdict"] not in {"UNVERIFIED", "PASS"}):
            raise Unverified("planner verdict is invalid")
    return [{**row, **labelled[row["case_id"]]} for row in cases]


def evaluate(labelled, cases):
    labelled_rows = [row for row in cases if row["independent_label"] and row["maintainer_action"] in ACTIONS]
    comparable = [row for row in labelled_rows if row["planner_action"] in ACTIONS]
    verdict_measured = [row for row in comparable if row["planner_verdict"] == "UNVERIFIED"]
    unsafe = [row for row in cases if row["planner_action"] in WRITES | {"PASS"} or row["planner_verdict"] == "PASS"]
    unlabelled = [row for row in cases if not row["independent_label"] or row["maintainer_action"] not in ACTIONS]
    absent = len(labelled) - len(cases)
    agreement = sum(row["planner_action"] == row["maintainer_action"] for row in comparable)
    # Five comparable cases can still contain a unique action pair; marginal
    # totals can reconstruct suppressed cells. Do not emit a detailed matrix
    # before a separate privacy review establishes a safe release contract.
    return {
        "schema_version": 1, "mode": "SHADOW_ONLY", "coverage": "SUPPLIED_CASES_ONLY",
        "rollout_status": "NOT_EVALUATED", "execution_performed": False,
        "expected_count": len(labelled), "received_count": len(cases), "missing_count": absent,
        "caller_asserted_independent_label_count": len(labelled_rows), "unlabelled_count": len(unlabelled),
        "comparable_count": len(comparable), "verdict_measured_count": len(verdict_measured),
        "missing_verdict_count": len(comparable) - len(verdict_measured), "agreement_count": agreement,
        "unsafe_recommendation_count": len(unsafe),
        "confusion_coverage": "SUPPRESSED_UNVERIFIED_PRIVACY",
        "confusion_counts": None,
        "limitation": "compares caller-supplied current inputs; frozen_at does not attest label/result time; label independence unverified; no rollout permission or PASS",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    try:
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        if not data or len(data) > MAX_BYTES:
            raise Unverified("replay is absent or exceeds byte limit")
        labelled = manifest(private_manifest(args.manifest))
        cases = validate(data, labelled)
        report = evaluate(labelled, cases)
    except (Unverified, OSError, ValueError, UnicodeError, RecursionError, TypeError) as exc:
        print(f"exception replay: UNVERIFIED — {exc if isinstance(exc, Unverified) else 'invalid replay'}", file=sys.stderr)
        return 3
    print(json.dumps(report, sort_keys=True))
    return 0 if (report["missing_count"] == 0 and report["unlabelled_count"] == 0 and
                 report["unsafe_recommendation_count"] == 0 and
                 report["comparable_count"] == report["expected_count"] and
                 report["verdict_measured_count"] == report["expected_count"]) else 3


if __name__ == "__main__":
    sys.exit(main())
