#!/usr/bin/env python3
"""Explicit local claim-publication intent; no dispatcher or remote effects."""

import contextlib
import copy
import importlib.util
import os
import stat
import sys
from pathlib import Path


def result(status, reason, request=None):
    value = {"status": status, "reason": reason, "mutation_authorized": False,
             "remote_effects_enabled": False}
    if request is not None:
        value.update(operation_id=request["operation_id"], comment_sha256=request["comment_sha256"])
    return value


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("trusted module unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def modules():
    source = Path(__file__).resolve().parents[1]
    installed = source / ".agents/skills/workspace-orchestrator/bin"
    return (load("intent_prepare", source / "scripts/prepare-task-claim.py"),
            load("intent_core", installed / "orchestrator-state.py"),
            load("intent_journal", installed / "monitor-journal.py"))


def durable(journal, db, root):
    """Complete commit/replay durability on the selected private physical file."""
    path = journal.check_path(root)
    with contextlib.ExitStack() as stack:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, directory)
        fd = os.open("history.sqlite3", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        stack.callback(os.close, fd)
        before = os.fstat(fd)
        if (db.file_identity != (before.st_dev, before.st_ino)
                or not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or before.st_nlink != 1 or before.st_mode & 0o077 or before.st_size > journal.MAX_DB):
            raise journal.JournalError("database identity differs before sync")
        # check_path validates modes, ownership, sidecars and link count, not
        # only identity. The second check detects replacements during barriers.
        journal.check_path(root)
        os.fsync(fd)
        os.fsync(directory)
        after = journal.check_path(root).lstat()
        opened = os.fstat(fd)
        if (db.file_identity != (after.st_dev, after.st_ino)
                or db.file_identity != (opened.st_dev, opened.st_ino)
                or opened.st_uid != os.getuid() or opened.st_nlink != 1 or opened.st_mode & 0o077
                or (before.st_size, before.st_mtime_ns) != (opened.st_size, opened.st_mtime_ns)):
            raise journal.JournalError("database changed during sync")
        parent = os.open(path.parent.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, parent)
        os.fsync(parent)


def record(args, claim, prepare, core, journal):
    """Lock order: coordinator then SQLite. Never hold SQLite while acquiring coordinator."""
    preflight = prepare.preflight
    with contextlib.ExitStack() as stack:
        authority = preflight.physical_root(args.authority_root, stack)
        invoking = preflight.physical_root(args.invoking_root, stack)
        left, right = os.fstat(authority), os.fstat(invoking)
        if (left.st_dev, left.st_ino) != (right.st_dev, right.st_ino):
            return result("CONFLICT", "ROOT_MISMATCH")
        store = preflight.directory(authority, ".orchestrator", stack, private=True)
        preflight.directory(store, "locks", stack, private=True)
        root = Path(args.authority_root) / ".orchestrator"
        with core.CoordinatorLock(root):
            retained = []
            task, identity = prepare.selected(args, stack, retained)
            preflight.validate_task(task)
            preflight.require(task["schema_version"] == 3, "UNSUPPORTED_SCHEMA")

            def fresh():
                output = prepare.prepare(args, claim)
                if output["status"] != "PREPARED_RETAINED_MATCH":
                    # Only fixed codes are exposed at the CLI boundary.
                    raise IntentRefusal(output["status"], output["reason"])
                prepare.unchanged(args, stack, retained, task, identity)
                current = os.fstat(store)
                selected = preflight.directory(authority, ".orchestrator", stack, private=True)
                observed = os.fstat(selected)
                preflight.require((current.st_dev, current.st_ino) == (observed.st_dev, observed.st_ino),
                                  "CHANGED_DURING_READ")
                return output

            public = fresh()
            # Input and current ownership validation precede even directory creation.
            monitor = root / "monitor"
            monitor.mkdir(mode=0o700, exist_ok=True)
            monitor_fd = preflight.directory(store, "monitor", stack, private=True)
            db = journal.open_store(monitor, writable=True)
            try:
                request = {"schema_version": 1, "action": "claim-publication",
                           "operation_id": claim["operation_id"],
                           "store_id": db.execute("SELECT store_id FROM meta").fetchone()[0],
                           "claim": copy.deepcopy(claim), "comment": public["comment"],
                           "comment_sha256": public["comment_sha256"],
                           "binding": {"task_id": task["task_id"], "created_at": task["created_at"],
                                       "task_sha256": journal.fingerprint(task), "revision": task["revision"],
                                       "generation": task["cooperative_binding"]["generation"],
                                       "session_id": task["cooperative_binding"]["session_id"],
                                       "worker": copy.deepcopy(task["worker"])}}

                def guarded():
                    fresh()
                    original = os.fstat(monitor_fd)
                    current_fd = preflight.directory(store, "monitor", stack, private=True)
                    current = os.fstat(current_fd)
                    preflight.require((original.st_dev, original.st_ino) == (current.st_dev, current.st_ino),
                                      "CHANGED_DURING_READ")
                    selected = journal.check_path(monitor).lstat()
                    if db.file_identity != (selected.st_dev, selected.st_ino):
                        raise journal.JournalError("database identity changed")

                status = journal.record_claim_intent(db, request, guard=guarded)
                durable(journal, db, monitor)
                guarded()
                return result(status, "LOCAL_PENDING_ONLY", request)
            finally:
                db.close()


class IntentRefusal(Exception):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason


def main():
    output = result("UNVERIFIED", "STORE_OR_DURABILITY_UNVERIFIED")
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        output = result("UNVERIFIED", "ISOLATED_PYTHON_REQUIRED")
    else:
        try:
            prepare, core, journal = modules()
            # Reuse the actual unchanged single-occurrence parser and preparation
            # API; invoking this separate command explicitly requests local record.
            try:
                args, claim = prepare.arguments()
            except prepare.codec.Unverified as exc:
                raise IntentRefusal("UNVERIFIED", str(exc)) from exc
            try:
                output = record(args, claim, prepare, core, journal)
            except IntentRefusal as exc:
                output = result(exc.status, exc.reason)
            except (prepare.codec.Unverified, prepare.preflight.Unverified) as exc:
                output = result("UNVERIFIED", str(exc))
            except core.BusyError:
                output = result("CONFLICT", "COORDINATOR_BUSY")
            except journal.JournalError as exc:
                if str(exc) == "conflicting claim operation":
                    output = result("CONFLICT", "OPERATION_CONFLICT")
                elif str(exc) == "claim intent capacity reached":
                    output = result("CONFLICT", "INTENT_CAPACITY_REACHED")
        except IntentRefusal as exc:
            output = result(exc.status, exc.reason)
        except Exception:
            # Includes parsing, SQLite busy/commit failures and private filesystem
            # errors. A row may survive; exact fresh retry is the recovery API.
            output = result("UNVERIFIED", "STORE_OR_DURABILITY_UNVERIFIED")
    import json
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 4 if output["status"] == "CONFLICT" else 0 if output["status"] in {"INTENT_RECORDED", "REPLAYED_PENDING"} else 3


if __name__ == "__main__":
    sys.exit(main())
