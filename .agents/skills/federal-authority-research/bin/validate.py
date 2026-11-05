"""Read-only bundle metadata validation; never certification of legal truth."""

import argparse
import datetime as dt
import json
import os
import re
import stat
import sys
from pathlib import Path
from urllib.parse import urlsplit

LIMIT = 1_000_000
STATUSES = {"verified", "unverified", "superseded"}
KINDS = {"legal", "eo", "policy", "owner_style", "heuristic"}
SOURCE_FIELDS = {
    "id",
    "uri",
    "publisher",
    "locator",
    "quote",
    "artifact_sha256",
    "version",
    "retrieved_at",
    "reviewed_at",
    "review_ref",
    "effective_from",
    "effective_until",
    "review_due",
    "status",
}
CLAIM_FIELDS = {
    "id",
    "source_ids",
    "rule_id",
    "authority_kind",
    "applicability",
    "exceptions",
    "status",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value, label, empty=False):
    require(isinstance(value, str), f"{label}: expected string")
    require("\x00" not in value, f"{label}: NUL forbidden")
    require(empty or bool(value.strip()), f"{label}: empty string")
    return value


def day(value):
    require(
        isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value),
        "date: expected YYYY-MM-DD",
    )
    return dt.date.fromisoformat(value)


def timestamp(value):
    require(
        isinstance(value, str)
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value),
        "timestamp: expected UTC YYYY-MM-DDTHH:MM:SSZ",
    )
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").date()


def fields(record, required, optional=frozenset()):
    require(isinstance(record, dict), "record: expected object")
    require(
        required <= record.keys() <= required | optional,
        "record: missing or unknown fields",
    )


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError(f"non-JSON constant: {value}")


def read_bundle(path):
    # Refuse symlink components as well as final symlinks. The sandbox must
    # prevent concurrent ancestor replacement; this is not host containment.
    path = Path(os.path.abspath(path))
    for component in (path, *path.parents):
        require(not component.is_symlink(), "input symlink forbidden")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        require(
            stat.S_ISREG(os.fstat(stream.fileno()).st_mode),
            "input must be a regular file",
        )
        data = stream.read(LIMIT + 1)
    require(len(data) <= LIMIT, "input exceeds 1000000 bytes")
    require(b"\x00" not in data, "input NUL forbidden")
    return json.loads(
        data.decode("utf-8"),
        object_pairs_hook=pairs,
        parse_constant=invalid_constant,
    )


def validate(bundle, as_of):
    fields(bundle, {"schema_version", "active_claim_ids", "sources", "claims"})
    require(
        type(bundle["schema_version"]) is int and bundle["schema_version"] == 1,
        "schema_version: expected integer 1",
    )
    require(
        isinstance(bundle["sources"], list) and bundle["sources"],
        "sources: expected nonempty array",
    )
    require(
        isinstance(bundle["claims"], list) and bundle["claims"],
        "claims: expected nonempty array",
    )
    sources = {}
    periods = {}
    claims = {}
    ids = set()
    reasons = []
    for source in bundle["sources"]:
        fields(source, SOURCE_FIELDS, {"superseded_by", "published_on"})
        sid = text(source["id"], "source id")
        require(sid not in ids, "duplicate id")
        ids.add(sid)
        sources[sid] = source
        for key in ("uri", "publisher", "locator"):
            text(source[key], key)
        uri = urlsplit(source["uri"])
        require(
            uri.scheme in {"https", "http"}
            and bool(uri.hostname)
            and not uri.username
            and not uri.password,
            "uri: expected HTTP(S) publisher URI",
        )
        for key in ("quote", "artifact_sha256", "version"):
            text(source[key], key, empty=True)
        digest = source["artifact_sha256"]
        require(
            digest == "" or re.fullmatch(r"[0-9a-f]{64}", digest),
            "artifact_sha256: expected lowercase SHA-256 or empty",
        )
        status = text(source["status"], "status")
        require(status in STATUSES, "invalid source status")
        retrieved = timestamp(source["retrieved_at"])
        reviewed = (
            None if source["reviewed_at"] is None else timestamp(source["reviewed_at"])
        )
        text(source["review_ref"], "review_ref", empty=True)
        if source.get("published_on") is not None:
            day(source["published_on"])
        start = (
            None if source["effective_from"] is None else day(source["effective_from"])
        )
        end = (
            None
            if source["effective_until"] is None
            else day(source["effective_until"])
        )
        due = day(source["review_due"])
        periods[sid] = (start, end, due)
        require(retrieved <= as_of, "retrieval after inclusive as-of cutoff")
        require(
            start is None or end is None or start <= end,
            "effective_until before effective_from",
        )
        require(due >= retrieved, "review_due before retrieval date")
        if reviewed is not None:
            require(
                retrieved <= reviewed <= as_of,
                "review outside retrieval/cutoff interval",
            )
            require(due >= reviewed, "review_due before review date")
        if "superseded_by" in source:
            text(source["superseded_by"], "superseded_by")
            require(
                status == "superseded", "supersession link requires superseded status"
            )
        if status == "verified":
            require(
                reviewed is not None and source["review_ref"].strip(),
                "verified source requires reviewed_at and review_ref",
            )
            require(
                all(
                    source[key].strip()
                    for key in ("quote", "artifact_sha256", "version")
                ),
                "verified source requires quote, artifact digest, version",
            )
    finished = set()
    for sid in sources:
        seen = set()
        current = sid
        while current is not None and current not in finished:
            require(current in sources, "dangling supersession link")
            require(current not in seen, "supersession cycle")
            seen.add(current)
            current = sources[current].get("superseded_by")
        finished.update(seen)
    for claim in bundle["claims"]:
        fields(claim, CLAIM_FIELDS)
        cid = text(claim["id"], "claim id")
        require(cid not in ids, "duplicate id")
        ids.add(cid)
        claims[cid] = claim
        for key in ("rule_id", "applicability", "exceptions"):
            text(claim[key], key)
        require(
            text(claim["authority_kind"], "authority_kind") in KINDS,
            "invalid authority_kind",
        )
        status = text(claim["status"], "status")
        require(status in STATUSES, "invalid claim status")
        refs = claim["source_ids"]
        require(isinstance(refs, list) and refs, "source_ids: expected nonempty array")
        for ref in refs:
            text(ref, "source reference")
        require(len(set(refs)) == len(refs), "duplicate source reference")
        require(all(ref in sources for ref in refs), "dangling source reference")
    active = bundle["active_claim_ids"]
    require(
        isinstance(active, list) and active, "active_claim_ids: nonempty array required"
    )
    for cid in active:
        text(cid, "active claim id")
    require(len(set(active)) == len(active), "duplicate active claim id")
    require(all(cid in claims for cid in active), "unknown active claim id")
    selected_sources = set()
    for cid in active:
        claim = claims[cid]
        if claim["status"] != "verified":
            reasons.append({"kind": "claim", "id": cid, "code": claim["status"]})
        selected_sources.update(claim["source_ids"])
    for sid, source in sources.items():
        if sid not in selected_sources:
            continue
        start, end, due = periods[sid]
        codes = []
        if source["status"] != "verified":
            codes.append(source["status"])
        if start is None:
            codes.append("unknown_effective_date")
        elif start > as_of:
            codes.append("not_yet_effective")
        if end is not None and end < as_of:
            codes.append("expired")
        if due < as_of:
            codes.append("review_overdue")
        reasons.extend({"kind": "source", "id": sid, "code": code} for code in codes)
    return reasons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle")
    parser.add_argument(
        "--as-of",
        required=True,
        metavar="YYYYMMDD",
        help="inclusive UTC calendar-day cutoff (explicit; no clock default)",
    )
    # Usage errors use the same malformed-input exit contract.
    try:
        args = parser.parse_args()
    except SystemExit as exc:
        return 0 if exc.code == 0 else 4
    try:
        require(re.fullmatch(r"\d{8}", args.as_of), "as-of: expected YYYYMMDD")
        as_of = day(f"{args.as_of[:4]}-{args.as_of[4:6]}-{args.as_of[6:]}")
        reasons = validate(read_bundle(args.bundle), as_of)
    except (ValueError, OSError, UnicodeError, RecursionError) as exc:
        print(json.dumps({"verdict": "invalid", "error": str(exc)}))
        return 4
    print(
        json.dumps(
            {
                "verdict": "unverified" if reasons else "current",
                "scope": "structural/current-review metadata only; NOT legal truth",
                "as_of": as_of.isoformat(),
                "reasons": reasons,
            }
        )
    )
    return 3 if reasons else 0


if __name__ == "__main__":
    sys.exit(main())
