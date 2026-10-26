#!/usr/bin/env python3
"""Classify a supplied PR snapshot; never attest or credit a completion."""

import sys

if not sys.flags.isolated or not sys.dont_write_bytecode:
    print("merge evidence: UNVERIFIED — run with python3 -I -B", file=sys.stderr)
    sys.exit(3)

import argparse
import json
import re
from datetime import datetime, timezone

MAX_INPUT = 16384
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA = re.compile(r"^[0-9a-f]{40}$")
STATES = {"OPEN", "CLOSED"}


class Unverified(Exception):
    pass


def unique_fields(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise Unverified("duplicate JSON field")
        result[key] = value
    return result


def parse_snapshot(data: bytes) -> dict:
    try:
        value = json.loads(data, object_pairs_hook=unique_fields)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Unverified("invalid supplied snapshot") from exc
    expected = {"schema_version", "repository", "number", "state", "merged_at", "head_sha", "merge_commit_sha"}
    if not isinstance(value, dict) or set(value) != expected or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise Unverified("snapshot fields or schema version invalid")
    if not isinstance(value["repository"], str) or not REPOSITORY.fullmatch(value["repository"]):
        raise Unverified("repository identity invalid")
    if type(value["number"]) is not int or not 1 <= value["number"] <= 2147483647:
        raise Unverified("PR number invalid")
    if not isinstance(value["state"], str) or value["state"] not in STATES:
        raise Unverified("PR state invalid")
    if not isinstance(value["head_sha"], str) or not SHA.fullmatch(value["head_sha"]):
        raise Unverified("PR head invalid")
    if value["merge_commit_sha"] is not None and (not isinstance(value["merge_commit_sha"], str) or not SHA.fullmatch(value["merge_commit_sha"])):
        raise Unverified("merge commit SHA invalid")
    merged_at = value["merged_at"]
    if merged_at is not None and (not isinstance(merged_at, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", merged_at)):
        raise Unverified("merge timestamp invalid")
    if merged_at is not None:
        try:
            instant = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise Unverified("merge timestamp has an impossible date or time") from exc
        if instant.tzinfo != timezone.utc:
            raise Unverified("merge timestamp must be UTC")
        if instant > datetime.now(timezone.utc):
            raise Unverified("merge timestamp is in the future")
    if value["state"] == "OPEN" and merged_at is not None:
        raise Unverified("open PR has a merge timestamp")
    if value["state"] == "OPEN" and value["merge_commit_sha"] is not None:
        raise Unverified("open PR has an ambiguous merge commit SHA")
    if value["state"] == "CLOSED" and merged_at is None and value["merge_commit_sha"] is not None:
        raise Unverified("closed PR has ambiguous merge evidence")
    if value["state"] == "CLOSED" and merged_at is not None and value["merge_commit_sha"] is None:
        raise Unverified("merged PR has no merge commit SHA")
    return value


def classify(value: dict, expected_repo: str, expected_number: int, expected_head: str) -> str:
    if value["repository"] != expected_repo or value["number"] != expected_number:
        raise Unverified("snapshot does not match requested repository and PR")
    if value["head_sha"] != expected_head:
        return "HEAD_MISMATCH_IN_SUPPLIED_SNAPSHOT"
    if value["state"] == "OPEN":
        return "NOT_MERGED_IN_SUPPLIED_SNAPSHOT"
    if value["merged_at"] is None:
        return "CLOSED_NOT_MERGED_IN_SUPPLIED_SNAPSHOT"
    # Squash and rebase merge commits differ from the head. Never equate them.
    return "MERGE_CLAIM_IN_SUPPLIED_SNAPSHOT"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--number", required=True, type=int)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    try:
        if not isinstance(args.repository, str) or not REPOSITORY.fullmatch(args.repository):
            raise Unverified("requested repository invalid")
        if not 1 <= args.number <= 2147483647 or not SHA.fullmatch(args.head):
            raise Unverified("requested PR number or head invalid")
        data = sys.stdin.buffer.read(MAX_INPUT + 1)
        if not data or len(data) > MAX_INPUT:
            raise Unverified("snapshot absent or exceeds byte limit")
        value = parse_snapshot(data)
        status = classify(value, args.repository, args.number, args.head)
    except (Unverified, OSError, TypeError, ValueError, RecursionError) as exc:
        message = str(exc) if isinstance(exc, Unverified) else "snapshot unavailable"
        print(f"merge evidence: UNVERIFIED — {message}", file=sys.stderr)
        return 3
    # Do not emit case IDs, PR text, the repository, raw snapshot, or an
    # unkeyed digest that could enable guessing private identifiers.
    print(json.dumps({
        "schema_version": 1,
        "classification": status,
        "provenance": "UNVERIFIED: caller-supplied snapshot, no GitHub corroboration or case binding",
        "delivery_credit": False,
        "policy_compliance": "UNMEASURED",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
