#!/usr/bin/env python3
"""Offline validation of declared intake sources and captured page evidence."""

import sys

if not sys.flags.isolated or not sys.dont_write_bytecode:
    print("intake sources: UNVERIFIED — run with python3 -I -B", file=sys.stderr)
    sys.exit(3)

import argparse
import contextlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 65536
MAX_SOURCES = 20
MAX_PAGES = 100
MAX_REQUESTS = 2000
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
TYPES = {"github_issues", "pr_review_requests", "project_items", "direct_requests"}


class Unverified(Exception):
    pass


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Unverified("duplicate JSON field")
        result[key] = value
    return result


def utc(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
        raise Unverified("UTC timestamp is malformed")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Unverified("UTC timestamp is impossible") from exc


def private_data(path):
    if not path.is_absolute() or path.name in ("", ".", ".."):
        raise Unverified("input path must be absolute")
    if sys.platform == "darwin" and path.parts[:2] == ("/", "var"):
        path = Path("/private/var", *path.parts[2:])
    with contextlib.ExitStack() as stack:
        fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, fd)
        for part in path.parent.parts[1:]:
            if part in (".", ".."):
                raise Unverified("input path contains an unsafe component")
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            stack.callback(os.close, child)
            fd = child
        parent = os.fstat(fd)
        if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
            raise Unverified("input parent must be current-user private")
        file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            info = os.fstat(file_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > MAX_BYTES:
                raise Unverified("input must be a bounded private regular file")
            with os.fdopen(file_fd, "rb") as handle:
                file_fd = -1
                data = handle.read(MAX_BYTES + 1)
        finally:
            if file_fd >= 0:
                os.close(file_fd)
        if not data or len(data) > MAX_BYTES:
            raise Unverified("input is empty or too large")
        return data


def parse(data):
    try:
        value = json.loads(data, object_pairs_hook=unique_fields)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Unverified("input JSON is malformed") from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "window_start", "as_of", "sources"} or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise Unverified("source registry schema is invalid")
    start, end = utc(value["window_start"]), utc(value["as_of"])
    if start >= end or end > datetime.now(timezone.utc):
        raise Unverified("registry observation window is invalid")
    sources = value["sources"]
    if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
        raise Unverified("source count is missing or excessive")
    return value, start, end


def evaluate(value, start, end, required):
    observed = set()
    seen_requests = set()
    incomplete = set()
    total = 0
    for source in value["sources"]:
        if not isinstance(source, dict) or set(source) != {"source_id", "source_type", "captured_at", "pages", "coverage"}:
            raise Unverified("source fields are invalid")
        name = source["source_id"]
        if not isinstance(name, str) or not ID.fullmatch(name) or name in observed or name not in required:
            raise Unverified("source identifier is unapproved or duplicated")
        observed.add(name)
        kind = source["source_type"]
        if not isinstance(kind, str) or kind not in TYPES or kind != required[name]:
            raise Unverified("source type is invalid")
        captured = utc(source["captured_at"])
        if captured < end or captured > datetime.now(timezone.utc):
            raise Unverified("source capture time does not cover the cutoff")
        if not isinstance(source["coverage"], str) or source["coverage"] not in {"complete", "partial"}:
            raise Unverified("source coverage is invalid")
        pages = source["pages"]
        if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES:
            raise Unverified("source page count is missing or excessive")
        previous = None
        cursors = set()
        last = None
        for page in pages:
            if not isinstance(page, dict) or set(page) != {"cursor_in", "cursor_out", "has_next", "request_ids"}:
                raise Unverified("page fields are invalid")
            if type(page["has_next"]) is not bool or not isinstance(page["request_ids"], list):
                raise Unverified("page flags or requests are invalid")
            if page["cursor_in"] != previous:
                raise Unverified("page cursor chain is incomplete or repeated")
            out = page["cursor_out"]
            if out is not None and (not isinstance(out, str) or not ID.fullmatch(out)):
                raise Unverified("page cursor shape is invalid")
            if out is not None and out in cursors:
                raise Unverified("page cursor repeats an earlier output")
            if page["has_next"] and out is None:
                raise Unverified("page declares another page without new cursor")
            if out is not None:
                cursors.add(out)
            if not page["has_next"] and page is not pages[-1]:
                raise Unverified("page ended before supplied final page")
            for request in page["request_ids"]:
                if not isinstance(request, str) or not ID.fullmatch(request) or request in seen_requests:
                    raise Unverified("request identifier is invalid or duplicated")
                seen_requests.add(request)
                total += 1
                if total > MAX_REQUESTS:
                    raise Unverified("request count exceeds limit")
            previous = out
            last = page
        if last is None:
            raise Unverified("source has no final page")
        if source["coverage"] == "partial" or last["has_next"]:
            incomplete.add(name)
    incomplete |= required.keys() - observed
    return {"schema_version": 1, "mode": "OFFLINE_SOURCE_EVIDENCE", "coverage": "operator_asserted_supplied_chain_only",
            "source_count": len(required), "observed_source_count": len(observed),
            "observed_request_count": total, "incomplete_source_count": len(incomplete),
            "status": "UNVERIFIED" if incomplete else "SUPPLIED_CHAIN_COHERENT",
            "limitation": "cursor chains and complete flags are supplied by the operator; no live API or independent source attestation"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--required-source", action="append", default=[], help="predeclared ID:TYPE, separately supplied from captured registry")
    args = parser.parse_args()
    try:
        if not 1 <= len(args.required_source) <= MAX_SOURCES:
            raise Unverified("required source set is absent or excessive")
        required = {}
        for entry in args.required_source:
            parts = entry.split(":")
            if len(parts) != 2 or not ID.fullmatch(parts[0]) or parts[1] not in TYPES or parts[0] in required:
                raise Unverified("required source ID/type is invalid or duplicated")
            required[parts[0]] = parts[1]
        value, start, end = parse(private_data(args.registry))
        result = evaluate(value, start, end, required)
    except (Unverified, OSError, ValueError, TypeError, RecursionError) as exc:
        print(f"intake sources: UNVERIFIED — {exc if isinstance(exc, Unverified) else 'source data unavailable'}", file=sys.stderr)
        return 3
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "SUPPLIED_CHAIN_COHERENT" else 3


if __name__ == "__main__":
    sys.exit(main())
