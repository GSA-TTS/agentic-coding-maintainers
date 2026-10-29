#!/usr/bin/env python3
"""Freeze execution requirements before dispatch and assess retained current cases.

The operator supplies independently reviewed oracle definitions. This is not
approval of those definitions or authority to merge, execute or claim readiness.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

MODULES = ("execution-plan.py", "execution-observe.py", "orchestrator-state.py", "review-collect.py",
           "review-evidence.py", "review-run.py", "review-accept.py")


class Unverified(Exception):
    pass


def load(name: str):
    path = Path(__file__).resolve().with_name(name + ".py")
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    if spec is None or spec.loader is None:
        raise Unverified("installed dependency unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def controller_manifest() -> dict[str, str]:
    return {name: digest(Path(__file__).with_name(name).read_bytes()) for name in MODULES}


def context(record: dict[str, Any], generation: dict[str, Any]) -> dict[str, Any]:
    return {"task_id": record["task_id"], "repo": record["repo"], "owner": generation["owner"],
            "generation": generation["number"], "material_epoch": generation["material_epoch"],
            "packet": generation["packet"], "policy": generation["policy"],
            "head": generation["head"], "base": generation["base"]}


def validate_request(request: dict[str, Any], e) -> None:
    e.fields(request, {"schema_version", "operation_id", "expected_revision", "action", "payload"})
    if type(request["schema_version"]) is not int or request["schema_version"] != 1 or request["action"] != "plan-execution":
        raise Unverified("unsupported execution plan request")
    e.token(request["operation_id"])
    if type(request["expected_revision"]) is not int or request["expected_revision"] < 0:
        raise Unverified("invalid expected task revision")
    e.fields(request["payload"], {"generation", "obligations"})
    if type(request["payload"]["generation"]) is not int or request["payload"]["generation"] < 1:
        raise Unverified("invalid generation")


def requirements(payload: dict[str, Any], generation: dict[str, Any], e) -> dict[str, dict[str, Any]]:
    obligations = payload["obligations"]
    e.fields(obligations, set(generation["obligations"]))
    operations: dict[str, dict[str, Any]] = {}
    for selections in obligations.values():
        if not isinstance(selections, list) or len(selections) > 12:
            raise Unverified("invalid obligation requirements")
        seen = set()
        for selection in selections:
            e.fields(selection, {"operation_id", "definition_sha256", "cases"})
            operation = e.token(selection["operation_id"])
            e.hash_value(selection["definition_sha256"])
            cases = selection["cases"]
            if not isinstance(cases, list) or not 1 <= len(cases) <= 12:
                raise Unverified("required cases must be nonempty and bounded")
            for case in cases:
                e.token(case)
            if len(cases) != len(set(cases)) or operation in seen:
                raise Unverified("duplicate obligation case selection")
            seen.add(operation)
            entry = operations.setdefault(operation, {"definition_sha256": selection["definition_sha256"], "cases": set()})
            if entry["definition_sha256"] != selection["definition_sha256"]:
                raise Unverified("operation references conflicting definitions")
            entry["cases"].update(cases)
    if len(operations) > 12:
        raise Unverified("execution plan exceeds attempt bound")
    # Empty explicit selections have NOT_REQUIRED semantics, not vacuous PASS.
    return operations


def packet_binding(packet_bytes: bytes, generation: dict[str, Any], definition: dict[str, Any], worktree: str, c) -> None:
    if digest(packet_bytes) != generation["packet"]:
        raise Unverified("packet content address mismatch")
    packet = c.decode(packet_bytes)
    if (packet.get("head") != generation["head"] or packet.get("base") != generation["base"]
            or packet.get("policy_sha256") != generation["policy"] or packet.get("kind") != "committed-local-source"):
        raise Unverified("packet identity differs from review")
    if definition["head"] != generation["head"] or definition["base"] != generation["base"]:
        raise Unverified("definition source commits differ from review")
    mounts = definition["mounts"]
    if len(mounts) != 1 or Path(mounts[0]["Source"]).resolve() != Path(worktree).resolve():
        raise Unverified("planned execution requires exactly the admitted source mount")
    captured = {}
    for item in packet["files"]:
        raw_path = base64.b64decode(item["path_base64"], validate=True)
        path = raw_path.decode("utf-8")
        if path in captured:
            raise Unverified("duplicate captured source")
        captured[path] = item["after"]
    for relative, expected in definition["source_sha256"].items():
        side = captured.get(relative)
        if not isinstance(side, dict) or side.get("kind") != "blob":
            raise Unverified("planned source absent from packet regular after-blobs")
        if side.get("encoding") == "utf-8":
            contents = side["content"].encode("utf-8")
        elif side.get("encoding") == "base64":
            contents = base64.b64decode(side["content"], validate=True)
        else:
            raise Unverified("unsupported packet source encoding")
        if digest(contents) != expected or side.get("sha256") != expected or side.get("bytes") != len(contents):
            raise Unverified("planned source does not match packet contents")
    guest_sources = {str(Path(mounts[0]["Destination"]) / path) for path in definition["source_sha256"]}
    if any(not guest_sources.intersection(case["argv"]) for case in definition["cases"]):
        raise Unverified("each oracle command must explicitly reference a captured guest source")


def validate_plans(record: dict[str, Any], root: Path) -> None:
    c, e, observer = load("review-collect"), load("review-evidence"), load("execution-observe")
    e.validate_protocol(record)
    plans = record.get("execution_plans", {})
    if not isinstance(plans, dict) or len(plans) > 16:
        raise Unverified("invalid execution plan ledger")
    generations, operation_ids, revisions, execution_ids = set(), set(), set(), set()
    for plan_id, plan in plans.items():
        e.fields(plan, {"request", "context", "controller", "worktree", "resulting_revision"})
        if digest(canonical(plan)) != plan_id:
            raise Unverified("plan content address differs")
        request = plan["request"]
        validate_request(request, e)
        number = request["payload"]["generation"]
        if not 1 <= number <= len(record["review_protocol"]["generations"]) or number in generations:
            raise Unverified("duplicate or unavailable plan generation")
        generations.add(number)
        generation = record["review_protocol"]["generations"][number - 1]
        if plan["context"] != context(record, generation) or plan["worktree"] != record["worktree"]:
            raise Unverified("plan does not bind this task/repository/review")
        if (type(plan["resulting_revision"]) is not int or plan["resulting_revision"] != request["expected_revision"] + 1
                or not generation["admission_revision"] < request["expected_revision"] < record["revision"]
                or plan["resulting_revision"] in revisions or request["operation_id"] in operation_ids):
            raise Unverified("plan mutation chronology is invalid")
        revisions.add(plan["resulting_revision"])
        operation_ids.add(request["operation_id"])
        e.fields(plan["controller"], set(MODULES))
        for sha in plan["controller"].values():
            e.hash_value(sha)
        operations = requirements(request["payload"], generation, e)
        if execution_ids.intersection(operations):
            raise Unverified("execution operation reserved by more than one plan")
        execution_ids.update(operations)
        for operation, selection in operations.items():
            raw = c.read_bytes(root / "review-artifacts" / selection["definition_sha256"], 200_000)
            if digest(raw) != selection["definition_sha256"]:
                raise Unverified("planned definition bytes changed")
            definition = c.decode(raw)
            observer.validate_definition(definition)
            if selection["cases"] != {case["id"] for case in definition["cases"]}:
                raise Unverified("plan must cover the complete oracle case inventory")
            packet_binding(c.read_bytes(root / "review-artifacts" / generation["packet"], c.PACKET_LIMIT),
                           generation, definition, plan["worktree"], c)
            attempt = record.get("execution_observations", {}).get(operation)
            if attempt is not None and (attempt.get("execution_plan") != plan_id
                    or attempt["request"]["definition_sha256"] != selection["definition_sha256"]
                    or attempt["request"]["expected_revision"] < plan["resulting_revision"]):
                raise Unverified("execution does not originate after its frozen plan")
    other_operations = list(record["review_protocol"]["operations"].items()) + list(record.get("runtime_collections", {}).get("operations", {}).items())
    if any(key in operation_ids or item["result"]["resulting_revision"] in revisions for key, item in other_operations):
        raise Unverified("plan operation collides with another mutation")
    for attempt in record.get("execution_observations", {}).values():
        if "execution_plan" in attempt and attempt["execution_plan"] not in plans:
            raise Unverified("execution origin plan is missing")


def admit(record: dict[str, Any], request: dict[str, Any], root: Path, packet: bytes,
          definitions: dict[str, bytes]) -> tuple[dict[str, Any], dict[str, Any], bool]:
    c, e, observer = load("review-collect"), load("review-evidence"), load("execution-observe")
    validate_request(request, e)
    load("orchestrator-state").require_repair_settled(record, new_review=True, root=root)
    validate_plans(record, root)
    for key, plan in record.get("execution_plans", {}).items():
        if plan["request"]["operation_id"] == request["operation_id"]:
            if plan["request"] != request:
                raise Unverified("operation ID reused with different plan")
            return record, {"status": "EXECUTION_PLAN_ADMITTED", "plan_id": key, "resulting_revision": plan["resulting_revision"]}, False
    if record["revision"] != request["expected_revision"] or not observer.active_execution_owner(record) or record.get("transition_intent"):
        raise Unverified("current admitted task revision required")
    generation = e.current(record)
    if request["payload"]["generation"] != generation["number"] or record["owner"] != generation["owner"]:
        raise Unverified("plan does not bind current review owner/generation")
    if any(plan["context"]["generation"] == generation["number"] for plan in record.get("execution_plans", {}).values()):
        raise Unverified("plan already frozen; new selection requires new review generation")
    operations = requirements(request["payload"], generation, e)
    reserved = {operation for previous in record.get("execution_plans", {}).values()
                for selections in previous["request"]["payload"]["obligations"].values()
                for operation in (selection["operation_id"] for selection in selections)}
    if reserved.intersection(operations):
        raise Unverified("execution operation already reserved by an earlier plan")
    if set(definitions) != {item["definition_sha256"] for item in operations.values()}:
        raise Unverified("supply exactly the referenced definitions")
    if any(attempt["request"]["expected_revision"] >= generation["admission_revision"]
           for attempt in record.get("execution_observations", {}).values()):
        raise Unverified("cannot select requirements after execution in this generation")
    store = c.ensure_store(root, Path(record["worktree"]))
    for operation, selection in operations.items():
        if operation in record.get("execution_observations", {}):
            raise Unverified("execution operation identity already used")
        raw = definitions[selection["definition_sha256"]]
        if digest(raw) != selection["definition_sha256"]:
            raise Unverified("definition content address mismatch")
        definition = c.decode(raw)
        observer.validate_definition(definition)
        observer.source_binding(record, definition, c)
        packet_binding(packet, generation, definition, record["worktree"], c)
        if selection["cases"] != {case["id"] for case in definition["cases"]}:
            raise Unverified("required cases omit or invent oracle assertions")
        c.publish(store, raw)
    if digest(packet) != generation["packet"]:
        raise Unverified("plan packet differs from current generation")
    c.publish(store, packet)
    directory = os.open(store, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    updated = copy.deepcopy(record)
    plan = {"request": copy.deepcopy(request), "context": context(record, generation), "controller": controller_manifest(),
            "worktree": record["worktree"], "resulting_revision": record["revision"] + 1}
    plan_id = digest(canonical(plan))
    updated.setdefault("execution_plans", {})[plan_id] = plan
    if len(canonical(updated)) > 900_000:
        raise Unverified("task evidence budget exceeded")
    validate_plans({**updated, "revision": record["revision"] + 1}, root)
    return updated, {"status": "EXECUTION_PLAN_ADMITTED", "plan_id": plan_id, "resulting_revision": plan["resulting_revision"]}, True


def dispatch_plan(record: dict[str, Any], root: Path, operation: str, definition_sha: str) -> str | None:
    if "execution_plans" not in record:
        if any("execution_plan" in attempt for attempt in record.get("execution_observations", {}).values()):
            raise Unverified("planned execution origin ledger is missing")
        return None  # Historical observer-only tasks retain their limited semantics.
    validate_plans(record, root)
    e = load("review-evidence")
    generation = e.current(record)
    for key, plan in record["execution_plans"].items():
        if plan["context"] != context(record, generation):
            continue
        operations = requirements(plan["request"]["payload"], generation, e)
        if operation not in operations or operations[operation]["definition_sha256"] != definition_sha:
            raise Unverified("execution not selected by current plan")
        if plan["controller"] != controller_manifest() or record["owner"] != plan["context"]["owner"]:
            raise Unverified("controller or owner differs from plan admission")
        return key
    raise Unverified("no frozen plan for current review")


def assess(record: dict[str, Any], root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "UNVERIFIED", "candidate_ready": False, "delivery_credit": False, "execution": {}}
    try:
        c, e, observer = load("review-collect"), load("review-evidence"), load("execution-observe")
        validate_plans(record, root)
        e.validate_collected_retention(record, root)
        result["review"] = e.assess(record)
        generation = e.current(record)
        matches = [(key, plan) for key, plan in record.get("execution_plans", {}).items() if plan["context"] == context(record, generation)]
        if len(matches) != 1 or record["state"] in {"Cancelled", "Blocked"} or record.get("transition_intent"):
            raise Unverified("current plan/state unavailable")
        key, plan = matches[0]
        if plan["controller"] != controller_manifest() or record["owner"] != plan["context"]["owner"]:
            raise Unverified("controller/owner no longer matches plan")
        result.update(plan_id=key, revision=record["revision"], context=plan["context"])
        for obligation, selections in plan["request"]["payload"]["obligations"].items():
            cases = []
            for selection in selections:
                operation = selection["operation_id"]
                status_by_id: dict[str, str] = {}
                reason = "required observation unavailable"
                try:
                    attempt = record.get("execution_observations", {})[operation]
                    if (attempt.get("execution_plan") != key or attempt["phase"] != "SETTLED"
                            or attempt.get("evidence_loss") or attempt["termination"] != "STOPPED_OBSERVED"
                            or attempt["owner"] != plan["context"]["owner"] or attempt["result"]["applicable"] is not True
                            or attempt["controller_sha256"] != plan["controller"]["execution-observe.py"]):
                        raise Unverified("attempt is unsettled, lost or inapplicable")
                    observer.validate_attempts({"execution_observations": {operation: attempt}}, root, c)
                    observer.source_binding(record, attempt["definition"], c)
                    status_by_id = {item["id"]: item["verdict"] for item in attempt["cases"]}
                    reason = "recomputed settled oracle for current packet-bound sources"
                except Exception:
                    pass
                cases.extend({"operation_id": operation, "case": name, "status": status_by_id.get(name, "UNVERIFIED"), "reason": reason}
                             for name in selection["cases"])
            statuses = {item["status"] for item in cases}
            status = "NOT_REQUIRED" if not cases else "FAIL" if "FAIL" in statuses else "UNVERIFIED" if "UNVERIFIED" in statuses else "PASS"
            result["execution"][obligation] = {"status": status, "cases": cases}
        statuses = {item["status"] for item in result["execution"].values()}
        result["status"] = "FAIL" if "FAIL" in statuses else "UNVERIFIED" if "UNVERIFIED" in statuses or statuses == {"NOT_REQUIRED"} else "PASS"
    except Exception:
        result["reason"] = "plan, source or retained evidence could not be validated"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--request", type=Path)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--definition", type=Path, action="append", default=[])
    args = parser.parse_args()
    try:
        if not sys.flags.isolated or not sys.dont_write_bytecode:
            raise Unverified("invoke with python3 -I -B")
        c, coordinator = load("review-collect"), load("orchestrator-state")
        root = coordinator.state_root(create=False)
        if args.request is None:
            if args.packet is not None or args.definition:
                raise Unverified("assessment does not accept mutable packet/definition inputs")
            before = coordinator.read_task(root, args.task_id)
            result = assess(before, root)
            if coordinator.read_task(root, args.task_id) != before:
                result = {"status": "UNVERIFIED", "reason": "task changed during assessment", "candidate_ready": False}
            print(json.dumps(result, sort_keys=True))
            return {"PASS": 0, "FAIL": 1}.get(result["status"], 3)
        request = c.decode(c.read_bytes(args.request, 100_000))
        if args.packet is None:
            raise Unverified("packet required for admission")
        packet = c.read_bytes(args.packet, c.PACKET_LIMIT)
        definitions = {digest(data): data for data in (c.read_bytes(path, 200_000) for path in args.definition)}
        with coordinator.CoordinatorLock(root):
            record = coordinator.read_task(root, args.task_id)
            coordinator.verify_reservations(root, record)
            if any(path.resolve().is_relative_to(Path(record["worktree"]).resolve()) for path in [args.request, *args.definition]):
                raise Unverified("approved plan/definitions must be outside candidate checkout")
            updated, result, changed = admit(record, request, root, packet, definitions)
            if changed:
                coordinator.write_task(root, updated)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"status": "UNVERIFIED", "reason": "execution plan unavailable"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
