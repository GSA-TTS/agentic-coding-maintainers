#!/usr/bin/env python3
"""Apply bounded owner-supplied replacement bytes; never execute candidate code.

Use the trusted installed controller with exclusive ownership. Candidate copies
are tested only in isolation. Filesystem application is not review approval.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import copy
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path
from typing import Any

LIMIT = 262_144
DENIED = {".git", ".orchestrator", ".opencode", ".agents", ".github", ".env", "AGENTS.md", "opencode.json", "opencode.jsonc"}


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


def relative_path(value: Any) -> str:
    if (not isinstance(value, str) or len(value) > 240 or not value.isascii()
            or any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", part) for part in value.split("/"))
            or any(part.casefold() in {item.casefold() for item in DENIED} for part in value.split("/"))):
        raise Unverified("repair requires conservative relative ordinary-file paths")
    return value


def in_scope(path: str, scopes: list[str], restrictive: bool = False) -> bool:
    if restrictive:
        path, scopes = path.casefold(), [scope.casefold() for scope in scopes]
    return any(scope in {".", ""} or path == scope.rstrip("/") or path.startswith(scope.rstrip("/") + "/") for scope in scopes)


def bundle(raw: bytes, correction: dict[str, Any]) -> list[dict[str, Any]]:
    c, e = load("review-collect"), load("review-evidence")
    if len(raw) > 800_000:
        raise Unverified("replacement bundle exceeds bound")
    value = c.decode(raw)
    e.fields(value, {"schema_version", "correction_id", "replacements"})
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["correction_id"] != digest(canonical(correction)):
        raise Unverified("bundle correction identity mismatch")
    entries = value["replacements"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 2:
        raise Unverified("repair must replace one or two existing files")
    result, seen, total = [], set(), 0
    for entry in entries:
        e.fields(entry, {"path", "before_sha256", "after_base64"})
        path = relative_path(entry["path"])
        if path.casefold() in seen or not in_scope(path, correction["owned_paths"]) or in_scope(path, correction["restricted_paths"], restrictive=True):
            raise Unverified("duplicate, unowned or restricted repair path")
        if any(path.casefold().startswith(other + "/") or other.startswith(path.casefold() + "/") for other in seen):
            raise Unverified("repair paths overlap")
        seen.add(path.casefold())
        e.hash_value(entry["before_sha256"])
        if not isinstance(entry["after_base64"], str):
            raise Unverified("replacement encoding must be base64")
        contents = base64.b64decode(entry["after_base64"], validate=True)
        if base64.b64encode(contents).decode() != entry["after_base64"]:
            raise Unverified("replacement encoding is noncanonical")
        total += len(contents)
        if len(contents) > LIMIT or total > 2 * LIMIT or digest(contents) == entry["before_sha256"]:
            raise Unverified("oversized or unchanged replacement")
        result.append({**entry, "after_sha256": digest(contents)})
    return result


@contextlib.contextmanager
def parent_fd(root: Path, path: str):
    # Component-by-component no-follow traversal; cooperative exclusive writer
    # remains required against concurrent ancestor relocation by the same user.
    c = load("review-collect")
    c.no_links(root)
    descriptors = [os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]
    device = os.fstat(descriptors[0]).st_dev
    try:
        for part in path.split("/")[:-1]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptors[-1])
            descriptors.append(fd)
            if os.fstat(fd).st_dev != device:
                raise Unverified("repair crosses a filesystem boundary")
        yield descriptors[-1], path.split("/")[-1], device
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def read_target(parent: int, name: str, device: int) -> tuple[bytes, os.stat_result]:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_dev != device
                or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) not in {0o600, 0o644}
                or getattr(info, "st_flags", 0)):
            raise Unverified("target must be a single-link owned ordinary non-executable file")
        try:
            if not hasattr(os, "listxattr") or os.listxattr(fd):
                raise Unverified("target metadata cannot be preserved safely")
        except OSError as exc:
            raise Unverified("target metadata cannot be preserved safely") from exc
        data = handle.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise Unverified("target exceeds repair bound")
        return data, info


def inspect_targets(root: Path, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for entry in entries:
        with parent_fd(root, entry["path"]) as (parent, name, device):
            data, info = read_target(parent, name, device)
        result.append({"path": entry["path"], "sha256": digest(data), "mode": stat.S_IMODE(info.st_mode)})
    return result


def replace_one(root: Path, entry: dict[str, Any], mode: int) -> None:
    with parent_fd(root, entry["path"]) as (parent, name, device):
        data, original = read_target(parent, name, device)
        if digest(data) != entry["before_sha256"] or stat.S_IMODE(original.st_mode) != mode:
            raise Unverified("target changed after repair preflight")
        temporary = ".repair-" + uuid.uuid4().hex
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                os.fchmod(handle.fileno(), mode)
                handle.write(base64.b64decode(entry["after_base64"], validate=True))
                handle.flush()
                os.fsync(handle.fileno())
            again, identity = read_target(parent, name, device)
            if (identity.st_dev, identity.st_ino) != (original.st_dev, original.st_ino) or digest(again) != entry["before_sha256"]:
                raise Unverified("target identity changed before replacement")
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass


def pending(record: dict[str, Any]) -> bool:
    return any(item["phase"] in {"APPLYING", "PARTIAL", "UNVERIFIED"} for item in record.get("repair_protocol", {}).get("operations", {}).values())


def validate_retained(record: dict[str, Any], root: Path) -> None:
    c, e = load("review-collect"), load("review-evidence")
    ledger = record.get("repair_protocol")
    if ledger is None:
        return
    e.fields(ledger, {"schema_version", "corrections", "operations"})
    if type(ledger["schema_version"]) is not int or ledger["schema_version"] != 1:
        raise Unverified("invalid repair ledger schema")
    for name in ("corrections", "operations"):
        if not isinstance(ledger[name], dict) or len(ledger[name]) > 3:
            raise Unverified("repair ledger exceeds cycle bound")
    for key, correction in ledger["corrections"].items():
        if digest(canonical(correction)) != key:
            raise Unverified("retained correction changed")
        if correction["task_id"] != record["task_id"] or correction["repo"] != record["repo"] or correction["worktree"] != record["worktree"]:
            raise Unverified("correction moved to another task")
        if type(correction.get("cycle")) is not int or not 1 <= correction["cycle"] <= 3:
            raise Unverified("invalid prepared repair cycle")
        number = correction.get("generation")
        generations = record.get("review_protocol", {}).get("generations", [])
        if type(number) is not int or not 1 <= number <= len(generations):
            raise Unverified("correction generation missing")
        generation = generations[number - 1]
        historical = {**record, "state": "Rework", "revision": correction["expected_revision"],
                      "owner": correction["owner"], "rework_count": correction["cycle"],
                      "base_sha": correction["base"], "head_sha": correction["head"],
                      "owned_paths": correction["owned_paths"], "restricted_paths": correction["restricted_paths"],
                      "acceptance_criteria": correction["acceptance_criteria"], "branch": correction["branch"],
                      "review_protocol": {**record["review_protocol"], "material_epoch": correction["material_epoch"],
                                          "generations": generations[:number]}}
        # Reproduce the prepared projection against the original generation;
        # filter later protocol receipts when reconstructing historical state.
        historical["review_protocol"]["operations"] = {key:value for key,value in record["review_protocol"]["operations"].items()
            if value["result"]["resulting_revision"] <= correction["expected_revision"]}
        reproduced = e.correction_request(historical)
        reproduced.update(cycle=correction["cycle"], material_epoch=correction["material_epoch"], generation=number)
        if reproduced != correction or generation["material_epoch"] != correction["material_epoch"]:
            raise Unverified("prepared correction differs from retained review context")
    for operation_id, item in ledger["operations"].items():
        e.fields(item, {"request", "correction_id", "bundle_sha256", "entries", "before", "phase", "worker", "cycle", "head", "epoch", "controller_sha256"})
        if item["request"]["operation_id"] != operation_id or item["correction_id"] not in ledger["corrections"]:
            raise Unverified("repair operation binding invalid")
        e.fields(item["request"], {"schema_version", "operation_id", "expected_revision", "correction_id", "bundle_sha256"})
        request = item["request"]
        correction = ledger["corrections"][item["correction_id"]]
        if (type(request["schema_version"]) is not int or request["schema_version"] != 1
                or request["correction_id"] != item["correction_id"] or request["bundle_sha256"] != item["bundle_sha256"]
                or type(request["expected_revision"]) is not int or not correction["expected_revision"] < request["expected_revision"] < record["revision"]
                or item["cycle"] != correction["cycle"] or item["head"] != correction["head"]
                or item["epoch"] != correction["material_epoch"] + 1 or item["worker"].get("owner") != correction["owner"]):
            raise Unverified("repair intent differs from prepared correction")
        e.token(operation_id)
        e.hash_value(item["controller_sha256"])
        if item["phase"] not in {"APPLYING", "APPLIED_UNREVIEWED", "NOT_APPLIED_OBSERVED", "PARTIAL", "UNVERIFIED"}:
            raise Unverified("invalid repair phase")
        raw = c.read_bytes(root / "review-artifacts" / e.hash_value(item["bundle_sha256"]), 800_000)
        if digest(raw) != item["bundle_sha256"] or bundle(raw, ledger["corrections"][item["correction_id"]]) != item["entries"]:
            raise Unverified("repair bundle lost or substituted")
        if len(item["before"]) != len(item["entries"]):
            raise Unverified("repair preconditions missing")
        for entry, before in zip(item["entries"], item["before"]):
            if before != {"path": entry["path"], "sha256": entry["before_sha256"], "mode": before.get("mode")} or before["mode"] not in {0o600, 0o644}:
                raise Unverified("invalid retained precondition")


def prepare(record: dict[str, Any], root: Path, revision: int) -> tuple[dict[str, Any], dict[str, Any]]:
    e, coordinator = load("review-evidence"), load("orchestrator-state")
    validate_retained(record, root)
    if record["state"] != "Rework" or record["revision"] != revision or record.get("transition_intent") or pending(record):
        raise Unverified("prepare requires current admitted Rework before owner claim")
    coordinator.require_execution_stopped(record)
    e.validate_collected_retention(record, root)
    correction = e.correction_request(record)
    correction["cycle"] = record["rework_count"]
    correction["material_epoch"] = record["review_protocol"]["material_epoch"]
    correction["generation"] = record["review_protocol"]["generations"][-1]["number"]
    key = digest(canonical(correction))
    updated = copy.deepcopy(record)
    ledger = updated.setdefault("repair_protocol", {"schema_version": 1, "corrections": {}, "operations": {}})
    existing = [old for old in ledger["corrections"].values() if old["cycle"] == correction["cycle"]]
    if existing:
        old = existing[0]
        if {k:v for k,v in old.items() if k not in {"expected_revision", "request_sha256"}} != {k:v for k,v in correction.items() if k not in {"expected_revision", "request_sha256"}}:
            raise Unverified("prepared correction context changed")
        return record, {"status": "CORRECTION_PREPARED", "correction_id": digest(canonical(old))}
    ledger["corrections"][key] = correction
    return updated, {"status": "CORRECTION_PREPARED", "correction_id": key}


def apply_repair(record: dict[str, Any], root: Path, request: dict[str, Any], raw: bytes, persist) -> dict[str, Any]:
    c, e, coordinator = load("review-collect"), load("review-evidence"), load("orchestrator-state")
    validate_retained(record, root)
    e.fields(request, {"schema_version", "operation_id", "expected_revision", "correction_id", "bundle_sha256"})
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise Unverified("invalid repair request version")
    operation = e.token(request["operation_id"])
    ledger = record.get("repair_protocol")
    if ledger is None:
        raise Unverified("correction must be prepared before reclaiming rework")
    prior = ledger["operations"].get(operation)
    if prior:
        if prior["request"] != request or digest(raw) != prior["bundle_sha256"]:
            raise Unverified("repair operation reused with different content")
        return result(prior)  # Exact retry never performs file writes.
    correction = ledger["corrections"].get(request["correction_id"])
    if correction is None or record["state"] != "Implementing" or record["kind"] != "implementation" or type(request["expected_revision"]) is not int or record["revision"] != request["expected_revision"]:
        raise Unverified("active original-owner implementation revision required")
    worker = record.get("worker")
    if (not worker or worker["owner"] != correction["owner"] or record["owner"] != correction["owner"]
            or type(record["leases"].get("implementation_lane")) is not int or type(record["leases"].get("global_slot")) is not int
            or record["rework_count"] != correction["cycle"] or not 1 <= record["rework_count"] <= 3):
        raise Unverified("repair owner, lease or cycle mismatch")
    for name in ("head", "base", "repo", "branch", "worktree", "owned_paths", "restricted_paths", "acceptance_criteria"):
        actual = record[{"head":"head_sha", "base":"base_sha"}.get(name, name)]
        if correction[name] != actual:
            raise Unverified("prepared correction source/scope changed")
    if record.get("transition_intent") or pending(record) or any(item["cycle"] == correction["cycle"] for item in ledger["operations"].values()):
        raise Unverified("repair cycle already used or unsettled")
    coordinator.require_execution_stopped(record)
    e.validate_collected_retention(record, root)
    generation = e.current(record)
    if generation["number"] != correction["generation"]:
        raise Unverified("correction generation changed")
    if record["review_protocol"]["material_epoch"] != correction["material_epoch"]:
        raise Unverified("correction epoch changed")
    e.validate_protocol(record)
    coordinator.verify_worktree_identity(record, require_head=True)
    coordinator.verify_clean_checkout(record["worktree"])
    if digest(raw) != request["bundle_sha256"]:
        raise Unverified("bundle differs from request")
    entries = bundle(raw, correction)
    worktree = Path(record["worktree"])
    if Path(__file__).resolve().is_relative_to(worktree.resolve()) or root.resolve().is_relative_to(worktree.resolve()):
        raise Unverified("running controller and authority must be outside repaired checkout")
    before = inspect_targets(worktree, entries)
    if any(item["sha256"] != entry["before_sha256"] for item, entry in zip(before, entries)):
        raise Unverified("before bytes differ; no targets modified")
    store = c.ensure_store(root, worktree)
    c.publish(store, raw)
    directory = os.open(store, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    item = {"request": copy.deepcopy(request), "correction_id": request["correction_id"], "bundle_sha256": digest(raw),
            "entries": entries, "before": before, "phase": "APPLYING", "worker": copy.deepcopy(worker),
            "cycle": record["rework_count"], "head": record["head_sha"], "epoch": correction["material_epoch"] + 1,
            "controller_sha256": digest(Path(__file__).read_bytes())}
    ledger["operations"][operation] = item
    record["review_protocol"]["material_epoch"] += 1
    record["reviewed_sha"], record["reviewers"], record["validation"] = "", [], []
    persist(record)  # Durable fence/invalidation before the first file write.
    for entry, original in zip(entries, before):
        replace_one(worktree, entry, original["mode"])
    observed = inspect_targets(worktree, entries)
    if any(actual["sha256"] != entry["after_sha256"] or actual["mode"] != original["mode"] for actual, entry, original in zip(observed, entries, before)):
        raise Unverified("post-write verification failed; repair remains fenced")
    item["phase"] = "APPLIED_UNREVIEWED"
    persist(record)
    return result(item)


def result(item: dict[str, Any]) -> dict[str, Any]:
    return {"status": item["phase"], "operation_id": item["request"]["operation_id"], "bundle_sha256": item["bundle_sha256"],
            "candidate_ready": False, "execution_credit": False, "delivery_credit": False}


def reconcile(record: dict[str, Any], root: Path, operation: str, persist) -> dict[str, Any]:
    validate_retained(record, root)
    item = record.get("repair_protocol", {}).get("operations", {}).get(operation)
    if item is None:
        raise Unverified("repair operation absent")
    if item["phase"] in {"APPLIED_UNREVIEWED", "NOT_APPLIED_OBSERVED"}:
        return result(item)  # Historical observation is immutable, not today's bytes.
    # Caller holds coordinator lock: a live cooperative mutator holds it through
    # all writes. Stale lock recovery is explicit, never performed here.
    if (record["head_sha"] != item["head"] or record.get("transition_intent")
            or record["state"] != "Implementing" or record["rework_count"] != item["cycle"]
            or record["review_protocol"]["material_epoch"] != item["epoch"]
            or record.get("worker") != item["worker"] or record["owner"] != item["worker"]["owner"]):
        raise Unverified("repair source identity changed")
    try:
        observed = inspect_targets(Path(record["worktree"]), item["entries"])
        before = all(a == b for a,b in zip(observed, item["before"]))
        after = all(a["sha256"] == e["after_sha256"] and a["mode"] == b["mode"] for a,e,b in zip(observed,item["entries"],item["before"]))
        known = all(a["sha256"] in {e["before_sha256"],e["after_sha256"]} and a["mode"] == b["mode"] for a,e,b in zip(observed,item["entries"],item["before"]))
        phase = "APPLIED_UNREVIEWED" if after else "NOT_APPLIED_OBSERVED" if before else "PARTIAL" if known else "UNVERIFIED"
    except (OSError, Unverified):
        phase = "UNVERIFIED"
    item["phase"] = phase
    persist(record)
    return result(item)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("action", choices=("prepare", "apply", "reconcile"))
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--operation-id")
    args = parser.parse_args()
    try:
        if not sys.flags.isolated or not sys.dont_write_bytecode:
            raise Unverified("invoke with python3 -I -B")
        c, coordinator = load("review-collect"), load("orchestrator-state")
        root = coordinator.state_root(create=False)
        request = c.decode(c.read_bytes(args.request, 100_000)) if args.request else None
        raw = c.read_bytes(args.bundle, 800_000) if args.bundle else None
        with coordinator.CoordinatorLock(root):
            record = coordinator.read_task(root, args.task_id)
            coordinator.verify_reservations(root, record)
            if args.action == "prepare":
                updated, response = prepare(record, root, args.expected_revision)
                if updated != record:
                    coordinator.write_task(root, updated)
            elif args.action == "apply":
                if request is None or raw is None:
                    raise Unverified("request and bundle required")
                response = apply_repair(record, root, request, raw, lambda value: coordinator.write_task(root, value))
            else:
                response = reconcile(record, root, args.operation_id, lambda value: coordinator.write_task(root, value))
        print(json.dumps(response, sort_keys=True))
        return 0 if response["status"] in {"CORRECTION_PREPARED", "APPLIED_UNREVIEWED", "NOT_APPLIED_OBSERVED"} else 3
    except Exception as exc:
        print(json.dumps({"status": "UNVERIFIED", "reason": str(exc) if isinstance(exc, Unverified) else "repair unavailable; preserve pending intent"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
