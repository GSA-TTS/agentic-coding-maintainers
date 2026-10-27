#!/usr/bin/env python3
"""Offline two-pass Issues capture adapter; no GitHub requests or global coverage."""

import sys

if not sys.flags.isolated or not sys.dont_write_bytecode:
    print("issues adapter: UNVERIFIED — run with python3 -I -B", file=sys.stderr)
    sys.exit(3)

import argparse
import hashlib
import hmac
import json
import os
import re
import stat
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 65536
MAX_PAGES = 10
MAX_NODES = 2000
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


class Unverified(Exception):
    pass


def pairs_unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise Unverified("duplicate capture field")
        result[name] = value
    return result


def utc(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
        raise Unverified("capture timestamp invalid")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Unverified("capture timestamp impossible") from exc


def private_parent(path, *, create=False):
    """Open a private directory through no-follow descriptors."""
    if not path.is_absolute() or path.name in ("", ".", ".."):
        raise Unverified("private path must be absolute")
    if sys.platform == "darwin" and path.parts[:2] == ("/", "var"):
        path = Path("/private/var", *path.parts[2:])
    stack = ExitStack()
    try:
        fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, fd)
        for part in path.parent.parts[1:]:
            if part in (".", ".."):
                raise Unverified("private path contains relative component")
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            stack.callback(os.close, fd)
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Unverified("private parent must be current-user owned mode 0700")
        return path.name, fd, stack
    except Exception:
        stack.close()
        raise


def private_read(path, max_bytes):
    name, parent, stack = private_parent(path)
    with stack:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > max_bytes:
                raise Unverified("private input file unsafe or oversized")
            data = handle.read(max_bytes + 1)
    if not data or len(data) > max_bytes:
        raise Unverified("private input absent or oversized")
    return data


def private_create(path, data):
    name, parent, stack = private_parent(path)
    with stack:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(fd, "wb", buffering=0) as handle:
            if handle.write(data) != len(data):
                raise Unverified("private output partially written; inspect before retry")
            os.fsync(handle.fileno())


def capture(data, repository, start, end, key):
    try:
        value = json.loads(data, object_pairs_hook=pairs_unique)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Unverified("capture JSON invalid") from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "repository", "window_start", "as_of", "query_type", "passes"} or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise Unverified("capture schema invalid")
    if value["repository"] != repository or value["window_start"] != start or value["as_of"] != end or value["query_type"] != "graphql_issues_created_asc":
        raise Unverified("capture query scope disagrees with expected scope")
    passes = value["passes"]
    if not isinstance(passes, list) or len(passes) != 2:
        raise Unverified("exactly two captured passes required")
    canonical = []
    previous_capture = None
    for run in passes:
        if not isinstance(run, dict) or set(run) != {"captured_at", "pages"}:
            raise Unverified("pass metadata invalid")
        observed = utc(run["captured_at"])
        if not utc(end) <= observed <= datetime.now(timezone.utc):
            raise Unverified("pass timestamp does not cover cutoff")
        if previous_capture is not None and observed <= previous_capture:
            raise Unverified("pass capture times are not strictly increasing")
        previous_capture = observed
        pages = run["pages"]
        if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES:
            raise Unverified("pass pages missing or excessive")
        cursor, seen, issues_seen, nodes = None, set(), set(), 0
        previous_time = None
        result = []
        full_evidence = []
        for index, page in enumerate(pages):
            if not isinstance(page, dict) or set(page) != {"cursor_in", "cursor_out", "has_next", "issues"}:
                raise Unverified("page fields invalid")
            inside, outside = page["cursor_in"], page["cursor_out"]
            if inside != cursor or (inside is not None and (not isinstance(inside, str) or len(inside) > 256)):
                raise Unverified("page cursor input disagrees with chain")
            if type(page["has_next"]) is not bool or not isinstance(page["issues"], list):
                raise Unverified("page connection malformed")
            if page["has_next"]:
                if not isinstance(outside, str) or not 1 <= len(outside) <= 256 or outside in seen or index == len(pages) - 1:
                    raise Unverified("incomplete or cyclic page chain")
                try:
                    outside.encode("utf-8")
                except UnicodeError as exc:
                    raise Unverified("page cursor is not valid UTF-8") from exc
                seen.add(outside)
            elif index != len(pages) - 1 or outside is not None:
                raise Unverified("terminal page is contradictory")
            ids = []
            page_evidence = []
            for issue in page["issues"]:
                nodes += 1
                if nodes > MAX_NODES or not isinstance(issue, dict) or set(issue) != {"number", "created_at"} or type(issue["number"]) is not int or issue["number"] <= 0:
                    raise Unverified("issue identity invalid or excessive")
                created = utc(issue["created_at"])
                page_evidence.append((issue["number"], issue["created_at"]))
                if previous_time is not None and created < previous_time:
                    raise Unverified("creation ordering contradicted")
                previous_time = created
                if issue["number"] in issues_seen:
                    raise Unverified("duplicate issue across pages")
                issues_seen.add(issue["number"])
                if utc(start) <= created < utc(end):
                    ids.append(issue["number"])
            result.append((inside, outside, page["has_next"], ids))
            full_evidence.append(tuple(page_evidence))
            cursor = outside
        canonical.append((result, full_evidence))
    if canonical[0] != canonical[1]:
        raise Unverified("captured passes disagree")
    rendered = []
    for inside, outside, has_next, numbers in canonical[1][0]:
        def token(raw):
            return None if raw is None else "c" + hmac.new(key, b"cursor-v1\0" + raw.encode(), hashlib.sha256).hexdigest()[:48]
        rendered.append({"cursor_in": token(inside), "cursor_out": token(outside), "has_next": has_next,
                         "request_ids": ["i" + hmac.new(key, f"issue-v1\0{repository}#{number}".encode(), hashlib.sha256).hexdigest()[:48] for number in numbers]})
    return {"schema_version": 1, "window_start": start, "as_of": end,
            "sources": [{"source_id": "issue-feed", "source_type": "github_issues",
                         "captured_at": passes[-1]["captured_at"], "coverage": "partial", "pages": rendered}]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()
    try:
        if not REPO.fullmatch(args.repository) or not utc(args.window_start) < utc(args.as_of) <= datetime.now(timezone.utc):
            raise Unverified("requested source scope invalid")
        key = private_read(args.key_file, 128)
        if not 32 <= len(key) <= 128:
            raise Unverified("private report key length invalid")
        source = capture(private_read(args.capture, MAX_BYTES), args.repository,
                         args.window_start, args.as_of, key)
        private_create(args.output, (json.dumps(source, sort_keys=True, separators=(",", ":")) + "\n").encode())
    except (Unverified, OSError, ValueError, TypeError, RecursionError, UnicodeError) as exc:
        print(f"issues adapter: UNVERIFIED — {exc if isinstance(exc, Unverified) else 'capture/output unavailable; inspect before retry'}", file=sys.stderr)
        return 3
    print("issues adapter: partial private supplied-chain entry created; provenance UNVERIFIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
