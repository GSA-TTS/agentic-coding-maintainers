#!/usr/bin/env python3
"""Offline shadow evaluation of supplied planner recommendations and labels."""

import sys

if not sys.flags.isolated or not sys.dont_write_bytecode:
    print("exception replay: UNVERIFIED — run with python3 -I -B", file=sys.stderr)
    sys.exit(3)

import argparse
import json
import re

MAX_BYTES = 65536
MAX_CASES = 500
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


def validate(data):
    try:
        value = json.loads(data, object_pairs_hook=unique_fields)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Unverified("invalid replay input") from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "expected_case_ids", "cases"} or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise Unverified("replay schema is invalid")
    expected, cases = value["expected_case_ids"], value["cases"]
    if not isinstance(expected, list) or not isinstance(cases, list) or not 1 <= len(expected) <= MAX_CASES or len(cases) > MAX_CASES:
        raise Unverified("replay cohort is absent or exceeds limit")
    if any(not isinstance(case, str) or not ID.fullmatch(case) for case in expected) or len(set(expected)) != len(expected):
        raise Unverified("cohort identifiers are invalid or duplicated")
    seen = set()
    for row in cases:
        if not isinstance(row, dict) or set(row) != {"case_id", "maintainer_action", "planner_action", "planner_verdict", "independent_label"}:
            raise Unverified("case fields are invalid")
        cid = row["case_id"]
        if not isinstance(cid, str) or cid not in expected or cid in seen:
            raise Unverified("case identity is outside cohort or duplicated")
        seen.add(cid)
        for field in ("maintainer_action", "planner_action"):
            if row[field] is not None and (not isinstance(row[field], str) or row[field] not in ACTIONS | WRITES | {"PASS"}):
                raise Unverified("action is not in the bounded vocabulary")
        if row["planner_verdict"] is not None and (not isinstance(row["planner_verdict"], str) or row["planner_verdict"] not in {"UNVERIFIED", "PASS"}):
            raise Unverified("planner verdict is invalid")
        if type(row["independent_label"]) is not bool:
            raise Unverified("label provenance is invalid")
    return expected, cases


def evaluate(expected, cases):
    labelled = [row for row in cases if row["independent_label"] and row["maintainer_action"] in ACTIONS]
    comparable = [row for row in labelled if row["planner_action"] in ACTIONS]
    verdict_measured = [row for row in comparable if row["planner_verdict"] == "UNVERIFIED"]
    unsafe = [row for row in cases if row["planner_action"] in WRITES | {"PASS"} or row["planner_verdict"] == "PASS"]
    unlabelled = [row for row in cases if not row["independent_label"] or row["maintainer_action"] not in ACTIONS]
    absent = len(expected) - len(cases)
    agreement = sum(row["planner_action"] == row["maintainer_action"] for row in comparable)
    matrix = {action: {candidate: 0 for candidate in sorted(ACTIONS)} for action in sorted(ACTIONS)}
    for row in comparable:
        matrix[row["maintainer_action"]][row["planner_action"]] += 1
    # Detailed cells disclose a label for tiny cohorts. Keep aggregate
    # counts and suppress the matrix until there are enough comparable cases
    # to avoid trivially singling out one maintainer classification.
    matrix_coverage = "SUPPRESSED_SMALL_COHORT" if len(comparable) < 5 else "DISPLAYED"
    return {
        "schema_version": 1, "mode": "SHADOW_ONLY", "coverage": "SUPPLIED_CASES_ONLY",
        "rollout_status": "NOT_EVALUATED", "execution_performed": False,
        "expected_count": len(expected), "received_count": len(cases), "missing_count": absent,
        "independently_labelled_count": len(labelled), "unlabelled_count": len(unlabelled),
        "comparable_count": len(comparable), "verdict_measured_count": len(verdict_measured),
        "missing_verdict_count": len(comparable) - len(verdict_measured), "agreement_count": agreement,
        "unsafe_recommendation_count": len(unsafe),
        "confusion_coverage": matrix_coverage,
        "confusion_counts": matrix if matrix_coverage == "DISPLAYED" else None,
        "limitation": "expected IDs, human labels, and independence flags are supplied, not corroborated; no rollout permission or PASS",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        if not data or len(data) > MAX_BYTES:
            raise Unverified("replay is absent or exceeds byte limit")
        expected, cases = validate(data)
        report = evaluate(expected, cases)
    except (Unverified, ValueError, UnicodeError, RecursionError, TypeError) as exc:
        print(f"exception replay: UNVERIFIED — {exc if isinstance(exc, Unverified) else 'invalid replay'}", file=sys.stderr)
        return 3
    print(json.dumps(report, sort_keys=True))
    return 0 if (report["missing_count"] == 0 and report["unlabelled_count"] == 0 and
                 report["unsafe_recommendation_count"] == 0 and
                 report["comparable_count"] == report["expected_count"] and
                 report["verdict_measured_count"] == report["expected_count"]) else 3


if __name__ == "__main__":
    sys.exit(main())
