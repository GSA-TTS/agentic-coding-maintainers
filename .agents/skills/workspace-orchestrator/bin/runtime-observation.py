"""Bounded local process observation for the coordination core.

`process_identity` reports whether one PID is visible to `ps` and its start time.
It is evidence about that single process only: it is not proof that descendants
stopped, that a worker's conversation or session is live, or that the task may be
released. Callers decide what an observation permits. Extracted unchanged from
`orchestrator-state.py`, which keeps a compatibility wrapper.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import selectors
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path


def process_identity(pid: int, *, environment: dict[str, str] | None = None) -> tuple[str, str | None]:
    try:
        value = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="], check=False,
            capture_output=True, text=True, timeout=3, env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown", None
    if value.returncode == 1 and value.stderr.strip():
        return "unknown", None
    if value.returncode not in (0, 1):
        return "unknown", None
    text = value.stdout.strip()
    return ("alive", text) if text else ("absent", None)


class NativeUnknown(Exception):
    """An unqualified observation, never evidence of absence."""


def _require(condition, message):
    if not condition:
        raise NativeUnknown(message)


def _decimal(value, *, positive=False):
    return (type(value) is str and len(value) <= 20
            and re.fullmatch(r"0|[1-9][0-9]*", value) is not None
            and (1 if positive else 0) <= int(value) < 2**64)


def _pid(value):
    return type(value) is int and 0 < value < 2**31


def _context(value):
    return (type(value) is dict and set(value) == {"boot_id", "pid_namespace_inode"}
            and type(value["boot_id"]) is str
            and re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value["boot_id"]) is not None
            and _decimal(value["pid_namespace_inode"], positive=True))


def valid_native_identity(value):
    """Exact ADR 0002 identity shape; do not coerce persisted values."""
    return (type(value) is dict and set(value) == {
        "schema_version", "backend", "boot_id", "pid_namespace_inode", "start_ticks"}
        and type(value["schema_version"]) is int and value["schema_version"] == 1
        and value["backend"] == "linux-procfs"
        and _context({key: value[key] for key in ("boot_id", "pid_namespace_inode")})
        and _decimal(value["start_ticks"]))


def _pairs(items):
    result = {}
    for key, value in items:
        _require(key not in result, "duplicate wire key")
        result[key] = value
    return result


def _reply(raw, request):
    _require(len(raw) <= 4096, "wire limit")
    value = json.loads(raw.decode("ascii"), object_pairs_hook=_pairs)
    _require(type(value) is dict and set(value) == {
        "version", "pid", "caller_tgid", "caller_tid", "status", "identity", "context"}, "wire shape")
    _require(type(value["version"]) is int and value["version"] == 1
             and all(_pid(value[key]) and value[key] == request[key]
                     for key in ("pid", "caller_tgid", "caller_tid")), "wire binding")
    expected = request["expected_context"]
    status, identity, context = value["status"], value["identity"], value["context"]
    _require(type(status) is str and status in ("alive", "absent", "unknown"), "wire status")
    if status == "unknown":
        _require(identity is None and context is None, "unknown payload")
    else:
        _require(_context(context) and (expected is None or context == expected), "wire context")
        if status == "alive":
            _require(valid_native_identity(identity)
                     and all(identity[key] == context[key] for key in context), "alive payload")
        else:
            _require(identity is None, "absent payload")
    return status, identity


def _regular_source(path, limit):
    # NONBLOCK prevents a substituted FIFO from stalling before its type check.
    # Regular-file I/O and process creation still have no universal kernel bound.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        _require(stat.S_ISREG(os.fstat(fd).st_mode), "installation file type")
        data = bytearray()
        for _ in range(limit // 4096 + 1):
            chunk = os.read(fd, min(4096, limit + 1 - len(data)))
            _require(len(data) + len(chunk) <= limit, "installation source limit")
            if not chunk:
                return bytes(data)
            data.extend(chunk)
        raise NativeUnknown("installation read call limit")
    finally:
        os.close(fd)


def _trusted_helper():
    """The installed checksum inventory is trusted alongside this module.

    This detects missing/mixed/substituted helper bytes, not a hostile owner who
    can rewrite the whole installation. Controller plans bind both modules too.
    """
    helper = Path(__file__).resolve().with_name("native-process-observation.py")
    manifest = helper.parent.parent / "CANONICAL-SHA256SUMS"
    inventory = _regular_source(manifest, 65536)
    entries = [line.split(b"  ", 1)[0] for line in inventory.splitlines()
               if line.endswith(b"  ./bin/native-process-observation.py")]
    _require(len(entries) == 1 and re.fullmatch(rb"[0-9a-f]{64}", entries[0]), "helper inventory")
    data = _regular_source(helper, 65536)
    _require(hashlib.sha256(data).hexdigest().encode() == entries[0], "helper checksum")
    return helper, data


# Only this fixed bootstrap is interpreter code supplied with -c. The verified
# immutable snapshot is data, never a pathname reopened by the child. Compile's
# filename and __file__ preserve diagnostics and installed-sibling semantics.
_NATIVE_BOOTSTRAP = (
    "import base64,sys;"
    "source=base64.b64decode(sys.argv[1],validate=True);"
    "path=sys.argv[2];request=sys.argv[3];sys.argv=[path,request];"
    "exec(compile(source,path,'exec'),"
    "{'__name__':'__main__','__file__':path,'__package__':None,'__spec__':None})"
)


def _collect(command):
    """Three-second collection deadline and 4 KiB combined output budget.

    Spawn and uninterruptible kernel waits cannot have a universal wall-clock
    bound. Cleanup has a separate one-second kill/reap deadline; failure to reap
    yields unknown. The caller retains responsibility for an unreaped helper
    (normal Popen child bookkeeping also retains it); no supervisor is created.
    """
    deadline = time.monotonic() + 3
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, close_fds=True,
                             env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    try:
        output, errors = bytearray(), bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ, output)
            selector.register(child.stderr, selectors.EVENT_READ, errors)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                _require(remaining > 0, "helper deadline")
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fd, 4096)
                    _require(len(output) + len(errors) + len(chunk) <= 4096, "helper output limit")
                    if not chunk:
                        selector.unregister(key.fd)
                    key.data.extend(chunk)
        remaining = deadline - time.monotonic()
        _require(remaining > 0, "helper deadline")
        _require(child.wait(timeout=remaining) == 0 and not errors, "helper exit/stderr")
        _require(time.monotonic() <= deadline, "helper deadline")
        return bytes(output)
    finally:
        try:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=1)
        finally:
            child.stdout.close()
            child.stderr.close()


def _native_observation(pid, expected=None):
    if not _pid(pid) or (expected is not None and not _context(expected)):
        return "unknown", None
    try:
        _require(sys.platform == "linux" and os.path.isabs(sys.executable), "native platform")
        helper, snapshot = _trusted_helper()
        encoded = base64.b64encode(snapshot).decode("ascii")
        request = {"version": 1, "pid": pid, "caller_tgid": os.getpid(),
                   "caller_tid": threading.get_native_id(), "expected_context": expected}
        raw = _collect([sys.executable, "-I", "-B", "-c", _NATIVE_BOOTSTRAP, encoded,
                        str(helper), json.dumps(request, separators=(",", ":"))])
        return _reply(raw, request)
    except (NativeUnknown, OSError, ValueError, RecursionError, subprocess.SubprocessError):
        return "unknown", None


def native_process_identity(pid: int) -> tuple[str, dict | None]:
    """Observe one PID using only the qualified native helper profile."""
    return _native_observation(pid)


def observe_worker_process(worker: dict, *, environment: dict[str, str] | None = None) -> tuple[str, str | dict | None]:
    """Record-directed observation; task/ownership validation belongs to callers.

    The native identity's start ticks may differ (PID reuse); return the observed
    object for exact comparison. Boot/namespace mismatch is always unknown.
    """
    if type(worker) is not dict or not _pid(worker.get("pid")):
        return "unknown", None
    legacy, native = "process_start" in worker, "process_identity" in worker
    if legacy == native:
        return "unknown", None
    if legacy:
        if type(worker["process_start"]) is not str:
            return "unknown", None
        return process_identity(worker["pid"], environment=environment)
    identity = worker["process_identity"]
    if not valid_native_identity(identity):
        return "unknown", None
    return _native_observation(worker["pid"], {key: identity[key] for key in ("boot_id", "pid_namespace_inode")})
