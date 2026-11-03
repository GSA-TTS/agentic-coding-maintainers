#!/usr/bin/env python3
"""Two explicit single-write bridges; never launch a reviewer or acquire capacity."""

import copy
import importlib.util
from pathlib import Path

ACTIONS = {"assign-prepared-review": "fgassign.", "admit-prepared-review": "fgadmit."}


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def derived(record, request):
    e, c = load("review-evidence"), load("review-collect")
    assign = request["action"] == "assign-prepared-review"
    prepare, generation, payload = (e.prepared_assignment if assign else e.prepared_admission)(record, request)
    key = ACTIONS[request["action"]] + c.digest(c.canonical(request))
    parent = "prepare_operation_id" if assign else "assign_operation_id"
    reference = {"table": "review_protocol.operations" if assign else "runtime_collections.operations",
                 "key": key, parent: request["payload"][parent], "packet": generation["packet"]}
    domain = {"schema_version": 1, "operation_id": key, "expected_revision": request["expected_revision"],
              "action": "assign" if assign else "admit", "payload": payload}
    return prepare, generation, domain, reference


def retained(record, request, reference):
    c = load("review-collect")
    _, _, domain, expected = derived(record, request)
    if reference != expected:
        raise c.Unverified("prepared review reference differs")
    table = "review_protocol" if request["action"] == "assign-prepared-review" else "runtime_collections"
    entry = record[table]["operations"][reference["key"]]
    if entry["request"] != domain:
        raise c.Unverified("prepared review lost exact domain operation")
    return entry["result"]


def apply(record, request, root):
    c, e, review = load("review-collect"), load("review-evidence"), load("foreground-review")
    prepare, generation, domain, reference = derived(record, request)
    # Same current source, full worker, scope and epoch guards as preparation.
    review.fresh_guard(record, prepare["request"], root, generation["number"])
    if e.current(record) != generation:
        raise c.Unverified("prepared generation is no longer current")
    packet = c.canonical(review.read_packet(root, generation["packet"]))
    if domain["action"] == "assign":
        expected = {"status": "ASSIGNED", "generation": generation["number"],
                    "run_id": domain["payload"]["run_id"], "resulting_revision": record["revision"] + 1}
    else:
        admitted = c.admission(record, domain["payload"], packet, e)
        expected = {"status": "COLLECTION_ADMITTED", "admission_id": c.digest(c.canonical(admitted)),
                    "resulting_revision": record["revision"] + 1}
    # Prospective domain validation sees both links; only the outer caller persists.
    staged = copy.deepcopy(record)
    staged["foreground_control"]["receipts"][request["operation_id"]] = {
        "request": copy.deepcopy(request), "request_sha256": c.digest(c.canonical(request)), "reference": reference,
        "result": load("foreground-delivery").acknowledgement(request, expected)}
    updated, result, changed = (e.apply(staged, domain) if domain["action"] == "assign"
                                else c.apply(staged, domain, root, packet=packet))
    if not changed or result != expected:
        raise c.Unverified("unlinked domain replay cannot acquire a foreground receipt")
    return updated, result, reference


def progress(record):
    """Bounded retained progress, subordinate to the existing finding assessment."""
    e = load("review-evidence")
    try:
        generation = e.current(record)
    except e.Unverified:
        return None
    receipts = record.get("foreground_control", {}).get("receipts", {})
    prepared = [r for r in receipts.values() if r["request"]["action"] == "prepare-repaired-review"
                and r["result"]["domain_result"]["generation"] == generation["number"]]
    if not prepared:
        return None
    prepare_id = prepared[0]["request"]["operation_id"]
    assigned = [r for r in receipts.values() if r["request"]["action"] == "assign-prepared-review"
                and r["request"]["payload"]["prepare_operation_id"] == prepare_id]
    admitted = {r["request"]["payload"]["assign_operation_id"] for r in receipts.values()
                if r["request"]["action"] == "admit-prepared-review"}
    pending = sorted(r["request"]["operation_id"] for r in assigned if r["request"]["operation_id"] not in admitted)
    return {"prepare_operation_id": prepare_id, "generation": generation["number"],
            "assignment_count": len(assigned), "admission_count": len(assigned) - len(pending),
            "pending_assign_operation_ids": pending,
            "next_action": "ASSIGN_PREPARED_REVIEW" if not assigned else "ADMIT_PREPARED_REVIEW" if pending else "PREPARATION_COMPLETE"}
