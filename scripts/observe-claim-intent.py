#!/usr/bin/env python3
"""Read-only correlation of one current local intent with fresh visible comments."""

import contextlib
import json
import os
import sys
import time
from pathlib import Path


def report(status, reason):
    return {"schema_version": 1, "status": status, "reason": reason,
            "remote_coverage": "unmeasured", "atomic_snapshot": False,
            "mutation_authorized": False, "absence_authorizing": False,
            "bound_retained_snapshot": False, "current_task_authority": "UNVERIFIED",
            "remote_operation_completion": "UNVERIFIED"}


def modules():
    import importlib.util

    def load(name, filename):
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
        if spec is None or spec.loader is None:
            raise ValueError("module unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    intent = load("observe_intent_cli", "journal-claim-intent.py")
    prepare, _, journal = intent.modules()
    return prepare, journal, load("observe_intent_remote", "observe-github-claims.py")


def arguments(prepare):
    # Reuse the journal CLI's actual preparation parser, including every required
    # fence and canonical public input. Only the optional private store fence is
    # extracted here; there is no second public-request builder.
    parser = prepare.codec.Parser(allow_abbrev=False, add_help=False)
    parser.add_argument("--store-id", action=prepare.codec.StoreOnce)
    extra, remaining = parser.parse_known_args()
    if extra.store_id is not None:
        prepare.codec.require(prepare.preflight.HEX32.fullmatch(extra.store_id) is not None,
                              "INVALID_ARGUMENTS")
    original = sys.argv
    try:
        sys.argv = [original[0], *remaining]
        args, claim = prepare.arguments()
    finally:
        sys.argv = original
    args.store_id = extra.store_id
    return args, claim


def snapshot(args, claim, prepare, journal):
    """Existing schema-3 API, exact selected row, private physical-file fences.

    All descriptors and the read-only SQLite connection close before returning.
    No CoordinatorLock is acquired: that API creates a lock directory. Repeated
    bounded reads provide retained consistency, not an atomic locked snapshot.
    """
    preflight = prepare.preflight
    with contextlib.ExitStack() as stack:
        retained = []
        task, identity = prepare.selected(args, stack, retained)
        if identity is None:
            raise Refusal("CONFLICT", "ROOT_MISMATCH")
        preflight.validate_task(task)
        preflight.require(task["schema_version"] == 3, "UNSUPPORTED_SCHEMA")
        public = prepare.prepare(args, claim)
        if public["status"] != "PREPARED_RETAINED_MATCH":
            raise Refusal(public["status"], public["reason"])
        authority = preflight.physical_root(args.authority_root, stack)
        store = preflight.directory(authority, ".orchestrator", stack, private=True)
        monitor_fd = preflight.directory(store, "monitor", stack, private=True)
        directories = tuple((os.fstat(fd).st_dev, os.fstat(fd).st_ino)
                            for fd in (authority, store, monitor_fd))
        preflight.require(directories[0] == identity, "CHANGED_DURING_READ")
        # Preserve lease file fingerprints across the network interval, rather
        # than merely accepting a later independently valid ownership summary.
        leases = task["leases"]
        paths = [["scopes", task["scope_key"] + ".lock", "owner.json"],
                 ["slots", str(leases["global_slot"]) + ".lock", "owner.json"]]
        if leases["implementation_lane"] is not None:
            paths.append(["implementation", str(leases["implementation_lane"]) + ".lock", "owner.json"])
        lease_retained = []
        lease_values = [preflight.read_selected(store, path, stack, lease_retained) for path in paths]
        monitor = Path(args.authority_root) / ".orchestrator/monitor"

        def files():
            database = journal.check_path(monitor)
            return tuple((name, preflight.fingerprint(path.lstat()) if path.exists() else None)
                         for name in ("", "-journal", "-wal", "-shm")
                         for path in (Path(str(database) + name),))

        before = files()
        # A read-only SQLite WAL open can create shared-memory sidecars. Refuse
        # recovery/WAL storage BEFORE SQLite opens it, even when files are private.
        preflight.require(all(stamp is None for _, stamp in before[1:]), "JOURNAL_RECOVERY_UNVERIFIED")
        fd = os.open("history.sqlite3", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=monitor_fd)
        stack.callback(os.close, fd)
        preflight.require(preflight.fingerprint(os.fstat(fd)) == before[0][1], "CHANGED_DURING_READ")
        header = os.read(fd, 20)
        preflight.require(header[:16] == b"SQLite format 3\x00" and header[18:20] == b"\x01\x01",
                          "JOURNAL_RECOVERY_UNVERIFIED")
        db = journal.open_store(monitor, writable=False)
        try:
            db.execute("BEGIN")
            journal.validate_store(db)
            version, store_id = db.execute("SELECT version,store_id FROM meta").fetchone()
            preflight.require(version == 3, "UNSUPPORTED_JOURNAL_SCHEMA")
            if args.store_id is not None and args.store_id != store_id:
                raise Refusal("CONFLICT", "STORE_ID_MISMATCH")
            rows = db.execute("SELECT request,request_sha256 FROM claim_intents WHERE operation_id=?",
                              (claim["operation_id"],)).fetchall()
            preflight.require(len(rows) == 1, "INTENT_NOT_FOUND")
            raw, request_sha256 = rows[0]
            request = journal.decode_intent(raw)
            journal.validate_claim_intent(request)
            binding = request["binding"]
            # Compare the validated immutable request directly. The recording CLI
            # has no exported builder; do not copy its request construction here.
            if (request["store_id"] != store_id or request["claim"] != claim
                    or request["comment"] != public["comment"]
                    or request["comment_sha256"] != public["comment_sha256"]
                    or request_sha256 != journal.fingerprint(request)
                    or binding["task_sha256"] != journal.fingerprint(task)
                    or any(binding[key] != task[key] for key in ("task_id", "created_at", "revision", "worker"))
                    or any(binding[key] != task["cooperative_binding"][key]
                           for key in ("session_id", "generation"))):
                raise Refusal("CONFLICT", "OPERATION_CONFLICT")
            selected = journal.check_path(monitor).lstat()
            preflight.require(db.file_identity == (selected.st_dev, selected.st_ino), "CHANGED_DURING_READ")
        finally:
            db.close()
        fresh = prepare.prepare(args, claim)
        preflight.require(fresh == public and files() == before
                          and preflight.fingerprint(os.fstat(fd)) == before[0][1], "CHANGED_DURING_READ")
        prepare.unchanged(args, stack, retained, task, identity)
        preflight.require(all(preflight.fingerprint(os.fstat(fd)) == stamp
                              for fd, stamp in retained + lease_retained),
                          "CHANGED_DURING_READ")
        current_store = preflight.directory(authority, ".orchestrator", stack, private=True)
        current_monitor = preflight.directory(current_store, "monitor", stack, private=True)
        preflight.require(directories == tuple((os.fstat(fd).st_dev, os.fstat(fd).st_ino)
                                              for fd in (authority, current_store, current_monitor)),
                          "CHANGED_DURING_READ")
        return (raw, request_sha256, identity, directories, before, task,
                tuple(stamp for _, stamp in retained + lease_retained), lease_values), request["comment"]


class Refusal(Exception):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason


def observe(args, claim, prepare, journal, observer):
    before, body = snapshot(args, claim, prepare, journal)
    # No private snapshot is accepted from a file or exported. Only this in-memory
    # body from the just-validated selected request reaches the internal matcher.
    transport = observer.Transport(claim["repo"], claim["issue"],
                                   time.monotonic() + observer.DEADLINE_SECONDS)
    try:
        remote = observer.observe(claim["repo"], claim["issue"], transport, expected_body=body)
    finally:
        try:
            after, _ = snapshot(args, claim, prepare, journal)
            if after != before:
                raise Refusal("UNVERIFIED", "LOCAL_SNAPSHOT_CHANGED")
        except Exception as exc:
            raise Refusal("UNVERIFIED", "LOCAL_SNAPSHOT_CHANGED") from exc
    if remote["status"] == "CONFLICT":
        output = report("CONFLICT", "OBSERVED_CONFLICT")
    elif remote["exact_match_comment_id"] is not None:
        output = report("VISIBLE_MATCH", "EXACT_PENDING_INTENT_VISIBLE")
        output.update(comment_id=remote["exact_match_comment_id"],
                      comment_sha256=remote["expected_body_sha256"])
    else:
        output = report("UNVERIFIED", "NO_MATCH_OBSERVED")
    output.update(bound_retained_snapshot=True)
    for key in ("remote_coverage", "repository_id", "issue_id", "issue_number", "issue_closed",
                "issue_locked", "page_count", "comment_count", "recognized_claim_count"):
        output[key] = remote[key]
    return output


def main():
    output = report("UNVERIFIED", "READ_UNAVAILABLE")
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        output = report("UNVERIFIED", "ISOLATED_PYTHON_REQUIRED")
    else:
        try:
            prepare, journal, observer = modules()
            try:
                args, claim = arguments(prepare)
                output = observe(args, claim, prepare, journal, observer)
            except Refusal as exc:
                output = report(exc.status, exc.reason)
            except (prepare.codec.Unverified, prepare.preflight.Unverified, observer.Unverified) as exc:
                output = report("UNVERIFIED", str(exc))
        except Exception:
            # SQLite/filesystem/process failures may contain private data. No
            # arbitrary exception text, raw body or subprocess diagnostics escape.
            output = report("UNVERIFIED", "READ_UNAVAILABLE")
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 4 if output["status"] == "CONFLICT" else 3


if __name__ == "__main__":
    sys.exit(main())
