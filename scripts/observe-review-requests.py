#!/usr/bin/env python3
"""Bounded read-only review-request event observation for one declared PR."""

import sys

if not sys.flags.isolated or not sys.dont_write_bytecode:
    print("review requests: UNVERIFIED — use python3 -I -B", file=sys.stderr)
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
from datetime import datetime, timezone
from pathlib import Path

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PAGE = re.compile(r"^[1-9][0-9]{0,3}$")
MAX_PAGES = 10
MAX_RESPONSE_BYTES = 65536
DEADLINE_SECONDS = 60
EVENTS = {"review_requested", "review_request_removed"}


class Unverified(Exception):
    pass


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Unverified("duplicate event response field")
        result[key] = value
    return result


def utc(raw):
    if not isinstance(raw, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", raw):
        raise Unverified("event/window time malformed")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Unverified("event/window time impossible") from exc


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
                raise Unverified("private key ancestor invalid")
            fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            fds.append(fd)
        parent = os.fstat(fd)
        if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
            raise Unverified("private key directory must be current-user private")
        file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            info = os.fstat(file_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or not 32 <= info.st_size <= 128:
                raise Unverified("private key file invalid")
            with os.fdopen(file_fd, "rb") as stream:
                file_fd = -1
                value = stream.read(129)
        finally:
            if file_fd >= 0:
                os.close(file_fd)
    finally:
        for descriptor in reversed(fds):
            os.close(descriptor)
    if not 32 <= len(value) <= 128:
        raise Unverified("private key length changed")
    return value


def read_get(repository, number, page, deadline):
    if any(os.environ.get(key) for key in ("GH_HOST", "GITHUB_HOST", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")):
        raise Unverified("GitHub host/proxy override is not supported")
    url = f"https://api.github.com/repos/{repository}/issues/{number}/events?per_page=100&page={page}"
    return bounded_get(url, deadline, include=True, projection=None, page=page)


def bounded_get(url, deadline, *, include, projection, page):
    process = None
    try:
        argv = ["gh", "api", "--method", "GET", "--include", url]
        if projection is not None:
            argv += ["--jq", projection]
        process = subprocess.Popen(argv,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        stdout, stderr = bytearray(), bytearray()
        with selectors.DefaultSelector() as selector:
            assert process.stdout and process.stderr
            selector.register(process.stdout, selectors.EVENT_READ, stdout)
            selector.register(process.stderr, selectors.EVENT_READ, stderr)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Unverified("GitHub event read timed out")
                for key, _ in selector.select(timeout=min(0.25, remaining)):
                    stream = key.fileobj
                    descriptor = stream if isinstance(stream, int) else stream.fileno()
                    chunk = os.read(descriptor, 4096)
                    if not chunk:
                        selector.unregister(stream)
                        continue
                    key.data.extend(chunk)
                    if len(stdout) + len(stderr) > MAX_RESPONSE_BYTES:
                        raise Unverified("GitHub event response exceeds byte bound")
        if process.wait(timeout=max(0.0, deadline - time.monotonic())) != 0 or not stdout:
            raise Unverified("GitHub event read unavailable")
        return parse_http(bytes(stdout), url, page) if include else parse_identity_http(bytes(stdout))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Unverified("GitHub event transport unavailable") from exc
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


def parse_http(raw, url, page):
    header, separator, body = raw.partition(b"\r\n\r\n")
    if not separator:
        header, separator, body = raw.partition(b"\n\n")
    if not separator:
        raise Unverified("response has no HTTP metadata")
    try:
        text = header.decode("ascii")
        lines = text.splitlines()
        if not re.fullmatch(r"HTTP/[0-9.]+ 200(?: .*)?", lines[0]):
            raise Unverified("HTTP response not successful")
        links = [line.split(":", 1)[1].strip() for line in lines[1:] if line.lower().startswith("link:")]
        if len(links) > 1:
            raise Unverified("duplicate pagination header")
        if links and not re.fullmatch(r'(?:<https://api\.github\.com/[A-Za-z0-9_./?=&-]+>;\s*rel="(?:next|prev|first|last)")(?:,\s*<https://api\.github\.com/[A-Za-z0-9_./?=&-]+>;\s*rel="(?:next|prev|first|last)")*', links[0]):
            raise Unverified("pagination header malformed")
        # Only a validated same-endpoint, consecutive page may be followed.
        next_pages = re.findall(r'<([^>]+)>;\s*rel="next"', links[0]) if links else []
        if len(next_pages) > 1:
            raise Unverified("ambiguous pagination successor")
        next_url = next_pages[0] if next_pages else None
        if next_url is not None:
            prefix = url.rsplit("page=", 1)[0] + "page="
            if not next_url.startswith(prefix) or not PAGE.fullmatch(next_url[len(prefix):]) or int(next_url[len(prefix):]) != page + 1:
                raise Unverified("pagination successor is not the next approved page")
        records = json.loads(body, object_pairs_hook=unique_fields)
    except (ValueError, UnicodeError, RecursionError, IndexError) as exc:
        raise Unverified("HTTP event response malformed") from exc
    if not isinstance(records, list):
        raise Unverified("event response is not an array")
    if len(records) > 100 or len(records) == 100 and next_url is None:
        raise Unverified("full event page has no trustworthy successor")
    return records, next_url


def parse_identity_http(raw):
    header, separator, body = raw.partition(b"\r\n\r\n")
    if not separator:
        header, separator, body = raw.partition(b"\n\n")
    if not separator:
        raise Unverified("PR identity response has no HTTP metadata")
    try:
        lines = header.decode("ascii").splitlines()
        if not re.fullmatch(r"HTTP/[0-9.]+ 200(?: .*)?", lines[0]):
            raise Unverified("PR identity HTTP response not successful")
        return json.loads(body, object_pairs_hook=unique_fields)
    except (ValueError, UnicodeError, RecursionError, IndexError) as exc:
        raise Unverified("PR identity response malformed") from exc


def verify_pr(repository, number, deadline):
    """Refuse ordinary issue numbers; the Issues events URL accepts both."""
    if any(os.environ.get(key) for key in ("GH_HOST", "GITHUB_HOST", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")):
        raise Unverified("GitHub host/proxy override is not supported")
    pr = bounded_get(f"https://api.github.com/repos/{repository}/pulls/{number}", deadline,
                     include=False, projection="{number,base:{repo:{full_name}}}", page=1)
    if not isinstance(pr, dict) or type(pr.get("number")) is not int or pr["number"] != number or not isinstance(pr.get("base"), dict) or not isinstance(pr["base"].get("repo"), dict) or pr["base"]["repo"].get("full_name") != repository:
        raise Unverified("issue number is not a verified PR in the requested repository")


def scan(repository, number, start, end, get, deadline):
    events = []
    seen = set()
    for page in range(1, MAX_PAGES + 1):
        if time.monotonic() >= deadline:
            raise Unverified("event scan deadline exceeded")
        records, successor = get(repository, number, page, deadline)
        if not isinstance(records, list) or (successor is not None and not records):
            raise Unverified("empty continuing page or malformed events")
        for item in records:
            if not isinstance(item, dict) or type(item.get("id")) is not int or item["id"] <= 0 or not isinstance(item.get("event"), str):
                raise Unverified("event identity or kind unavailable")
            if item["id"] in seen:
                raise Unverified("event duplicated across pages")
            seen.add(item["id"])
            created = utc(item.get("created_at"))
            if item["event"] in EVENTS:
                reviewer = item.get("requested_reviewer")
                team = item.get("requested_team")
                if reviewer is None and team is None:
                    raise Unverified("review-request target unavailable")
                if reviewer is not None and team is not None:
                    raise Unverified("review-request target ambiguous")
                target = reviewer if reviewer is not None else team
                field = "login" if reviewer is not None else "slug"
                if not isinstance(target, dict) or not isinstance(target.get(field), str) or not target[field]:
                    raise Unverified("review-request target identity incomplete")
                if start <= created < end:
                    events.append((item["id"], item["event"], item["created_at"], field, target[field]))
        if successor is None:
            return events, page
    raise Unverified("event page limit reached before termination")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not REPO.fullmatch(args.repository) or not 1 <= args.pr <= 2147483647:
            raise Unverified("repository or PR identity invalid")
        start, end = utc(args.window_start), utc(args.as_of)
        if not start < end <= datetime.now(timezone.utc):
            raise Unverified("event observation window invalid")
        key = private_key(args.key_file)
        deadline = time.monotonic() + DEADLINE_SECONDS
        verify_pr(args.repository, args.pr, deadline)
        first = scan(args.repository, args.pr, start, end, read_get, deadline)
        second = scan(args.repository, args.pr, start, end, read_get, deadline)
        if first != second:
            raise Unverified("review-request event observations changed")
        fingerprint = hmac.new(key, b"review-request-events-v1\0" + json.dumps(
            {"repository": args.repository, "pr": args.pr, "start": args.window_start,
             "end": args.as_of, "events": second[0]}, sort_keys=True).encode(), hashlib.sha256).hexdigest()
        print(json.dumps({"schema_version": 1, "mode": "READ_ONLY_PER_PR_REVIEW_EVENTS",
                          "coverage": "TWO_CONSISTENT_VISIBLE_READS_NOT_ATOMIC",
                          "event_count": len(second[0]), "page_count": second[1],
                          "observation_identity_hmac": fingerprint,
                          "limitation": "only one declared PR; not repository-wide or historical snapshot coverage"}, sort_keys=True))
    except (Unverified, OSError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
        print(f"review requests: UNVERIFIED — {exc if isinstance(exc, Unverified) else 'event evidence unavailable'}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
