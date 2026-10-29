#!/usr/bin/env python3
"""Bounded review claims and shared assessment, without execution or remote credit."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

MAX_BYTES = 1_000_000
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
HASH = re.compile(r"^[0-9a-f]{64}$")
BASELINE = {"correctness", "acceptance", "test-adequacy", "maintainability", "baseline-security"}


class Unverified(Exception):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode("ascii")


def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise Unverified("duplicate JSON field")
        value[key] = item
    return value


def parse(data: bytes) -> dict[str, Any]:
    if not data or len(data) > MAX_BYTES:
        raise Unverified("absent or oversized request")
    try:
        result = json.loads(data, object_pairs_hook=unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(Unverified("nonfinite JSON")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Unverified("malformed request") from exc
    if not isinstance(result, dict):
        raise Unverified("request must be an object")
    return result


def fields(value: Any, names: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != names:
        raise Unverified("unexpected or missing fields")


def text(value: Any, limit: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\0" in value:
        raise Unverified("invalid bounded text")
    return value


def token(value: Any) -> str:
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise Unverified("invalid identifier")
    return value


def hash_value(value: Any) -> str:
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise Unverified("invalid content digest")
    return value


def validate_request(request: dict[str, Any]) -> None:
    fields(request, {"schema_version", "operation_id", "expected_revision", "action", "payload"})
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise Unverified("unsupported request version")
    token(request["operation_id"])
    if type(request["expected_revision"]) is not int or request["expected_revision"] < 0:
        raise Unverified("invalid expected task revision")
    if request["action"] not in {"begin", "assign", "accept"} or not isinstance(request["payload"], dict):
        raise Unverified("invalid operation")


def begin(record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    fields(payload, {"packet", "policy", "base", "head", "obligations"})
    hash_value(payload["packet"])
    hash_value(payload["policy"])
    for name in ("base", "head"):
        if not isinstance(payload[name], str) or not re.fullmatch(r"[0-9a-f]{40}", payload[name]):
            raise Unverified("review requires explicit full base and head commits")
    if payload["base"] != record["base_sha"] or payload["head"] != record["head_sha"] or not payload["head"]:
        raise Unverified("source comparison does not match task")
    obligations = payload["obligations"]
    if not isinstance(obligations, list) or not 5 <= len(obligations) <= 32:
        raise Unverified("invalid obligation list")
    for item in obligations:
        token(item)
    if len(set(obligations)) != len(obligations) or not BASELINE <= set(obligations):
        raise Unverified("mandatory obligations missing or duplicated")
    review = record.setdefault("review_protocol", {"schema_version": 1, "material_epoch": 0, "generations": [], "operations": {}})
    if len(review["generations"]) >= 16:
        raise Unverified("review generation budget exhausted")
    # The third admitted repair must still receive independent re-review;
    # admission of a fourth repair is fenced by coordinator transitions.
    generation = {**copy.deepcopy(payload), "number": len(review["generations"]) + 1,
                  "material_epoch": review["material_epoch"],
                  "admission_revision": record["revision"], "owner": record["owner"],
                  "assignments": {}, "reports": {}, "acceptance_order": []}
    review["generations"].append(generation)
    return {"generation": generation["number"], "status": "BEGUN", "evidence_kind": "claims-only"}


def current(record: dict[str, Any]) -> dict[str, Any]:
    review = record.get("review_protocol")
    if not review or not review.get("generations"):
        raise Unverified("no review generation")
    generation = review["generations"][-1]
    if (generation["head"] != record["head_sha"] or generation["base"] != record["base_sha"]
            or generation["material_epoch"] != review["material_epoch"]):
        raise Unverified("review comparison is stale")
    return generation


def assign(record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    fields(payload, {"generation", "run_id", "reviewer", "profile", "obligations", "adapter", "session"})
    generation = current(record)
    if type(payload["generation"]) is not int or payload["generation"] != generation["number"]:
        raise Unverified("superseded assignment generation")
    run_id = token(payload["run_id"])
    reviewer = token(payload["reviewer"])
    hash_value(payload["profile"])
    text(payload["session"], 256)
    if reviewer == generation["owner"] or payload["adapter"] not in {"fake", "native-session"}:
        raise Unverified("reviewer must be separate from owner and use an explicit adapter")
    obligations = payload["obligations"]
    if not isinstance(obligations, list) or not obligations or len(obligations) > 32:
        raise Unverified("invalid assignment obligations")
    if any(not isinstance(item, str) for item in obligations) or len(set(obligations)) != len(obligations):
        raise Unverified("invalid assignment obligations")
    if not set(obligations) <= set(generation["obligations"]):
        raise Unverified("assignment obligations are outside current plan")
    if run_id in generation["assignments"] or len(generation["assignments"]) >= 12:
        raise Unverified("run already assigned or assignment budget exhausted")
    generation["assignments"][run_id] = copy.deepcopy(payload)
    return {"generation": generation["number"], "run_id": run_id, "status": "ASSIGNED"}


def validate_finding(finding: Any) -> None:
    fields(finding, {"id", "invariant", "trigger", "path", "impact", "evidence"})
    token(finding["id"])
    for name in ("invariant", "trigger", "path", "impact", "evidence"):
        text(finding[name])


def accept(record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    expected = {"generation", "run_id", "packet", "policy", "profile", "session", "coverage", "findings", "dispositions", "limitations"}
    if "collection_origin" in payload:
        fields(payload["collection_origin"], {"admission_id", "operation_id"})
        hash_value(payload["collection_origin"]["admission_id"])
        token(payload["collection_origin"]["operation_id"])
        expected.add("collection_origin")
    fields(payload, expected)
    generation = current(record)
    if type(payload["generation"]) is not int or payload["generation"] != generation["number"]:
        raise Unverified("superseded result generation")
    run_id = token(payload["run_id"])
    assignment = generation["assignments"].get(run_id)
    if assignment is None or run_id in generation["reports"]:
        raise Unverified("unassigned or already accepted run")
    for name in ("packet", "policy"):
        if payload[name] != generation[name]:
            raise Unverified("result does not bind current source/policy")
    for name in ("profile", "session"):
        if payload[name] != assignment[name]:
            raise Unverified("result does not bind assigned reviewer context")
    coverage = payload["coverage"]
    fields(coverage, set(assignment["obligations"]))
    if any(value not in {"reviewed", "unverified"} for value in coverage.values()):
        raise Unverified("invalid obligation coverage")
    for name, maximum in (("findings", 50), ("dispositions", 50), ("limitations", 32)):
        if not isinstance(payload[name], list) or len(payload[name]) > maximum:
            raise Unverified("oversized result list")
    for limitation in payload["limitations"]:
        text(limitation)
    known = finding_history(record)
    seen = set(known)
    for finding in payload["findings"]:
        validate_finding(finding)
        if finding["id"] in seen:
            raise Unverified("finding identifier already used")
        seen.add(finding["id"])
    disposed: set[str] = set()
    for disposition in payload["dispositions"]:
        fields(disposition, {"finding_id", "resolution", "counterevidence"})
        finding_id = token(disposition["finding_id"])
        text(disposition["counterevidence"])
        if disposition["resolution"] not in {"fixed", "refuted", "persists"} or finding_id not in known or finding_id in disposed:
            raise Unverified("invalid finding disposition")
        if (known[finding_id]["generation"], known[finding_id]["run_id"]) == (generation["number"], run_id):
            raise Unverified("finding disposition requires a separate run")
        disposed.add(finding_id)
    generation["reports"][run_id] = copy.deepcopy(payload)
    generation["acceptance_order"].append(run_id)
    return {"status": "CLAIM_ACCEPTED", "run_id": run_id, "generation": generation["number"],
            "report_sha256": hashlib.sha256(canonical(payload)).hexdigest(), "execution_credit": False}


def finding_history(record: dict[str, Any]) -> dict[str, Any]:
    history: dict[str, Any] = {}
    for generation in record.get("review_protocol", {}).get("generations", []):
        for run_id in generation["acceptance_order"]:
            report = generation["reports"][run_id]
            for finding in report["findings"]:
                history[finding["id"]] = {"finding": finding, "generation": generation["number"],
                                          "run_id": run_id, "dispositions": []}
            for disposition in report["dispositions"]:
                if disposition["finding_id"] not in history:
                    raise Unverified("finding history references absent evidence")
                history[disposition["finding_id"]]["dispositions"].append(
                    {**disposition, "generation": generation["number"], "run_id": run_id})
    return history


def assess(record: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "UNVERIFIED", "review_process": "UNVERIFIED",
                              "candidate_ready": False, "execution_credit": False, "delivery_credit": False}
    try:
        validate_protocol(record)
        generation = current(record)
        covered: set[str] = set()
        for report in generation["reports"].values():
            covered.update(name for name, value in report["coverage"].items() if value == "reviewed")
        unresolved = []
        for identifier, history in finding_history(record).items():
            dispositions = [item for item in history["dispositions"] if item["generation"] == generation["number"]]
            if not dispositions or dispositions[-1]["resolution"] == "persists":
                unresolved.append(identifier)
        missing = sorted(set(generation["obligations"]) - covered)
        result.update(generation=generation["number"], missing_obligations=missing, unresolved_findings=unresolved,
                      review_process="CLAIMS_COMPLETE" if not missing else "UNVERIFIED",
                      reason="Submitted review claims are not corroborated runtime/source-access evidence.")
        if unresolved:
            result["status"] = "HOLD"
    except (Unverified, KeyError, TypeError, ValueError):
        result["reason"] = "Review evidence is absent, invalid or stale."
    return result


def correction_request(record: dict[str, Any]) -> dict[str, Any]:
    """Derive an owner-addressed repair request without granting a write lease."""
    validate_protocol(record)
    generation = current(record)
    assessment = assess(record)
    if record["kind"] != "implementation" or record["state"] not in {"Reviewing", "Rework"}:
        raise Unverified("correction requires an implementation in review or rework")
    original_owner = record["review_protocol"]["generations"][0]["owner"]
    if record["owner"] != original_owner or generation["owner"] != original_owner or not original_owner:
        raise Unverified("original implementation owner changed")
    count = record["rework_count"]
    if type(count) is not int or not 0 <= count <= 3 or (record["state"] == "Reviewing" and count == 3):
        raise Unverified("repair budget exhausted; checkpoint and escalate")
    if record["state"] == "Rework" and count == 0:
        raise Unverified("rework state has no admitted cycle")
    identifiers = assessment.get("unresolved_findings")
    if not identifiers:
        raise Unverified("no unresolved finding requires correction")
    history = finding_history(record)
    request = {
        "schema_version": 1, "kind": "owner-correction-request", "task_id": record["task_id"],
        "expected_revision": record["revision"], "owner": original_owner,
        "repo": record["repo"], "branch": record["branch"], "worktree": record["worktree"],
        "base": record["base_sha"], "head": record["head_sha"], "generation": generation["number"],
        "packet": generation["packet"], "policy": generation["policy"],
        "owned_paths": record["owned_paths"], "restricted_paths": record["restricted_paths"],
        "acceptance_criteria": record["acceptance_criteria"],
        "findings": [history[identifier] for identifier in identifiers],
        "remaining_rework_cycles": 3 - count + (1 if record["state"] == "Rework" else 0),
        "write_authority": False,
        "next_action": "Original owner must claim rework through the coordinator before changing its assigned worktree; independently re-review the new generation.",
    }
    request["request_sha256"] = hashlib.sha256(canonical(request)).hexdigest()
    return request


def apply(record: dict[str, Any], request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], bool]:
    validate_request(request)
    load_coordinator().require_repair_settled(record, new_review=True)
    validate_protocol(record)
    request_digest = hashlib.sha256(canonical(request)).hexdigest()
    operations = record.get("review_protocol", {}).get("operations", {})
    prior = operations.get(request["operation_id"])
    if prior is not None:
        if prior["request_sha256"] != request_digest:
            raise Unverified("operation ID reused with different content")
        return record, prior["result"], False
    if request["expected_revision"] != record["revision"]:
        raise Unverified("task revision changed")
    if record["state"] not in {"Claimed", "Implementing", "Reviewing", "Rework"}:
        raise Unverified("task is not admitted for review mutation")
    if record.get("transition_intent") is not None:
        raise Unverified("unfinished lifecycle transition must be reconciled")
    if len(operations) >= 100:
        raise Unverified("operation receipt budget exhausted")
    updated = copy.deepcopy(record)
    result = {"begin": begin, "assign": assign, "accept": accept}[request["action"]](updated, request["payload"])
    result["resulting_revision"] = record["revision"] + 1
    updated["review_protocol"]["operations"][request["operation_id"]] = {
        "request_sha256": request_digest, "request": copy.deepcopy(request), "result": result}
    prospective = {**updated, "revision": record["revision"] + 1}
    validate_protocol(prospective)
    if len(canonical(updated)) > 900_000:
        raise Unverified("authoritative evidence record budget exhausted")
    return updated, result, True


def validate_protocol(record: dict[str, Any]) -> None:
    """Revalidate persisted claims through the same acceptance contracts."""
    if "review_protocol" not in record:
        return
    review = record["review_protocol"]
    fields(review, {"schema_version", "material_epoch", "generations", "operations"})
    if type(review["schema_version"]) is not int or review["schema_version"] != 1:
        raise Unverified("invalid persisted review schema")
    if type(review["material_epoch"]) is not int or review["material_epoch"] < 0:
        raise Unverified("invalid material epoch")
    if not isinstance(review["generations"], list) or not 1 <= len(review["generations"]) <= 16:
        raise Unverified("invalid persisted generations")
    replay = {"revision": 0, "owner": "", "kind": "review", "rework_count": 0}
    previous_epoch = 0
    for index, generation in enumerate(review["generations"], 1):
        fields(generation, {"packet", "policy", "base", "head", "obligations", "number", "material_epoch",
                            "admission_revision", "owner", "assignments", "reports", "acceptance_order"})
        epoch = generation["material_epoch"]
        if type(epoch) is not int or not previous_epoch <= epoch <= review["material_epoch"]:
            raise Unverified("invalid generation epoch order")
        previous_epoch = epoch
        if type(generation["number"]) is not int or generation["number"] != index:
            raise Unverified("invalid generation numbering")
        if type(generation["admission_revision"]) is not int or not 0 <= generation["admission_revision"] < record["revision"]:
            raise Unverified("invalid admission revision")
        for name in ("base", "head"):
            if not isinstance(generation[name], str) or not re.fullmatch(r"[0-9a-f]{40}", generation[name]):
                raise Unverified("invalid persisted commit identity")
        text(generation["owner"])
        replay.update(revision=generation["admission_revision"], owner=generation["owner"],
                      base_sha=generation["base"], head_sha=generation["head"])
        if "review_protocol" not in replay:
            replay["review_protocol"] = {"schema_version": 1, "material_epoch": epoch, "generations": [], "operations": {}}
        replay["review_protocol"]["material_epoch"] = epoch
        begin(replay, {key: generation[key] for key in ("packet", "policy", "base", "head", "obligations")})
        assignments, reports, order = generation["assignments"], generation["reports"], generation["acceptance_order"]
        if not isinstance(assignments, dict) or not isinstance(reports, dict) or not isinstance(order, list):
            raise Unverified("invalid persisted report containers")
        if any(not isinstance(item, str) for item in order) or len(order) != len(set(order)) or set(order) != set(reports):
            raise Unverified("accepted reports disagree with acceptance order")
        for run_id, assignment in assignments.items():
            if not isinstance(assignment, dict) or assignment.get("run_id") != run_id:
                raise Unverified("assignment index disagrees with run")
            assign(replay, assignment)
        for run_id in order:
            if not isinstance(reports[run_id], dict) or reports[run_id].get("run_id") != run_id:
                raise Unverified("report index disagrees with run")
            accept(replay, reports[run_id])
    operations = review["operations"]
    if not isinstance(operations, dict) or len(operations) > 100:
        raise Unverified("invalid operation receipts")
    mutations: set[tuple[Any, ...]] = set()
    mutation_revisions: dict[tuple[Any, ...], int] = {}
    revisions: set[int] = set()
    for operation_id, receipt in operations.items():
        token(operation_id)
        fields(receipt, {"request_sha256", "request", "result"})
        hash_value(receipt["request_sha256"])
        request = receipt["request"]
        validate_request(request)
        if request["operation_id"] != operation_id or hashlib.sha256(canonical(request)).hexdigest() != receipt["request_sha256"]:
            raise Unverified("receipt request binding is invalid")
        result = receipt["result"]
        if not isinstance(result, dict):
            raise Unverified("invalid operation result")
        status = result.get("status")
        expected = {"status", "generation", "resulting_revision"}
        if status == "BEGUN":
            fields(result, expected | {"evidence_kind"})
            if result["evidence_kind"] != "claims-only":
                raise Unverified("receipt grants unsupported evidence")
        elif status in {"ASSIGNED", "CLAIM_ACCEPTED"}:
            fields(result, expected | {"run_id"} | ({"report_sha256", "execution_credit"} if status == "CLAIM_ACCEPTED" else set()))
            token(result["run_id"])
            if status == "CLAIM_ACCEPTED":
                hash_value(result["report_sha256"])
                if result["execution_credit"] is not False:
                    raise Unverified("receipt grants execution credit")
        else:
            raise Unverified("unsupported receipt status")
        if type(result["resulting_revision"]) is not int or not 1 <= result["resulting_revision"] <= record["revision"]:
            raise Unverified("invalid receipt revision")
        if type(result["generation"]) is not int or not 1 <= result["generation"] <= len(review["generations"]):
            raise Unverified("invalid receipt generation")
        generation = review["generations"][result["generation"] - 1]
        if result["resulting_revision"] != request["expected_revision"] + 1 or result["resulting_revision"] in revisions:
            raise Unverified("receipt mutation revision is inconsistent")
        revisions.add(result["resulting_revision"])
        payload = request["payload"]
        if status == "BEGUN":
            expected_payload = {key: generation[key] for key in ("packet", "policy", "base", "head", "obligations")}
            mutation = (result["generation"], "begin")
            if request["action"] != "begin" or payload != expected_payload or request["expected_revision"] != generation["admission_revision"]:
                raise Unverified("begin receipt disagrees with generation")
        else:
            action = "assign" if status == "ASSIGNED" else "accept"
            group = "assignments" if action == "assign" else "reports"
            retained = generation[group].get(result["run_id"])
            mutation = (result["generation"], action, result["run_id"])
            if request["action"] != action or retained is None or payload != retained:
                raise Unverified("receipt references missing or substituted evidence")
            if action == "accept" and hashlib.sha256(canonical(retained)).hexdigest() != result["report_sha256"]:
                raise Unverified("report digest disagrees with receipt")
        if mutation in mutations:
            raise Unverified("duplicate mutation receipt")
        mutations.add(mutation)
        mutation_revisions[mutation] = result["resulting_revision"]
    expected_mutations = set()
    for generation in review["generations"]:
        expected_mutations.add((generation["number"], "begin"))
        expected_mutations.update((generation["number"], "assign", run_id) for run_id in generation["assignments"])
        expected_mutations.update((generation["number"], "accept", run_id) for run_id in generation["reports"])
    if mutations != expected_mutations:
        raise Unverified("retained mutations lack operation receipts")
    for index, generation in enumerate(review["generations"], 1):
        created = mutation_revisions[(index, "begin")]
        next_created = mutation_revisions.get((index + 1, "begin"), record["revision"] + 1)
        if created >= next_created:
            raise Unverified("generation begin receipts are out of order")
        for run_id in generation["assignments"]:
            assigned = mutation_revisions[(index, "assign", run_id)]
            if not created < assigned < next_created:
                raise Unverified("assignment receipt violates generation chronology")
        order = generation["acceptance_order"]
        accepted_revisions = [mutation_revisions[(index, "accept", run_id)] for run_id in order]
        if accepted_revisions != sorted(accepted_revisions):
            raise Unverified("acceptance order disagrees with receipt chronology")
        for run_id, accepted in zip(order, accepted_revisions):
            if not mutation_revisions[(index, "assign", run_id)] < accepted < next_created:
                raise Unverified("report receipt violates assignment chronology")


def load_coordinator():
    source = Path(__file__).resolve().with_name("orchestrator-state.py")
    spec = importlib.util.spec_from_file_location("installed_coordinator", source)
    if spec is None or spec.loader is None:
        raise Unverified("installed coordinator unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_request(path: Path) -> dict[str, Any]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise Unverified("staging input is not a regular file")
        return parse(handle.read(MAX_BYTES + 1))


def validate_collected_retention(record: dict[str, Any], root: Path) -> None:
    has_collected_reports = any("collection_origin" in report
                                for generation in record.get("review_protocol", {}).get("generations", [])
                                for report in generation["reports"].values())
    if "collected_review_acceptances" in record or has_collected_reports:
        source = Path(__file__).resolve().with_name("review-accept.py")
        spec = importlib.util.spec_from_file_location("installed_review_acceptance", source)
        if spec is None or spec.loader is None:
            raise Unverified("installed collected-review validator unavailable")
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        validator.validate_retained(record, root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--request", type=Path)
    parser.add_argument("--correction", action="store_true", help="emit an owner-directed correction without changing state")
    args = parser.parse_args()
    try:
        if not sys.flags.isolated or not sys.dont_write_bytecode:
            raise Unverified("invoke with python3 -I -B")
        if args.correction and args.request is not None:
            raise Unverified("correction projection cannot mutate evidence")
        coordinator = load_coordinator()
        root = coordinator.state_root(create=args.request is not None)
        if args.request is None:
            record = coordinator.read_task(root, args.task_id)
            validate_collected_retention(record, root)
            result = correction_request(record) if args.correction else assess(record)
        else:
            request = read_request(args.request)
            if isinstance(request.get("payload"), dict) and "collection_origin" in request["payload"]:
                raise Unverified("collection provenance requires the collected-acceptance controller")
            with coordinator.CoordinatorLock(root):
                record = coordinator.read_task(root, args.task_id)
                coordinator.verify_reservations(root, record)
                validate_collected_retention(record, root)
                updated, result, changed = apply(record, request)
                if changed:
                    coordinator.write_task(root, updated)
        print(json.dumps(result, sort_keys=True))
        return 0 if args.request is not None or args.correction else 3
    except Exception as exc:
        reason = str(exc) if isinstance(exc, Unverified) else "evidence operation unavailable"
        print(json.dumps({"status": "UNVERIFIED", "reason": reason}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
