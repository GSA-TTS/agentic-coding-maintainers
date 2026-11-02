#!/usr/bin/env python3
"""Single-action local protocol handoff, not autonomous delivery or execution.

Pause gates only this dispatcher: it neither terminates workers nor releases
leases. Receipts acknowledge retained history, never current applicability.
Invoke the installed controller using python3 -I -B.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import socket
import sys
from pathlib import Path

MAX_RECEIPTS = 64
MAX_REQUEST = 16_384
ACTIONS = {"collect-review", "accept-review", "prepare-correction", "pause", "resume", "status"}
DOMAIN_ACTIONS = {"collect-review": "collect", "accept-review": "accept-collected"}


def dependency(name):
    path = Path(__file__).resolve().with_name(name + ".py")
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    if spec is None or spec.loader is None:
        raise ValueError("installed dependency unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_request(request, c, e):
    c.fields(request, {"schema_version", "task_id", "incarnation", "expected_revision",
                       "operation_id", "action", "payload"})
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise c.Unverified("unsupported foreground request")
    for name in ("task_id", "operation_id"):
        e.token(request[name])
    e.hash_value(request["incarnation"])
    revision = request["expected_revision"]
    if type(revision) is not int or not 0 <= revision < 2**53:
        raise c.Unverified("invalid expected revision")
    action = request["action"]
    if not isinstance(action, str) or action not in ACTIONS:
        raise c.Unverified("unsupported foreground action")
    payload = request["payload"]
    expected = {"admission_id", "artifact_sha256"} if action == "collect-review" else (
        {"admission_id"} if action == "accept-review" else set())
    c.fields(payload, expected)
    if "admission_id" in expected:
        e.hash_value(payload["admission_id"])
    if "artifact_sha256" in expected:
        c.fields(payload["artifact_sha256"], set(c.ARTIFACTS))
        for value in payload["artifact_sha256"].values():
            e.hash_value(value)
    if len(c.canonical(request)) > MAX_REQUEST:
        raise c.Unverified("foreground request exceeds bound")


def domain_request(request):
    return {name: copy.deepcopy(request[name]) for name in
            ("schema_version", "operation_id", "expected_revision", "payload")} | {
                "action": DOMAIN_ACTIONS[request["action"]]}


def acknowledgement(request, domain_result):
    return {"status": domain_result["status"], "task_id": request["task_id"],
            "incarnation": request["incarnation"], "operation_id": request["operation_id"],
            "action": request["action"], "resulting_revision": request["expected_revision"] + 1,
            "domain_result": copy.deepcopy(domain_result), "acknowledgement": "retained-history-only",
            "current_applicability": False, "pause_scope": "dispatcher-only",
            "candidate_ready": False, "execution_credit": False, "delivery_credit": False}


def referenced_result(record, request, reference, c):
    """Resolve a receipt through already-validated authoritative domain history."""
    action, operation = request["action"], request["operation_id"]
    if action in DOMAIN_ACTIONS:
        table = "runtime_collections" if action == "collect-review" else "collected_review_acceptances"
        if reference != {"table": table, "key": operation}:
            raise c.Unverified("foreground domain reference changed")
        entries = record.get(table, {})
        if action == "collect-review":
            entries = entries.get("operations", {})
        entry = entries.get(operation)
        if entry is None or entry["request"] != domain_request(request):
            raise c.Unverified("foreground receipt lost its domain operation")
        return (entry if action == "collect-review" else
                record["review_protocol"]["operations"][operation])["result"]
    if action == "prepare-correction":
        c.fields(reference, {"table", "key"})
        if reference["table"] != "repair_protocol.corrections":
            raise c.Unverified("invalid correction reference")
        correction = record.get("repair_protocol", {}).get("corrections", {}).get(reference["key"])
        if correction is None or correction["expected_revision"] != request["expected_revision"]:
            raise c.Unverified("foreground receipt lost its prepared correction")
        return {"status": "CORRECTION_PREPARED", "correction_id": reference["key"]}
    if action not in {"pause", "resume"} or reference is not None:
        raise c.Unverified("invalid control receipt")
    return {"status": "PAUSED" if action == "pause" else "RESUMED"}


def validate_retained(record, root, c, e):
    # Validate artifacts even when there has not yet been an accepted report.
    if "review_protocol" in record:
        e.validate_protocol(record)
    if "runtime_collections" in record or "collected_review_acceptances" in record:
        dependency("review-accept").validate_retained(record, root)
    e.validate_collected_retention(record, root)
    dependency("repair-apply").validate_retained(record, root)
    initialized = record.get("foreground_initialized")
    if "foreground_initialized" in record and initialized is not True:
        raise c.Unverified("invalid foreground initialization marker")
    if ("foreground_control" in record) != (initialized is True):
        raise c.Unverified("initialized foreground task lost control history")
    state = record.get("foreground_control", {"schema_version": 1, "paused": False, "receipts": {}})
    c.fields(state, {"schema_version", "paused", "receipts"})
    if (type(state["schema_version"]) is not int or state["schema_version"] != 1
            or type(state["paused"]) is not bool or not isinstance(state["receipts"], dict)
            or len(state["receipts"]) > MAX_RECEIPTS):
        raise c.Unverified("invalid foreground control state")
    identity = dependency("candidate-binding").incarnation(record)
    revisions, ordered = set(), []
    domain_revisions = {item["result"]["resulting_revision"]
                        for table in ("review_protocol", "runtime_collections")
                        for item in record.get(table, {}).get("operations", {}).values()}
    for operation, receipt in state["receipts"].items():
        c.fields(receipt, {"request", "request_sha256", "reference", "result"})
        request = receipt["request"]
        validate_request(request, c, e)
        revision = request["expected_revision"] + 1
        if (request["operation_id"] != operation or request["task_id"] != record["task_id"]
                or request["incarnation"] != identity or revision > record["revision"]
                or revision in revisions or c.digest(c.canonical(request)) != receipt["request_sha256"]):
            raise c.Unverified("foreground receipt binding mismatch")
        if request["action"] not in DOMAIN_ACTIONS and revision in domain_revisions:
            raise c.Unverified("foreground control revision collides with domain history")
        result = referenced_result(record, request, receipt["reference"], c)
        if c.canonical(receipt["result"]) != c.canonical(acknowledgement(request, result)):
            raise c.Unverified("foreground receipt result differs from domain history")
        revisions.add(revision)
        ordered.append((revision, request["action"]))
    paused = False
    for _, action in sorted(ordered):
        if action in {"pause", "resume"}:
            paused = action == "pause"
        elif paused:
            raise c.Unverified("foreground action recorded while dispatcher paused")
    if state["paused"] != paused:
        raise c.Unverified("pause state differs from retained receipts")
    return state


def status(record, state):
    e = dependency("review-evidence")
    review = e.assess(record)
    if record["state"] in {"Done", "Cancelled"}:
        next_action = "TERMINAL_NO_DISPATCH"
    elif record["state"] not in {"Claimed", "Implementing", "Reviewing", "Rework"}:
        next_action = "COORDINATOR_READMISSION_REQUIRED"
    elif state["paused"]:
        next_action = "RESUME_FOREGROUND"
    elif record["state"] == "Rework":
        prepared = any(item["cycle"] == record["rework_count"]
                       for item in record.get("repair_protocol", {}).get("corrections", {}).values())
        next_action = "ORIGINAL_OWNER_RECLAIM" if prepared else "PREPARE_CORRECTION"
    elif review.get("unresolved_findings"):
        next_action = "OWNER_REWORK_ADMISSION_REQUIRED"
    else:
        generation = None
        try:
            generation = e.current(record)
            if generation["owner"] != record["owner"]:
                generation = None
        except (e.Unverified, KeyError, TypeError):
            pass
        pending = []
        for item in record.get("runtime_collections", {}).get("collections", {}):
            admitted = record["runtime_collections"]["admissions"][item]
            if (generation is not None and admitted["generation"] == generation["number"]
                    and admitted["material_epoch"] == generation["material_epoch"]
                    and admitted["owner"] == record["owner"]
                    and admitted["assignment"] == generation["assignments"].get(admitted["run_id"])
                    and admitted["run_id"] not in generation["reports"]):
                pending.append(item)
        if generation is None and "review_protocol" in record:
            next_action = "FRESH_REVIEW_GENERATION_REQUIRED"
        elif pending:
            next_action = "ACCEPT_COLLECTED_REVIEW"
        elif review.get("review_process") == "CLAIMS_COMPLETE":
            next_action = "HUMAN_HANDOFF_REQUIRES_VALIDATION_AND_LIVE_PR_CHECKS"
        else:
            next_action = "REVIEW_ADMISSION_OR_BUNDLE_REQUIRED"
    return {"status": "FOREGROUND_STATUS", "task_id": record["task_id"],
            "incarnation": dependency("candidate-binding").incarnation(record),
            "revision": record["revision"], "task_state": record["state"],
            "paused": state["paused"], "pause_scope": "dispatcher-only",
            "receipt_count": len(state["receipts"]), "next_action": next_action,
            "review_claims": review, "candidate_ready": False,
            "execution_credit": False, "delivery_credit": False}


def dispatch(record, request, root, bundle=None):
    """Lock-free domain composition. Caller owns the sole coordinator lock/write."""
    c, e = dependency("review-collect"), dependency("review-evidence")
    state = validate_retained(record, root, c, e)
    if request is None:
        if bundle is not None:
            raise c.Unverified("bundle requires collect-review")
        return record, status(record, state), False
    validate_request(request, c, e)
    if (request["task_id"] != record["task_id"] or request["incarnation"] !=
            dependency("candidate-binding").incarnation(record)):
        raise c.Unverified("task incarnation changed")
    action = request["action"]
    if bundle is not None and action != "collect-review":
        raise c.Unverified("bundle requires collect-review")
    prior = state["receipts"].get(request["operation_id"])
    if prior is not None:
        if prior["request"] != request:
            raise c.Unverified("operation ID reused with changed request")
        return record, copy.deepcopy(prior["result"]), False
    if request["expected_revision"] != record["revision"]:
        raise c.Unverified("task revision changed")
    if action == "status":
        return record, status(record, state), False
    if record["state"] not in {"Claimed", "Implementing", "Reviewing", "Rework"} or record.get("transition_intent"):
        raise c.Unverified("task is not admitted for foreground mutation")
    coordinator = dependency("orchestrator-state")
    coordinator.require_execution_stopped(record)
    coordinator.require_repair_settled(record, root=root)
    if record["state"] != "Rework" and record.get("worker") is None:
        raise c.Unverified("active lifecycle lacks a worker; reconcile explicitly")
    if len(state["receipts"]) >= MAX_RECEIPTS:
        raise c.Unverified("foreground receipt budget exhausted")
    if state["paused"] and action not in {"pause", "resume"}:
        raise c.Unverified("foreground dispatcher is paused")
    operation = request["operation_id"]
    if (any(operation in record.get(table, {}).get("operations", {}) for table in
            ("review_protocol", "runtime_collections", "repair_protocol"))
            or operation in record.get("collected_review_acceptances", {})):
        raise c.Unverified("operation identifier already used outside dispatcher")
    # Never hand the caller's object to an API that might return/mutate it.
    updated, reference = copy.deepcopy(record), None
    if action in DOMAIN_ACTIONS:
        if action == "collect-review":
            if bundle is None:
                raise c.Unverified("collect-review requires --bundle")
            artifacts = {name: c.read_bytes(bundle / name) for name in c.ARTIFACTS}
            updated, result, changed = c.apply(updated, domain_request(request), root, artifacts=artifacts)
            table = "runtime_collections"
        else:
            updated, result, changed = dependency("review-accept").apply(updated, domain_request(request), root)
            table = "collected_review_acceptances"
        if not changed:
            raise c.Unverified("unlinked domain replay cannot acquire a foreground receipt")
        reference = {"table": table, "key": operation}
    elif action == "prepare-correction":
        updated, result = dependency("repair-apply").prepare(updated, root, request["expected_revision"])
        reference = {"table": "repair_protocol.corrections", "key": result["correction_id"]}
    else:
        result = {"status": "PAUSED" if action == "pause" else "RESUMED"}
    updated["foreground_initialized"] = True
    control = updated.setdefault("foreground_control", copy.deepcopy(state))
    if action in {"pause", "resume"}:
        control["paused"] = action == "pause"
    response = acknowledgement(request, result)
    control["receipts"][operation] = {"request": copy.deepcopy(request),
        "request_sha256": c.digest(c.canonical(request)), "reference": reference, "result": response}
    validate_retained({**updated, "revision": record["revision"] + 1}, root, c, e)
    if len(c.canonical(updated)) > 900_000:
        raise c.Unverified("task evidence budget exceeded")
    return updated, response, True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--request", type=Path, help="one strict action; omit for read-only status")
    parser.add_argument("--bundle", type=Path, help="collect-review runtime artifact directory")
    args = parser.parse_args()
    try:
        if not sys.flags.isolated or not sys.dont_write_bytecode:
            raise ValueError("invoke with python3 -I -B")
        c, coordinator = dependency("review-collect"), dependency("orchestrator-state")
        request = c.decode(c.read_bytes(args.request, MAX_REQUEST)) if args.request else None
        root = coordinator.state_root(create=False)
        with coordinator.CoordinatorLock(root):
            # Strict decoding also rejects duplicate task/receipt keys on reads.
            record = coordinator.validate_record(c.decode(c.read_bytes(
                coordinator.task_path(root, args.task_id), 1_000_000)), args.task_id)
            coordinator.verify_reservations(root, record)
            if record.get("transition_intent"):
                raise c.Unverified("unfinished lifecycle transition; reconcile explicitly")
            worker = record.get("worker")
            if worker is not None:
                live, start = coordinator.process_identity(worker["pid"])
                if (live != "alive" or start != worker["process_start"]
                        or worker["hostname"] != socket.gethostname() or worker["owner"] != record["owner"]):
                    raise c.Unverified("worker identity unavailable; reconcile explicitly")
            updated, result, changed = dispatch(record, request, root, args.bundle)
            if changed:
                coordinator.write_task(root, updated)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"status": "UNVERIFIED", "reason":
            "foreground action unavailable; verify request, revision, pause, ownership and retained evidence"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
