#!/usr/bin/env python3
"""Human-only finite grant activation/revocation; no remote mutating endpoint."""

import contextlib
import copy
import hashlib
import importlib.util
import os
import stat
import sys
import time
from pathlib import Path

REVOKE_WAIT_SECONDS = 35


def load_dispatch():
    spec = importlib.util.spec_from_file_location("standing_controller_dispatch", Path(__file__).with_name("standing-grant-dispatch.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("ADAPTER_UNAVAILABLE")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def proposal(path, grant, typed, *, qualification=False):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        grant.require(stat.S_ISREG(info.st_mode) and info.st_size <= 16384 and info.st_nlink == 1)
        raw = os.read(fd, 16385)
        after = os.fstat(fd)
        grant.require(len(raw) == info.st_size and (info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) ==
                      (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns))
        definition = typed.decode(raw.decode("ascii").strip())
        (grant.validate_qualification_manifest if qualification else grant.validate_definition)(definition)
        return definition
    finally:
        os.close(fd)


class GrantDecision:
    """Distinct grant validator and receipt; never manufactures assignment authority."""

    def __init__(self, publisher, binding, grant):
        grant.require(type(binding) is dict and binding.get("action") in {"activate", "revoke", "install-qualification", "revoke-qualification"})
        self.binding = publisher.canonical(binding)
        self.approval = publisher.collect_terminal(binding, binding["action"].upper(),
            "Standing grant " + binding["action"] + " (private scope; cooperative host authority)")

    def validate(self, publisher, binding):
        publisher.require(self.binding == publisher.canonical(binding), "APPROVAL_BINDING_CHANGED")
        receipt = self.approval.validate(binding)
        receipt["interaction"] = "CONTROLLING_TTY_GRANT_CHALLENGE"
        return receipt


def verify_artifacts(store, grant, manifest, expected_report=None):
    """Fixed private evidence directory, descriptor-relative no-symlink reads.

    Artifacts are data, never imported/executed. Transcript bytes are hashed but
    not displayed; the bounded report, hashes, sizes and human assessment are
    shown. This proves retained bytes/bindings, not actual test execution.
    """
    grant.validate_qualification_manifest(manifest)
    with contextlib.ExitStack() as stack:
        p = store.preflight
        root = p.physical_root(store.args.authority_root, stack)
        state = p.directory(root, ".orchestrator", stack, private=True)
        evidence = p.directory(state, "qualification-evidence", stack, private=True)
        selected = p.directory(evidence, manifest["qualification_id"], stack, private=True)
        directory_identity = p.fingerprint(os.fstat(selected))
        retained = []
        contents = {}
        for key in ("report", "transcript"):
            artifact = manifest[key]
            fd = os.open(artifact["name"], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=selected)
            stack.callback(os.close, fd)
            info = os.fstat(fd)
            grant.require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077
                          and info.st_nlink == 1 and info.st_size == artifact["size"], "QUALIFICATION_ARTIFACT_UNSAFE")
            chunks, remaining = [], artifact["size"] + 1
            while remaining:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            grant.require(len(raw) == artifact["size"] and hashlib.sha256(raw).hexdigest() == artifact["sha256"],
                          "QUALIFICATION_ARTIFACT_CHANGED")
            retained.append((fd, p.fingerprint(info), artifact["name"]))
            if key == "report":
                contents[key] = store.typed.decode(raw.decode("ascii"))
        for fd, before, name in retained:
            grant.require(p.fingerprint(os.fstat(fd)) == before
                          and p.fingerprint(os.stat(name, dir_fd=selected, follow_symlinks=False)) == before,
                          "QUALIFICATION_ARTIFACT_CHANGED")
        grant.require(p.fingerprint(os.fstat(selected)) == directory_identity, "QUALIFICATION_ARTIFACT_CHANGED")
        grant.require(p.fingerprint(os.stat(manifest["qualification_id"], dir_fd=evidence, follow_symlinks=False)) == directory_identity,
                      "QUALIFICATION_ARTIFACT_CHANGED")
    report = contents["report"]
    grant.validate_qualification_report(manifest, report)
    grant.require(expected_report is None or report == expected_report, "QUALIFICATION_ARTIFACT_CHANGED")
    return report


def existing_qualification(db, grant):
    if db.execute("SELECT version FROM meta").fetchone()[0] != 7:
        return None
    if db.execute("SELECT count(*) FROM standing_qualification_selector").fetchone()[0] == 0:
        return None
    return grant.qualification_selector(db)


def qualification_idle(store, db, grant):
    """Qualification installation/revocation cannot race a selected live grant."""
    if db.execute("SELECT version FROM meta").fetchone()[0] == 7:
        if db.execute("SELECT count(*) FROM standing_selector").fetchone()[0]:
            selected = grant.selector(db)
            grant.require(selected["state"] == "revoked", "PRIOR_GRANT_NOT_REVOKED")
    for path in (store.root / "locks").glob("standing-effect-*.lock"):
        grant.require(not path.exists() and not path.is_symlink(), "QUALIFICATION_EFFECT_GATE_PENDING")


def install_qualification(args, dispatch):
    os.environ.pop("GH_TOKEN", None)
    adapter, publisher, grant = dispatch.modules()
    store, _ = dispatch.make_store(args, adapter)
    # Same bounded canonical proposal reader, with qualification shape instead
    # of granting the proposal any authority before a real controller decision.
    manifest = proposal(args.proposal, grant, store.typed, qualification=True)
    adapter.implementation_head(args.implementation_head)
    grant.require(manifest["scope"]["implementation_head"] == args.implementation_head
                  and manifest["scope"]["policy_sha256"] == dispatch.policy_digest(), "QUALIFICATION_BINDING_CHANGED")
    report = verify_artifacts(store, grant, manifest)
    installed = grant.clock()
    with store.locked() as db:
        store.journal.validate_store(db)
        qualification_idle(store, db, grant)
        previous = existing_qualification(db, grant)
        grant.require(args.expected_epoch == (previous["epoch"] if previous else 0), "QUALIFICATION_EPOCH_CHANGED")
        grant.require(previous is None or previous["state"] == "revoked", "QUALIFICATION_NOT_REVOKED")
        binding = {"action": "install-qualification", "manifest": manifest, "report": report,
                   "epoch": args.expected_epoch + 1, "installed": installed,
                   "store_id": db.execute("SELECT store_id FROM meta").fetchone()[0]}
    decision = GrantDecision(publisher, binding, grant)
    adapter.implementation_head(args.implementation_head)
    verify_artifacts(store, grant, manifest, expected_report=report)
    with store.locked() as db:
        grant.require(existing_qualification(db, grant) == previous, "QUALIFICATION_EPOCH_CHANGED")
        qualification_idle(store, db, grant)
        verify_artifacts(store, grant, manifest, expected_report=report)
        grant.continuity(installed, grant.clock())
        receipt = decision.validate(publisher, binding)
        document = {key: value for key, value in binding.items() if key != "action"} | {"receipt": receipt}
        with db:
            db.execute("BEGIN IMMEDIATE")
            grant.migrate(db)
            forbidden = store.typed.identifiers(db) | grant.identifiers(db) | {binding["store_id"]}
            for row in db.execute("SELECT request FROM claim_intents"):
                forbidden.update(store.journal.claim_intent_identifiers(store.journal.decode_intent(row[0])))
            for row in db.execute("SELECT incarnation,operation_id FROM binding_acks"):
                forbidden.update(row)
            forbidden.update(row[0] for row in db.execute("SELECT observation_id FROM claim_observations"))
            grant.require(manifest["qualification_id"] not in forbidden, "QUALIFICATION_IDENTIFIER_COLLISION")
            db.execute("INSERT INTO standing_qualifications VALUES(?,?,?)",
                (manifest["qualification_id"], store.typed.canonical(document), store.typed.digest(document)))
            grant.put_qualification_selector(db, {"qualification_id": manifest["qualification_id"], "epoch": binding["epoch"],
                                                 "state": "active", "revocation": None})
            store.journal.validate_store(db)
        store.durable(db)
    return {"status": "OFFLINE_QUALIFICATION_INSTALLED_FOR_ONE_USE_LIVE_PILOT", "epoch": binding["epoch"], "reservation": "settled"}


def revoke_qualification(args, dispatch):
    os.environ.pop("GH_TOKEN", None)
    adapter, publisher, grant = dispatch.modules()
    store, _ = dispatch.make_store(args, adapter)
    adapter.implementation_head(args.implementation_head)
    with store.locked() as db:
        qualification_idle(store, db, grant)
        selected = grant.qualification_selector(db)
        grant.require(selected["epoch"] == args.expected_epoch and selected["state"] == "active", "QUALIFICATION_EPOCH_CHANGED")
        binding = {"action": "revoke-qualification", "qualification_id": selected["qualification_id"],
                   "epoch": selected["epoch"], "store_id": db.execute("SELECT store_id FROM meta").fetchone()[0],
                   "implementation_head": args.implementation_head}
    decision = GrantDecision(publisher, binding, grant)
    with store.locked() as db:
        qualification_idle(store, db, grant)
        grant.require(grant.qualification_selector(db) == selected, "QUALIFICATION_EPOCH_CHANGED")
        selected["state"] = "revoked"
        selected["revocation"] = {"binding": binding, "receipt": decision.validate(publisher, binding)}
        with db:
            db.execute("BEGIN IMMEDIATE")
            grant.put_qualification_selector(db, selected)
            store.journal.validate_store(db)
        store.durable(db)
    return {"status": "QUALIFICATION_REVOKED", "epoch": selected["epoch"], "reservation": "settled"}


def activate(args, dispatch):
    token = os.environ.pop("GH_TOKEN", None)
    adapter, publisher, grant = dispatch.modules()
    adapter.require(token is not None and not os.environ.get("GITHUB_TOKEN"), "EXPLICIT_GH_TOKEN_REQUIRED")
    store, transport = dispatch.make_store(args, adapter)
    definition = proposal(args.proposal, grant, store.typed)
    adapter.implementation_head(args.implementation_head)
    grant.require(definition["implementation_head"] == args.implementation_head and
                  definition["policy_sha256"] == dispatch.policy_digest())
    started = grant.clock()
    with store.locked() as db:
        store.journal.validate_store(db)
        qualification = dispatch.require_endpoint_qualification(store, db, grant, definition)
        version = db.execute("SELECT version FROM meta").fetchone()[0]
        grant.require(version in {5, 6, 7})
        previous = grant.selector(db) if version == 7 and db.execute("SELECT count(*) FROM standing_selector").fetchone()[0] else None
        grant.require(args.expected_epoch == (previous["epoch"] if previous else 0), "GRANT_EPOCH_CHANGED")
        if previous:
            grant.require(previous["state"] == "revoked", "PRIOR_GRANT_NOT_REVOKED")
            grant.continuity(previous["clock"], started)
        task = store.task()
        dispatch.admitted(store, task, definition)
        store.core.require_assignment_settled(task)
        binding = {"action": "activate", "definition": definition, "epoch": args.expected_epoch + 1,
                   "store_id": db.execute("SELECT store_id FROM meta").fetchone()[0],
                   "admission": store.typed.task_binding(task), "activated": started,
                   "effective_scope": grant.effective_scope(definition),
                   "qualification_id": qualification["manifest"]["qualification_id"]}
    decision = GrantDecision(publisher, binding, grant)
    # Fresh permission/identity reads after the human challenge, outside locks.
    client = transport.Transport(definition["repository"], None, token)
    token = None
    try:
        client.fresh_repository(grant.observed(definition))
    finally:
        client.close()
    adapter.implementation_head(args.implementation_head)
    with store.locked() as db:
        grant.require(dispatch.require_endpoint_qualification(store, db, grant, definition) == qualification,
                      "QUALIFICATION_BINDING_CHANGED")
        current = grant.selector(db) if db.execute("SELECT version FROM meta").fetchone()[0] == 7 and db.execute("SELECT count(*) FROM standing_selector").fetchone()[0] else None
        grant.require(current == previous and store.task() == task, "SELECTED_ROWS_CHANGED")
        dispatch.admitted(store, task, definition)
        grant.continuity(started, grant.clock())
        activation = decision.validate(publisher, binding)
        document = {"definition": definition, "activation": activation, "epoch": binding["epoch"],
                    "activated": started, "expires": started["wall"] + definition["lifetime_seconds"],
                    "admission": binding["admission"], "store_id": binding["store_id"],
                    "qualification_id": binding["qualification_id"]}
        with db:
            db.execute("BEGIN IMMEDIATE")
            grant.migrate(db)
            forbidden = store.typed.identifiers(db) | grant.identifiers(db) | {binding["store_id"]}
            for row in db.execute("SELECT request FROM claim_intents"):
                forbidden.update(store.journal.claim_intent_identifiers(store.journal.decode_intent(row[0])))
            for row in db.execute("SELECT incarnation,operation_id FROM binding_acks"):
                forbidden.update(row)
            forbidden.update(row[0] for row in db.execute("SELECT observation_id FROM claim_observations"))
            grant.require(definition["grant_id"] not in forbidden, "GRANT_IDENTIFIER_COLLISION")
            db.execute("INSERT INTO standing_grants VALUES(?,?,?)", (definition["grant_id"], store.typed.canonical(document), store.typed.digest(document)))
            grant.put_selector(db, {"grant_id": definition["grant_id"], "epoch": binding["epoch"], "state": "active", "clock": started, "revocation": None})
            store.journal.validate_store(db)
        store.durable(db)
    return {"status": "GRANT_ACTIVATED", "epoch": binding["epoch"], "reservation": "settled"}


def revoke(args, dispatch):
    os.environ.pop("GH_TOKEN", None)
    adapter, publisher, grant = dispatch.modules()
    store, _ = dispatch.make_store(args, adapter)
    adapter.implementation_head(args.implementation_head)
    with store.locked() as db:
        store.journal.validate_store(db)
        selected = grant.selector(db)
        grant.require(selected["epoch"] == args.expected_epoch, "GRANT_EPOCH_CHANGED")
        grant.require(selected["state"] in {"active", "paused", "revoke-requested"}, "GRANT_INACTIVE_OR_EPOCH_CHANGED")
        resuming = selected["state"] == "revoke-requested"
        binding = {"action": "revoke", "selector": copy.deepcopy(selected), "implementation_head": args.implementation_head,
                    "store_id": db.execute("SELECT store_id FROM meta").fetchone()[0]}
    if resuming:
        # Historical receipt already passed the complete store validator. It
        # authorizes completion of this exact request only, never another effect.
        # No fresh timestamp, receipt or approval is manufactured on resume.
        return complete_revocation(store, dispatch, grant, selected)
    decision = GrantDecision(publisher, binding, grant)
    with store.locked() as db:
        current = grant.selector(db)
        # Dispatch may have advanced only the clock while the human was typing.
        # Bind identity/epoch, then retain that latest clock rather than rolling it back.
        grant.require(current["grant_id"] == selected["grant_id"] and current["epoch"] == selected["epoch"]
                      and current["state"] in {"active", "paused"}, "GRANT_EPOCH_CHANGED")
        selected = current
        receipt = decision.validate(publisher, binding)
        selected["state"] = "revoke-requested"
        selected["revocation"] = {"binding": binding, "receipt": receipt}
        with db:
            db.execute("BEGIN IMMEDIATE")
            grant.put_selector(db, selected)
        store.durable(db)
    return complete_revocation(store, dispatch, grant, selected)


def complete_revocation(store, dispatch, grant, selected):
    # Do not hold the coordinator while the synchronous effect producer returns.
    # A dead/unknown owner is never taken over: leave requested, no completion ack.
    until = time.monotonic() + REVOKE_WAIT_SECONDS
    while True:
        path = dispatch.gate_path(store, selected["grant_id"])
        # The waiting revoker must not continually contend for the coordinator
        # that the producer needs for evidence/settlement and gate release.
        if path.exists() or path.is_symlink():
            if time.monotonic() >= until:
                return {"status": "REVOKE_REQUESTED_GATE_UNVERIFIED", "reservation": "pending"}
            time.sleep(0.1)
            continue
        with store.locked():
            try:
                gate = dispatch.acquire_gate(store, selected["grant_id"])
                break
            except store.core.BusyError:
                if time.monotonic() >= until:
                    return {"status": "REVOKE_REQUESTED_GATE_UNVERIFIED", "reservation": "pending"}
        time.sleep(0.1)
    try:
        with store.locked() as db:
            store.journal.validate_store(db)
            grant.require(grant.selector(db) == selected, "GRANT_EPOCH_CHANGED")
            selected["state"] = "revoked"
            with db:
                db.execute("BEGIN IMMEDIATE")
                grant.put_selector(db, selected)
            store.durable(db)
    finally:
        dispatch.release_gate(store, selected["grant_id"], gate)
    return {"status": "GRANT_REVOKED_QUIESCENT", "epoch": selected["epoch"], "reservation": "settled"}


def main():
    dispatch = load_dispatch()
    adapter, publisher, _ = dispatch.modules()
    try:
        adapter.require(sys.flags.isolated and sys.dont_write_bytecode, "ISOLATED_PYTHON_REQUIRED")
        args = dispatch.arguments(controller=True)
        output = {"activate": activate, "revoke": revoke, "install-qualification": install_qualification,
                  "revoke-qualification": revoke_qualification}[args.action](args, dispatch)
    except Exception as exc:
        output = publisher.public_failure(exc)
    return publisher.emit_result(output)


if __name__ == "__main__":
    sys.exit(main())
