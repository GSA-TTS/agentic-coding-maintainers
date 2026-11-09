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

    def connect(self):
        started = time.monotonic()
        code = ("import json,socket; "
                "a=socket.getaddrinfo('api.github.com',443,socket.AF_INET,socket.SOCK_STREAM); "
                "print(json.dumps(a[0][4][0] if a else None))")
        try:
            child = subprocess.run([sys.executable, "-I", "-B", "-c", code],
                                   env={}, cwd="/", stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   close_fds=True, timeout=self.timeout, check=True)
            address = json.loads(child.stdout)
            require(type(address) is str and len(address) <= 15, "DNS_UNVERIFIED")
            socket.inet_pton(socket.AF_INET, address)
            remaining = self.timeout - (time.monotonic() - started)
            require(remaining > 0, "DEADLINE_EXCEEDED")
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(remaining)
            self.sock.connect((address, 443))
            self.sock = self._context.wrap_socket(self.sock, server_hostname="api.github.com")
        except (subprocess.SubprocessError, ValueError, OSError) as exc:
            self.close()
            raise Refusal("DNS_OR_CONNECT_UNVERIFIED") from exc


class Refusal(Exception):
    """Fixed diagnostic only; never propagate HTTP bodies or credentials."""


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


def decode(raw):
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(Refusal("INVALID_JSON")))
        require(type(value) is dict, "INCOMPLETE_RESPONSE")
        return value
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise Refusal("INVALID_JSON") from exc


def read_chunked(response, maximum):
    """Strict bounded chunk framing; extensions/trailers are unsupported.

    HTTPResponse's chunk reader tolerates EOF while discarding trailers and does
    not validate the data terminator bytes. Read its already-header-parsed body
    stream directly so even syntactically valid JSON requires complete framing.
    """
    require(response.chunked and response.fp is not None, "INVALID_HTTP_FRAMING")
    chunks = []
    total = 0
    while True:
        line = response.fp.readline(128)
        require(re.fullmatch(rb"[0-9A-Fa-f]{1,16}\r\n", line) is not None, "INVALID_HTTP_FRAMING")
        size = int(line[:-2], 16)
        require(total + size <= maximum, "OUTPUT_BYTE_BOUND")
        if size == 0:
            require(response.fp.readline(128) == b"\r\n", "INCOMPLETE_HTTP_BODY")
            response.close()
            return b"".join(chunks)
        chunk = response.fp.read(size)
        require(len(chunk) == size and response.fp.read(2) == b"\r\n", "INCOMPLETE_HTTP_BODY")
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
        require(positive(number), "ISSUE_NUMBER_INVALID")
        require(type(token) is str and re.fullmatch(r"(?:ghp|gho)_[A-Za-z0-9]{36,255}", token),
                "UNSUPPORTED_CREDENTIAL")
        require(not any(os.environ.get(key) for key in (
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy",
            "SSL_CERT_FILE", "SSL_CERT_DIR", "SSLKEYLOGFILE")), "ROUTING_OR_TLS_OVERRIDE_REFUSED")
        self.repository, self.number = repository, number
        self.repo_path = "/repos/" + repository
        self.issue_path = self.repo_path + "/issues/" + str(number)
        self._token = token
        self._context = ssl.create_default_context()
        self._remaining = MAX_BYTES
        self._until = time.monotonic() + MAX_SECONDS
        self._post_attempted = False
        self._closed = False

    def close(self):
        self._token = None
        self._closed = True

    def _request(self, method, path, body=None):
        require(not self._closed, "TRANSPORT_CLOSED")
        allowed = {"/user", self.repo_path, self.issue_path}
        assignable = re.fullmatch(re.escape(self.repo_path) + "/assignees/(" + LOGIN + ")", path)
        require((method == "GET" and (path in allowed or assignable) and body is None)
                or (method == "POST" and path == self.issue_path + "/assignees"
                    and type(body) is bytes), "ENDPOINT_REFUSED")
        if method == "POST":
            require(not self._post_attempted, "POST_REPLAY_REFUSED")
            self._post_attempted = True  # Before connection creation, including failure.
        remaining = self._until - time.monotonic()
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
                fields = {}
                for key, value in response.getheaders():
                    key = key.lower()
                    require(key not in fields, "DUPLICATE_HTTP_HEADER")
                    fields[key] = value
                require(not {"location", "link", "content-encoding"} & fields.keys(),
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
                return decode(raw), fields
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise Refusal("TRANSPORT_UNVERIFIED") from exc
        finally:
            if connection is not None:
                connection.close()

    def issue(self, observed):
        value, _ = self._request("GET", self.issue_path)
        return self.validate_issue(value, observed)

    def validate_issue(self, value, observed):
        require(type(value) is dict and value.get("id") == observed["issue_id"]
                and positive(value.get("id")) and value.get("node_id") == observed["issue_node_id"]
                and type(value.get("number")) is int and value["number"] == self.number
                and value.get("url") == API + self.issue_path
                and value.get("repository_url") == API + self.repo_path
                and "pull_request" not in value and value.get("state") == "open"
                and value.get("locked") is False, "ISSUE_IDENTITY_OR_STATE_CHANGED")
        assignees = value.get("assignees")
        require(type(assignees) is list and len(assignees) <= 10, "ASSIGNEES_INCOMPLETE")
        ids = []
        for user in assignees:
            require(type(user) is dict and positive(user.get("id")), "ASSIGNEES_INCOMPLETE")
            ids.append(user["id"])
        require(len(set(ids)) == len(ids), "ASSIGNEES_INCOMPLETE")
        return sorted(ids)

    def fresh(self, observed):
        """Fresh actor, target, credential scopes, push permission and assignability."""
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
        ids = self.issue(observed)
        require(observed["actor_id"] in ids or len(ids) < 10, "ASSIGNEE_CAPACITY_EXHAUSTED")
        return ids

    def assign(self, observed):
        """One additive POST. Caller must retain UNKNOWN if this raises."""
        value, _ = self._request("POST", self.issue_path + "/assignees",
                                 payload(observed["actor_login"]))
        self.validate_issue(value, observed)


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
