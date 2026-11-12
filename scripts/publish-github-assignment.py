#!/usr/bin/env python3
"""Private, genuine-terminal approval primitives for the assignment-only runner.

Assignment-only adapter with durable core/journal fencing and no automatic retry.
Never interpret a stored approval digest as authority to launch another attempt.
"""

import hashlib
import importlib.util
import json
import math
import os
import re
import select
import stat
import sys
import termios
import time
from pathlib import Path

MAX_APPROVAL_SECONDS = 120
MAX_DISPLAY_BYTES = 32768
_SEAL = object()
PUBLIC_REASONS = frozenset("""
DISPATCH_OR_DURABILITY_UNVERIFIED ISOLATED_PYTHON_REQUIRED ADAPTER_UNAVAILABLE
INVALID_ARGUMENTS DUPLICATE_ARGUMENT INTERACTION_REQUIRED APPROVAL_EXPIRED
APPROVAL_BINDING_CHANGED INVALID_APPROVAL_BINDING REUSED_OPERATION_ID
APPROVAL_DISPLAY_BOUND FOREGROUND_CONTROLLING_TTY_REQUIRED CANONICAL_TTY_REQUIRED
MONOTONIC_CLOCK_UNVERIFIED TTY_UNAVAILABLE APPROVAL_DECLINED TTY_CHANGED_DURING_INTERACTION
IMPLEMENTATION_HEAD_CHANGED ROOT_MISMATCH EXISTING_JOURNAL_REQUIRED STORE_IDENTITY_CHANGED
JOURNAL_RECOVERY_REQUIRED
TASK_CHANGED OWNERSHIP_UNVERIFIED WORKER_HOST_CHANGED LANE_CHANGED LEASE_CHANGED
OWNERSHIP_CHANGED WORKER_NOT_ACTIVE IDENTITY_BOUND_INTENT_REQUIRED INTENT_NOT_FOUND
INTENT_CHANGED RECOVERY_BINDING_INVALID PRODUCER_TERMINATION_PROOF_UNSUPPORTED
RESERVATION_REQUEST_CHANGED RECOVERY_EVIDENCE_CHANGED EXPLICIT_GH_TOKEN_REQUIRED
REVISION_LIMIT ORIGINAL_INTENT_BINDING_CHANGED POST_REPLAY_REFUSED SELECTED_ROWS_CHANGED
PRIOR_ASSIGNEES_CHANGED RESERVATION_NOT_FOUND REVISION_MISMATCH
INVALID_METADATA UNSUPPORTED_SCHEMA UNSAFE_STORE CHANGED_DURING_READ
REPOSITORY_INVALID ISSUE_NUMBER_INVALID UNSUPPORTED_CREDENTIAL ROUTING_OR_TLS_OVERRIDE_REFUSED
ACTOR_LOGIN_INVALID DNS_UNVERIFIED DNS_OR_CONNECT_UNVERIFIED DEADLINE_EXCEEDED
DUPLICATE_JSON_KEY INVALID_JSON INCOMPLETE_RESPONSE INVALID_HTTP_FRAMING
OUTPUT_BYTE_BOUND INCOMPLETE_HTTP_BODY MAIN_THREAD_REQUIRED EXISTING_TIMER_REFUSED
TRANSPORT_CLOSED ENDPOINT_REFUSED DUPLICATE_HTTP_HEADER ROUTING_OR_INCOMPLETE_RESPONSE
RATE_LIMITED HTTP_STATUS_REFUSED CONFLICTING_HTTP_FRAMING CONTENT_TYPE_REFUSED
TRANSPORT_UNVERIFIED ISSUE_IDENTITY_OR_STATE_CHANGED ASSIGNEES_INCOMPLETE
ACTOR_IDENTITY_CHANGED REPOSITORY_IDENTITY_CHANGED ASSIGNMENT_PERMISSION_UNPROVEN
CREDENTIAL_SCOPE_UNPROVEN ASSIGNEE_CAPACITY_EXHAUSTED ASSIGNMENT_CAPACITY_EXHAUSTED
ASSIGNMENT_IDENTIFIER_COLLISION
CLOCK_PLATFORM_UNSUPPORTED CLOCK_UNVERIFIED CLOCK_CONTINUITY_LOST GRANT_NOT_FOUND
NO_ACTIVE_GRANT GRANT_INACTIVE_OR_EPOCH_CHANGED GRANT_EXPIRED GRANT_EPOCH_CHANGED
PRIOR_GRANT_NOT_REVOKED GRANT_IDENTIFIER_COLLISION ACTIVATED_ADMISSION_CHANGED
STANDING_GRANT_UNVERIFIED LOGICAL_WORK_ALREADY_ATTEMPTED TARGET_PENDING
DAILY_BUDGET_EXHAUSTED UNRESOLVED_BUDGET_EXHAUSTED REMOTE_DUPLICATE_OR_CORRELATION
ISSUE_LIST_INCOMPLETE
CREATE_ASSIGNEES_CHANGED
ENDPOINT_QUALIFICATION_NOT_INSTALLED
QUALIFICATION_MODE_UNSUPPORTED QUALIFICATION_CASE_FAILED QUALIFICATION_ARTIFACT_CHANGED
QUALIFICATION_ARTIFACT_UNSAFE QUALIFICATION_REVOKED QUALIFICATION_BINDING_CHANGED
QUALIFICATION_EFFECT_GATE_PENDING QUALIFICATION_EPOCH_CHANGED QUALIFICATION_NOT_REVOKED
QUALIFICATION_IDENTIFIER_COLLISION
""".split())


class Refusal(Exception):
    """Fixed public refusal code."""


def require(condition, reason):
    if not condition:
        raise Refusal(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)


def binding_digest(binding):
    return hashlib.sha256(canonical(binding).encode("ascii")).hexdigest()


class _Approval:
    """In-memory evidence minted only by the actual collector, never deserialized.

    Cooperative binding, not cryptographic authentication against same-UID code.
    The deadline begins before the displayed challenge, so interaction itself is
    bounded. Serialization deliberately omits authority and monotonic clock values.
    """

    def __init__(self, binding, started, seal):
        require(seal is _SEAL, "INTERACTION_REQUIRED")
        self._binding = canonical(binding)
        self._started = started
        self._pid = os.getpid()
        self._seal = seal

    def validate(self, binding):
        age = time.monotonic() - self._started
        require(self._seal is _SEAL and self._pid == os.getpid(), "INTERACTION_REQUIRED")
        require(math.isfinite(age) and 0 <= age < MAX_APPROVAL_SECONDS, "APPROVAL_EXPIRED")
        require(self._binding == canonical(binding), "APPROVAL_BINDING_CHANGED")
        return {"binding_sha256": binding_digest(binding),
                "interaction": "CONTROLLING_TTY_EXACT_CHALLENGE",
                "age_milliseconds": int(age * 1000),
                "maximum_age_seconds": MAX_APPROVAL_SECONDS}


def validate_binding(binding):
    require(type(binding) is dict and set(binding) == {
        "schema_version", "action", "intent_operation_id", "operation_id", "attempt_id",
        "intent_sha256", "store_id", "target", "publisher", "payload", "payload_sha256",
        "prior_assignee_ids", "task_binding", "implementation_head"}, "INVALID_APPROVAL_BINDING")
    require(type(binding["schema_version"]) is int and binding["schema_version"] == 1
            and binding["action"] == "add-assignee", "INVALID_APPROVAL_BINDING")
    for key in ("intent_operation_id", "operation_id", "attempt_id", "store_id"):
        require(type(binding[key]) is str and re.fullmatch(r"[0-9a-f]{32}", binding[key]),
                "INVALID_APPROVAL_BINDING")
    require(len({binding[key] for key in ("intent_operation_id", "operation_id", "attempt_id", "store_id")}) == 4,
            "REUSED_OPERATION_ID")
    for key in ("intent_sha256", "payload_sha256"):
        require(type(binding[key]) is str and re.fullmatch(r"[0-9a-f]{64}", binding[key]),
                "INVALID_APPROVAL_BINDING")
    require(type(binding["implementation_head"]) is str
            and re.fullmatch(r"[0-9a-f]{40}", binding["implementation_head"]), "INVALID_APPROVAL_BINDING")
    publisher = binding["publisher"]
    require(type(publisher) is dict and set(publisher) == {"id", "node_id", "login"},
            "INVALID_APPROVAL_BINDING")
    login = publisher["login"]
    require(type(login) is str and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", login)
            and "--" not in login, "INVALID_APPROVAL_BINDING")
    require(type(publisher["id"]) is int and 0 < publisher["id"] <= 2**63 - 1,
            "INVALID_APPROVAL_BINDING")
    require(type(publisher["node_id"]) is str
            and re.fullmatch(r"[A-Za-z0-9_+/=-]{1,256}", publisher["node_id"]), "INVALID_APPROVAL_BINDING")
    expected_payload = canonical({"assignees": [login]})
    require(binding["payload"] == expected_payload
            and binding["payload_sha256"] == hashlib.sha256(expected_payload.encode("ascii")).hexdigest(),
            "INVALID_APPROVAL_BINDING")
    target = binding["target"]
    require(type(target) is dict and set(target) == {
        "repository", "repository_id", "repository_node_id", "issue", "issue_id", "issue_node_id"},
        "INVALID_APPROVAL_BINDING")
    require(type(target["repository"]) is str and re.fullmatch(
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9][A-Za-z0-9._-]{0,99}",
        target["repository"]), "INVALID_APPROVAL_BINDING")
    for key in ("repository_id", "issue", "issue_id"):
        require(type(target[key]) is int and 0 < target[key] <= 2**63 - 1, "INVALID_APPROVAL_BINDING")
    for key in ("repository_node_id", "issue_node_id"):
        require(type(target[key]) is str and re.fullmatch(r"[A-Za-z0-9_+/=-]{1,256}", target[key]),
                "INVALID_APPROVAL_BINDING")
    ids = binding["prior_assignee_ids"]
    require(type(ids) is list and len(ids) <= 10
            and all(type(value) is int and 0 < value <= 2**63 - 1 for value in ids)
            and ids == sorted(set(ids)) and (publisher["id"] in ids or len(ids) < 10),
            "INVALID_APPROVAL_BINDING")
    # The journal validates the complete retained task binding. This collector
    # binds those exact bytes; it does not replace the core ownership validator.
    task = binding["task_binding"]
    require(type(task) is dict and set(task) == {
        "task_id", "created_at", "task_sha256", "revision", "generation", "session_id", "worker"},
        "INVALID_APPROVAL_BINDING")
    require(type(task["task_sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", task["task_sha256"])
            and type(task["worker"]) is dict, "INVALID_APPROVAL_BINDING")
    require(len(canonical(binding)) <= MAX_DISPLAY_BYTES, "APPROVAL_DISPLAY_BOUND")


def terminal_settings(attributes):
    """Compare settings without PENDIN's transient input-reprocessing state.

    The kernel may clear PENDIN while reading pending input (observed on macOS).
    It is not an approval policy setting. Preserve every other flag, speed and
    control character; platforms without PENDIN retain exact comparison.
    """
    settings = list(attributes)
    settings[3] &= ~getattr(termios, "PENDIN", 0)
    return settings


def collect_approval(binding):
    validate_binding(binding)
    return collect_terminal(binding, "APPROVE", "Assignment action (private binding; do not publish)")


def collect_terminal(binding, verb, description):
    """Read one exact challenge from /dev/tty, outside all coordinator/DB locks.

    stdin/stdout, files, environment variables and caller booleans cannot approve.
    Reject background process groups and non-canonical terminals. Flush queued input
    before displaying the challenge. Every displayed input is JSON-escaped, avoiding
    terminal control injection from private metadata. Fixtures must use a real PTY.
    """
    require(verb in {"APPROVE", "ACTIVATE", "REVOKE", "INSTALL-QUALIFICATION", "REVOKE-QUALIFICATION"}
            and len(canonical(binding)) <= MAX_DISPLAY_BYTES,
            "APPROVAL_DISPLAY_BOUND")
    # Snapshot before interaction: mutation of the caller's dict cannot rebind it.
    binding = json.loads(canonical(binding))
    fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        require(stat.S_ISCHR(os.fstat(fd).st_mode) and os.isatty(fd)
                and os.tcgetpgrp(fd) == os.getpgrp(), "FOREGROUND_CONTROLLING_TTY_REQUIRED")
        attributes = termios.tcgetattr(fd)
        require(bool(attributes[3] & termios.ICANON), "CANONICAL_TTY_REQUIRED")
        termios.tcflush(fd, termios.TCIFLUSH)
        started = time.monotonic()
        require(math.isfinite(started), "MONOTONIC_CLOCK_UNVERIFIED")
        challenge = verb + " " + binding_digest(binding)
        prompt = ("\n" + description + ":\n"
                  + canonical(binding) + "\nType exactly " + challenge
                  + " to confirm, or anything else to decline:\n")
        output = memoryview(prompt.encode("ascii"))
        while output:
            remaining = MAX_APPROVAL_SECONDS - (time.monotonic() - started)
            require(math.isfinite(remaining) and 0 < remaining <= MAX_APPROVAL_SECONDS, "APPROVAL_EXPIRED")
            _, writable, _ = select.select([], [fd], [], remaining)
            require(bool(writable), "APPROVAL_EXPIRED")
            try:
                count = os.write(fd, output)
            except BlockingIOError:
                continue
            require(count > 0, "TTY_UNAVAILABLE")
            output = output[count:]
        received = bytearray()
        while b"\n" not in received:
            remaining = MAX_APPROVAL_SECONDS - (time.monotonic() - started)
            require(math.isfinite(remaining) and 0 < remaining <= MAX_APPROVAL_SECONDS, "APPROVAL_EXPIRED")
            readable, _, _ = select.select([fd], [], [], remaining)
            require(bool(readable), "APPROVAL_EXPIRED")
            try:
                chunk = os.read(fd, 256)
            except BlockingIOError:
                continue
            require(bool(chunk) and len(received) + len(chunk) <= 256, "APPROVAL_DECLINED")
            received.extend(chunk)
        require(bytes(received) == (challenge + "\n").encode("ascii"), "APPROVAL_DECLINED")
        require(os.tcgetpgrp(fd) == os.getpgrp()
                and terminal_settings(termios.tcgetattr(fd)) == terminal_settings(attributes),
                "TTY_CHANGED_DURING_INTERACTION")
        approval = _Approval(binding, started, _SEAL)
        approval.validate(binding)
        return approval
    finally:
        os.close(fd)


def public_failure(error):
    """Exact fixed codes only, including known refusals from imported preflight modules."""
    reason = error.args[0] if len(error.args) == 1 and type(error.args[0]) is str else None
    output = {"status": "UNVERIFIED", "reason": reason if reason in PUBLIC_REASONS else
              "DISPATCH_OR_DURABILITY_UNVERIFIED", "reservation": "unverified", "completion": "UNKNOWN"}
    status = getattr(error, "http_status", None)
    if reason in PUBLIC_REASONS and type(status) is int and 100 <= status <= 599:
        output["http_status"] = status
    return output


def emit_result(output):
    """Flush before reporting completion; delivery is not a durable-state receipt."""
    try:
        encoded = canonical(output) + "\n"
        require(sys.stdout.write(encoded) == len(encoded), "FINAL_OUTPUT_UNVERIFIED")
        sys.stdout.flush()
    except Exception:
        # Do not let interpreter shutdown retry buffered output and emit a raw
        # exception. The stream may already contain a partial or complete line.
        try:
            target = sys.stdout.fileno()
            sink = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(sink, target)
            finally:
                os.close(sink)
        except Exception:
            pass
        sys.stdout = None
        try:
            sys.stderr.write("FINAL_OUTPUT_UNVERIFIED\n")
            sys.stderr.flush()
        except Exception:
            # Finalization also retries stderr. Neutralize its failed buffer so
            # that a second broken destination cannot replace exit 3 with 120.
            try:
                target = sys.stderr.fileno()
                sink = os.open(os.devnull, os.O_WRONLY)
                try:
                    os.dup2(sink, target)
                finally:
                    os.close(sink)
            except Exception:
                pass
            sys.stderr = None
        return 3
    return 0 if output.get("reservation") == "settled" else 3


def load_adapter():
    spec = importlib.util.spec_from_file_location("assignment_dispatch", Path(__file__).with_name("assignment-dispatch.py"))
    require(spec is not None and spec.loader is not None, "ADAPTER_UNAVAILABLE")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    return adapter


def main():
    output = {"status": "UNVERIFIED", "reason": "DISPATCH_OR_DURABILITY_UNVERIFIED",
              "reservation": "unverified", "completion": "UNKNOWN"}
    try:
        require(sys.flags.isolated and sys.dont_write_bytecode, "ISOLATED_PYTHON_REQUIRED")
        adapter = load_adapter()
        args = adapter.arguments()
        # Pass the live module, preserving its private collector seal.
        output = (adapter.dispatch if args.action == "assign" else adapter.recover)(args, sys.modules[__name__])
    except Exception as exc:
        output = public_failure(exc)
    return emit_result(output)


if __name__ == "__main__":
    sys.exit(main())
