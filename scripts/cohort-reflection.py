#!/usr/bin/env python3
"""Read-only four-week reflection on sanitized, host-local case events."""

import sys

if not sys.flags.isolated or not sys.dont_write_bytecode:
    print("reflection: UNVERIFIED — run with python3 -I -B", file=sys.stderr)
    sys.exit(3)

import argparse
import contextlib
import hashlib
import hmac
import json
import os
import re
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_BYTES = 2_000_000
MAX_EVENTS = 2000
MAX_SOURCES = 20
MAX_REQUESTS = 2000
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
TYPES = {"intake", "transition", "review", "rework", "handoff", "outcome", "eligibility_correction"}
STATES = {"open", "blocked", "cancelled", "abandoned", "ready_for_human_review"}
ELIGIBILITY = {"eligible", "excluded", "unknown"}
CORRECTION_REASONS = {"duplicate_review", "spam_review", "external_pr_review", "eligibility_review", "clerical_error"}
CASE_TYPES = {"implementation", "review", "security", "documentation", "other"}
CHECKS = {"passing", "failing", "unavailable", "unknown", "not_applicable"}
SHARED = {"schema_version", "event_id", "case_id", "event_type", "occurred_at", "recorded_at"}
FIELDS = {
    "intake": {"case_type", "eligibility"},
    "transition": {"state"},
    "review": {"head_sha", "independent"},
    "rework": {"review_event_id", "changed_sha", "substantive"},
    "handoff": {"head_sha", "review_event_id", "checks"},
    "outcome": {"head_sha", "handoff_event_id", "repository_event_id"},
    "eligibility_correction": {"intake_event_id", "replacement", "reason_code"},
}


class Unverified(Exception):
    pass


def timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise Unverified("event timestamp must be UTC with Z suffix")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Unverified("event timestamp is malformed") from exc
    return parsed.astimezone(timezone.utc)


def unique_fields(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise Unverified("event has duplicate JSON fields")
        result[key] = value
    return result


def pseudonym(case_id: str, key: bytes) -> str:
    # A keyed local pseudonym resists trivial enumeration of issue-like IDs.
    # The key stays in a separate private file; the report cannot be used to
    # recover case identifiers without it. Never echo caller-supplied IDs.
    return "case-" + hmac.new(key, case_id.encode(), hashlib.sha256).hexdigest()[:24]


def private_file(path: Path) -> bytes:
    """Bounded no-follow read through a private directory, never executing data."""
    if not path.is_absolute():
        raise Unverified("event ledger path must be absolute")
    if path.name in ("", ".", ".."):
        raise Unverified("event ledger filename is invalid")
    # macOS has a platform /var -> /private/var link. Normalize ONLY that
    # known prefix; any other ancestor symlink is an unsafe redirect and must
    # be refused by the descriptor-relative O_NOFOLLOW walk.
    if sys.platform == "darwin" and path.parts[:2] == ("/", "var"):
        path = Path("/private/var", *path.parts[2:])
    with contextlib.ExitStack() as stack:
        fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, fd)
        for component in path.parent.parts[1:]:
            if component in (".", ".."):
                raise Unverified("ledger path contains a relative component")
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            stack.callback(os.close, next_fd)
            fd = next_fd
        directory = os.fstat(fd)
        if directory.st_uid != os.getuid() or directory.st_mode & 0o077:
            raise Unverified("event directory must be current-user private")
        file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            info = os.fstat(file_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise Unverified("event file must be current-user private and regular")
            if info.st_size > MAX_BYTES:
                raise Unverified("event file exceeds byte limit")
            with os.fdopen(file_fd, "rb") as handle:
                file_fd = -1
                data = handle.read(MAX_BYTES + 1)
        finally:
            if file_fd >= 0:
                os.close(file_fd)
        if len(data) > MAX_BYTES:
            raise Unverified("event file grew past byte limit during read")
        return data


def events_from(data: bytes, as_of: datetime) -> list[dict]:
    if not data or not data.endswith(b"\n"):
        raise Unverified("event ledger is empty or has an incomplete final line")
    lines = data.splitlines()
    if len(lines) > MAX_EVENTS:
        raise Unverified("event ledger exceeds event limit")
    events: list[dict] = []
    seen: dict[str, dict] = {}
    intake: dict[str, datetime] = {}
    prior_recorded: datetime | None = None
    corrected: set[str] = set()
    for line in lines:
        try:
            event = json.loads(line, object_pairs_hook=unique_fields)
        except Unverified:
            raise
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise Unverified("event ledger has a malformed line") from exc
        if not isinstance(event, dict) or not isinstance(event.get("event_type"), str) or event["event_type"] not in TYPES:
            raise Unverified("event type is invalid")
        kind = event["event_type"]
        if set(event) != SHARED | FIELDS[kind] or type(event.get("schema_version")) is not int or event["schema_version"] != 1:
            raise Unverified("event fields or schema version are invalid")
        for field in ("case_id", "event_id"):
            if not isinstance(event[field], str) or not ID.fullmatch(event[field]):
                raise Unverified("event identifier is invalid")
        if event["event_id"] in seen:
            raise Unverified("duplicate event identifier")
        occurred = timestamp(event["occurred_at"])
        recorded = timestamp(event["recorded_at"])
        if occurred > recorded:
            raise Unverified("event timestamp ordering is inconsistent")
        if prior_recorded is not None and recorded < prior_recorded:
            raise Unverified("append order disagrees with recorded time")
        prior_recorded = recorded
        if kind == "intake":
            if (event["case_id"] in intake or not isinstance(event["case_type"], str) or
                    event["case_type"] not in CASE_TYPES or not isinstance(event["eligibility"], str) or
                    event["eligibility"] not in ELIGIBILITY):
                raise Unverified("duplicate or invalid intake")
            intake[event["case_id"]] = occurred
        elif event["case_id"] not in intake:
            raise Unverified("event refers to a case without intake")
        elif occurred < intake[event["case_id"]]:
            raise Unverified("event predates case intake")
        elif kind == "transition" and (not isinstance(event["state"], str) or event["state"] not in STATES):
            raise Unverified("transition state is invalid")
        elif kind in {"review", "handoff", "outcome"} and (not isinstance(event["head_sha"], str) or not SHA.fullmatch(event["head_sha"])):
            raise Unverified("head SHA is invalid")
        elif kind == "review" and (not isinstance(event["independent"], str) or event["independent"] not in {"yes", "no", "unknown"}):
            raise Unverified("review independence is invalid")
        elif kind == "eligibility_correction":
            reference = event["intake_event_id"]
            target = seen.get(reference) if isinstance(reference, str) else None
            if (target is None or target["event_type"] != "intake" or target["case_id"] != event["case_id"] or
                    event["case_id"] in corrected or occurred < timestamp(target["recorded_at"]) or
                    not isinstance(event["replacement"], str) or event["replacement"] not in ELIGIBILITY or
                    event["replacement"] == target["eligibility"] or
                    not isinstance(event["reason_code"], str) or event["reason_code"] not in CORRECTION_REASONS):
                raise Unverified("eligibility correction is invalid, duplicate or cross-case")
            corrected.add(event["case_id"])
        elif kind in {"handoff", "rework", "outcome"}:
            ref_field = "handoff_event_id" if kind == "outcome" else "review_event_id"
            referenced = seen.get(event[ref_field])
            ref_kind = "handoff" if kind == "outcome" else "review"
            if referenced is None or referenced["event_type"] != ref_kind or referenced["case_id"] != event["case_id"]:
                raise Unverified("event reference is missing, cross-case or wrong type")
            if occurred < timestamp(referenced["occurred_at"]):
                raise Unverified("event precedes the evidence it references")
            if kind == "handoff" and (not isinstance(event["checks"], str) or event["checks"] not in CHECKS or
                                       event["head_sha"] != referenced["head_sha"]):
                raise Unverified("handoff checks or reviewed head invalid")
            if kind == "rework" and (not isinstance(event["substantive"], str) or event["substantive"] not in {"yes", "no", "unknown"} or
                                     not isinstance(event["changed_sha"], str) or not SHA.fullmatch(event["changed_sha"]) or
                                     event["changed_sha"] == referenced["head_sha"]):
                raise Unverified("rework disposition or changed head invalid")
            if kind == "outcome" and (event["head_sha"] != referenced["head_sha"] or
                                      not isinstance(event["repository_event_id"], str) or
                                      not ID.fullmatch(event["repository_event_id"])):
                raise Unverified("outcome head or evidence reference invalid")
        seen[event["event_id"]] = event
        events.append(event)
    return events


def reflect(events: list[dict], as_of: datetime, key: bytes) -> dict:
    try:
        start = as_of - timedelta(days=28)
    except OverflowError as exc:
        raise Unverified("snapshot cutoff is outside the supported range") from exc
    case_events: dict[str, list[dict]] = {}
    for event in events:
        # Validate the whole append-only ledger first; later recorded events
        # are normal when reproducing an earlier snapshot. The reporting view
        # uses recorded_at as its cutoff, not occurrence alone.
        if timestamp(event["recorded_at"]) > as_of:
            continue
        case_events.setdefault(event["case_id"], []).append(event)
    cohort = {
        case_id: rows for case_id, rows in case_events.items()
        if start <= timestamp(rows[0]["occurred_at"]) < as_of
    }
    effective = {cid: next((row["replacement"] for row in reversed(rows)
                            if row["event_type"] == "eligibility_correction"), rows[0]["eligibility"])
                 for cid, rows in case_events.items()}
    # Keep the historical intake cohort frozen at the ORIGINAL classification.
    # A later correction changes the operational queue, not the denominator
    # that an earlier intake decision was measured against.
    eligible = sorted(cid for cid, rows in cohort.items() if rows[0]["eligibility"] == "eligible")
    excluded = sorted(cid for cid, rows in cohort.items() if rows[0]["eligibility"] == "excluded")
    unknown = sorted(cid for cid, rows in cohort.items() if rows[0]["eligibility"] == "unknown")
    # This is a PRIVATE report bucket, not a GitHub notification. It deliberately
    # names only keyed case labels, the case type, age and a review-due signal.
    # No model, issue text or automatic eligibility decision is involved.
    disposition_age_days = 7
    # The operational queue includes all still-unknown recorded intakes,
    # including cases older than the 28-day PERFORMANCE cohort. Otherwise the
    # oldest unresolved case disappears merely because time passed.
    queued = []
    for cid, rows in case_events.items():
        if effective[cid] != "unknown":
            continue
        elapsed = as_of - timestamp(rows[0]["occurred_at"])
        if elapsed.total_seconds() < 0:
            raise Unverified("unknown case intake is after the report cutoff")
        queued.append((elapsed.total_seconds(), {
            "case_label": pseudonym(cid, key), "case_type": rows[0]["case_type"],
            # Whole days avoid displaying 7.00 while the seven-day flag is false.
            "age_whole_days": elapsed.days,
            "review_due": elapsed >= timedelta(days=disposition_age_days),
        }))
    disposition_queue = [row for _, row in sorted(queued, key=lambda pair: (-pair[0], pair[1]["case_label"]))]
    unfinished: list[tuple[str, str, float]] = []
    documented_outcomes = []
    reworked = []
    reviewed = []
    for case_id in eligible:
        rows = cohort[case_id]
        kinds = {row["event_id"]: row for row in rows}
        transitions = ((timestamp(row["occurred_at"]), index, row["state"])
                       for index, row in enumerate(rows) if row["event_type"] == "transition")
        latest = max(transitions, default=(None, -1, "open"))[2]
        if any(row["event_type"] == "outcome" for row in rows):
            documented_outcomes.append(case_id)
        # Recorded outcomes remain unfinished for VERIFIED throughput until a
        # separate repository/head/check attestation has been established.
        unfinished.append((case_id, latest,
                           round((as_of - timestamp(rows[0]["occurred_at"])).total_seconds() / 86400, 2)))
        if any(row["event_type"] == "review" and row["independent"] == "yes" for row in rows):
            reviewed.append(case_id)
        if any(row["event_type"] == "rework" and row["substantive"] == "yes" and
               kinds[row["review_event_id"]]["independent"] == "yes" for row in rows):
            reworked.append(case_id)
    label = {case_id: pseudonym(case_id, key) for case_id in case_events}
    if len(set(label.values())) != len(label):
        raise Unverified("report case labels collide")
    original_counts = {state: sum(rows[0]["eligibility"] == state for rows in cohort.values())
                       for state in ("eligible", "excluded", "unknown")}
    corrections = {
        cid: next((event for event in rows if event["event_type"] == "eligibility_correction"), None)
        for cid, rows in cohort.items()
    }
    corrected_by_original = {
        state: sorted(label[cid] for cid, row in corrections.items()
                      if row is not None and cohort[cid][0]["eligibility"] == state)
        for state in original_counts
    }
    # Use writer-set recorded_at for both ends. occurred_at may be backdated;
    # it is not evidence of when a maintainer actually made a disposition.
    resolved_unknown = sorted((
        {"case_label": label[cid], "recorded_delay_hours": round(
            (timestamp(row["recorded_at"]) - timestamp(cohort[cid][0]["recorded_at"])).total_seconds() / 3600, 2)}
        for cid, row in corrections.items() if row is not None and
        cohort[cid][0]["eligibility"] == "unknown" and row["replacement"] != "unknown"
    ), key=lambda entry: entry["case_label"])
    pending_unknown = sorted(label[cid] for cid, rows in cohort.items()
                             if rows[0]["eligibility"] == "unknown" and effective[cid] == "unknown")
    return {
        "as_of": as_of.isoformat(), "window_days": 28,
        "coverage": "recorded_eligible_cohort" if eligible else "no_eligible_evidence",
        "out_of_window_recorded_case_count": len(case_events) - len(cohort),
        "intake_completeness": "UNMEASURED: independent request inventory absent",
        "eligible_ids": [label[cid] for cid in eligible], "excluded_ids": [label[cid] for cid in excluded],
        "unknown_eligibility_ids": [label[cid] for cid in unknown],
        "eligibility_correction_count": sum(row is not None for row in corrections.values()),
        "intake_cohort_count": len(cohort),
        "original_eligibility_counts": original_counts,
        "correction_quality": {
            "coverage": "recorded_events_only" if cohort else "no_evidence",
            "denominator_first_intakes": len(cohort),
            "corrected_case_count": sum(row is not None for row in corrections.values()),
            "corrected_case_labels_by_original_eligibility": corrected_by_original,
            "original_unknown_count": original_counts["unknown"],
            "unknown_resolved_count": len(resolved_unknown),
            "unknown_recorded_disposition_delays": resolved_unknown,
            "unknown_pending_case_labels": pending_unknown,
            "scope": "recorded decisions within first-intake cohort; not independently verified outcomes",
        },
        "corrected_case_labels": sorted(label[cid] for cid in cohort if any(
            row["event_type"] == "eligibility_correction" for row in cohort[cid])),
        "effective_eligibility_labels": {
            status: sorted(label[cid] for cid in cohort if effective[cid] == status)
            for status in ("eligible", "excluded", "unknown")
        },
        "needs_maintainer_disposition": disposition_queue,
        "disposition_policy": "manual review; review_due after 7 days; no automatic exclusion or remote alert",
        "documented_outcome_ids_unverified": sorted(label[cid] for cid in documented_outcomes),
        "verified_completion_ids": [], "verified_completion_coverage": "UNVERIFIED: no live GitHub/head/check attestation",
        "unfinished_for_verified_throughput": sorted(
            ({"case_id": label[cid], "state": state, "age_days": age} for cid, state, age in unfinished),
            key=lambda row: (-row["age_days"], row["case_id"]),
        ),
        "independent_review_recorded_ids": sorted(label[cid] for cid in reviewed),
        "post_review_substantive_rework_ids": sorted(label[cid] for cid in reworked),
        "recommendations": [
            "Reconcile the intake cohort against an independently defined request inventory.",
            "Verify outcome head, checks and repository event before counting any completion.",
        ][:3],
    }


def reconcile_inventory(data: bytes, events: list[dict], as_of: datetime, key: bytes, required: set[str]) -> dict:
    """Conditional, source-attested intake coverage; never all-real-world coverage."""
    try:
        inventory = json.loads(data, object_pairs_hook=unique_fields)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Unverified("request inventory is malformed") from exc
    if not isinstance(inventory, dict) or set(inventory) != {"schema_version", "as_of", "window_start", "sources"}:
        raise Unverified("request inventory fields are invalid")
    if type(inventory["schema_version"]) is not int or inventory["schema_version"] != 1:
        raise Unverified("request inventory schema is unsupported")
    start = as_of - timedelta(days=28)
    if timestamp(inventory["as_of"]) != as_of or timestamp(inventory["window_start"]) != start:
        raise Unverified("request inventory window does not match report cutoff")
    sources = inventory["sources"]
    if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
        raise Unverified("request inventory source count is invalid")
    observed: set[str] = set()
    eligible: set[str] = set()
    received_at: dict[str, datetime] = {}
    excluded: set[str] = set()
    unknown: set[str] = set()
    source_names: set[str] = set()
    incomplete: set[str] = set()
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"source_id", "enumerated_at", "coverage", "requests"}:
            raise Unverified("request inventory source fields are invalid")
        name = source["source_id"]
        if not isinstance(name, str) or not ID.fullmatch(name) or name in source_names:
            raise Unverified("request inventory source identifier is invalid or duplicated")
        source_names.add(name)
        enumerated = timestamp(source["enumerated_at"])
        if enumerated < as_of or enumerated > datetime.now(timezone.utc):
            raise Unverified("request inventory enumeration time is inconsistent")
        if not isinstance(source["coverage"], str) or source["coverage"] not in {"complete", "partial"}:
            raise Unverified("request inventory source coverage is invalid")
        if source["coverage"] == "partial":
            incomplete.add(name)
        requests = source["requests"]
        if not isinstance(requests, list) or len(observed) + len(requests) > MAX_REQUESTS:
            raise Unverified("request inventory exceeds request limit")
        for request in requests:
            if not isinstance(request, dict) or set(request) != {"request_id", "received_at", "eligibility"}:
                raise Unverified("request inventory entry fields are invalid")
            request_id = request["request_id"]
            if not isinstance(request_id, str) or not ID.fullmatch(request_id) or request_id in observed:
                raise Unverified("request inventory identifier is invalid or duplicated")
            observed.add(request_id)
            received = timestamp(request["received_at"])
            received_at[request_id] = received
            if not start <= received < as_of or not isinstance(request["eligibility"], str) or request["eligibility"] not in ELIGIBILITY:
                raise Unverified("request inventory entry is outside window or has invalid eligibility")
            if request["eligibility"] == "eligible":
                eligible.add(request_id)
            elif request["eligibility"] == "excluded":
                excluded.add(request_id)
            elif request["eligibility"] == "unknown":
                unknown.add(request_id)
    if not required or not source_names <= required:
        raise Unverified("required source set is missing or inventory has unapproved sources")
    incomplete |= required - source_names
    cases: dict[str, list[dict]] = {}
    for event in events:
        if timestamp(event["recorded_at"]) <= as_of:
            cases.setdefault(event["case_id"], []).append(event)
    recorded = {cid: rows for cid, rows in cases.items() if start <= timestamp(rows[0]["occurred_at"]) < as_of}
    missing = eligible - recorded.keys()
    extra = recorded.keys() - observed
    conflicting = {cid for cid in observed & recorded.keys() if
                   timestamp(recorded[cid][0]["occurred_at"]) < received_at[cid] or
                   (cid in eligible and next((row["replacement"] for row in reversed(recorded[cid])
                                              if row["event_type"] == "eligibility_correction"), recorded[cid][0]["eligibility"]) != "eligible") or
                   (cid in excluded and next((row["replacement"] for row in reversed(recorded[cid])
                                              if row["event_type"] == "eligibility_correction"), recorded[cid][0]["eligibility"]) != "excluded") or
                   (cid in unknown and next((row["replacement"] for row in reversed(recorded[cid])
                                             if row["event_type"] == "eligibility_correction"), recorded[cid][0]["eligibility"]) != "unknown")}
    matched = {cid for cid in eligible if cid in recorded and cid not in conflicting}
    # The inventory has no eligibility-decision timestamp. It cannot tell
    # whether its classification applied BEFORE or AFTER a correction, even
    # when the label happens to match. Refuse a positive coverage status until
    # an independently evidenced source-decision-time contract exists.
    corrected = {cid for cid, rows in recorded.items() if any(
        row["event_type"] == "eligibility_correction" for row in rows)}
    matched -= corrected
    status = "operator_asserted_source_coverage" if eligible and not missing and not incomplete and not unknown and not extra and not conflicting and not corrected else "UNVERIFIED"
    return {
        "status": status,
        "scope": "eligible requests in declared, operator-provided enumerations only; not all real-world requests",
        "eligible_enumerated_count": len(eligible),
        "eligible_recorded_count": len(matched),
        "missing_eligible_labels": sorted(pseudonym(cid, key) for cid in missing),
        "unknown_eligibility_labels": sorted(pseudonym(cid, key) for cid in unknown),
        "ledger_only_labels": sorted(pseudonym(cid, key) for cid in extra),
        "conflicting_eligibility_labels": sorted(pseudonym(cid, key) for cid in conflicting),
        "uncorroborated_correction_labels": sorted(pseudonym(cid, key) for cid in corrected),
        "incomplete_source_labels": sorted(pseudonym(cid, key) for cid in incomplete),
        "inventory_identity_hmac": hmac.new(key, b"inventory-identity-v1\0" + data, hashlib.sha256).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True, help="absolute private file containing a random pseudonym key")
    parser.add_argument("--inventory", type=Path, help="private source-attested request inventory")
    parser.add_argument("--required-source", action="append", default=[], help="predeclared source ID; repeat for each expected source")
    parser.add_argument("--as-of", required=True, help="fixed UTC snapshot, e.g. 2026-10-22T00:00:00Z")
    args = parser.parse_args()
    try:
        as_of = timestamp(args.as_of)
        key = private_file(args.key_file)
        if len(key) < 32 or len(key) > 128:
            raise Unverified("pseudonym key must be 32-128 random bytes")
        data = private_file(args.ledger)
        events = events_from(data, as_of)
        report = reflect(events, as_of, key)
        if not args.inventory or not args.required_source:
            raise Unverified("intake coverage requires both --inventory and at least one --required-source")
        if args.inventory:
            if len(args.required_source) != len(set(args.required_source)):
                raise Unverified("required source list contains duplicates")
            report["intake_inventory"] = reconcile_inventory(
                private_file(args.inventory), events, as_of, key, set(args.required_source),
            )
            report["intake_completeness"] = (
                "CONDITIONAL: operator-asserted enumerations of declared sources only"
                if report["intake_inventory"]["status"] == "operator_asserted_source_coverage"
                else "UNVERIFIED: inventory missing requests, coverage, or consistent eligibility"
            )
        # `--as-of` alone is not an immutable snapshot: a later append with a
        # backdated recorded_at can revise it. Bind every report to the exact
        # bytes consumed so changed input cannot masquerade as the same run.
        report["ledger_identity_hmac"] = hmac.new(key, b"ledger-identity-v1\0" + data, hashlib.sha256).hexdigest()
    except (Unverified, OSError, ValueError, TypeError, RecursionError) as exc:
        print(f"reflection: UNVERIFIED — {exc if isinstance(exc, Unverified) else 'ledger unavailable'}", file=sys.stderr)
        return 3
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report["coverage"] == "recorded_eligible_cohort" and (
        report["intake_inventory"]["status"] == "operator_asserted_source_coverage"
    ) else 3


if __name__ == "__main__":
    sys.exit(main())
