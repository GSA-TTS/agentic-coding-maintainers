#!/usr/bin/env python3
"""Read-only GitHub merge observation bound to a private maintainer mapping."""

import sys

if not sys.flags.isolated or not sys.dont_write_bytecode:
    print("merge observation: UNVERIFIED — run with python3 -I -B", file=sys.stderr)
    sys.exit(3)

import argparse
import contextlib
import datetime
import hashlib
import hmac
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import re
import selectors
import signal
import stat
import subprocess
import time

MAX_BYTES = 8192
PR_FIELDS = "{number,base:{repo:{full_name}},head:{sha},state,merged,merged_at,merge_commit_sha,merged_at_present:has(\"merged_at\"),merge_commit_sha_present:has(\"merge_commit_sha\")}"
COMMIT_FIELDS = "{sha}"
SHA = re.compile(r"^[0-9a-f]{40}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
CASE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
VALIDATOR_SHA256 = "d8613320df169ecb6bfafce10f3bee5a4a11102a74d0433ab90cd3db14d88975"
MAX_VALIDATOR_BYTES = 65536


class Unverified(Exception):
    pass


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Unverified("duplicate evidence field")
        result[key] = value
    return result


def private_mapping(path):
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise Unverified("mapping path must be absolute")
    if sys.platform == "darwin" and path.parts[:2] == ("/", "var"):
        path = pathlib.Path("/private/var", *path.parts[2:])
    with contextlib.ExitStack() as stack:
        fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, fd)
        for component in path.parent.parts[1:]:
            if component in {".", ".."}:
                raise Unverified("mapping parent is unsafe")
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            stack.callback(os.close, next_fd)
            fd = next_fd
        parent = os.fstat(fd)
        if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
            raise Unverified("mapping directory must be current-user private")
        file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            info = os.fstat(file_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > MAX_BYTES:
                raise Unverified("mapping file must be bounded and private")
            with os.fdopen(file_fd, "rb") as handle:
                file_fd = -1
                raw = handle.read(MAX_BYTES + 1)
        finally:
            if file_fd >= 0:
                os.close(file_fd)
    if not raw or len(raw) > MAX_BYTES:
        raise Unverified("mapping is empty or too large")
    try:
        value = json.loads(raw, object_pairs_hook=no_duplicates)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Unverified("mapping is malformed") from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "case_id", "repository", "number", "head_sha"} or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise Unverified("mapping schema is invalid")
    if not isinstance(value["case_id"], str) or not CASE.fullmatch(value["case_id"]):
        raise Unverified("case identity is invalid")
    if not isinstance(value["repository"], str) or not REPO.fullmatch(value["repository"]):
        raise Unverified("repository identity is invalid")
    if type(value["number"]) is not int or not 1 <= value["number"] <= 2147483647:
        raise Unverified("PR number is invalid")
    if not isinstance(value["head_sha"], str) or not SHA.fullmatch(value["head_sha"]):
        raise Unverified("expected head SHA is invalid")
    return value


def load_validator():
    """Load the reviewed ledger parser from exactly one pinned no-follow read."""
    # Importing a mutable sibling after a path check executes whatever bytes
    # the filesystem supplies at import time. Read ONE no-follow descriptor,
    # authenticate its complete bytes against the reviewed pin, then compile
    # precisely those bytes. A later canonical validator update requires an
    # explicit reviewed pin change; a changed file cannot execute silently.
    script = pathlib.Path(__file__).absolute()
    with contextlib.ExitStack() as stack:
        parent = os.open(script.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, parent)
        try:
            fd = os.open("cohort-reflection.py", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        except OSError as exc:
            raise Unverified("trusted ledger validator unavailable") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_VALIDATOR_BYTES:
                raise Unverified("trusted ledger validator unavailable")
            with os.fdopen(fd, "rb") as handle:
                fd = -1
                source = handle.read(MAX_VALIDATOR_BYTES + 1)
        finally:
            if fd >= 0:
                os.close(fd)
    if not source or len(source) > MAX_VALIDATOR_BYTES or hashlib.sha256(source).hexdigest() != VALIDATOR_SHA256:
        raise Unverified("trusted ledger validator digest mismatch")
    class PinnedValidatorLoader(importlib.machinery.SourceFileLoader):
        def get_code(self, fullname):
            # SourceFileLoader normally reads a path (and possibly cached
            # bytecode). Override that method: the loader can execute only the
            # authenticated bytes already read from our single descriptor.
            return compile(source, "<pinned cohort validator>", "exec")

    loader = PinnedValidatorLoader("cohort_reader_for_merge", "<pinned cohort validator>")
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise Unverified("trusted ledger validator unavailable")
    reader = importlib.util.module_from_spec(spec)
    try:
        loader.exec_module(reader)
    except Exception as exc:
        raise Unverified("trusted ledger validator unavailable") from exc
    return reader


def private_key(reader, path):
    try:
        key = reader.private_file(path)
    except reader.Unverified as exc:
        raise Unverified("private report key unavailable") from exc
    if not 32 <= len(key) <= 128:
        raise Unverified("private report key has invalid length")
    return key


def bind_ledger(path, mapping, key, reader=None):
    """Check recorded case membership, never authenticate the PR association."""
    reader = reader if reader is not None else load_validator()
    as_of = datetime.datetime.now(datetime.timezone.utc)
    try:
        data = reader.private_file(path)
        events = reader.events_from(data, as_of)
    except reader.Unverified as exc:
        raise Unverified("private case ledger is unavailable or invalid") from exc
    if any(reader.timestamp(row["recorded_at"]) > as_of for row in events):
        raise Unverified("private case ledger contains future-recorded events")
    case = [row for row in events if row["case_id"] == mapping["case_id"]]
    if not case or case[0]["event_type"] != "intake":
        raise Unverified("mapping case has no recorded intake")
    if case[0]["case_type"] not in {"implementation", "documentation"}:
        raise Unverified("case type has no PR-merge delivery mapping")
    effective = next((row["replacement"] for row in reversed(case)
                      if row["event_type"] == "eligibility_correction"), case[0]["eligibility"])
    if effective != "eligible":
        raise Unverified("mapping case is not recorded eligible")
    links = [row for row in case if row["event_type"] == "pr_association"]
    if len(links) != 1:
        raise Unverified("case has no single recorded PR association")
    link = links[0]
    if (link["repository"], link["pr_number"], link["head_sha"]) != (
        mapping["repository"], mapping["number"], mapping["head_sha"]
    ):
        raise Unverified("recorded PR association disagrees with supplied mapping")
    if any(row["event_type"] == "outcome" and row["head_sha"] != mapping["head_sha"] for row in case):
        raise Unverified("ledger outcome claim conflicts with mapped head")
    return as_of, hmac.new(key, b"merge-ledger-v1\0" + data, hashlib.sha256).hexdigest()


def github_get(endpoint, projection):
    # GH_HOST and enterprise-api overrides must not redirect a relative API
    # request to another host with the same owner/repo name. Use an absolute
    # public GitHub API URL and fail if an inherited host selector is present.
    if os.environ.get("GH_HOST") or os.environ.get("GITHUB_HOST"):
        raise Unverified("GitHub host override is not supported")
    if not isinstance(endpoint, str) or not endpoint.startswith("repos/"):
        raise Unverified("GitHub endpoint is not allowlisted")
    if projection not in {PR_FIELDS, COMMIT_FIELDS}:
        raise Unverified("GitHub projection is not allowlisted")
    process = None
    try:
        process = subprocess.Popen(["gh", "api", "--method", "GET", f"https://api.github.com/{endpoint}", "--jq", projection],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        output = bytearray()
        diagnostic = bytearray()
        deadline = time.monotonic() + 15
        with selectors.DefaultSelector() as selector:
            assert process.stdout and process.stderr
            selector.register(process.stdout, selectors.EVENT_READ, output)
            selector.register(process.stderr, selectors.EVENT_READ, diagnostic)
            while selector.get_map():
                if time.monotonic() >= deadline:
                    raise Unverified("GitHub read timed out")
                for key, _ in selector.select(timeout=min(0.25, max(0.0, deadline - time.monotonic()))):
                    stream = key.fileobj
                    descriptor = stream if isinstance(stream, int) else stream.fileno()
                    chunk = os.read(descriptor, min(4096, MAX_BYTES + 1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    key.data.extend(chunk)
                    if len(key.data) > MAX_BYTES:
                        raise Unverified("GitHub response exceeds byte limit")
        remaining = max(0.0, deadline - time.monotonic())
        if process.wait(timeout=remaining) != 0 or not output:
            raise Unverified("GitHub returned no bounded evidence")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Unverified("GitHub read unavailable") from exc
    finally:
        if process is not None:
            # A CLI may spawn a credential helper or a descendant retaining a
            # pipe. Kill the whole isolated process group even when the direct
            # gh process exited but a child kept stdout/stderr open.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()
    try:
        return json.loads(output, object_pairs_hook=no_duplicates)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Unverified("GitHub response malformed") from exc


def observe(mapping, get=github_get):
    repository, number, head = mapping["repository"], mapping["number"], mapping["head_sha"]
    pr = get(f"repos/{repository}/pulls/{number}", PR_FIELDS)
    if not isinstance(pr, dict) or type(pr.get("number")) is not int or pr["number"] != number or not isinstance(pr.get("base"), dict) or not isinstance(pr["base"].get("repo"), dict) or pr["base"]["repo"].get("full_name") != repository:
        raise Unverified("GitHub PR identity disagrees with mapping")
    if not isinstance(pr.get("head"), dict) or pr["head"].get("sha") != head:
        raise Unverified("GitHub PR head disagrees with mapping")
    if pr.get("state") not in {"open", "closed"} or not isinstance(pr.get("state"), str):
        raise Unverified("GitHub PR state is unavailable or malformed")
    merged = pr.get("merged")
    if type(merged) is not bool:
        raise Unverified("GitHub merge state is not measured")
    if type(pr.get("merged_at_present")) is not bool or not pr["merged_at_present"] or type(pr.get("merge_commit_sha_present")) is not bool or not pr["merge_commit_sha_present"]:
        raise Unverified("GitHub merge fields are omitted")
    if "merged_at" not in pr or "merge_commit_sha" not in pr:
        raise Unverified("projected merge fields contradict presence flags")
    if not merged:
        if pr.get("merged_at") is not None:
            raise Unverified("unmerged PR has contradictory merge time")
        return "NOT_MERGED"
    if pr["state"] != "closed":
        raise Unverified("merged PR has contradictory open state")
    merged_at, commit = pr.get("merged_at"), pr.get("merge_commit_sha")
    if not isinstance(merged_at, str) or not isinstance(commit, str) or not SHA.fullmatch(commit):
        raise Unverified("merged PR lacks merge time or commit identity")
    try:
        at = datetime.datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Unverified("GitHub merge time is malformed") from exc
    if at.tzinfo != datetime.timezone.utc or at > datetime.datetime.now(datetime.timezone.utc):
        raise Unverified("GitHub merge time is not valid UTC history")
    commit_data = get(f"repos/{repository}/commits/{commit}", COMMIT_FIELDS)
    if not isinstance(commit_data, dict) or commit_data.get("sha") != commit:
        raise Unverified("merge commit could not be corroborated")
    return "MERGE_OBSERVED_IN_GITHUB"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", required=True, type=pathlib.Path)
    parser.add_argument("--ledger", required=True, type=pathlib.Path)
    parser.add_argument("--key-file", required=True, type=pathlib.Path)
    parser.add_argument("--case-id", required=True)
    args = parser.parse_args()
    try:
        mapping = private_mapping(args.mapping)
        if args.case_id != mapping["case_id"]:
            raise Unverified("requested case disagrees with private mapping")
        # The report key is private, stable per consumer and never echoed.
        # An unkeyed digest would permit guessing a small ledger offline.
        reader = load_validator()
        key = private_key(reader, args.key_file)
        observed_at, ledger_identity = bind_ledger(args.ledger, mapping, key, reader)
        status = observe(mapping)
    except (Unverified, OSError, ValueError, TypeError, RecursionError) as exc:
        print(f"merge observation: UNVERIFIED — {exc if isinstance(exc, Unverified) else 'evidence unavailable'}", file=sys.stderr)
        return 3
    # Never output raw case ID, repository or PR metadata. Pseudonyms need a
    # private key and case-ledger binding that this first attestor lacks.
    print(json.dumps({"schema_version": 1, "classification": status,
                      "source": "fresh GitHub GET observation; agent-recorded eligible case-to-PR link; association authenticity UNVERIFIED",
                      "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
                      "ledger_identity_hmac": ledger_identity,
                      "policy_compliance": "UNMEASURED", "cohort_delivery_credit": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
