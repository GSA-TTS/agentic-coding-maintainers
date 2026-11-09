#!/usr/bin/env python3
"""Explicit identity-bound local intent; fresh GET evidence grants no authority."""

import contextlib
import copy
import os
import sys
import uuid
from pathlib import Path


def modules():
    import importlib.util

    def load(name, filename):
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
        if spec is None or spec.loader is None:
            raise ValueError("trusted module unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    intent = load("approved_intent", "journal-claim-intent.py")
    prepare, core, journal = intent.modules()
    return (prepare, core, journal, intent, load("approved_declaration", "prepare-approved-claim.py"),
            load("approved_remote", "observe-github-claims.py"))


def lookup(args, claim, prepare, journal):
    """Private read-only DELETE-mode snapshot; absent storage is never initialized."""
    preflight = prepare.preflight
    monitor = Path(args.authority_root) / ".orchestrator/monitor"
    with contextlib.ExitStack() as stack:
        authority = preflight.physical_root(args.authority_root, stack)
        store = preflight.directory(authority, ".orchestrator", stack, private=True)
        if not os.path.lexists(monitor):
            return None, None
        directory = preflight.directory(store, "monitor", stack, private=True)
        identity = (os.fstat(directory).st_dev, os.fstat(directory).st_ino)
        path = journal.check_path(monitor)
        preflight.require(not any(os.path.lexists(str(path) + suffix)
                                  for suffix in ("-journal", "-wal", "-shm")), "JOURNAL_RECOVERY_UNVERIFIED")
        if not os.path.lexists(path):
            return (identity, None), None
        fd = os.open("history.sqlite3", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        stack.callback(os.close, fd)
        before = preflight.fingerprint(os.fstat(fd))
        header = os.read(fd, 20)
        preflight.require(header[:16] == b"SQLite format 3\x00" and header[18:20] == b"\x01\x01",
                          "JOURNAL_RECOVERY_UNVERIFIED")
        db = journal.open_store(monitor, writable=False)
        try:
            db.execute("BEGIN")
            journal.validate_store(db)
            version, store_id = db.execute("SELECT version,store_id FROM meta").fetchone()
            rows = db.execute("SELECT request,request_sha256 FROM claim_intents WHERE operation_id=?",
                              (claim["operation_id"],)).fetchall() if version in {3, 4, 5} else []
            prior = journal.decode_intent(rows[0][0]) if rows else None
            preflight.require(db.file_identity == (os.fstat(fd).st_dev, os.fstat(fd).st_ino),
                              "CHANGED_DURING_READ")
        finally:
            db.close()
        current = preflight.directory(store, "monitor", stack, private=True)
        preflight.require(before == preflight.fingerprint(os.fstat(fd))
                          == preflight.fingerprint(journal.check_path(monitor).lstat())
                          and identity == (os.fstat(current).st_dev, os.fstat(current).st_ino)
                          and not any(os.path.lexists(str(path) + suffix)
                                      for suffix in ("-journal", "-wal", "-shm")), "CHANGED_DURING_READ")
        return (identity, before, version, store_id, tuple(tuple(row) for row in rows)), prior


def binding(task, journal):
    return {"task_id": task["task_id"], "created_at": task["created_at"],
            "task_sha256": journal.fingerprint(task), "revision": task["revision"],
            "generation": task["cooperative_binding"]["generation"],
            "session_id": task["cooperative_binding"]["session_id"], "worker": copy.deepcopy(task["worker"])}


def replay_matches(args, claim, task, public, prior, journal):
    if (prior["schema_version"] != 2 or prior["claim"] != claim
            or prior["binding"] != binding(task, journal) or prior["comment"] != public["comment"]
            or prior["comment_sha256"] != public["comment_sha256"]
            or any(prior["identity_observation"][key] != getattr(args, argument) for key, argument in (
                ("actor_id", "expected_actor_id"), ("repository_id", "expected_repo_id"),
                ("issue_id", "expected_issue_id")))
            or prior["public_text_declaration"] != {
                "schema_version": 1, "reviewer": args.reviewer,
                "approved_body_sha256": args.approved_body_sha256,
                "public_text_approval": "DECLARED_UNAUTHENTICATED"}):
        raise Refusal("CONFLICT", "OPERATION_CONFLICT")


class Refusal(Exception):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason


def initialized_snapshot_matches(before, after, *, created):
    """Allow only our new child directory's parent metadata change."""
    old_task, old_root, old_store, old_leases, old_files = before
    task, root, store, leases, files = after
    if (task, root, leases, files) != (old_task, old_root, old_leases, old_files):
        return False
    if not created:
        return store == old_store
    # check-native-ownership.fingerprint: dev, ino, size, mtime_ns,
    # ctime_ns, mode, uid, nlink. mkdir may change size/times and either add
    # one directory link or leave nlink unchanged on filesystems that do not
    # count subdirectories. Neither case can change identity or permissions.
    # The caller pins the physical child and requires an exact parent snapshot
    # after initialization; this exception applies only across our mkdir.
    old_dev, old_ino, _, _, _, old_mode, old_uid, old_links = old_store
    dev, ino, _, _, _, mode, uid, links = store
    return ((dev, ino, mode, uid) == (old_dev, old_ino, old_mode, old_uid)
            and links in (old_links, old_links + 1))


def record(args, claim, prepare, core, journal, intent, approval, observer):
    before, public = approval.snapshot(args, claim, prepare)
    prepare.codec.require(public["comment_sha256"] == args.approved_body_sha256
                          == prepare.codec.digest(prepare.codec.render(claim)), "APPROVED_BODY_MISMATCH")
    storage, prior = lookup(args, claim, prepare, journal)
    if prior is not None:
        replay_matches(args, claim, before[0], public, prior, journal)
        request = prior
    else:
        collected, fresh, _, observed, declaration = approval.collect_private(
            args, claim, prepare, observer, expected=(before, public))
        prepare.codec.require(collected == before and fresh == public, "LOCAL_SNAPSHOT_CHANGED")
        prospective_store_id = storage[3] if storage is not None and len(storage) > 2 else uuid.uuid4().hex
        while prospective_store_id in public["comment"]:
            prospective_store_id = uuid.uuid4().hex
        request = {"schema_version": 2, "action": "claim-publication", "operation_id": claim["operation_id"],
                   "store_id": prospective_store_id,
                   "claim": copy.deepcopy(claim), "comment": public["comment"],
                   "comment_sha256": public["comment_sha256"], "binding": binding(before[0], journal),
                   "identity_observation": observed, "public_text_declaration": declaration}
        # Validate the fresh typed material before any local initialization. The
        # provisional store ID is replaced only by the physically selected store.
        journal.validate_claim_intent(request)
    preflight = prepare.preflight
    with contextlib.ExitStack() as stack:
        authority = preflight.physical_root(args.authority_root, stack)
        store = preflight.directory(authority, ".orchestrator", stack, private=True)
        preflight.directory(store, "locks", stack, private=True)
        root = Path(args.authority_root) / ".orchestrator"
        with core.CoordinatorLock(root):
            current, text = approval.snapshot(args, claim, prepare)
            selected, row = lookup(args, claim, prepare, journal)
            if current != before or text != public or selected != storage or row != prior:
                raise Refusal("UNVERIFIED", "LOCAL_SNAPSHOT_CHANGED")
            monitor = root / "monitor"
            created = storage is None
            preflight.require(preflight.fingerprint(os.fstat(store)) == before[2], "CHANGED_DURING_READ")
            if created:
                monitor.mkdir(mode=0o700)
            monitor_fd = preflight.directory(store, "monitor", stack, private=True)
            monitor_identity = (os.fstat(monitor_fd).st_dev, os.fstat(monitor_fd).st_ino)
            initialized_parent = preflight.fingerprint(os.fstat(store))
            guarded_snapshot, guarded_text = approval.snapshot(args, claim, prepare)
            preflight.require(guarded_text == public and guarded_snapshot[2] == initialized_parent
                              and initialized_snapshot_matches(before, guarded_snapshot, created=created),
                              "LOCAL_SNAPSHOT_CHANGED")
            db = journal.open_store(monitor, writable=True)
            try:
                selected_store_id = db.execute("SELECT store_id FROM meta").fetchone()[0]
                if storage is not None and len(storage) > 2:
                    preflight.require(db.file_identity == storage[1][:2]
                                      and selected_store_id == storage[3], "CHANGED_DURING_READ")
                request["store_id"] = selected_store_id

                def guard(must_exist=False):
                    local, body = approval.snapshot(args, claim, prepare)
                    preflight.require(local == guarded_snapshot and body == public, "LOCAL_SNAPSHOT_CHANGED")
                    fresh_store = preflight.directory(authority, ".orchestrator", stack, private=True)
                    fresh_monitor = preflight.directory(fresh_store, "monitor", stack, private=True)
                    preflight.require(monitor_identity == (os.fstat(fresh_monitor).st_dev, os.fstat(fresh_monitor).st_ino),
                                      "CHANGED_DURING_READ")
                    info = journal.check_path(monitor).lstat()
                    preflight.require(db.file_identity == (info.st_dev, info.st_ino), "CHANGED_DURING_READ")
                    journal.validate_store(db)
                    journal.validate_claim_intent(request)
                    rows = db.execute("SELECT request,request_sha256 FROM claim_intents WHERE operation_id=?",
                                      (claim["operation_id"],)).fetchall() if db.execute(
                                          "SELECT version FROM meta").fetchone()[0] in {3, 4, 5} else []
                    if rows:
                        preflight.require(len(rows) == 1 and tuple(rows[0]) == (
                            journal.canonical(request), journal.fingerprint(request)), "CHANGED_DURING_READ")
                    else:
                        preflight.require(prior is None and not must_exist, "CHANGED_DURING_READ")

                status = journal.record_claim_intent(db, request, guard=guard)
                intent.durable(journal, db, monitor)
                guard(must_exist=True)
                return intent.result(status, "LOCAL_PENDING_ONLY", request)
            finally:
                db.close()


def main():
    import json

    output = {"status": "UNVERIFIED", "reason": "STORE_OR_DURABILITY_UNVERIFIED",
              "mutation_authorized": False, "remote_effects_enabled": False}
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        output["reason"] = "ISOLATED_PYTHON_REQUIRED"
    else:
        try:
            prepare, core, journal, intent, approval, observer = modules()
            try:
                args, claim = approval.arguments(prepare)
                output = record(args, claim, prepare, core, journal, intent, approval, observer)
            except (Refusal, approval.Refusal) as exc:
                output = intent.result(exc.status, exc.reason)
            except (prepare.codec.Unverified, prepare.preflight.Unverified, observer.Unverified) as exc:
                output = intent.result("UNVERIFIED", str(exc))
            except core.BusyError:
                output = intent.result("CONFLICT", "COORDINATOR_BUSY")
            except journal.JournalError as exc:
                reasons = {"conflicting claim operation": "OPERATION_CONFLICT",
                           "claim intent capacity reached": "INTENT_CAPACITY_REACHED"}
                if str(exc) in reasons:
                    output = intent.result("CONFLICT", reasons[str(exc)])
        except Exception:
            pass  # Fixed failure only: never expose filesystem/SQLite diagnostics.
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 4 if output["status"] == "CONFLICT" else 0 if output["status"] in {
        "INTENT_RECORDED", "REPLAYED_PENDING"} else 3


if __name__ == "__main__":
    sys.exit(main())
