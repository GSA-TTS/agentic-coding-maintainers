#!/usr/bin/env python3
"""Bounded read-only GitHub Issues observation; not an atomic snapshot."""

import sys

if not sys.flags.isolated or not sys.dont_write_bytecode:
    print("issues observation: UNVERIFIED — run with python3 -I -B", file=sys.stderr)
    sys.exit(3)

import argparse
import hashlib
import hmac
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAX_PAGES = 10
MAX_BYTES = 65536
DEADLINE_SECONDS = 60
KEY_BYTES_MIN = 32
QUERY = """query($owner:String!,$repo:String!,$after:String){
 repository(owner:$owner,name:$repo){
  issues(first:100,after:$after,orderBy:{field:CREATED_AT,direction:ASC}){
   pageInfo{hasNextPage endCursor}
   nodes{number createdAt}
  }
 }
}"""


class Unverified(Exception):
    pass


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Unverified("GitHub issues response has duplicate fields")
        result[key] = value
    return result


def utc(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
        raise Unverified("UTC window or issue time is malformed")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Unverified("UTC time is impossible") from exc


def private_key(path):
    if not path.is_absolute() or path.name in ("", ".", ".."):
        raise Unverified("private key path must be absolute")
    if sys.platform == "darwin" and path.parts[:2] == ("/", "var"):
        path = Path("/private/var", *path.parts[2:])
    fds = []
    try:
        fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fds.append(fd)
        for component in path.parent.parts[1:]:
            if component in (".", ".."):
                raise Unverified("private key path contains unsafe component")
            fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            fds.append(fd)
        parent = os.fstat(fd)
        if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
            raise Unverified("private key directory must be current-user private")
        file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            info = os.fstat(file_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or not KEY_BYTES_MIN <= info.st_size <= 128:
                raise Unverified("private key file is unsafe or has invalid length")
            with os.fdopen(file_fd, "rb") as handle:
                file_fd = -1
                data = handle.read(129)
        finally:
            if file_fd >= 0:
                os.close(file_fd)
    finally:
        for descriptor in reversed(fds):
            os.close(descriptor)
    if not KEY_BYTES_MIN <= len(data) <= 128:
        raise Unverified("private key length changed during read")
    return data


def private_capture(path, data):
    """Exclusive private output; never replace an earlier observation."""
    if not path.is_absolute() or path.name in ("", ".", "..") or len(data) > MAX_BYTES:
        raise Unverified("capture output path or size invalid")
    if sys.platform == "darwin" and path.parts[:2] == ("/", "var"):
        path = Path("/private/var", *path.parts[2:])
    with ExitStack() as stack:
        fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, fd)
        for component in path.parent.parts[1:]:
            if component in (".", ".."):
                raise Unverified("capture path contains unsafe component")
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            stack.callback(os.close, child)
            fd = child
        parent = os.fstat(fd)
        if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
            raise Unverified("capture directory must be current-user private")
        output = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        with os.fdopen(output, "wb", buffering=0) as handle:
            if handle.write(data) != len(data):
                raise Unverified("capture write incomplete; inspect before retry")
            os.fsync(handle.fileno())


def fetch(owner, repo, after, deadline):
    if os.environ.get("GH_HOST") or os.environ.get("GITHUB_HOST"):
        raise Unverified("GitHub host override is not supported")
    # This first slice assumes direct GitHub routing. A corporate proxy needs
    # an explicitly reviewed transport contract; do not silently inherit one.
    proxy_vars = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
    if any(os.environ.get(name) for name in proxy_vars):
        raise Unverified("proxy routing needs an explicitly reviewed transport")
    # Absolute public API URL pins the request host even if gh's config or
    # current-repository context names an enterprise/default host.
    argv = ["gh", "api", "--method", "POST", "https://api.github.com/graphql",
            "-f", f"query={QUERY}", "-f", f"owner={owner}", "-f", f"repo={repo}"]
    if after is not None:
        argv.extend(["-f", f"after={after}"])
    process = None
    try:
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        output, diagnostic = bytearray(), bytearray()
        with selectors.DefaultSelector() as selector:
            assert process.stdout and process.stderr
            selector.register(process.stdout, selectors.EVENT_READ, output)
            selector.register(process.stderr, selectors.EVENT_READ, diagnostic)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Unverified("GitHub issues request timed out")
                for key, _ in selector.select(timeout=min(0.25, remaining)):
                    stream = key.fileobj
                    descriptor = stream if isinstance(stream, int) else stream.fileno()
                    chunk = os.read(descriptor, 4096)
                    if not chunk:
                        selector.unregister(stream)
                        continue
                    key.data.extend(chunk)
                    if len(output) + len(diagnostic) > MAX_BYTES:
                        raise Unverified("GitHub issues response and diagnostics exceed combined byte bound")
        if process.wait(timeout=max(0.0, deadline - time.monotonic())) != 0 or not output:
            raise Unverified("GitHub issues response unavailable")
        try:
            response = json.loads(output, object_pairs_hook=unique_fields)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise Unverified("GitHub issues response malformed") from exc
        return response
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Unverified("GitHub issues read unavailable") from exc
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()


def scan(repository, start, end, get, deadline):
    owner, repo = repository.split("/", 1)
    seen, cursors = set(), set()
    previous_time = None
    cursor = None
    pages = []
    for _ in range(MAX_PAGES):
        if time.monotonic() >= deadline:
            raise Unverified("issue observation deadline exceeded")
        response = get(owner, repo, cursor, deadline)
        if not isinstance(response, dict) or "errors" in response or not isinstance(response.get("data"), dict):
            raise Unverified("GitHub issues GraphQL coverage is unavailable")
        parent = response["data"].get("repository")
        if not isinstance(parent, dict) or not isinstance(parent.get("issues"), dict):
            raise Unverified("repository or issue listing unavailable")
        issues = parent["issues"]
        info = issues.get("pageInfo")
        nodes = issues.get("nodes")
        if not isinstance(info, dict) or type(info.get("hasNextPage")) is not bool or not isinstance(nodes, list):
            raise Unverified("issues page metadata malformed")
        if not nodes and info["hasNextPage"]:
            raise Unverified("empty issues page claims a successor")
        page_ids = []
        boundary = False
        for issue in nodes:
            if not isinstance(issue, dict) or set(issue) != {"number", "createdAt"} or type(issue["number"]) is not int or issue["number"] <= 0:
                raise Unverified("issue identity malformed")
            created = utc(issue["createdAt"])
            if previous_time is not None and created < previous_time:
                raise Unverified("issue creation order changed during scan")
            previous_time = created
            number = issue["number"]
            if number in seen:
                raise Unverified("duplicate issue identity during scan")
            seen.add(number)
            if created >= end:
                boundary = True
            if start <= created < end:
                page_ids.append(number)
        next_cursor = info.get("endCursor")
        if info["hasNextPage"]:
            if not isinstance(next_cursor, str) or not 1 <= len(next_cursor) <= 256 or next_cursor in cursors:
                raise Unverified("issue cursor absent or repeated")
        elif next_cursor is not None and not isinstance(next_cursor, str):
            raise Unverified("terminal issue cursor malformed")
        if boundary:
            # Stop only after consuming the entire page, including all entries
            # that share a boundary second. Later pages cannot have an older
            # creation time if the server honored the requested ordering.
            pages.append(tuple(page_ids))
            return pages
        pages.append(tuple(page_ids))
        if not info["hasNextPage"]:
            return pages
        cursors.add(next_cursor)
        cursor = next_cursor
    raise Unverified("issue page limit reached before termination")


def scan_full_capture(repository, get, deadline):
    """Request-to-response chain, ending ONLY at the real API terminal page.

    Unlike summary scan(), do not stop at the creation-window boundary when
    the API reports another page. Reuse the same QUERY and bounded fetch().
    """
    owner, repo = repository.split("/", 1)
    cursor = None
    cursors, issue_numbers = set(), set()
    previous_time = None
    pages = []
    for _ in range(MAX_PAGES):
        if time.monotonic() >= deadline:
            raise Unverified("capture deadline exceeded before terminal page")
        response = get(owner, repo, cursor, deadline)
        if not isinstance(response, dict) or "errors" in response or not isinstance(response.get("data"), dict):
            raise Unverified("capture GraphQL response unavailable")
        parent = response["data"].get("repository")
        issues = parent.get("issues") if isinstance(parent, dict) else None
        if not isinstance(issues, dict):
            raise Unverified("capture Issues connection unavailable")
        info, nodes = issues.get("pageInfo"), issues.get("nodes")
        if not isinstance(info, dict) or type(info.get("hasNextPage")) is not bool or not isinstance(nodes, list):
            raise Unverified("capture pageInfo or nodes malformed")
        more, raw_end = info["hasNextPage"], info.get("endCursor")
        if more:
            if not nodes or not isinstance(raw_end, str) or not 1 <= len(raw_end) <= 256 or raw_end in cursors:
                raise Unverified("capture continuation is empty, missing or repeated")
            try:
                raw_end.encode("utf-8")
            except UnicodeError as exc:
                raise Unverified("capture continuation is not UTF-8") from exc
            cursors.add(raw_end)
        elif raw_end is not None:
            if not isinstance(raw_end, str) or not 1 <= len(raw_end) <= 256:
                raise Unverified("capture terminal cursor malformed")
            try:
                raw_end.encode("utf-8")
            except UnicodeError as exc:
                raise Unverified("capture terminal cursor is not UTF-8") from exc
        collected = []
        for node in nodes:
            if not isinstance(node, dict) or set(node) != {"number", "createdAt"} or type(node["number"]) is not int or node["number"] <= 0:
                raise Unverified("capture issue identity malformed")
            created = utc(node["createdAt"])
            if previous_time is not None and created < previous_time:
                raise Unverified("capture issue order changed")
            previous_time = created
            if node["number"] in issue_numbers:
                raise Unverified("capture issue duplicated across pages")
            issue_numbers.add(node["number"])
            collected.append({"number": node["number"], "created_at": node["createdAt"]})
        # API may supply a non-null terminal endCursor. The adapter contract's
        # cursor_out is a CONTINUATION, so normalize it to null on termination.
        # This format does not retain the API's raw terminal endCursor; it is
        # therefore still insufficient for independent response attestation.
        pages.append({"cursor_in": cursor, "cursor_out": raw_end if more else None,
                      "has_next": more, "issues": collected})
        if not more:
            return pages, raw_end
        cursor = raw_end
    raise Unverified("capture page cap reached before API termination")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--key-file", required=True, type=Path)
    parser.add_argument("--capture-output", type=Path,
                        help="exclusive private full-terminal two-pass capture; never an atomic snapshot")
    args = parser.parse_args()
    try:
        if not REPO.fullmatch(args.repository):
            raise Unverified("repository identity invalid")
        start, end = utc(args.window_start), utc(args.as_of)
        if not start < end <= datetime.now(timezone.utc):
            raise Unverified("observation window invalid")
        key = private_key(args.key_file)
        deadline = time.monotonic() + DEADLINE_SECONDS
        if args.capture_output:
            first_pages, first_terminal = scan_full_capture(args.repository, fetch, deadline)
            first_time = datetime.now(timezone.utc)
            second_pages, second_terminal = scan_full_capture(args.repository, fetch, deadline)
            second_time = datetime.now(timezone.utc)
            if first_pages != second_pages or first_terminal != second_terminal:
                raise Unverified("full-terminal Issues captures disagree")
            # The v1 capture schema has second-resolution timestamps. A fast
            # pair can finish in one second, so wait (bounded by the SAME
            # deadline) rather than fabricate an elapsed second.
            while int(second_time.timestamp()) <= int(first_time.timestamp()):
                if time.monotonic() >= deadline:
                    raise Unverified("no time budget to distinguish capture passes")
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
                second_time = datetime.now(timezone.utc)
            def stamp(moment):
                return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
            capture = {"schema_version": 1, "repository": args.repository,
                       "window_start": args.window_start, "as_of": args.as_of,
                       "query_type": "graphql_issues_created_asc",
                       "passes": [{"captured_at": stamp(first_time), "pages": first_pages},
                                  {"captured_at": stamp(second_time), "pages": second_pages}]}
            raw = (json.dumps(capture, sort_keys=True, separators=(",", ":")) + "\n").encode()
            private_capture(args.capture_output, raw)
            print("issues observation: private full-terminal capture written; provenance/atomicity UNVERIFIED")
            return 0
        first = scan(args.repository, start, end, fetch, deadline)
        second = scan(args.repository, start, end, fetch, deadline)
        if first != second:
            raise Unverified("issue observations changed between passes")
        ids = [number for page in second for number in page]
        # A keyed fingerprint binds the observed list without publishing issue
        # numbers (which could identify private review work). A stable local
        # key allows comparing runs; this is not a GitHub snapshot signature.
        canonical = json.dumps({"repository": args.repository, "window_start": args.window_start,
                                "as_of": args.as_of, "issue_numbers": ids}, sort_keys=True).encode()
        print(json.dumps({"schema_version": 1, "mode": "READ_ONLY_GITHUB_ISSUES",
                          "coverage": "TWO_CONSISTENT_VISIBLE_READS_NOT_ATOMIC",
                          "page_count": len(second), "issue_count": len(ids),
                          "observation_identity_hmac": hmac.new(key, b"github-issues-v1\0" + canonical, hashlib.sha256).hexdigest(),
                          "limitation": "visible Issues connection only; no atomic historical snapshot or other intake sources"}, sort_keys=True))
    except (Unverified, OSError, ValueError, TypeError, RecursionError) as exc:
        print(f"issues observation: UNVERIFIED — {exc if isinstance(exc, Unverified) else 'read unavailable'}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
