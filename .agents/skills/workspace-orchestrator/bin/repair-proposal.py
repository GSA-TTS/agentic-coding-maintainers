#!/usr/bin/env python3
"""Admit and collect read-only owner proposals into existing replacement bundles."""

from __future__ import annotations

import argparse
import base64
import copy
import importlib.util
import json
import os
import sys
from pathlib import Path


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise ValueError("installed dependency unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def owner_context(record, correction_id, sources, c, repair):
    correction = record.get("repair_protocol", {}).get("corrections", {}).get(correction_id)
    if correction is None:
        raise ValueError("prepared correction unavailable")
    if (record["kind"] != "implementation" or record["state"] != "Implementing" or repair.pending(record)
            or record["owner"] != correction["owner"] or record["rework_count"] != correction["cycle"]
            or record["head_sha"] != correction["head"] or record["base_sha"] != correction["base"]
            or record["review_protocol"]["material_epoch"] != correction["material_epoch"]
            or record["review_protocol"]["generations"][-1]["number"] != correction["generation"]
            or not record.get("worker") or record["worker"]["owner"] != correction["owner"]
            or type(record["leases"].get("implementation_lane")) is not int
            or type(record["leases"].get("global_slot")) is not int or record.get("transition_intent")):
        raise ValueError("original owner must hold prepared rework lease")
    for field in ("repo", "branch", "worktree", "owned_paths", "restricted_paths", "acceptance_criteria"):
        if record[field] != correction[field]:
            raise ValueError("prepared proposal scope changed")
    coordinator = load("orchestrator-state")
    coordinator.require_execution_stopped(record)
    coordinator.verify_worktree_identity(record, require_head=True)
    coordinator.verify_clean_checkout(record["worktree"])
    if not isinstance(sources, dict) or not 1 <= len(sources) <= 2:
        raise ValueError("one or two explicit source mappings required")
    hashes = {}
    for guest, relative in sources.items():
        c.absolute_guest_path(guest)
        repair.relative_path(relative)
        if not repair.in_scope(relative, correction["owned_paths"]) or repair.in_scope(relative, correction["restricted_paths"], restrictive=True):
            raise ValueError("proposal source outside correction scope")
        hashes[guest] = c.digest(c.read_bytes(Path(record["worktree"]) / relative, 50_000))
    if len(set(sources.values())) != len(sources):
        raise ValueError("duplicate proposal target")
    return {"correction_id": correction_id, "correction": correction, "source_paths": sources}, hashes


def render(final_text, admitted, repair, c):
    if not isinstance(final_text, str) or len(final_text.encode()) > 100_000:
        raise ValueError("proposal output exceeds bound")
    output = c.decode(final_text.encode())
    c.fields(output, {"schema_version", "status", "replacements", "limitations"})
    if type(output["schema_version"]) is not int or output["schema_version"] != 1:
        raise ValueError("unsupported proposal")
    if not isinstance(output["limitations"], list) or len(output["limitations"]) > 32 or any(not isinstance(x, str) or len(x) > 2000 for x in output["limitations"]):
        raise ValueError("invalid limitations")
    if output["status"] == "unable":
        if output["replacements"] != [] or not output["limitations"]:
            raise ValueError("unable response requires reason and no replacements")
        return None
    if output["status"] != "proposed" or not isinstance(output["replacements"], list) or not 1 <= len(output["replacements"]) <= 2:
        raise ValueError("invalid proposed replacements")
    sources = admitted["context"]["source_paths"]
    before = {relative: admitted["source_sha256"][guest] for guest, relative in sources.items()}
    replacements, total = [], 0
    for item in output["replacements"]:
        c.fields(item, {"path", "content"})
        if item["path"] not in before or not isinstance(item["content"], str):
            raise ValueError("proposal changes an unadmitted source")
        data = item["content"].encode("utf-8")
        total += len(data)
        if total > 50_000:
            raise ValueError("proposal content exceeds bound")
        replacements.append({"path": item["path"], "before_sha256": before[item["path"]], "after_base64": base64.b64encode(data).decode()})
    raw = c.canonical({"schema_version": 1, "correction_id": admitted["context"]["correction_id"], "replacements": replacements})
    repair.bundle(raw, admitted["context"]["correction"])
    return raw


def verify_artifacts(admitted, artifacts, c, runner, repair):
    c.fields(artifacts, set(c.ARTIFACTS))
    receipt = c.decode(artifacts["receipt.json"])
    for name in ("model", "agent", "binary_sha256", "profile_sha256", "source_sha256"):
        if receipt.get(name) != admitted[name]:
            raise ValueError("proposal runtime differs from admission")
    if (receipt.get("role") != "owner-proposal" or receipt.get("context_sha256") != c.digest(c.canonical(admitted["context"]))
            or receipt.get("sessions") != [admitted["session"]] or receipt.get("status") != "REVIEW_OBSERVED"
            or receipt.get("candidate_ready") is not False or receipt.get("execution_credit") is not False):
        raise ValueError("proposal role/context/session mismatch")
    if receipt.get("transcript_sha256") != c.digest(artifacts["transcript.jsonl"]) or receipt.get("stderr_sha256") != c.digest(artifacts["stderr.txt"]):
        raise ValueError("proposal artifact substitution")
    if type(receipt.get("returncode")) is not int or receipt["returncode"] != 0 or receipt.get("export_returncode") != 0 or receipt.get("export_failure") is not None:
        raise ValueError("proposal transport unsuccessful")
    summary = runner.corroborate(artifacts["transcript.jsonl"], 0, admitted["source_sha256"], Path(admitted["cwd"]), artifacts["session-export.json"], 0, None)
    if summary["status"] != "REVIEW_OBSERVED" or summary["sessions"] != [admitted["session"]] or summary["final_text"] != receipt.get("final_text"):
        raise ValueError("proposal completion uncorroborated")
    info = c.decode(artifacts["session-export.json"])["info"]
    model = info.get("model", {})
    if info.get("agent") != admitted["agent"] or f"{model.get('providerID')}/{model.get('id')}" != admitted["model"]:
        raise ValueError("export model/agent differs")
    return render(summary["final_text"], admitted, repair, c)


def validate(record, root):
    c, repair, runner = load("review-collect"), load("repair-apply"), load("review-run")
    repair.validate_retained(record, root)
    state = record.get("repair_proposals", {})
    if not isinstance(state, dict) or len(state) > 6:
        raise ValueError("proposal budget exceeded")
    operations, revisions, sessions = set(), set(), set()
    external_ids = set(record.get("review_protocol", {}).get("operations", {})) | set(record.get("runtime_collections", {}).get("operations", {})) | set(record.get("repair_protocol", {}).get("operations", {}))
    external_revisions = {item["result"]["resulting_revision"] for group in (record.get("review_protocol", {}).get("operations", {}), record.get("runtime_collections", {}).get("operations", {})) for item in group.values()}
    reviewer_sessions = {assignment["session"] for generation in record.get("review_protocol", {}).get("generations", []) for assignment in generation["assignments"].values()}
    def check_request(request, resulting, expected_action, request_sha):
        c.fields(request, {"schema_version","operation_id","expected_revision","action","payload"})
        load("review-evidence").token(request["operation_id"])
        if (type(request["schema_version"]) is not int or request["schema_version"] != 1 or request["action"] != expected_action
                or type(request["expected_revision"]) is not int or request["expected_revision"] < 0
                or c.digest(c.canonical(request)) != request_sha
                or request["operation_id"] in operations or request["operation_id"] in external_ids
                or resulting in revisions or resulting in external_revisions):
            raise ValueError("proposal operation identity/revision corruption")
        operations.add(request["operation_id"])
        revisions.add(resulting)
    for key, item in state.items():
        c.fields(item, {"admission", "request", "request_sha256", "resulting_revision", "collection"})
        admitted = item["admission"]
        c.fields(admitted, {"correction_id","session","model","agent","binary_sha256","profile_sha256","cwd","sources","task_id","worker","context","source_sha256"})
        c.fields(admitted["context"], {"correction_id","correction","source_paths"})
        if admitted["sources"] != admitted["context"]["source_paths"] or admitted["correction_id"] != admitted["context"]["correction_id"]:
            raise ValueError("proposal source/context mapping differs")
        if set(admitted["source_sha256"]) != set(admitted["sources"]):
            raise ValueError("proposal source inventory incomplete")
        for sha in admitted["source_sha256"].values():
            load("review-evidence").hash_value(sha)
        request = item["request"]
        check_request(request,item["resulting_revision"],"admit",item["request_sha256"])
        if (type(item["resulting_revision"]) is not int or item["resulting_revision"] != request["expected_revision"] + 1
                or item["resulting_revision"] > record["revision"]):
            raise ValueError("proposal admission chronology invalid")
        expected_payload = {name:admitted[name] for name in ("correction_id","session","model","agent","binary_sha256","profile_sha256","cwd","sources")}
        if request["action"] != "admit" or request["payload"] != expected_payload:
            raise ValueError("proposal request differs from admission")
        if c.digest(c.canonical(admitted)) != key or admitted["task_id"] != record["task_id"]:
            raise ValueError("proposal admission binding changed")
        correction_id = admitted["context"]["correction_id"]
        if record.get("repair_protocol", {}).get("corrections", {}).get(correction_id) != admitted["context"]["correction"]:
            raise ValueError("prepared correction differs from proposal")
        correction = admitted["context"]["correction"]
        if not isinstance(admitted["worker"],dict) or admitted["worker"].get("owner") != correction["owner"]:
            raise ValueError("proposal original worker ownership differs")
        if request["expected_revision"] <= correction["expected_revision"]:
            raise ValueError("proposal admission predates prepared correction")
        if admitted["session"] in sessions or admitted["session"] in reviewer_sessions:
            raise ValueError("owner and reviewer sessions must be distinct")
        sessions.add(admitted["session"])
        collection = item["collection"]
        if collection is not None:
            c.fields(collection, {"request", "request_sha256", "artifacts", "bundle_sha256", "status", "resulting_revision"})
            c.fields(collection["artifacts"], set(c.ARTIFACTS))
            request = collection["request"]
            check_request(request,collection["resulting_revision"],"collect",collection["request_sha256"])
            if (request["action"] != "collect" or request["payload"] != {"admission_id":key,"artifact_sha256":collection["artifacts"]}
                    or type(collection["resulting_revision"]) is not int
                    or collection["resulting_revision"] != request["expected_revision"]+1
                    or not item["resulting_revision"] < collection["resulting_revision"] <= record["revision"]):
                raise ValueError("proposal collection chronology invalid")
            for applied in record.get("repair_protocol", {}).get("operations", {}).values():
                if applied["correction_id"] == correction_id and applied["request"]["expected_revision"] < collection["resulting_revision"]:
                    raise ValueError("proposal collection postdates repair application")
            artifacts = {}
            for name, sha in collection["artifacts"].items():
                load("review-evidence").hash_value(sha)
                data = c.read_bytes(root / "review-artifacts" / sha)
                if c.digest(data) != sha:
                    raise ValueError("proposal artifact lost")
                artifacts[name] = data
            raw = verify_artifacts(admitted, artifacts, c, runner, repair)
            expected = c.digest(raw) if raw is not None else None
            if expected != collection["bundle_sha256"] or collection["status"] != ("PROPOSAL_COLLECTED" if raw is not None else "UNABLE_OBSERVED"):
                raise ValueError("proposal bundle/result mismatch")
            if raw is not None and c.read_bytes(root / "review-artifacts" / expected, 800_000) != raw:
                raise ValueError("rendered repair bundle lost")


def apply(record, request, root, artifacts=None):
    c, e, repair, runner = [load(name) for name in ("review-collect", "review-evidence", "repair-apply", "review-run")]
    c.fields(request, {"schema_version", "operation_id", "expected_revision", "action", "payload"})
    if type(request["schema_version"]) is not int or request["schema_version"] != 1 or request["action"] not in {"admit", "collect"}:
        raise ValueError("invalid proposal request")
    e.token(request["operation_id"])
    validate(record, root)
    for key, item in record.get("repair_proposals", {}).items():
        for prior, response in ((item["request"], {"status": "PROPOSAL_ADMITTED", "admission_id": key, "context": item["admission"]["context"]}),
                                ((item["collection"] or {}).get("request"), {"status": (item["collection"] or {}).get("status"), "admission_id": key, "bundle_sha256": (item["collection"] or {}).get("bundle_sha256")})):
            if prior and prior["operation_id"] == request["operation_id"]:
                if prior != request:
                    raise ValueError("proposal operation reused")
                return record, response, False
    if type(request["expected_revision"]) is not int or record["revision"] != request["expected_revision"]:
        raise ValueError("task revision changed")
    updated = copy.deepcopy(record)
    payload = request["payload"]
    if request["action"] == "admit":
        c.fields(payload, {"correction_id", "session", "model", "agent", "binary_sha256", "profile_sha256", "cwd", "sources"})
        for name in ("correction_id", "binary_sha256", "profile_sha256"):
            e.hash_value(payload[name])
        e.token(payload["session"])
        e.token(payload["agent"])
        e.text(payload["model"], 200)
        c.absolute_guest_path(payload["cwd"])
        context, sources = owner_context(record, payload["correction_id"], payload["sources"], c, repair)
        if any(assignment["session"] == payload["session"] for generation in record.get("review_protocol", {}).get("generations", []) for assignment in generation["assignments"].values()):
            raise ValueError("reviewer session cannot become an owner proposal session")
        admitted = {**copy.deepcopy(payload), "task_id": record["task_id"], "worker": copy.deepcopy(record["worker"]),
                    "context": context, "source_sha256": sources}
        key = c.digest(c.canonical(admitted))
        if key in updated.get("repair_proposals", {}) or any(item["admission"]["session"] == payload["session"] for item in updated.get("repair_proposals", {}).values()):
            raise ValueError("proposal session already admitted")
        updated.setdefault("repair_proposals", {})[key] = {"admission": admitted, "request": request, "request_sha256":c.digest(c.canonical(request)), "resulting_revision": record["revision"]+1, "collection": None}
        result = {"status": "PROPOSAL_ADMITTED", "admission_id": key, "context": context}
    else:
        c.fields(payload, {"admission_id", "artifact_sha256"})
        item = updated.get("repair_proposals", {}).get(payload["admission_id"])
        if item is None or item["collection"] is not None or artifacts is None:
            raise ValueError("proposal unavailable/already collected")
        admitted = item["admission"]
        context, sources = owner_context(record, admitted["correction_id"], admitted["sources"], c, repair)
        if context != admitted["context"] or sources != admitted["source_sha256"] or record["worker"] != admitted["worker"]:
            raise ValueError("proposal owner/source changed")
        actual = {name:c.digest(data) for name,data in artifacts.items()}
        if actual != payload["artifact_sha256"]:
            raise ValueError("proposal artifact request mismatch")
        raw = verify_artifacts(admitted, artifacts, c, runner, repair)
        store = c.ensure_store(root, Path(record["worktree"]))
        for data in artifacts.values():
            c.publish(store, data)
        sha = c.publish(store, raw) if raw is not None else None
        fd = os.open(store, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        item["collection"] = {"request": request, "request_sha256":c.digest(c.canonical(request)), "artifacts": actual, "bundle_sha256": sha,
                              "status": "PROPOSAL_COLLECTED" if raw is not None else "UNABLE_OBSERVED", "resulting_revision": record["revision"]+1}
        result = {"status": item["collection"]["status"], "admission_id": payload["admission_id"], "bundle_sha256": sha}
    if len(c.canonical(updated)) > 900_000:
        raise ValueError("task byte budget exceeded")
    validate({**updated, "revision":record["revision"]+1}, root)
    return updated, result, True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    try:
        if not sys.flags.isolated or not sys.dont_write_bytecode:
            raise ValueError("isolated Python required")
        c, state = load("review-collect"), load("orchestrator-state")
        request = c.decode(c.read_bytes(args.request, 100_000))
        artifacts = {name:c.read_bytes(args.bundle/name) for name in c.ARTIFACTS} if args.bundle else None
        root = state.state_root(create=False)
        with state.CoordinatorLock(root):
            record = state.read_task(root, args.task_id)
            state.verify_reservations(root, record)
            updated, result, changed = apply(record, request, root, artifacts)
            if changed:
                state.write_task(root, updated)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"status":"UNVERIFIED","reason":"owner proposal unavailable; retained evidence unchanged"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
