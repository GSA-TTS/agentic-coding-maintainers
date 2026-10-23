#!/usr/bin/env python3
"""Append one validated event to a private local ledger (no GitHub writes)."""

import sys

if not sys.flags.isolated or not sys.dont_write_bytecode:
    print("cohort append: UNVERIFIED — run with python3 -I -B", file=sys.stderr)
    sys.exit(3)

import argparse
import contextlib
import datetime
import fcntl
import importlib.util
import json
import os
import pathlib
import stat
import time

MAX_INPUT = 8192
LOCK_WAIT_SECONDS = 5.0


def load_reader():
    # Load only our own trusted sibling, never code selected by --ledger.
    path = pathlib.Path(__file__).resolve().with_name("cohort-reflection.py")
    spec = importlib.util.spec_from_file_location("cohort_reflection_writer", path)
    if spec is None or spec.loader is None:
        raise ValueError("trusted ledger validator unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parent_fd(path: pathlib.Path) -> int:
    """Open the given private directory without following untrusted ancestors."""
    if not path.is_absolute() or path.name in ("", ".", ".."):
        raise ValueError("ledger must be an absolute path under a private directory")
    if sys.platform == "darwin" and path.parts[:2] == ("/", "var"):
        path = pathlib.Path("/private/var", *path.parts[2:])
    with contextlib.ExitStack() as stack:
        fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, fd)
        for part in path.parent.parts[1:]:
            if part in (".", ".."):
                raise ValueError("relative path component")
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            stack.callback(os.close, next_fd)
            fd = next_fd
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("ledger directory must be current-user private (0700)")
        return os.dup(fd)


def append(path: pathlib.Path, proposed: dict, reader) -> None:
    if not isinstance(proposed, dict) or "recorded_at" in proposed:
        raise ValueError("submit one event object without recorded_at; the writer sets it")
    with contextlib.ExitStack() as stack:
        directory = parent_fd(path)
        stack.callback(os.close, directory)
        # A ledger is initialized explicitly by the operator. Refusing a
        # missing ledger avoids a half-created empty file if validation fails.
        flags = os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open(path.name, flags, dir_fd=directory)
        with os.fdopen(fd, "r+b", buffering=0) as ledger:
            deadline = time.monotonic() + LOCK_WAIT_SECONDS
            while True:
                try:
                    fcntl.flock(ledger, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("ledger is locked; no append attempted") from exc
                    time.sleep(0.05)
            if os.stat(path.name, dir_fd=directory, follow_symlinks=False).st_ino != os.fstat(ledger.fileno()).st_ino:
                raise ValueError("ledger pathname changed during append")
            info = os.fstat(ledger.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("ledger must be a private, current-user regular file (0600)")
            if info.st_size > reader.MAX_BYTES:
                raise ValueError("ledger exceeds byte limit")
            current = ledger.read(reader.MAX_BYTES + 1)
            if len(current) > reader.MAX_BYTES:
                raise ValueError("ledger grew past byte limit")
            now = datetime.datetime.now(datetime.timezone.utc)
            if current:
                reader.events_from(current, now)
            event = dict(proposed)
            event["recorded_at"] = now.isoformat(timespec="microseconds").replace("+00:00", "Z")
            line = (json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
            if len(current) + len(line) > reader.MAX_BYTES:
                raise ValueError("new event exceeds ledger byte limit")
            # Revalidate the entire candidate before writing anything; this
            # catches duplicate IDs, forward/cross-case refs, invalid types,
            # timestamps, and event-count overflow in the reader's own contract.
            reader.events_from(current + line, now)
            if os.stat(path.name, dir_fd=directory, follow_symlinks=False).st_ino != info.st_ino:
                raise ValueError("ledger pathname changed before append")
            # O_APPEND places the write at the current EOF even if a writer
            # ignoring flock extended the file after our validation. That
            # noncooperating writer can still invalidate the full ledger;
            # the postcheck below refuses to report a verified append.
            if ledger.write(line) != len(line):
                # A partial append is intentionally NOT silently repaired;
                # the reader will fail closed on an incomplete final line.
                raise OSError("event append was incomplete; inspect the ledger")
            os.fsync(ledger.fileno())
            final = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
            if final.st_ino != info.st_ino or final.st_dev != info.st_dev:
                raise OSError("ledger path replaced after append; inspect before retry")
            ledger.seek(0)
            try:
                verified = ledger.read(reader.MAX_BYTES + 1)
                reader.events_from(verified, datetime.datetime.now(datetime.timezone.utc))
            except Exception as exc:
                raise OSError("ledger changed during append; inspect before retry") from exc
            if verified != current + line:
                raise OSError("ledger differs from validated append; inspect before retry")


def initialize(path: pathlib.Path) -> None:
    """Exclusive-create an empty private ledger; never truncate an existing one."""
    with contextlib.ExitStack() as stack:
        directory = parent_fd(path)
        stack.callback(os.close, directory)
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        with os.fdopen(fd, "wb", buffering=0) as ledger:
            os.fsync(ledger.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=pathlib.Path)
    parser.add_argument("--init", action="store_true", help="exclusively create an empty private ledger")
    args = parser.parse_args()
    try:
        if args.init:
            if sys.stdin.buffer.read(1):
                raise ValueError("initialization takes no event on stdin")
            initialize(args.ledger)
            print("cohort append: initialized private ledger")
            return 0
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if not raw or len(raw) > MAX_INPUT:
            raise ValueError("one event on stdin is required (max 8192 bytes)")
        reader = load_reader()
        proposed = json.loads(raw, object_pairs_hook=reader.unique_fields)
        append(args.ledger, proposed, reader)
    except Exception as exc:  # includes the trusted sibling's Unverified type
        # Never echo operator-provided event text, filesystem errors containing
        # private paths, or exception bodies that could include sensitive IDs.
        print(f"cohort append: UNVERIFIED — {type(exc).__name__}; event may have been written; inspect event_id before retry", file=sys.stderr)
        return 3
    print("cohort append: recorded (not independently verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
