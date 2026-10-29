#!/usr/bin/env python3
"""Accept structured collected final responses as bound review claims, not proof."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


def dependencies():
    # Isolated Python plus a fixed sibling path selects installed controller code.
    import importlib.util

    path = Path(__file__).resolve().with_name("review-collect.py")
    spec = importlib.util.spec_from_file_location("installed_collection", path)
    if spec is None or spec.loader is None:
        raise ValueError("installed collection dependency unavailable")
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    return collector, collector.load_module("review-evidence"), collector.load_module("review-run")


def final_report(record: dict[str, Any], admission_id: str, store: Path, c, e) -> dict[str, Any]:
    state = record["runtime_collections"]
    admitted = state["admissions"].get(admission_id)
    collected = state["collections"].get(admission_id)
    if admitted is None or collected is None:
        raise c.Unverified("no retained collection for admission")
    receipt = c.decode(c.read_bytes(store / collected["artifacts"]["receipt.json"]))
    text = receipt.get("final_text")
    if not isinstance(text, str) or len(text.encode("utf-8")) > 100_000:
        raise c.Unverified("final response is absent or oversized")
    if c.digest(text.encode("utf-8")) != collected["summary"]["final_text_sha256"]:
        raise c.Unverified("final response differs from collected summary")
    content = e.parse(text.encode("utf-8"))
    e.fields(content, {"schema_version", "coverage", "findings", "dispositions", "limitations"})
    if type(content["schema_version"]) is not int or content["schema_version"] != 1:
        raise c.Unverified("unsupported structured review version")
    return {"generation": admitted["generation"], "run_id": admitted["run_id"],
            "packet": admitted["packet"], "policy": admitted["policy"],
            "profile": admitted["assignment"]["profile"], "session": admitted["assignment"]["session"],
            **{name: content[name] for name in ("coverage", "findings", "dispositions", "limitations")}}


def validate_request(request: dict[str, Any], c, e) -> None:
    e.fields(request, {"schema_version", "operation_id", "expected_revision", "action", "payload"})
    if type(request["schema_version"]) is not int or request["schema_version"] != 1 or request["action"] != "accept-collected":
        raise c.Unverified("unsupported collected acceptance request")
    e.token(request["operation_id"])
    if type(request["expected_revision"]) is not int or request["expected_revision"] < 0:
        raise c.Unverified("invalid expected task revision")
    e.fields(request["payload"], {"admission_id"})
    e.hash_value(request["payload"]["admission_id"])


def validate_links(record: dict[str, Any], store: Path, c, e) -> None:
    links = record.get("collected_review_acceptances", {})
    if not isinstance(links, dict) or len(links) > c.MAX_OPERATIONS:
        raise c.Unverified("invalid acceptance link table")
    admissions_seen = set()
    for operation_id, link in links.items():
        e.fields(link, {"request", "request_sha256", "report_sha256"})
        request = link["request"]
        validate_request(request, c, e)
        if request["operation_id"] != operation_id or c.digest(c.canonical(request)) != link["request_sha256"]:
            raise c.Unverified("acceptance request binding mismatch")
        admission_id = request["payload"]["admission_id"]
        if admission_id in admissions_seen:
            raise c.Unverified("collection accepted more than once")
        admissions_seen.add(admission_id)
        report = final_report(record, admission_id, store, c, e)
        operation = record["review_protocol"]["operations"].get(operation_id)
        expected = {**request, "action": "accept", "payload": report}
        if operation is None or operation["request"] != expected or operation["result"].get("report_sha256") != link["report_sha256"]:
            raise c.Unverified("accepted claim differs from retained final response")
        if operation_id in record["runtime_collections"]["operations"]:
            raise c.Unverified("operation identifier collides with collection operation")
        collection_operations = [item for item in record["runtime_collections"]["operations"].values()
                                 if item["request"]["action"] == "collect"
                                 and item["result"]["admission_id"] == admission_id]
        if len(collection_operations) != 1 or collection_operations[0]["result"]["resulting_revision"] > request["expected_revision"]:
            raise c.Unverified("claim acceptance precedes collection")


def validate_retained(record: dict[str, Any], root: Path) -> None:
    """Shared artifact-aware check for acceptance and controller assessments."""
    c, e, runner = dependencies()
    e.validate_protocol(record)
    store = root / "review-artifacts"
    c.no_links(store)
    if store.resolve().is_relative_to(Path(record["worktree"]).resolve()):
        raise c.Unverified("accepted artifacts are inside candidate worktree")
    info = store.stat()
    if info.st_uid != c.os.getuid() or info.st_mode & 0o077:
        raise c.Unverified("accepted artifact store is not private")
    c.validate_retained(record["runtime_collections"], store, record, e, runner)
    validate_links(record, store, c, e)


def apply(record: dict[str, Any], request: dict[str, Any], root: Path) -> tuple[dict[str, Any], dict[str, Any], bool]:
    c, e, runner = dependencies()
    validate_request(request, c, e)
    e.validate_protocol(record)
    state = record.get("runtime_collections")
    if state is None:
        raise c.Unverified("task has no collected runtime observations")
    store = root / "review-artifacts"
    validate_retained(record, root)
    operation_id = request["operation_id"]
    prior = record.get("collected_review_acceptances", {}).get(operation_id)
    if prior is not None:
        if prior["request"] != request:
            raise c.Unverified("acceptance operation ID reused with different content")
        return record, record["review_protocol"]["operations"][operation_id]["result"], False
    if operation_id in record["review_protocol"]["operations"] or operation_id in state["operations"]:
        raise c.Unverified("operation identifier already used")
    if len(record.get("collected_review_acceptances", {})) >= c.MAX_OPERATIONS:
        raise c.Unverified("acceptance budget exhausted")
    if request["expected_revision"] != record["revision"]:
        raise c.Unverified("task revision changed")
    admission_id = request["payload"]["admission_id"]
    report = final_report(record, admission_id, store, c, e)
    generation = e.current(record)
    admitted = state["admissions"][admission_id]
    if (admitted["generation"] != generation["number"] or admitted["material_epoch"] != generation["material_epoch"]
            or admitted["owner"] != record["owner"] or admitted["assignment"] != generation["assignments"].get(admitted["run_id"])):
        raise c.Unverified("collected observation is superseded")
    updated, result, changed = e.apply(record, {**request, "action": "accept", "payload": report})
    if not changed:
        raise c.Unverified("unlinked existing claim cannot be promoted")
    updated.setdefault("collected_review_acceptances", {})[operation_id] = {
        "request": copy.deepcopy(request), "request_sha256": c.digest(c.canonical(request)),
        "report_sha256": result["report_sha256"]}
    prospective = {**updated, "revision": record["revision"] + 1}
    c.validate_retained(prospective["runtime_collections"], store, prospective, e, runner)
    validate_links(prospective, store, c, e)
    if len(c.canonical(updated)) > 900_000:
        raise c.Unverified("task evidence budget exceeded")
    return updated, result, True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not sys.flags.isolated or not sys.dont_write_bytecode:
            raise ValueError("invoke with python3 -I -B")
        c, _, _ = dependencies()
        request = c.decode(c.read_bytes(args.request, 100_000))
        coordinator = c.load_module("orchestrator-state")
        root = coordinator.state_root(create=False)
        with coordinator.CoordinatorLock(root):
            record = coordinator.read_task(root, args.task_id)
            coordinator.verify_reservations(root, record)
            updated, result, changed = apply(record, request, root)
            if changed:
                coordinator.write_task(root, updated)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"status": "UNVERIFIED", "reason": "collected acceptance unavailable; verify request, current assignment and retained artifacts"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
