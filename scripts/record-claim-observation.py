#!/usr/bin/env python3
"""Explicit durable historical claim observation; no remote mutation or authority."""

import contextlib
import json
import os
import sys
from pathlib import Path


def modules():
    import importlib.util

    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ValueError("module unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    intent = load("receipt_intent", Path(__file__).with_name("journal-claim-intent.py"))
    prepare, core, journal = intent.modules()
    observe = load("receipt_observe", Path(__file__).with_name("observe-claim-intent.py"))
    _, _, observer = observe.modules()
    return prepare, core, journal, intent, observe, observer


def result(status, reason, receipt=None, journal=None):
    output = {"schema_version": 1, "status": status, "reason": reason,
              "historical": True, "stored_freshness_current": False,
              "atomic_snapshot": False, "mutation_authorized": False,
              "absence_authorizing": False, "remote_effects_enabled": False,
              "current_task_authority": "UNVERIFIED", "remote_operation_completion": "UNVERIFIED"}
    if receipt is not None:
        output.update(observation_id=receipt["observation_id"], receipt_sha256=journal.fingerprint(receipt),
                      observation_status="HISTORICAL_" + receipt["status"])
    return output


def arguments(prepare, observe):
    parser = prepare.codec.Parser(allow_abbrev=False, add_help=False)
    parser.add_argument("--observation-id", required=True, action=prepare.codec.StoreOnce)
    parser.add_argument("--show", action="store_true")
    extra, remaining = parser.parse_known_args()
    prepare.codec.require(prepare.preflight.HEX32.fullmatch(extra.observation_id) is not None,
                          "INVALID_OBSERVATION_ID")
    original = sys.argv
    try:
        sys.argv = [original[0], *remaining]
        if extra.show:
            show_parser = prepare.codec.Parser(allow_abbrev=False)
            show_parser.add_argument("--authority-root", required=True, action=prepare.codec.StoreOnce)
            args = show_parser.parse_args()
            claim = None
        else:
            args, claim = observe.arguments(prepare)
    finally:
        sys.argv = original
    args.observation_id, args.show = extra.observation_id, extra.show
    return args, claim


def show(args, prepare, journal):
    """Read-only physical DELETE-mode journal snapshot; no current task lookup."""
    preflight = prepare.preflight
    with contextlib.ExitStack() as stack:
        authority = preflight.physical_root(args.authority_root, stack)
        store = preflight.directory(authority, ".orchestrator", stack, private=True)
        monitor_fd = preflight.directory(store, "monitor", stack, private=True)
        monitor = Path(args.authority_root) / ".orchestrator/monitor"
        path = journal.check_path(monitor)
        preflight.require(not any(Path(str(path) + suffix).exists() for suffix in ("-journal", "-wal", "-shm")),
                          "JOURNAL_RECOVERY_UNVERIFIED")
        fd = os.open("history.sqlite3", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=monitor_fd)
        stack.callback(os.close, fd)
        before = preflight.fingerprint(os.fstat(fd))
        header = os.read(fd, 20)
        preflight.require(header[:16] == b"SQLite format 3\x00" and header[18:20] == b"\x01\x01",
                          "JOURNAL_RECOVERY_UNVERIFIED")
        db = journal.open_store(monitor, writable=False)
        try:
            db.execute("BEGIN")
            journal.validate_store(db)
            receipt = journal.claim_observation(db, args.observation_id)
            preflight.require(receipt is not None, "OBSERVATION_NOT_FOUND")
            preflight.require(db.file_identity == (os.fstat(fd).st_dev, os.fstat(fd).st_ino),
                              "CHANGED_DURING_READ")
        finally:
            db.close()
        current_store = preflight.directory(authority, ".orchestrator", stack, private=True)
        current_monitor = preflight.directory(current_store, "monitor", stack, private=True)
        preflight.require(before == preflight.fingerprint(os.fstat(fd))
                          == preflight.fingerprint(journal.check_path(monitor).lstat())
                          and not any(Path(str(path) + suffix).exists() for suffix in ("-journal", "-wal", "-shm"))
                          and (os.fstat(monitor_fd).st_dev, os.fstat(monitor_fd).st_ino)
                          == (os.fstat(current_monitor).st_dev, os.fstat(current_monitor).st_ino),
                          "CHANGED_DURING_READ")
        return result("HISTORICAL_SHOWN", "LOCAL_HISTORY_ONLY", receipt, journal)


def record(args, claim, prepare, core, journal, intent, observe, observer):
    initial = observe.snapshot(args, claim, prepare, journal, args.observation_id)
    before, _ = initial
    task = before[5]
    # Explicit known-identifier equality, including private surviving recovery IDs.
    prepare.codec.require(args.observation_id not in prepare.private_tokens(task, args)
                          | {claim["claim_id"], claim["operation_id"], json.loads(before[0])["store_id"]},
                          "PRIVATE_IDENTIFIER_REUSE")
    prior = before[8]
    if prior is not None and (prior["operation_id"] != claim["operation_id"]
                              or prior["intent_request_sha256"] != before[1]):
        raise observe.Refusal("CONFLICT", "OBSERVATION_CONFLICT")
    # Replay never invokes the observer, even if the remote state has changed.
    collected = None if prior is not None else observe.collect(
        args, claim, prepare, journal, observer, initial=initial, observation_id=args.observation_id)
    if collected is not None:
        remote = collected.remote
        status = "CONFLICT" if remote["status"] == "CONFLICT" else (
            "VISIBLE_MATCH" if remote["exact_match_comment_id"] is not None else "NO_MATCH_OBSERVED")
        summary = {key: remote[key] for key in ("remote_coverage", "repository_id", "issue_id",
                   "issue_number", "issue_closed", "issue_locked", "page_count", "comment_count",
                   "recognized_claim_count")}
        summary.update(comment_id=remote["exact_match_comment_id"] if status == "VISIBLE_MATCH" else None,
                       comment_sha256=remote["expected_body_sha256"] if status == "VISIBLE_MATCH" else None)
        receipt = {"schema_version": 1, "observation_id": args.observation_id,
                   "operation_id": claim["operation_id"], "store_id": json.loads(before[0])["store_id"],
                   "intent_request_sha256": before[1], "status": status,
                   "reason": {"CONFLICT": "OBSERVED_CONFLICT", "VISIBLE_MATCH": "EXACT_PENDING_INTENT_VISIBLE",
                              "NO_MATCH_OBSERVED": "NO_MATCH_OBSERVED"}[status],
                   "summary": summary, "observed_at": collected.observed_at}
    else:
        receipt = prior
    preflight = prepare.preflight
    with contextlib.ExitStack() as stack:
        authority = preflight.physical_root(args.authority_root, stack)
        store = preflight.directory(authority, ".orchestrator", stack, private=True)
        preflight.directory(store, "locks", stack, private=True)
        root = Path(args.authority_root) / ".orchestrator"
        with core.CoordinatorLock(root):
            current, _ = observe.snapshot(args, claim, prepare, journal, args.observation_id)
            if current != before:
                raise observe.Refusal("UNVERIFIED", "LOCAL_SNAPSHOT_CHANGED")
            monitor = root / "monitor"
            preflight.directory(store, "monitor", stack, private=True)
            retained = []
            selected, identity = prepare.selected(args, stack, retained)
            leases = []
            paths = [["scopes", task["scope_key"] + ".lock", "owner.json"],
                     ["slots", str(task["leases"]["global_slot"]) + ".lock", "owner.json"]]
            if task["leases"]["implementation_lane"] is not None:
                paths.append(["implementation", str(task["leases"]["implementation_lane"]) + ".lock", "owner.json"])
            values = [preflight.read_selected(store, path, stack, leases) for path in paths]
            prepare.unchanged(args, stack, retained, task, identity)
            preflight.require(selected == task and identity == before[2] and values == before[7]
                              and tuple(stamp for _, stamp in retained + leases) == before[6],
                              "CHANGED_DURING_READ")
            preflight.require(preflight.fingerprint(journal.check_path(monitor).lstat()) == before[4][0][1],
                              "CHANGED_DURING_READ")
            db = journal.open_store(monitor, writable=True)
            try:
                def guard():
                    # Our SQLite append changes the database fingerprint. Compare
                    # task/lease fingerprints and physical database identity here,
                    # not a pre-write whole-journal fingerprint against our write.
                    public = prepare.prepare(args, claim)
                    preflight.require(public["status"] == "PREPARED_RETAINED_MATCH", "CHANGED_DURING_READ")
                    prepare.unchanged(args, stack, retained, task, identity)
                    preflight.require(all(preflight.fingerprint(os.fstat(fd)) == stamp for fd, stamp in leases),
                                      "CHANGED_DURING_READ")
                    fresh_leases = []
                    fresh_values = [preflight.read_selected(store, path, stack, fresh_leases) for path in paths]
                    fresh_store = preflight.directory(authority, ".orchestrator", stack, private=True)
                    fresh_monitor = preflight.directory(fresh_store, "monitor", stack, private=True)
                    preflight.require(fresh_values == values
                        and tuple(stamp for _, stamp in fresh_leases) == tuple(stamp for _, stamp in leases)
                        and before[3] == tuple(
                        (os.fstat(fd).st_dev, os.fstat(fd).st_ino) for fd in (authority, fresh_store, fresh_monitor)),
                        "CHANGED_DURING_READ")
                    info = journal.check_path(monitor).lstat()
                    preflight.require(db.file_identity == (info.st_dev, info.st_ino)
                                      == (before[4][0][1][0], before[4][0][1][1]), "CHANGED_DURING_READ")
                    journal.validate_store(db)
                    journal.validate_claim_observation(db, receipt)
                    row = db.execute("SELECT request,request_sha256 FROM claim_intents WHERE operation_id=?",
                                     (claim["operation_id"],)).fetchone()
                    preflight.require(tuple(row) == before[:2], "CHANGED_DURING_READ")

                status = journal.record_claim_observation(db, receipt, guard=guard)
                intent.durable(journal, db, monitor)
                guard()
                return result(status, "LOCAL_HISTORY_ONLY", receipt, journal)
            finally:
                db.close()


def main():
    output = result("UNVERIFIED", "STORE_OR_DURABILITY_UNVERIFIED")
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        output = result("UNVERIFIED", "ISOLATED_PYTHON_REQUIRED")
    else:
        try:
            prepare, core, journal, intent, observe, observer = modules()
            try:
                args, claim = arguments(prepare, observe)
                output = show(args, prepare, journal) if args.show else record(
                    args, claim, prepare, core, journal, intent, observe, observer)
            except observe.Refusal as exc:
                output = result(exc.status, exc.reason)
            except (prepare.codec.Unverified, prepare.preflight.Unverified, observer.Unverified) as exc:
                output = result("UNVERIFIED", str(exc))
            except core.BusyError:
                output = result("CONFLICT", "COORDINATOR_BUSY")
            except journal.JournalError as exc:
                if str(exc) in {"conflicting claim observation", "claim observation capacity reached"}:
                    output = result("CONFLICT", "OBSERVATION_CONFLICT" if str(exc) == "conflicting claim observation"
                                    else "OBSERVATION_CAPACITY_REACHED")
        except Exception:
            output = result("UNVERIFIED", "STORE_OR_DURABILITY_UNVERIFIED")
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 4 if output["status"] == "CONFLICT" or output.get("observation_status") == "HISTORICAL_CONFLICT" else 3


if __name__ == "__main__":
    sys.exit(main())
