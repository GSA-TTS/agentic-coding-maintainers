#!/usr/bin/env python3
"""Bounded foreground linkage for the existing two-persist repair engine.

No lock, worker, scheduler, target writer or rollback implementation lives here.
The caller holds the coordinator lock throughout the domain call and persistence.
"""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

PREFIX = "fgrepair."
TERMINAL = {"APPLIED_UNREVIEWED", "NOT_APPLIED_OBSERVED"}
OBSERVED = TERMINAL | {"PARTIAL", "UNVERIFIED"}


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise ValueError("installed dependency unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ledger(record):
    return record.get("foreground_repairs", {"schema_version": 1, "applications": {}, "reconciliations": {}})


def pending(record):
    return any(item["final"] is None for item in ledger(record)["applications"].values())


def count(record):
    state = ledger(record)
    return len(state["applications"]) + len(state["reconciliations"])


def repair_id(request, c):
    return PREFIX + c.digest(c.canonical(request))


def response(request, item, phase, revision):
    return {"status": phase, "task_id": request["task_id"], "incarnation": request["incarnation"],
            "operation_id": request["operation_id"], "action": request["action"],
            "resulting_revision": revision, "domain_result": {
                "status": phase, "operation_id": item["request"]["operation_id"],
                "bundle_sha256": item["bundle_sha256"], "candidate_ready": False,
                "execution_credit": False, "delivery_credit": False},
            "acknowledgement": "retained-history-only", "current_applicability": False,
            "pause_scope": "dispatcher-only", "candidate_ready": False,
            "execution_credit": False, "delivery_credit": False}


def replay(record, request, c):
    state = ledger(record)
    operation = request["operation_id"]
    for table in ("applications", "reconciliations"):
        prior = state[table].get(operation)
        if prior is None:
            continue
        if prior["request"] != request:
            raise c.Unverified("foreground repair operation reused with changed request")
        if table == "reconciliations":
            return copy.deepcopy(prior["result"])
        if prior["final"] is not None:
            return copy.deepcopy(prior["final"]["result"])
        item = record["repair_protocol"]["operations"][prior["repair_operation_id"]]
        return response(request, item, "REPAIR_RECONCILIATION_REQUIRED", prior["intent_revision"])
    return None


def validate(record, c, e):
    """Retained links in both directions, exact requests and nonoverlapping revisions.

    Domain artifacts are validated by the foreground retention validator first.
    Historical reconciliation outcomes never claim to describe today's bytes.
    """
    state = ledger(record)
    c.fields(state, {"schema_version", "applications", "reconciliations"})
    if type(state["schema_version"]) is not int or state["schema_version"] != 1:
        raise c.Unverified("invalid foreground repair schema")
    for table, bound in (("applications", 3), ("reconciliations", 64)):
        if not isinstance(state[table], dict) or len(state[table]) > bound:
            raise c.Unverified("foreground repair budget exceeded")
    control = record.get("foreground_control", {}).get("receipts", {})
    if count(record) + len(control) > 64:
        raise c.Unverified("foreground receipt budget exceeded")
    if "foreground_repairs" in record and record.get("foreground_initialized") is not True:
        raise c.Unverified("repair ledger lost foreground control")
    operations = record.get("repair_protocol", {}).get("operations", {})
    used_ops = set(control) | set(record.get("collected_review_acceptances", {}))
    used_revs = {item["request"]["expected_revision"] + 1 for item in control.values()}
    for table in ("review_protocol", "runtime_collections"):
        entries = record.get(table, {}).get("operations", {})
        used_ops.update(entries)
        used_revs.update(item["result"]["resulting_revision"] for item in entries.values())
    for item in record.get("repair_proposals", {}).values():
        for entry in (item, item["collection"]):
            if entry is not None:
                used_ops.add(entry["request"]["operation_id"])
                used_revs.add(entry["resulting_revision"])
    external_ops = set(used_ops)
    used_ops.update(operations)
    # Direct repair intents also occupy a revision, except linked ones checked below.
    used_revs.update(item["request"]["expected_revision"] + 1 for key, item in operations.items()
                     if not key.startswith(PREFIX))
    identity = load("candidate-binding").incarnation(record)
    fg = load("foreground-delivery")
    events, linked = [], set()

    def revision(value):
        if type(value) is not int or not 1 <= value <= record["revision"] or value in used_revs:
            raise c.Unverified("foreground repair revision collision")
        used_revs.add(value)

    def request_entry(key, entry, action):
        request = entry["request"]
        fg.validate_request(request, c, e)
        if (request["action"] != action or request["operation_id"] != key
                or key.startswith(PREFIX) or key in used_ops
                or request["task_id"] != record["task_id"] or request["incarnation"] != identity
                or c.digest(c.canonical(request)) != entry["request_sha256"]):
            raise c.Unverified("foreground repair request binding invalid")
        used_ops.add(key)
        revision(request["expected_revision"] + 1)
        events.append((request["expected_revision"] + 1, action))
        return request

    for key, app in state["applications"].items():
        c.fields(app, {"request", "request_sha256", "repair_operation_id", "intent_revision", "final"})
        request = request_entry(key, app, "apply-owner-proposal")
        op = repair_id(request, c)
        if (app["repair_operation_id"] != op or op in external_ops
                or type(app["intent_revision"]) is not int
                or app["intent_revision"] != request["expected_revision"] + 1):
            raise c.Unverified("foreground repair intent binding changed")
        item = operations.get(op)
        proposal = record.get("repair_proposals", {}).get(request["payload"]["admission_id"])
        if item is None or proposal is None or proposal["collection"] is None:
            raise c.Unverified("foreground repair lost domain intent or collection")
        admitted, collection = proposal["admission"], proposal["collection"]
        expected = {"schema_version": 1, "operation_id": op, "expected_revision": request["expected_revision"],
                    "correction_id": admitted["correction_id"], "bundle_sha256": collection["bundle_sha256"]}
        if (item["request"] != expected or item["worker"] != admitted["worker"]
                or collection["status"] != "PROPOSAL_COLLECTED"
                or collection["resulting_revision"] > request["expected_revision"]
                or any(other["admission"]["correction_id"] == admitted["correction_id"]
                       and other["resulting_revision"] > proposal["resulting_revision"]
                       for other in record["repair_proposals"].values())):
            raise c.Unverified("foreground repair differs from latest collected proposal")
        linked.add(op)
        final = app["final"]
        if final is not None:
            c.fields(final, {"via", "resulting_revision", "result"})
            if item["phase"] not in TERMINAL:
                raise c.Unverified("foreground terminal receipt lost domain outcome")
            end = final["resulting_revision"]
            if final["via"] is None:
                if end != app["intent_revision"] + 1 or item["phase"] != "APPLIED_UNREVIEWED":
                    raise c.Unverified("invalid two-write repair completion")
                revision(end)
            else:
                reconciliation = state["reconciliations"].get(final["via"])
                if (reconciliation is None or reconciliation["request"]["payload"]["apply_operation_id"] != key
                        or reconciliation["resulting_revision"] != end
                        or reconciliation["result"]["status"] != item["phase"]):
                    raise c.Unverified("repair finalization lost reconciliation")
            if c.canonical(final["result"]) != c.canonical(response(request, item, item["phase"], end)):
                raise c.Unverified("foreground repair final result changed")
    if {key for key in operations if key.startswith(PREFIX)} != linked:
        raise c.Unverified("orphan reserved repair operation; foreground history missing")
    for key, entry in state["reconciliations"].items():
        c.fields(entry, {"request", "request_sha256", "resulting_revision", "result"})
        request = request_entry(key, entry, "reconcile-owner-proposal")
        app = state["applications"].get(request["payload"]["apply_operation_id"])
        if app is None or request["expected_revision"] < app["intent_revision"]:
            raise c.Unverified("reconciliation precedes repair intent")
        item = operations[app["repair_operation_id"]]
        end, phase = entry["resulting_revision"], entry["result"]["status"]
        if (type(end) is not int or end != request["expected_revision"] + 1 or phase not in OBSERVED
                or c.canonical(entry["result"]) != c.canonical(response(request, item, phase, end))):
            raise c.Unverified("invalid retained reconciliation outcome")
        final = app["final"]
        if phase in TERMINAL:
            if final is None or final["resulting_revision"] > end or final["result"]["status"] != phase:
                raise c.Unverified("terminal reconciliation lacks application finalization")
        elif final is not None and end >= final["resulting_revision"]:
            raise c.Unverified("partial observation follows terminal finalization")
    return events


def run(record, request, root, persist, control):
    c, repair, proposal = [load(name) for name in ("review-collect", "repair-apply", "repair-proposal")]
    updated = copy.deepcopy(record)
    updated["foreground_initialized"] = True
    updated.setdefault("foreground_control", copy.deepcopy(control))
    state = updated.setdefault("foreground_repairs", copy.deepcopy(ledger(record)))
    key = request["operation_id"]
    fg, e = load("foreground-delivery"), load("review-evidence")

    def checked_persist(value):
        prospective = {**value, "revision": value["revision"] + 1}
        fg.validate_retained(prospective, root, c, e)
        if prospective["revision"] >= 2**53 or len(c.canonical(prospective)) > 900_000:
            raise c.Unverified("foreground repair revision or evidence budget exhausted")
        persist(value)

    if request["action"] == "apply-owner-proposal":
        if len(control["receipts"]) + count(record) > 62:
            raise c.Unverified("application requires capacity for an explicit recovery observation")
        selected = updated.get("repair_proposals", {}).get(request["payload"]["admission_id"])
        if selected is None or selected["collection"] is None or selected["collection"]["status"] != "PROPOSAL_COLLECTED":
            raise c.Unverified("collected owner proposal required")
        admitted = selected["admission"]
        latest = max((item for item in updated["repair_proposals"].values()
                      if item["admission"]["correction_id"] == admitted["correction_id"]),
                     key=lambda item: item["resulting_revision"])
        context, sources = proposal.owner_context(updated, admitted["correction_id"], admitted["sources"], c, repair)
        if (latest != selected or context != admitted["context"] or sources != admitted["source_sha256"]
                or updated["worker"] != admitted["worker"]):
            raise c.Unverified("latest proposal, current context, sources or full worker changed")
        op = repair_id(request, c)
        if op in updated["repair_protocol"]["operations"] or len(state["applications"]) >= 3:
            raise c.Unverified("repair operation collision or application budget exhausted")
        sha = selected["collection"]["bundle_sha256"]
        raw = c.read_bytes(root / "review-artifacts" / sha, 800_000)
        app = {"request": copy.deepcopy(request), "request_sha256": c.digest(c.canonical(request)),
               "repair_operation_id": op, "intent_revision": request["expected_revision"] + 1, "final": None}
        calls = 0

        def apply_persist(value):
            nonlocal calls
            calls += 1
            item = value["repair_protocol"]["operations"][op]
            if calls == 1:
                state["applications"][key] = app
                # Reserve space/revision for the final receipt before any target write.
                if len(c.canonical(value)) > 880_000 or value["revision"] + 2 >= 2**53:
                    raise c.Unverified("insufficient durable completion budget")
            elif calls == 2 and item["phase"] == "APPLIED_UNREVIEWED":
                app["final"] = {"via": None, "resulting_revision": value["revision"] + 1,
                    "result": response(request, item, item["phase"], value["revision"] + 1)}
            else:
                raise c.Unverified("unexpected repair persist sequence")
            checked_persist(value)

        repair.apply_repair(updated, root, {"schema_version": 1, "operation_id": op,
            "expected_revision": request["expected_revision"], "correction_id": admitted["correction_id"],
            "bundle_sha256": sha}, raw, apply_persist)
        if calls != 2:
            raise c.Unverified("unlinked domain replay cannot acquire foreground history")
        return copy.deepcopy(app["final"]["result"])

    app = state["applications"].get(request["payload"]["apply_operation_id"])
    if app is None:
        raise c.Unverified("foreground application absent")
    op = app["repair_operation_id"]
    persisted = False

    def reconcile_persist(value):
        nonlocal persisted
        if persisted:
            raise c.Unverified("unexpected reconciliation persist sequence")
        persisted = True
        item = value["repair_protocol"]["operations"][op]
        end = value["revision"] + 1
        state["reconciliations"][key] = {"request": copy.deepcopy(request),
            "request_sha256": c.digest(c.canonical(request)), "resulting_revision": end,
            "result": response(request, item, item["phase"], end)}
        if item["phase"] in TERMINAL and app["final"] is None:
            app["final"] = {"via": key, "resulting_revision": end,
                "result": response(app["request"], item, item["phase"], end)}
        checked_persist(value)

    repair.reconcile(updated, root, op, reconcile_persist)
    # A domain terminal replay does not call persist. Retain this *new* explicit
    # reconciliation request once, using that immutable domain outcome.
    if not persisted:
        reconcile_persist(updated)
    return copy.deepcopy(state["reconciliations"][key]["result"])
