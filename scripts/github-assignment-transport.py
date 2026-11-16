#!/usr/bin/env python3
"""Fixed-endpoint assignment transport; callers must fence and approve every effect.

No CLI, credential discovery, redirect, retry, or comment endpoint. DNS alone
uses a credential-free, timeout-killed-and-reaped isolated subprocess.
This module alone is not a publisher and does not confer dispatch authority.
"""

import contextlib
import hashlib
import http.client
import json
import math
import os
import re
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time

API = "https://api.github.com"
API_VERSION = "2022-11-28"
MAX_BYTES = 512 * 1024
MAX_SECONDS = 30
LOGIN = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?"
_HTTPS = http.client.HTTPSConnection


class BoundedHTTPSConnection(_HTTPS):
    """DNS in a credential-free exec, killed AND reaped on timeout.

    getaddrinfo can block in libc past a Python signal deadline. The isolated
    resolver has no token, environment, inherited descriptors or POST code. The
    dispatch-capable process itself connects a numeric sockaddr, then verifies
    TLS against the fixed API hostname. There is no DNS inside socket.connect.
    """

    def __init__(self, host: str, port: int = 443, *, timeout: float,
                 context: ssl.SSLContext | None = None):
        # Internal callers must supply a bounded timeout, never the stdlib's
        # global default/None. Retain the explicit context used for TLS wrapping.
        require(type(timeout) in (int, float) and math.isfinite(timeout)
                and 0 < timeout <= MAX_SECONDS, "DEADLINE_EXCEEDED")
        self._connect_timeout = timeout
        self._tls_context = context if context is not None else ssl.create_default_context()
        super().__init__(host, port, timeout=timeout, context=self._tls_context)

    def connect(self):
        started = time.monotonic()
        code = ("import json,socket; "
                "a=socket.getaddrinfo('api.github.com',443,socket.AF_INET,socket.SOCK_STREAM); "
                "print(json.dumps(a[0][4][0] if a else None))")
        try:
            child = subprocess.run([sys.executable, "-I", "-B", "-c", code],
                                   env={}, cwd="/", stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   close_fds=True, timeout=self._connect_timeout, check=True)
            address = json.loads(child.stdout)
            require(type(address) is str and len(address) <= 15, "DNS_UNVERIFIED")
            socket.inet_pton(socket.AF_INET, address)
            remaining = self._connect_timeout - (time.monotonic() - started)
            require(remaining > 0, "DEADLINE_EXCEEDED")
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(remaining)
            self.sock.connect((address, 443))
            self.sock = self._tls_context.wrap_socket(self.sock, server_hostname="api.github.com")
        except (subprocess.SubprocessError, ValueError, OSError) as exc:
            self.close()
            raise Refusal("DNS_OR_CONNECT_UNVERIFIED") from exc


class Refusal(Exception):
    """Fixed diagnostic only; never propagate HTTP bodies or credentials."""

    # Only the request boundary attaches a measurement. An absent attribute lets
    # dispatch fall back to the client's status; explicit None must override it.
    http_status: int | None


def require(condition, reason):
    if not condition:
        raise Refusal(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def payload(login):
    require(type(login) is str and re.fullmatch(LOGIN, login) and "--" not in login,
            "ACTOR_LOGIN_INVALID")
    return canonical({"assignees": [login]}).encode("ascii")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def positive(value):
    return type(value) is int and 0 < value <= 2**63 - 1


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def decode(raw, *, listing=False):
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(Refusal("INVALID_JSON")))
        require(type(value) is (list if listing else dict), "INCOMPLETE_RESPONSE")
        return value
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise Refusal("INVALID_JSON") from exc


def read_chunked(response: http.client.HTTPResponse, maximum: int):
    """Strict bounded chunk framing; extensions/trailers are unsupported.

    HTTPResponse's chunk reader tolerates EOF while discarding trailers and does
    not validate the data terminator bytes. Read its already-header-parsed body
    stream directly so even syntactically valid JSON requires complete framing.
    """
    stream = response.fp
    if not response.chunked or stream is None:
        raise Refusal("INVALID_HTTP_FRAMING")
    chunks = []
    total = 0
    while True:
        line = stream.readline(128)
        require(re.fullmatch(rb"[0-9A-Fa-f]{1,16}\r\n", line) is not None, "INVALID_HTTP_FRAMING")
        size = int(line[:-2], 16)
        require(total + size <= maximum, "OUTPUT_BYTE_BOUND")
        if size == 0:
            require(stream.readline(128) == b"\r\n", "INCOMPLETE_HTTP_BODY")
            response.close()
            return b"".join(chunks)
        chunk = stream.read(size)
        require(len(chunk) == size and stream.read(2) == b"\r\n", "INCOMPLETE_HTTP_BODY")
        chunks.append(chunk)
        total += size


@contextlib.contextmanager
def deadline(seconds):
    """Bound slow response headers; dispatch runs synchronously in this process.

    Intentionally Unix/main-thread only. Refuse an existing alarm rather than
    weakening someone else's timeout. No use while a coordinator/SQLite lock is held.
    """
    require(threading.current_thread() is threading.main_thread(), "MAIN_THREAD_REQUIRED")
    require(math.isfinite(seconds) and 0 < seconds <= MAX_SECONDS, "DEADLINE_EXCEEDED")
    require(signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), "EXISTING_TIMER_REFUSED")
    previous = signal.getsignal(signal.SIGALRM)

    def expired(_signum, _frame):
        raise Refusal("DEADLINE_EXCEEDED")

    signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class Transport:
    """Credential-isolated synchronous HTTPS, with a single possible POST.

    Accept only recognizable classic PAT / OAuth access tokens. Every fresh user
    response must also prove OAuth scopes. Fine-grained PAT, App, installation,
    Actions, and legacy unprefixed credentials are deliberately unsupported.
    Credentials stay in this process, not argv, subprocess environments or receipts.
    """

    def __init__(self, repository, number, token):
        require(type(repository) is str and re.fullmatch(
            LOGIN + r"/[A-Za-z0-9][A-Za-z0-9._-]{0,99}", repository)
            and "--" not in repository.split("/")[0]
            and ".." not in repository.split("/")[1] and not repository.endswith("."),
            "REPOSITORY_INVALID")
        require(number is None or positive(number), "ISSUE_NUMBER_INVALID")
        require(type(token) is str and re.fullmatch(r"(?:ghp|gho)_[A-Za-z0-9]{36,255}", token),
                "UNSUPPORTED_CREDENTIAL")
        require(not any(os.environ.get(key) for key in (
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy",
            "SSL_CERT_FILE", "SSL_CERT_DIR", "SSLKEYLOGFILE")), "ROUTING_OR_TLS_OVERRIDE_REFUSED")
        self.repository, self.number = repository, number
        self.repo_path = "/repos/" + repository
        self.issue_path = self.repo_path + "/issues/" + str(number) if number is not None else None
        self._token: str | None = token
        self._context = ssl.create_default_context()
        self._remaining = MAX_BYTES
        self._until = time.monotonic() + MAX_SECONDS
        self._post_attempted = False
        self._closed = False
        self.http_status: int | None = None

    def close(self):
        self._token = None
        self._closed = True

    def _request(self, method, path, body=None):
        # Per-call measurement, reset even when refusing before network activity.
        self.http_status = None
        require(not self._closed, "TRANSPORT_CLOSED")
        if type(path) is not str:
            raise Refusal("ENDPOINT_REFUSED")
        allowed = {"/user", self.repo_path, self.issue_path}
        listing = re.fullmatch(re.escape(self.repo_path) + r"/issues\?state=all&per_page=100&page=([1-9]|10)", path)
        assignable = re.fullmatch(re.escape(self.repo_path) + "/assignees/(" + LOGIN + ")", path)
        require((method == "GET" and (path in allowed or assignable or listing) and body is None)
                or (method == "POST" and (path == self.repo_path + "/issues" and self.number is None
                    or self.issue_path is not None and path == self.issue_path + "/assignees")
                    and type(body) is bytes), "ENDPOINT_REFUSED")
        if method == "POST":
            require(not self._post_attempted, "POST_REPLAY_REFUSED")
            self._post_attempted = True  # Before connection creation, including failure.
        remaining = self._until - time.monotonic()
        if self._token is None:
            raise Refusal("TRANSPORT_CLOSED")
        headers = {"Authorization": "Bearer " + self._token,
                   "Accept": "application/vnd.github.raw+json",
                   "X-GitHub-Api-Version": API_VERSION,
                   "User-Agent": "operator-assignment-runner",
                   "Accept-Encoding": "identity"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection = None
        try:
            with deadline(remaining):
                connection = BoundedHTTPSConnection("api.github.com", 443,
                                                         context=self._context, timeout=remaining)
                connection.request(method, path, body=body, headers=headers)
                response = connection.getresponse()
                if type(response.status) is int and 100 <= response.status <= 599:
                    self.http_status = response.status
                fields = {}
                for key, value in response.getheaders():
                    key = key.lower()
                    require(key not in fields, "DUPLICATE_HTTP_HEADER")
                    fields[key] = value
                # RFC 9110 10.2.2 / 15.3.2: Location on the expected POST 201
                # describes the created resource. It is inert metadata here,
                # never a redirect or an endpoint for the follow-up observation.
                require("content-encoding" not in fields and ("link" not in fields or listing is not None)
                        and ("location" not in fields or (method == "POST" and response.status == 201)),
                         "ROUTING_OR_INCOMPLETE_RESPONSE")
                # Any rate-limit instruction ends this run. Never sleep/retry a POST.
                require("retry-after" not in fields and fields.get("x-ratelimit-remaining") != "0",
                        "RATE_LIMITED")
                expected = 201 if method == "POST" else 204 if assignable else 200
                require(response.status == expected, "HTTP_STATUS_REFUSED")
                length = fields.get("content-length")
                encoding = fields.get("transfer-encoding")
                require(not (length is not None and encoding is not None), "CONFLICTING_HTTP_FRAMING")
                if length is not None:
                    require(re.fullmatch(r"0|[1-9][0-9]{0,18}", length) is not None,
                            "INVALID_HTTP_FRAMING")
                    length = int(length)
                    require(length <= self._remaining, "OUTPUT_BYTE_BOUND")
                if expected == 204:
                    require(encoding is None and length in (None, 0), "INVALID_HTTP_FRAMING")
                else:
                    require((encoding == "chunked" and length is None)
                            or (encoding is None and length is not None), "INVALID_HTTP_FRAMING")
                raw = (read_chunked(response, self._remaining) if encoding == "chunked"
                       else response.read(self._remaining + 1))
                self._remaining -= len(raw)
                require(self._remaining >= 0, "OUTPUT_BYTE_BOUND")
                # read(amount) can return valid JSON after premature EOF without
                # raising IncompleteRead. Require the declared body length before
                # decode; chunk framing was fully checked by read_chunked above.
                if length is not None:
                    require(len(raw) == length, "INCOMPLETE_HTTP_BODY")
                if expected == 204:
                    require(not raw, "INCOMPLETE_RESPONSE")
                    return {}, fields
                media = fields.get("content-type", "").split(";", 1)[0].strip()
                require(media in {"application/json", "application/vnd.github.raw+json"},
                        "CONTENT_TYPE_REFUSED")
                return decode(raw, listing=listing is not None), fields
        except Refusal as exc:
            exc.http_status = self.http_status
            raise
        except (OSError, http.client.HTTPException, ValueError) as exc:
            error = Refusal("TRANSPORT_UNVERIFIED")
            error.http_status = self.http_status
            raise error from exc
        finally:
            if connection is not None:
                connection.close()

    def issue(self, observed):
        if self.issue_path is None:
            raise Refusal("ISSUE_NUMBER_INVALID")
        value, _ = self._request("GET", self.issue_path)
        return self.validate_issue(value, observed)

    def validate_issue(self, value, observed):
        if self.issue_path is None:
            raise Refusal("ISSUE_NUMBER_INVALID")
        require(type(value) is dict and value.get("id") == observed["issue_id"]
                and positive(value.get("id")) and value.get("node_id") == observed["issue_node_id"]
                and type(value.get("number")) is int and value["number"] == self.number
                and value.get("url") == API + self.issue_path
                and value.get("repository_url") == API + self.repo_path
                and "pull_request" not in value and value.get("state") == "open"
                and value.get("locked") is False, "ISSUE_IDENTITY_OR_STATE_CHANGED")
        assignees = value.get("assignees")
        if type(assignees) is not list or len(assignees) > 10:
            raise Refusal("ASSIGNEES_INCOMPLETE")
        ids = []
        for user in assignees:
            if type(user) is not dict or not positive(user.get("id")):
                raise Refusal("ASSIGNEES_INCOMPLETE")
            ids.append(user["id"])
        require(len(set(ids)) == len(ids), "ASSIGNEES_INCOMPLETE")
        return sorted(ids)

    def fresh_repository(self, observed):
        """Repository authority independent of a positive issue number."""
        user, headers = self._request("GET", "/user")
        require(user.get("type") == "User" and positive(user.get("id"))
                and user["id"] == observed["actor_id"]
                and user.get("node_id") == observed["actor_node_id"]
                and user.get("login") == observed["actor_login"], "ACTOR_IDENTITY_CHANGED")
        repo, _ = self._request("GET", self.repo_path)
        require(positive(repo.get("id")) and repo["id"] == observed["repository_id"]
                and repo.get("node_id") == observed["repository_node_id"]
                and repo.get("full_name") == self.repository and repo.get("url") == API + self.repo_path
                and type(repo.get("private")) is bool and repo.get("archived") is False
                and repo.get("disabled") is False, "REPOSITORY_IDENTITY_CHANGED")
        permissions = repo.get("permissions")
        require(type(permissions) is dict and permissions.get("push") is True,
                "ASSIGNMENT_PERMISSION_UNPROVEN")
        scopes = {part.strip() for part in headers.get("x-oauth-scopes", "").split(",")}
        require("repo" in scopes or (not repo["private"] and "public_repo" in scopes),
                "CREDENTIAL_SCOPE_UNPROVEN")
        self._request("GET", self.repo_path + "/assignees/" + observed["actor_login"])

    def fresh(self, observed, *, admission=True):
        """Fresh identity/permissions; assignee capacity gates admission only."""
        require(self.number is not None, "ISSUE_NUMBER_INVALID")
        self.fresh_repository(observed)
        ids = self.issue(observed)
        if admission:
            require(observed["actor_id"] in ids or len(ids) < 10, "ASSIGNEE_CAPACITY_EXHAUSTED")
        return ids

    def assign(self, observed):
        """One additive POST. Caller must retain UNKNOWN if this raises."""
        self.http_status = None
        if self.issue_path is None:
            raise Refusal("ISSUE_NUMBER_INVALID")
        value, _ = self._request("POST", self.issue_path + "/assignees",
                                 payload(observed["actor_login"]))
        self.validate_issue(value, observed)

    def complete_issues(self):
        """Bounded complete all-state traversal, never search-absence authority.

        Link values are validated against fixed-origin numeric page URLs and are
        never followed. Concurrent remote changes remain a snapshot limitation.
        """
        result, seen = [], set()
        prefix = self.repo_path + "/issues?state=all&per_page=100&page="
        for page in range(1, 11):
            values, headers = self._request("GET", prefix + str(page))
            require(len(values) <= 100, "ISSUE_LIST_INCOMPLETE")
            relations = {}
            if "link" in headers:
                for part in headers["link"].split(","):
                    match = re.fullmatch(r'\s*<' + re.escape(API + prefix) + r'([1-9][0-9]{0,5})>; rel="(next|last|first|prev)"\s*', part)
                    if match is None or match[2] in relations:
                        raise Refusal("ISSUE_LIST_INCOMPLETE")
                    relations[match[2]] = int(match[1])
                require(all(number <= 10 for number in relations.values()), "ISSUE_LIST_INCOMPLETE")
                require("next" not in relations or relations["next"] == page + 1, "ISSUE_LIST_INCOMPLETE")
            for value in values:
                require(type(value) is dict and positive(value.get("id")) and positive(value.get("number"))
                        and value.get("repository_url") == API + self.repo_path
                        and value.get("url") == API + self.repo_path + "/issues/" + str(value["number"])
                        and value.get("state") in {"open", "closed"}
                        and type(value.get("title")) is str and type(value.get("body")) in {str, type(None)}
                        and value["id"] not in seen, "ISSUE_LIST_INCOMPLETE")
                seen.add(value["id"])
                result.append(value)
            if "next" not in relations:
                require(len(values) < 100 and ("last" not in relations or relations["last"] == page), "ISSUE_LIST_INCOMPLETE")
                return result
        raise Refusal("ISSUE_LIST_INCOMPLETE")

    def create(self, expected, observed):
        require(self.number is None and type(expected) is dict and set(expected) == {"title", "body"}
                and all(type(expected[key]) is str for key in expected), "ENDPOINT_REFUSED")
        value, headers = self._request("POST", self.repo_path + "/issues", canonical(expected).encode("ascii"))
        require(positive(value.get("number")) and positive(value.get("id")), "ISSUE_IDENTITY_OR_STATE_CHANGED")
        number = value["number"]
        require("location" not in headers or headers["location"] == API + self.repo_path + "/issues/" + str(number),
                "ISSUE_IDENTITY_OR_STATE_CHANGED")
        self.number, self.issue_path = number, self.repo_path + "/issues/" + str(number)
        return self.created_issue(value, expected, observed)

    def created_issue(self, value, expected, observed):
        author = value.get("user")
        require(type(author) is dict and author.get("type") == "User"
                and positive(author.get("id")) and author["id"] == observed["actor_id"]
                and author.get("node_id") == observed["actor_node_id"]
                and author.get("login") == observed["actor_login"], "ACTOR_IDENTITY_CHANGED")
        require(type(value.get("node_id")) is str and re.fullmatch(r"[A-Za-z0-9_+/=-]{1,256}", value["node_id"]),
                "ISSUE_IDENTITY_OR_STATE_CHANGED")
        ids = self.validate_issue(value, {"issue_id": value.get("id"), "issue_node_id": value["node_id"]})
        # Creation is text-only; unexpected assignment cannot confer setup authority.
        require(ids == [], "CREATE_ASSIGNEES_CHANGED")
        require(all(value.get(key) == expected[key] for key in ("title", "body")), "ISSUE_IDENTITY_OR_STATE_CHANGED")
        return {key: value[key] for key in ("id", "node_id", "number", "title", "body")}

    def observe_created(self, created, expected, observed):
        if self.issue_path is None:
            raise Refusal("ISSUE_NUMBER_INVALID")
        value, _ = self._request("GET", self.issue_path)
        require(value.get("id") == created["id"] and value.get("node_id") == created["node_id"],
                "ISSUE_IDENTITY_OR_STATE_CHANGED")
        require(self.created_issue(value, expected, observed) == created, "ISSUE_IDENTITY_OR_STATE_CHANGED")
        return created


def actual_result(prior_ids, result_ids, actor_id):
    """Observation is separate from completion/provenance; no retry decision here."""
    for values in (prior_ids, result_ids):
        require(type(values) is list and len(values) <= 10
                and all(positive(value) for value in values)
                and values == sorted(set(values)), "ASSIGNEES_INCOMPLETE")
    require(positive(actor_id), "ACTOR_IDENTITY_CHANGED")
    if not set(prior_ids) <= set(result_ids):
        return "DRIFT", False
    if actor_id not in result_ids:
        return "FAILED_ACTUAL_RESULT", False
    # Only the fenced dispatcher can combine this observation with a retained
    # successful POST receipt. Presence alone must never claim write provenance.
    return "PRESERVED_ACTOR_PRESENT", True
