#!/usr/bin/env python3
"""GET-only, bounded visible issue-comment traversal; never ownership authority."""

import sys

if not sys.flags.isolated or not sys.dont_write_bytecode:
    print('{"schema_version":1,"status":"UNVERIFIED","reason":"ISOLATED_PYTHON_REQUIRED",'
          '"remote_coverage":"unmeasured","atomic_snapshot":false,"mutation_authorized":false,'
          '"absence_authorizing":false}')
    sys.exit(3)

import importlib.util
import json
import os
import re
import selectors
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

# Reuse the canonical codec, including strict JSON, marker parsing and rendering.
# The existing observers' GraphQL/PR-event transports do not fit this REST contract.
spec = importlib.util.spec_from_file_location("native_claim", Path(__file__).with_name("native-claim.py"))
assert spec and spec.loader
codec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(codec)
require = codec.require
Unverified = codec.Unverified
MAX_BYTES = 512 * 1024  # Combined stdout/stderr across the entire observation.
MAX_PAGES = 10
MAX_COMMENTS = 1000
DEADLINE_SECONDS = 60
API = "https://api.github.com"


def report(status, reason):
    return {"schema_version": 1, "status": status, "reason": reason,
            "remote_coverage": "unmeasured", "atomic_snapshot": False,
            "mutation_authorized": False, "absence_authorizing": False}


def environment():
    require(not any(os.environ.get(key) for key in
                    ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")),
            "PROXY_ROUTING_UNVERIFIED")
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_") and key not in
           {"GITHUB_HOST", "GH_DEBUG", "GH_PAGER", "PAGER"}}
    env.update(GH_HOST="github.com", GH_PROMPT_DISABLED="1", GH_PAGER="cat")
    return env


class Transport:
    """Only internally constructed identity and comments endpoints are accepted."""

    def __init__(self, repository, number, deadline):
        self.repo_url = f"{API}/repos/{repository}"
        self.issue_url = f"{self.repo_url}/issues/{number}"
        self.comments_url = self.issue_url + "/comments"
        self.number = number
        self.repository_id = None  # Set only after the repository response is verified.
        self.deadline = deadline
        self.remaining_bytes = MAX_BYTES
        self.env = environment()

    def get(self, url, page=None):
        allowed = {API + "/user", self.repo_url, self.issue_url}
        if page is not None:
            require(type(page) is int and 1 <= page <= MAX_PAGES, "PAGE_BOUND")
            allowed = {f"{self.comments_url}?per_page=100&page={page}"}
        require(url in allowed, "ENDPOINT_REFUSED")
        require(time.monotonic() < self.deadline, "DEADLINE_EXCEEDED")
        argv = ["gh", "api", "--hostname", "github.com", "--method", "GET", "--include",
                "-H", "Accept: application/vnd.github.raw+json",
                "-H", "X-GitHub-Api-Version: 2022-11-28", url]
        process = None
        try:
            process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       env=self.env, start_new_session=True)
            output = bytearray()
            with selectors.DefaultSelector() as selector:
                assert process.stdout and process.stderr
                selector.register(process.stdout, selectors.EVENT_READ, True)
                selector.register(process.stderr, selectors.EVENT_READ, False)
                while selector.get_map():
                    remaining = self.deadline - time.monotonic()
                    require(remaining > 0, "DEADLINE_EXCEEDED")
                    for key, _ in selector.select(timeout=min(0.25, remaining)):
                        chunk = os.read(key.fd, 4096)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        self.remaining_bytes -= len(chunk)
                        require(self.remaining_bytes >= 0, "OUTPUT_BYTE_BOUND")
                        if key.data:
                            output.extend(chunk)
            require(process.wait(timeout=max(0.0, self.deadline - time.monotonic())) == 0
                    and bool(output), "API_READ_UNAVAILABLE")
            return parse_http(bytes(output), self.comments_url if page else None, page,
                              repository_id=self.repository_id, issue_number=self.number)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Unverified("API_READ_UNAVAILABLE") from exc
        finally:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                # SIGKILL applies to the process group, including pipe-holding children.
                process.wait(timeout=1)
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()


def parse_http(raw, endpoint=None, page=None, *, repository_id=None, issue_number=None):
    # gh may follow redirects before returning this final response. These checks
    # cannot attest intermediate routing or credential handling.
    header, separator, body = raw.partition(b"\r\n\r\n")
    if not separator:
        header, separator, body = raw.partition(b"\n\n")
    require(bool(separator), "HTTP_METADATA_MISSING")
    try:
        lines = header.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise Unverified("HTTP_METADATA_INVALID") from exc
    require(bool(lines) and re.fullmatch(r"HTTP/(?:1\.[01]|2(?:\.0)?) 200(?: OK)?", lines[0]),
            "HTTP_STATUS_REFUSED")
    headers = {}
    for line in lines[1:]:
        require(re.fullmatch(r"[A-Za-z0-9-]+:[\x20-\x7e]*", line), "HTTP_METADATA_INVALID")
        key, value = line.split(":", 1)
        key = key.lower()
        require(key not in headers, "DUPLICATE_HTTP_HEADER")
        headers[key] = value.strip()
    require("location" not in headers, "FINAL_LOCATION_REFUSED")
    successor = None
    if "link" in headers:
        require(endpoint is not None, "IDENTITY_PAGINATION_REFUSED")
        endpoints = {endpoint}
        if repository_id is not None:
            require(codec.positive(repository_id) and codec.positive(issue_number), "LINK_IDENTITY_INVALID")
            endpoints.add(f"{API}/repositories/{repository_id}/issues/{issue_number}/comments")
        relations = set()
        last_page = None
        for entry in headers["link"].split(","):
            match = re.fullmatch(r'\s*<([^<>\s]+)>;\s*rel="(next|prev|first|last)"\s*', entry)
            require(match is not None, "LINK_INVALID")
            target, relation = match.groups()
            require(relation not in relations, "LINK_DUPLICATE_RELATION")
            relations.add(relation)
            try:
                parsed = urlsplit(target)
                query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
            except ValueError as exc:
                raise Unverified("LINK_URL_INVALID") from exc
            base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            require(base in endpoints and not parsed.fragment, "LINK_ENDPOINT_MISMATCH")
            require(len(query) == 2 and set(key for key, _ in query) == {"page", "per_page"},
                    "LINK_QUERY_INVALID")
            values = dict(query)
            require(values["per_page"] == "100" and re.fullmatch(r"[1-9][0-9]*", values["page"]),
                    "LINK_QUERY_INVALID")
            target_page = int(values["page"])
            require(1 <= target_page <= MAX_PAGES, "PAGE_BOUND")
            require(target in {f"{base}?per_page=100&page={target_page}",
                               f"{base}?page={target_page}&per_page=100"}, "LINK_QUERY_INVALID")
            require((relation != "next" or target_page == page + 1)
                    and (relation != "prev" or target_page == page - 1)
                    and (relation != "first" or target_page == 1)
                    and (relation != "last" or target_page >= page), "LINK_ORDER_INVALID")
            if relation == "next":
                successor = target_page
            if relation == "last":
                last_page = target_page
        require(last_page is None or (successor is None and last_page == page)
                or (successor is not None and last_page >= successor), "LINK_TERMINATION_INVALID")
    records = codec.parse_json(body)
    if endpoint is not None:
        require(type(records) is list and len(records) <= 100
                and (successor is None or bool(records)), "COMMENT_PAGE_INVALID")
    else:
        require(type(records) is dict, "IDENTITY_RESPONSE_INVALID")
    return records, successor


def timestamp(value):
    require(type(value) is str and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value),
            "TIMESTAMP_INVALID")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Unverified("TIMESTAMP_INVALID") from exc


def issue_anchor(value, transport, number):
    require(codec.positive(value.get("id")) and type(value.get("number")) is int
            and value["number"] == number and value.get("url") == transport.issue_url
            and value.get("repository_url") == transport.repo_url
            and value.get("html_url") == transport.issue_url.replace(API + "/repos/", "https://github.com/")
            and "pull_request" not in value, "ISSUE_IDENTITY_MISMATCH")
    timestamp(value.get("updated_at"))
    require(type(value.get("comments")) is int and 0 <= value["comments"] <= MAX_COMMENTS
            and value.get("state") in {"open", "closed"} and type(value.get("locked")) is bool,
            "ISSUE_ANCHOR_INVALID")
    return tuple(value[key] for key in ("id", "number", "updated_at", "comments", "state", "locked"))


def observe(repository, number, transport, *, expected_body=None):
    # Internal composition only: compare bounded raw bodies during this fresh
    # traversal, never upgrade a caller-supplied summary or capture file.
    expected = codec.parse_marker(expected_body) if expected_body is not None else None
    if expected_body is not None:
        require(expected is not None and expected_body == codec.render(expected)
                and expected["repo"] == repository and expected["issue"] == number,
                "EXPECTED_BODY_INVALID")
    exact_ids = []
    user, _ = transport.get(API + "/user")
    require(codec.positive(user.get("id")) and codec.login(user.get("login"))
            and user.get("type") == "User", "CURRENT_USER_INVALID")
    repo, _ = transport.get(transport.repo_url)
    require(codec.positive(repo.get("id")) and repo.get("full_name") == repository
            and repo.get("url") == transport.repo_url, "REPOSITORY_IDENTITY_MISMATCH")
    transport.repository_id = repo["id"]
    issue, _ = transport.get(transport.issue_url)
    anchor = issue_anchor(issue, transport, number)
    seen, operations, claims, conflicts, summaries = set(), set(), {}, set(), []
    previous = None
    for page in range(1, MAX_PAGES + 1):
        records, successor = transport.get(f"{transport.comments_url}?per_page=100&page={page}", page)
        for comment in records:
            require(type(comment) is dict and codec.positive(comment.get("id")), "COMMENT_INVALID")
            identifier = comment["id"]
            require(identifier not in seen, "DUPLICATE_COMMENT_ID")
            seen.add(identifier)
            require(len(seen) <= MAX_COMMENTS, "COMMENT_BOUND")
            author = comment.get("user")
            require(type(author) is dict and codec.positive(author.get("id"))
                    and codec.captured_login(author.get("login")), "COMMENT_AUTHOR_INVALID")
            require(comment.get("issue_url") == transport.issue_url, "COMMENT_ISSUE_MISMATCH")
            created, updated = timestamp(comment.get("created_at")), timestamp(comment.get("updated_at"))
            order = (created, identifier)
            require(updated >= created and (previous is None or order > previous), "COMMENT_ORDER_INVALID")
            previous = order
            body = comment.get("body")
            require(type(body) is str and len(body.encode("utf-8")) <= codec.MAX_BODY_BYTES,
                    "COMMENT_BODY_INVALID")
            # Only the canonical codec can attribute a claim. A malformed body
            # remains UNVERIFIED even if prose contains the expected operation.
            claim = codec.parse_marker(body)
            if claim is None:
                continue
            if claim["repo"] != repository or claim["issue"] != number:
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
            summaries.append({"comment_id": identifier, "body_sha256": codec.digest(body),
                              "actor_is_current_user": claim["actor"] == user["login"]
                              and author["login"] == user["login"] and author["id"] == user["id"],
                              "author_matches_actor": claim["actor"] == author["login"]})
            if expected is not None:
                if (claim != expected or body != expected_body
                        or codec.digest(body) != codec.digest(expected_body)):
                    conflicts.add("OTHER_CLAIM_OR_PAYLOAD")
                elif not summaries[-1]["actor_is_current_user"]:
                    conflicts.add("EXPECTED_ACTOR_MISMATCH")
                else:
                    exact_ids.append(identifier)
        if successor is None:
            break
    else:
        raise Unverified("PAGE_BOUND")
    reread, _ = transport.get(transport.issue_url)
    require(issue_anchor(reread, transport, number) == anchor and anchor[3] == len(seen),
            "ISSUE_CHANGED_OR_COUNT_MISMATCH")
    if len(claims) > 1:
        conflicts.add("MULTIPLE_CLAIMS")
    result = report("CONFLICT" if conflicts else "OBSERVED", "OBSERVED_CONFLICT" if conflicts else "VISIBLE_TRAVERSAL")
    result.update(remote_coverage="complete_pagination", repository_id=repo["id"], issue_id=anchor[0],
                  issue_number=number, issue_closed=anchor[4] == "closed", issue_locked=anchor[5],
                  page_count=page, comment_count=len(seen), recognized_claim_count=len(summaries),
                  claims=summaries, conflict_reasons=sorted(conflicts))
    if expected is not None:
        result.update(exact_match_comment_id=exact_ids[0] if len(exact_ids) == 1 and not conflicts else None,
                      expected_body_sha256=codec.digest(expected_body))
    return result


def main():
    try:
        parser = codec.Parser(description=__doc__, allow_abbrev=False)
        parser.add_argument("--repo", required=True, action=codec.StoreOnce)
        parser.add_argument("--issue", required=True, action=codec.StoreOnce)
        args = parser.parse_args()
        number = codec.number(args.issue)
        require(type(args.repo) is str and args.repo.count("/") == 1, "REPOSITORY_INVALID")
        owner, name = args.repo.split("/")
        require(codec.login(owner) and codec.matches(name, codec.REPOSITORY)
                and ".." not in name and not name.endswith("."), "REPOSITORY_INVALID")
        transport = Transport(args.repo, number, time.monotonic() + DEADLINE_SECONDS)
        output = observe(args.repo, number, transport)
    except Unverified as exc:
        output = report("UNVERIFIED", str(exc))
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError, subprocess.TimeoutExpired):
        output = report("UNVERIFIED", "READ_UNAVAILABLE")
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return {"OBSERVED": 0, "CONFLICT": 4, "UNVERIFIED": 3}[output["status"]]


if __name__ == "__main__":
    sys.exit(main())
