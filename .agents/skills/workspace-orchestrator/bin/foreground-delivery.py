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
PROPOSAL_ACTIONS = {"admit-owner-proposal", "collect-owner-proposal"}
COLLECT_ACTIONS = {"collect-review", "collect-owner-proposal"}
DOMAIN_ACTIONS = {"collect-review": "collect", "accept-review": "accept-collected",
                  "admit-owner-proposal": "admit", "collect-owner-proposal": "collect"}
REPAIR_ACTIONS = {"apply-owner-proposal", "reconcile-owner-proposal"}
ACTIONS = set(DOMAIN_ACTIONS) | REPAIR_ACTIONS | {"prepare-correction", "pause", "resume", "status", "adopt-owner-repair-head", "prepare-repaired-review"}
PROPOSAL_FIELDS = {"correction_id", "session", "model", "agent", "binary_sha256",
                   "profile_sha256", "cwd", "sources"}


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
    expected = {"adopt_operation_id"} if action == "prepare-repaired-review" else {"apply_operation_id", "head"} if action == "adopt-owner-repair-head" else PROPOSAL_FIELDS if action == "admit-owner-proposal" else (
        {"admission_id", "artifact_sha256"} if action in COLLECT_ACTIONS else (
        {"admission_id"} if action in {"accept-review", "apply-owner-proposal"} else (
        {"apply_operation_id"} if action == "reconcile-owner-proposal" else set())))
    c.fields(payload, expected)
    if "admission_id" in expected:
        e.hash_value(payload["admission_id"])
    if "apply_operation_id" in expected:
        e.token(payload["apply_operation_id"])
    if "adopt_operation_id" in expected:
        e.token(payload["adopt_operation_id"])
    if request["operation_id"].startswith("fgreview."):
        raise c.Unverified("reserved foreground review namespace")
    if "head" in expected:
        if not isinstance(payload["head"], str) or not dependency("foreground-adopt").OID.fullmatch(payload["head"]):
            raise c.Unverified("full repair commit object ID required")
    if "artifact_sha256" in expected:
        c.fields(payload["artifact_sha256"], set(c.ARTIFACTS))
        for value in payload["artifact_sha256"].values():
            e.hash_value(value)
    if action == "admit-owner-proposal":
        for name in ("correction_id", "binary_sha256", "profile_sha256"):
            e.hash_value(payload[name])
        for name in ("session", "agent"):
            e.token(payload[name])
        e.text(payload["model"], 200)
        c.absolute_guest_path(payload["cwd"])
        sources = payload["sources"]
        if not isinstance(sources, dict) or not 1 <= len(sources) <= 2:
            raise c.Unverified("one or two proposal source mappings required")
        repair = dependency("repair-apply")
        for guest, relative in sources.items():
            c.absolute_guest_path(guest)
            repair.relative_path(relative)
        if len(set(sources.values())) != len(sources):
            raise c.Unverified("duplicate proposal source target")
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


def referenced_result(record, request, reference, c, root):
    """Resolve a receipt through already-validated authoritative domain history."""
    action, operation = request["action"], request["operation_id"]
    if action == "prepare-repaired-review":
        return dependency("foreground-review").retained(record, request, reference, root)
    if action == "adopt-owner-repair-head":
        return dependency("foreground-adopt").retained(record, request, reference)
    if action in PROPOSAL_ACTIONS:
        c.fields(reference, {"table", "key"})
        if reference["table"] != "repair_proposals":
            raise c.Unverified("invalid proposal reference")
        key = reference["key"]
        item = record.get("repair_proposals", {}).get(key)
        entry = item if action == "admit-owner-proposal" else (item or {}).get("collection")
        if (entry is None or entry["request"] != domain_request(request)
                or entry["resulting_revision"] != request["expected_revision"] + 1):
            raise c.Unverified("foreground receipt lost its proposal operation")
        if action == "admit-owner-proposal":
            return {"status": "PROPOSAL_ADMITTED", "admission_id": key,
                    "context": item["admission"]["context"]}
        if key != request["payload"]["admission_id"]:
            raise c.Unverified("foreground proposal admission reference changed")
        return {"status": entry["status"], "admission_id": key, "bundle_sha256": entry["bundle_sha256"]}
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
    has_collected = any("collection_origin" in report
                        for generation in record.get("review_protocol", {}).get("generations", [])
                        for report in generation["reports"].values())
    if "runtime_collections" in record or "collected_review_acceptances" in record or has_collected:
        dependency("review-accept").validate_retained(record, root)
    # Retention only: the shared mutation gate deliberately rejects pending repairs.
    # Call its artifact validators directly without inventing settled phases.
    if "repair_proposals" in record:
        dependency("repair-proposal").validate(record, root)
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
    domain_revisions.update(entry["resulting_revision"]
                            for item in record.get("repair_proposals", {}).values()
                            for entry in (item, item["collection"]) if entry is not None)
    for operation, receipt in state["receipts"].items():
        c.fields(receipt, {"request", "request_sha256", "reference", "result"})
        request = receipt["request"]
        validate_request(request, c, e)
        if request["action"] in REPAIR_ACTIONS:
            raise c.Unverified("repair receipts require the separate repair ledger")
        revision = request["expected_revision"] + 1
        if (request["operation_id"] != operation or request["task_id"] != record["task_id"]
                or request["incarnation"] != identity or revision > record["revision"]
                or revision in revisions or c.digest(c.canonical(request)) != receipt["request_sha256"]):
            raise c.Unverified("foreground receipt binding mismatch")
        if request["action"] not in set(DOMAIN_ACTIONS) | {"prepare-repaired-review"} and revision in domain_revisions:
            raise c.Unverified("foreground control revision collides with domain history")
        result = referenced_result(record, request, receipt["reference"], c, root)
        if c.canonical(receipt["result"]) != c.canonical(acknowledgement(request, result)):
            raise c.Unverified("foreground receipt result differs from domain history")
        revisions.add(revision)
        ordered.append((revision, request["action"]))
    ordered.extend(dependency("foreground-repair").validate(record, c, e))
    paused = False
    for _, action in sorted(ordered):
        if action in {"pause", "resume"}:
            paused = action == "pause"
        elif paused and action != "reconcile-owner-proposal":
            raise c.Unverified("foreground action recorded while dispatcher paused")
    if state["paused"] != paused:
        raise c.Unverified("pause state differs from retained receipts")
    return state


def owner_boundary(record):
    """Project the current repair boundary, never revive a historical proposal."""
    ledger = record.get("repair_protocol", {})
    prepared = [(key, item) for key, item in ledger.get("corrections", {}).items()
                if item["cycle"] == record["rework_count"]]
    if not prepared:
        return None
    key, correction = prepared[0]
    operations = [item for item in ledger.get("operations", {}).values() if item["correction_id"] == key]
    if operations:
        e = dependency("review-evidence")
        try:
            newer_current = e.current(record)["number"] > correction["generation"]
        except (e.Unverified, KeyError, TypeError):
            newer_current = False
        if newer_current and all(
                item["phase"] == "NOT_APPLIED_OBSERVED" or (
                    item["phase"] == "APPLIED_UNREVIEWED" and record["head_sha"] != item["head"])
                for item in operations):
            return None
        if any(item["phase"] == "APPLIED_UNREVIEWED" for item in operations):
            if any(receipt["request"]["action"] == "adopt-owner-repair-head"
                   and receipt["result"]["domain_result"]["head"] == record["head_sha"]
                   for receipt in record.get("foreground_control", {}).get("receipts", {}).values()):
                return "PREPARE_REPAIRED_REVIEW"
            return "REPAIRED_CANDIDATE_REQUIRES_COMMIT_EXECUTION_AND_REVIEW"
        return "REPAIR_RECONCILIATION_REQUIRED"
    matches = {"owner": "owner", "base_sha": "base", "head_sha": "head", "repo": "repo",
               "branch": "branch", "worktree": "worktree", "owned_paths": "owned_paths",
               "restricted_paths": "restricted_paths", "acceptance_criteria": "acceptance_criteria"}
    protocol = record.get("review_protocol", {})
    if (any(record[field] != correction[target] for field, target in matches.items())
            or protocol.get("material_epoch") != correction["material_epoch"]
            or protocol["generations"][-1]["number"] != correction["generation"]):
        return "OWNER_PROPOSAL_CONTEXT_RECONCILIATION_REQUIRED"
    if record["state"] == "Rework":
        return "ORIGINAL_OWNER_RECLAIM"
    if record["state"] == "Claimed":
        return "ORIGINAL_OWNER_IMPLEMENTING_REQUIRED"
    if (record["state"] != "Implementing" or not record.get("worker")
            or record["worker"]["owner"] != correction["owner"]
            or type(record["leases"].get("global_slot")) is not int
            or type(record["leases"].get("implementation_lane")) is not int):
        return "OWNER_PROPOSAL_CONTEXT_RECONCILIATION_REQUIRED"
    try:
        coordinator = dependency("orchestrator-state")
        coordinator.require_execution_stopped(record)
        coordinator.verify_worktree_identity(record, require_head=True)
        coordinator.verify_clean_checkout(record["worktree"])
    except Exception:
        return "OWNER_PROPOSAL_CONTEXT_RECONCILIATION_REQUIRED"
    proposals = [item for item in record.get("repair_proposals", {}).values()
                 if item["admission"]["correction_id"] == key]
    if not proposals:
        return "ADMIT_OWNER_PROPOSAL"
    latest = max(proposals, key=lambda item: item["resulting_revision"])
    admitted = latest["admission"]
    proposal = dependency("repair-proposal")
    try:
        context, sources = proposal.owner_context(record, key, admitted["sources"],
                                                  dependency("review-collect"), dependency("repair-apply"))
        if (context != admitted["context"] or sources != admitted["source_sha256"]
                or record["worker"] != admitted["worker"]):
            return "OWNER_PROPOSAL_CONTEXT_RECONCILIATION_REQUIRED"
    except Exception:
        return "OWNER_PROPOSAL_CONTEXT_RECONCILIATION_REQUIRED"
    collection = latest["collection"]
    if collection is None:
        return "COLLECT_OWNER_PROPOSAL"
    if collection["status"] == "UNABLE_OBSERVED":
        return "OWNER_PROPOSAL_UNABLE_REQUIRES_OPERATOR"
    return "COLLECTED_OWNER_BUNDLE_REQUIRES_GUARDED_APPLY"


def status(record, state):
    e = dependency("review-evidence")
    review = e.assess(record)
    if record["state"] in {"Done", "Cancelled"}:
        next_action = "TERMINAL_NO_DISPATCH"
    elif record["state"] not in {"Claimed", "Implementing", "Reviewing", "Rework"}:
        next_action = "COORDINATOR_READMISSION_REQUIRED"
    elif dependency("repair-apply").pending(record) or dependency("foreground-repair").pending(record):
        next_action = "REPAIR_RECONCILIATION_REQUIRED"
    elif state["paused"]:
        next_action = "RESUME_FOREGROUND"
    elif (boundary := owner_boundary(record)) is not None:
        next_action = boundary
    elif record["state"] == "Rework":
        next_action = "PREPARE_CORRECTION"
    elif fresh_review_pending(record):
        next_action = "FRESH_EXECUTION_AND_INDEPENDENT_REVIEW_REQUIRED"
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
            "receipt_count": len(state["receipts"]) + dependency("foreground-repair").count(record),
            "next_action": next_action,
            "review_claims": review, "candidate_ready": False,
            "execution_credit": False, "delivery_credit": False}


def fresh_review_pending(record):
    e = dependency("review-evidence")
    try:
        generation = e.current(record)
    except (e.Unverified, KeyError, TypeError):
        return False
    if not any(r["request"]["action"] == "prepare-repaired-review"
               and r["result"]["domain_result"]["generation"] == generation["number"]
               for r in record.get("foreground_control", {}).get("receipts", {}).values()):
        return False
    assessment = e.assess(record)
    return not any(report["findings"] or any(d["resolution"] == "persists" for d in report["dispositions"])
                   for report in generation["reports"].values()) and (
                       assessment.get("unresolved_findings") or assessment.get("review_process") != "CLAIMS_COMPLETE")


def dispatch(record, request, root, bundle=None, persist=None):
    """Caller holds the lock; repair owns its two durable writes via persist."""
    c, e = dependency("review-collect"), dependency("review-evidence")
    state = validate_retained(record, root, c, e)
    if request is None:
        if bundle is not None:
            raise c.Unverified("bundle requires a collection action")
        return record, status(record, state), False
    validate_request(request, c, e)
    if (request["task_id"] != record["task_id"] or request["incarnation"] !=
            dependency("candidate-binding").incarnation(record)):
        raise c.Unverified("task incarnation changed")
    action = request["action"]
    if bundle is not None and action not in COLLECT_ACTIONS:
        raise c.Unverified("bundle requires a collection action")
    prior = state["receipts"].get(request["operation_id"])
    if prior is not None:
        if prior["request"] != request:
            raise c.Unverified("operation ID reused with changed request")
        return record, copy.deepcopy(prior["result"]), False
    repair_bridge = dependency("foreground-repair")
    prior_result = repair_bridge.replay(record, request, c)
    if prior_result is not None:
        return record, prior_result, False
    if request["expected_revision"] != record["revision"]:
        raise c.Unverified("task revision changed")
    if action == "status":
        return record, status(record, state), False
    if record["state"] not in {"Claimed", "Implementing", "Reviewing", "Rework"} or record.get("transition_intent"):
        raise c.Unverified("task is not admitted for foreground mutation")
    coordinator = dependency("orchestrator-state")
    coordinator.require_execution_stopped(record)
    if action not in {"pause", "resume", "reconcile-owner-proposal"}:
        coordinator.require_repair_settled(record, root=root)
        if repair_bridge.pending(record):
            raise c.Unverified("foreground repair requires reconciliation")
    if record["state"] != "Rework" and record.get("worker") is None:
        raise c.Unverified("active lifecycle lacks a worker; reconcile explicitly")
    receipt_count = len(state["receipts"]) + repair_bridge.count(record)
    if receipt_count >= MAX_RECEIPTS:
        raise c.Unverified("foreground receipt budget exhausted")
    if (not repair_bridge.targets_pending(record, request) and repair_bridge.pending(record)
            and receipt_count >= MAX_RECEIPTS - 1):
        raise c.Unverified("final receipt slot requires reconciliation of a pending application")
    if state["paused"] and action not in {"pause", "resume", "reconcile-owner-proposal"}:
        raise c.Unverified("foreground dispatcher is paused")
    operation = request["operation_id"]
    if operation.startswith(repair_bridge.PREFIX):
        raise c.Unverified("reserved repair operation namespace")
    if (any(operation in record.get(table, {}).get("operations", {}) for table in
             ("review_protocol", "runtime_collections", "repair_protocol"))
            or operation in record.get("collected_review_acceptances", {})
            or any(entry["request"]["operation_id"] == operation
                   for item in record.get("repair_proposals", {}).values()
                   for entry in (item, item["collection"]) if entry is not None)):
        raise c.Unverified("operation identifier already used outside dispatcher")
    if action in REPAIR_ACTIONS:
        if persist is None:
            raise c.Unverified("repair requires a lock-held persistence callback")
        return record, repair_bridge.run(record, request, root, persist, state), False
    # Never hand the caller's object to an API that might return/mutate it.
    updated, reference = copy.deepcopy(record), None
    if action == "adopt-owner-repair-head":
        result, reference = dependency("foreground-adopt").adopt(updated, request, root)
    elif action == "prepare-repaired-review":
        updated, result, reference = dependency("foreground-review").prepare(updated, request, root)
    elif action in DOMAIN_ACTIONS:
        artifacts = None
        if action in COLLECT_ACTIONS:
            if bundle is None:
                raise c.Unverified("collection requires --bundle")
            artifacts = {name: c.read_bytes(bundle / name) for name in c.ARTIFACTS}
        if action in PROPOSAL_ACTIONS:
            updated, result, changed = dependency("repair-proposal").apply(
                updated, domain_request(request), root, artifacts=artifacts)
            reference = {"table": "repair_proposals", "key": result["admission_id"]}
        elif action == "collect-review":
            updated, result, changed = c.apply(updated, domain_request(request), root, artifacts=artifacts)
            reference = {"table": "runtime_collections", "key": operation}
        else:
            updated, result, changed = dependency("review-accept").apply(updated, domain_request(request), root)
            reference = {"table": "collected_review_acceptances", "key": operation}
        if not changed:
            raise c.Unverified("unlinked domain replay cannot acquire a foreground receipt")
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
    if action in {"adopt-owner-repair-head", "prepare-repaired-review"}:
        repair_bridge.check_write_budget(updated, record["revision"] + 1, c, coordinator)
    return updated, response, True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--request", type=Path, help="one strict action; omit for read-only status")
    parser.add_argument("--bundle", type=Path, help="review or owner-proposal runtime artifact directory")
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
            updated, result, changed = dispatch(record, request, root, args.bundle,
                persist=lambda value: coordinator.write_task(root, value))
            if changed:
                coordinator.write_task(root, updated)
        print(json.dumps(result, sort_keys=True))
        return 3 if result["status"] in {"REPAIR_RECONCILIATION_REQUIRED", "PARTIAL", "UNVERIFIED"} else 0
    except Exception:
        print(json.dumps({"status": "UNVERIFIED", "reason":
            "foreground action unavailable; verify request, revision, pause, ownership and retained evidence"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
