#!/usr/bin/env python3
"""Offline proposed GitHub public claim codec; never grants mutation authority."""

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import stat
import sys
from typing import NotRequired, TypedDict, TypeGuard

MAX_BYTES = 1_000_000
MAX_BODY_BYTES = 65_536
MAX_COMMENTS = 2000
MAX_INTEGER = 2**63 - 1
LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
HEX32 = re.compile(r"[0-9a-f]{32}")
HEX64 = re.compile(r"[0-9a-f]{64}")
BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9/_-]{0,127}")
FIELDS = {"version", "action", "repo", "issue", "claim_id", "operation_id",
          "actor", "branch", "task_ref", "scope"}
PREFIX = "<!-- native-claim:v1 "
SUFFIX = " -->"
SUMMARY = ("Public coordination claim proposal (v1).\n"
           "Operator review of every public field is required before posting.\n"
           "This comment does not grant admission or mutation authority.\n")


class Unverified(Exception):
    """Only fixed reason codes may be returned to the caller."""


class ClaimReport(TypedDict):
    status: str
    reason: str
    remote_coverage: str
    mutation_authorized: bool
    comment: NotRequired[str]
    comment_sha256: NotRequired[str]
    public_review: NotRequired[str]
    observed_match_ids: NotRequired[list[int]]
    observed_comment_count: NotRequired[int]
    conflict_reasons: NotRequired[list[str]]


def require(condition, reason="INVALID_INPUT"):
    if not condition:
        raise Unverified(reason)


def matches(value: object, pattern: re.Pattern[str]) -> TypeGuard[str]:
    return type(value) is str and pattern.fullmatch(value) is not None


def positive(value):
    return type(value) is int and 1 <= value <= MAX_INTEGER


def login(value):
    return matches(value, LOGIN) and "--" not in value


def captured_login(value):
    # Only the exact GitHub App suffix extends the ordinary-login grammar.
    # Never strip it when comparing a marker actor with the captured author.
    return login(value) or (type(value) is str and value.endswith("[bot]")
                            and login(value[:-5]))


def validate_claim(value):
    if not (type(value) is dict and set(value) == FIELDS):
        raise Unverified("INVALID_CLAIM")
    require(type(value["version"]) is int and value["version"] == 1
            and value["action"] == "claim", "INVALID_CLAIM")
    repo = value["repo"]
    if not (type(repo) is str and repo.count("/") == 1):
        raise Unverified("INVALID_CLAIM")
    owner, name = repo.split("/")
    require(login(owner) and matches(name, REPOSITORY) and ".." not in name
            and not name.endswith("."), "INVALID_CLAIM")
    require(positive(value["issue"]) and login(value["actor"]), "INVALID_CLAIM")
    for key in ("claim_id", "operation_id"):
        require(matches(value[key], HEX32), "INVALID_CLAIM")
    branch = value["branch"]
    require(matches(branch, BRANCH) and not branch.endswith("/")
            and "//" not in branch, "INVALID_CLAIM")
    task = value["task_ref"]
    require(type(task) is str and re.fullmatch(r"issue:[1-9][0-9]{0,18}", task)
            is not None and int(task[6:]) <= MAX_INTEGER, "INVALID_CLAIM")
    require(type(value["scope"]) is str and value["scope"] in {"implementation", "review"},
            "INVALID_CLAIM")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def render(claim):
    validate_claim(claim)
    return SUMMARY + "\n" + PREFIX + canonical(claim) + SUFFIX + "\n"


def digest(body):
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def report(status: str, reason: str) -> ClaimReport:
    return {"status": status, "reason": reason, "remote_coverage": "unmeasured",
            "mutation_authorized": False}


def prepare(claim) -> ClaimReport:
    body = render(claim)
    return {**report("PREPARED", "PUBLIC_REVIEW_REQUIRED"), "comment": body,
            "comment_sha256": digest(body), "public_review": "REQUIRED"}


def unique(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def invalid_constant(_value):
    raise Unverified("INVALID_JSON")


def bounded(value, depth=0):
    require(depth <= 32, "INVALID_JSON")
    if type(value) is str:
        require(len(value.encode("utf-8")) <= MAX_BODY_BYTES, "INVALID_JSON")
    elif type(value) is dict:
        require(len(value) <= MAX_COMMENTS, "INVALID_JSON")
        for key, item in value.items():
            bounded(key, depth + 1)
            bounded(item, depth + 1)
    elif type(value) is list:
        require(len(value) <= MAX_COMMENTS, "INVALID_JSON")
        for item in value:
            bounded(item, depth + 1)
    elif type(value) is float:
        require(math.isfinite(value), "INVALID_JSON")


def parse_json(data):
    require(0 < len(data) <= MAX_BYTES, "INVALID_JSON")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=invalid_constant)
        bounded(value)
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Unverified("INVALID_JSON") from exc


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def read_capture(path):
    # Walk physical components: O_NOFOLLOW on only the leaf is insufficient.
    require(type(path) is str and path.startswith("/") and len(path.encode("utf-8")) <= 4096
            and not any(ord(c) < 32 for c in path), "INVALID_CAPTURE_PATH")
    parts = path[1:].split("/")
    require(all(part not in {"", ".", ".."} for part in parts), "INVALID_CAPTURE_PATH")
    require(all(hasattr(os, name) for name in ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK")),
            "SAFE_READ_UNAVAILABLE")
    with contextlib.ExitStack() as stack:
        parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, parent)
        directories = []
        for part in parts[:-1]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            stack.callback(os.close, fd)
            info = os.fstat(fd)
            directories.append((parent, part, info.st_dev, info.st_ino))
            parent = fd
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        stack.callback(os.close, fd)
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and 0 < before.st_size <= MAX_BYTES, "UNSAFE_CAPTURE")
        chunks = []
        remaining = MAX_BYTES + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        require(len(data) == before.st_size
                and fingerprint(os.fstat(fd)) == fingerprint(before)
                and fingerprint(os.stat(parts[-1], dir_fd=parent, follow_symlinks=False))
                == fingerprint(before), "CHANGED_DURING_READ")
        for parent_fd, name, device, inode in directories:
            info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            require(stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (device, inode),
                    "CHANGED_DURING_READ")
        return parse_json(data)


def parse_marker(body):
    # A reserved-family mention that is not the exact codec is refused, including
    # quoted/foreign versions, multiple markers and edits to the fixed summary.
    if "native-claim" not in body.casefold():
        return None
    require(body.startswith(SUMMARY + "\n" + PREFIX) and body.endswith(SUFFIX + "\n"),
            "MALFORMED_MARKER")
    payload = body[len(SUMMARY + "\n" + PREFIX):-len(SUFFIX + "\n")]
    claim = validate_claim(parse_json(payload.encode("utf-8")))
    require(body == render(claim), "NONCANONICAL_OR_EDITED_MARKER")
    return claim


def reconcile(comments, intended, known_comment_id=None, known_body_sha256=None) -> ClaimReport:
    validate_claim(intended)
    require((known_comment_id is None) == (known_body_sha256 is None), "INVALID_RECEIPT")
    if known_comment_id is not None:
        require(positive(known_comment_id) and matches(known_body_sha256, HEX64), "INVALID_RECEIPT")
    if not (type(comments) is list and len(comments) <= MAX_COMMENTS):
        raise Unverified("INVALID_CAPTURE")
    issue_url = f"https://api.github.com/repos/{intended['repo']}/issues/{intended['issue']}"
    ids, operations, claims = set(), set(), {}
    matches_seen, conflicts = [], set()
    receipt_seen = False
    for comment in comments:
        if not (type(comment) is dict and positive(comment.get("id"))):
            raise Unverified("INVALID_COMMENT")
        comment_id = comment["id"]
        require(comment_id not in ids, "DUPLICATE_COMMENT_ID")
        ids.add(comment_id)
        author = comment.get("user")
        if not (type(author) is dict and captured_login(author.get("login"))):
            raise Unverified("INVALID_COMMENT")
        body = comment.get("body")
        if not (type(body) is str and len(body.encode("utf-8")) <= MAX_BODY_BYTES):
            raise Unverified("INVALID_COMMENT")
        require(comment.get("issue_url") == issue_url, "COMMENT_ISSUE_MISMATCH")
        if comment_id == known_comment_id:
            receipt_seen = True
            if digest(body) != known_body_sha256:
                conflicts.add("KNOWN_COMMENT_EDITED")
        claim = parse_marker(body)
        if claim is None:
            continue
        if claim["repo"] != intended["repo"] or claim["issue"] != intended["issue"]:
            conflicts.add("MARKER_ISSUE_MISMATCH")
        if claim["actor"] != author["login"]:
            conflicts.add("AUTHOR_MISMATCH")
        if claim["operation_id"] in operations:
            conflicts.add("DUPLICATE_OPERATION_ID")
        operations.add(claim["operation_id"])
        prior = claims.get(claim["claim_id"])
        if prior is not None and prior != claim:
            conflicts.add("CLAIM_PAYLOAD_MISMATCH")
        claims[claim["claim_id"]] = claim
        if claim == intended and claim["actor"] == author["login"]:
            matches_seen.append(comment_id)
        else:
            conflicts.add("OTHER_CLAIM_OR_PAYLOAD")
    if conflicts:
        status, reason = "CONFLICT", "OBSERVED_CONFLICT"
    elif known_comment_id is not None and not receipt_seen:
        status, reason = "UNVERIFIED", "KNOWN_COMMENT_NOT_OBSERVED"
    elif matches_seen:
        status, reason = "OBSERVED_MATCH", "CAPTURE_COVERAGE_UNMEASURED"
    else:
        status, reason = "UNVERIFIED", "NO_MATCH_OBSERVED"
    return {**report(status, reason), "observed_match_ids": sorted(matches_seen),
            "observed_comment_count": len(comments), "conflict_reasons": sorted(conflicts)}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Unverified("INVALID_ARGUMENTS")


class StoreOnce(argparse.Action):
    """Reject duplicate value-bearing options before input validation or reads."""

    def __call__(self, parser, namespace, values, option_string=None):
        require(getattr(namespace, self.dest, None) is None, "DUPLICATE_ARGUMENT")
        setattr(namespace, self.dest, values)


def number(value):
    require(re.fullmatch(r"[1-9][0-9]{0,18}", value) is not None, "INVALID_ARGUMENTS")
    result = int(value)
    require(positive(result), "INVALID_ARGUMENTS")
    return result


def main():
    try:
        require(sys.flags.isolated and sys.dont_write_bytecode, "ISOLATED_PYTHON_REQUIRED")
        parser = Parser(description=__doc__, allow_abbrev=False)
        commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
        for command in ("prepare", "reconcile"):
            sub = commands.add_parser(command, allow_abbrev=False)
            for name in ("repo", "issue", "claim-id", "operation-id", "actor", "branch",
                         "task-ref", "scope"):
                sub.add_argument("--" + name, required=True, action=StoreOnce)
            if command == "reconcile":
                sub.add_argument("--comments", required=True, action=StoreOnce)
                sub.add_argument("--known-comment-id", action=StoreOnce)
                sub.add_argument("--known-body-sha256", action=StoreOnce)
        args = parser.parse_args()
        claim = validate_claim({"version": 1, "action": "claim", "repo": args.repo,
                                "issue": number(args.issue), "claim_id": args.claim_id,
                                "operation_id": args.operation_id, "actor": args.actor,
                                "branch": args.branch, "task_ref": args.task_ref,
                                "scope": args.scope})
        if args.command == "prepare":
            output = prepare(claim)
        else:
            known_id = number(args.known_comment_id) if args.known_comment_id is not None else None
            output = reconcile(read_capture(args.comments), claim, known_id, args.known_body_sha256)
    except Unverified as exc:
        output = report("UNVERIFIED", str(exc))
    except (OSError, ValueError, UnicodeError, TypeError, RecursionError):
        output = report("UNVERIFIED", "INPUT_UNAVAILABLE")
    print(canonical(output))
    return {"PREPARED": 0, "OBSERVED_MATCH": 3, "UNVERIFIED": 3, "CONFLICT": 4}[output["status"]]


if __name__ == "__main__":
    sys.exit(main())
