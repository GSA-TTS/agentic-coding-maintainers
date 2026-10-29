#!/usr/bin/env python3
"""Controller-owned admission and retention of bounded review observations.

Task JSON is authoritative. Artifacts are published before the task reference;
unreferenced artifacts from interruption confer no evidence credit. Consistency
checking does not authenticate a worker-supplied bundle or grant readiness.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

ARTIFACTS = ("receipt.json", "transcript.jsonl", "session-export.json", "stderr.txt", "export-stderr.txt")
LIMIT = 4_000_000
PACKET_LIMIT = 8_000_000
MAX_OPERATIONS = 64


class Unverified(Exception):
    pass


def load_module(name: str):
    source = Path(__file__).resolve().with_name(name + ".py")
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), source)
    if spec is None or spec.loader is None:
        raise Unverified("installed dependency unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("ascii")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Unverified("duplicate JSON field")
        result[key] = value
    return result


def decode(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data, object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(Unverified("nonfinite JSON")))
        if not isinstance(value, dict):
            raise Unverified("JSON object required")
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Unverified("malformed JSON") from exc


def no_links(path: Path) -> None:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise Unverified("path contains a symlink")


def read_bytes(path: Path, limit: int = LIMIT) -> bytes:
    no_links(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise Unverified("artifact is not a bounded regular file")
        data = handle.read(limit + 1)
        if len(data) > limit:
            raise Unverified("artifact grew beyond its bound")
        return data


def fields(value: Any, expected: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise Unverified("unexpected or missing fields")


def absolute_guest_path(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 4096 or "\0" in value:
        raise Unverified("invalid guest path")
    path = PurePosixPath(value)
    if not path.is_absolute() or str(path) != value or ".." in path.parts or value.startswith("//"):
        raise Unverified("guest path must be canonical and absolute")
    return value


def request_header(request: dict[str, Any], evidence) -> None:
    fields(request, {"schema_version", "operation_id", "expected_revision", "action", "payload"})
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise Unverified("unsupported collection request")
    evidence.token(request["operation_id"])
    if type(request["expected_revision"]) is not int or request["expected_revision"] < 0:
        raise Unverified("invalid task revision")
    if request["action"] not in {"admit", "collect"} or not isinstance(request["payload"], dict):
        raise Unverified("invalid collection action")


def packet_sources(packet_bytes: bytes, payload: dict[str, Any], generation: dict[str, Any], evidence) -> dict[str, str]:
    if len(packet_bytes) > PACKET_LIMIT or digest(packet_bytes) != generation["packet"]:
        raise Unverified("packet bytes do not match current generation")
    packet = decode(packet_bytes)
    if (packet.get("kind") != "committed-local-source" or packet.get("schema_version") != 1
            or packet.get("head") != generation["head"] or packet.get("base") != generation["base"]
            or packet.get("policy_sha256") != generation["policy"] or packet.get("changed_inventory") != "COMPLETE"):
        raise Unverified("packet comparison or policy differs from current generation")
    entries = packet.get("files")
    if not isinstance(entries, list) or len(entries) > 200:
        raise Unverified("invalid packet inventory")
    lookup = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path_base64"), str):
            raise Unverified("invalid packet path")
        key = entry["path_base64"]
        if key in lookup:
            raise Unverified("duplicate packet path")
        lookup[key] = entry
    sources = payload["sources"]
    if not isinstance(sources, dict) or not 1 <= len(sources) <= 20:
        raise Unverified("admission requires 1-20 packet-backed source files")
    manifest = {}
    for guest, selection in sources.items():
        absolute_guest_path(guest)
        fields(selection, {"path_base64", "side"})
        if selection["side"] not in {"before", "after"}:
            raise Unverified("source selection must name before or after")
        entry = lookup.get(selection["path_base64"])
        if entry is None:
            raise Unverified("selected source is absent from packet")
        side = entry.get(selection["side"])
        if not isinstance(side, dict) or side.get("kind") != "blob":
            raise Unverified("selected source must be a regular captured blob")
        if side.get("encoding") == "utf-8" and isinstance(side.get("content"), str):
            data = side["content"].encode("utf-8")
        elif side.get("encoding") == "base64" and isinstance(side.get("content"), str):
            data = base64.b64decode(side["content"], validate=True)
        else:
            raise Unverified("invalid source encoding")
        evidence.hash_value(side.get("sha256"))
        if digest(data) != side["sha256"] or type(side.get("bytes")) is not int or side["bytes"] != len(data):
            raise Unverified("packet source digest or length mismatch")
        manifest[guest] = side["sha256"]
    return manifest


def admission(record: dict[str, Any], payload: dict[str, Any], packet: bytes, evidence) -> dict[str, Any]:
    fields(payload, {"generation", "run_id", "binary_sha256", "model", "agent", "cwd", "sources"})
    generation = evidence.current(record)
    if type(payload["generation"]) is not int or payload["generation"] != generation["number"]:
        raise Unverified("superseded collection generation")
    run_id = evidence.token(payload["run_id"])
    assignment = generation["assignments"].get(run_id)
    if assignment is None or assignment["adapter"] != "native-session":
        raise Unverified("collection requires an existing native-session assignment")
    evidence.hash_value(payload["binary_sha256"])
    evidence.text(payload["model"], 200)
    evidence.token(payload["agent"])
    absolute_guest_path(payload["cwd"])
    manifest = packet_sources(packet, payload, generation, evidence)
    return {**copy.deepcopy(payload), "task_id": record["task_id"], "owner": record["owner"],
            "base": record["base_sha"], "head": record["head_sha"], "packet": generation["packet"],
            "policy": generation["policy"], "material_epoch": generation["material_epoch"],
            "assignment": copy.deepcopy(assignment), "source_sha256": manifest,
            "admission_revision": record["revision"]}


def verify_bundle(admitted: dict[str, Any], artifacts: dict[str, bytes], runner) -> dict[str, Any]:
    if set(artifacts) != set(ARTIFACTS) or any(len(data) > LIMIT for data in artifacts.values()):
        raise Unverified("incomplete or oversized runtime bundle")
    receipt = decode(artifacts["receipt.json"])
    for field in ("binary_sha256", "model", "agent", "source_sha256"):
        if receipt.get(field) != admitted[field]:
            raise Unverified(f"runtime {field} differs from controller admission")
    if receipt.get("sessions") != [admitted["assignment"]["session"]]:
        raise Unverified("runtime session differs from assigned attempt")
    if receipt.get("profile_sha256") != admitted["assignment"]["profile"]:
        raise Unverified("runtime profile differs from assigned configuration")
    for name, field in (("transcript.jsonl", "transcript_sha256"), ("stderr.txt", "stderr_sha256")):
        if digest(artifacts[name]) != receipt.get(field):
            raise Unverified("runtime artifact differs from receipt")
    if type(receipt.get("returncode")) is not int or receipt["returncode"] != 0:
        raise Unverified("runtime did not exit successfully")
    if receipt.get("status") != "REVIEW_OBSERVED" or receipt.get("execution_credit") is not False or receipt.get("candidate_ready") is not False:
        raise Unverified("receipt has unsupported verdict or credit")
    if "export_returncode" in receipt and (type(receipt["export_returncode"]) is not int or receipt["export_returncode"] != 0 or receipt.get("export_failure") is not None):
        raise Unverified("runtime reports unsuccessful export")
    summary = runner.corroborate(artifacts["transcript.jsonl"], receipt["returncode"], admitted["source_sha256"],
                                Path(admitted["cwd"]), artifacts["session-export.json"], 0, None)
    if summary["status"] != "REVIEW_OBSERVED":
        raise Unverified("runtime artifacts do not corroborate source reads and completion")
    exported = decode(artifacts["session-export.json"])
    info = exported["info"]
    model = info.get("model", {})
    if not isinstance(model, dict) or f"{model.get('providerID')}/{model.get('id')}" != admitted["model"] or info.get("agent") != admitted["agent"]:
        raise Unverified("export model/agent differs from admission")
    for field in ("source_reads", "sessions", "final_text", "tokens"):
        if receipt.get(field) != summary.get(field):
            raise Unverified("receipt summary differs from recomputed runtime observations")
    return {"status": "OBSERVATION_COLLECTED", "sessions": summary["sessions"],
            "source_reads": summary["source_reads"], "tokens": summary["tokens"],
            "final_text_sha256": digest(summary["final_text"].encode("utf-8")),
            "authenticity": "UNVERIFIED: internally consistent worker-supplied artifacts",
            "candidate_ready": False, "execution_credit": False, "delivery_credit": False}


def ensure_store(root: Path, worktree: Path) -> Path:
    store = root / "review-artifacts"
    no_links(store)
    if store.resolve().is_relative_to(worktree.resolve()):
        raise Unverified("controller artifacts must be outside candidate worktree")
    store.mkdir(mode=0o700, exist_ok=True)
    info = store.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise Unverified("artifact store must be private and current-user owned")
    parent = os.open(root, os.O_RDONLY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    return store


def publish(store: Path, data: bytes) -> str:
    key = digest(data)
    target = store / key
    if target.exists() or target.is_symlink():
        if read_bytes(target, PACKET_LIMIT) != data:
            raise Unverified("existing content-addressed artifact is incomplete or changed")
        return key
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=store)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o400)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target, follow_symlinks=False)
        except FileExistsError:
            if read_bytes(target, PACKET_LIMIT) != data:
                raise Unverified("concurrent artifact differs from its content address")
    finally:
        os.unlink(temporary)
    return key


def validate_retained(state: dict[str, Any], store: Path, record: dict[str, Any], evidence, runner) -> None:
    fields(state, {"schema_version", "admissions", "collections", "operations"})
    if type(state["schema_version"]) is not int or state["schema_version"] != 1:
        raise Unverified("unsupported collection state")
    for name in ("admissions", "collections", "operations"):
        if not isinstance(state[name], dict) or len(state[name]) > MAX_OPERATIONS:
            raise Unverified("invalid collection state")
    for key, admitted in state["admissions"].items():
        if not isinstance(admitted, dict) or digest(canonical(admitted)) != key:
            raise Unverified("admission content address mismatch")
        number = admitted.get("generation")
        generations = record.get("review_protocol", {}).get("generations", [])
        if type(number) is not int or not 1 <= number <= len(generations):
            raise Unverified("admission generation unavailable")
        generation = generations[number - 1]
        historical = {**record, "base_sha": generation["base"], "head_sha": generation["head"],
                      "owner": generation["owner"], "revision": admitted.get("admission_revision"),
                      "review_protocol": {**record["review_protocol"], "generations": generations[:number],
                                          "material_epoch": generation["material_epoch"]}}
        if type(historical["revision"]) is not int or not generation["admission_revision"] < historical["revision"] < record["revision"]:
            raise Unverified("invalid admission revision")
        payload = {name: admitted.get(name) for name in ("generation", "run_id", "binary_sha256", "model", "agent", "cwd", "sources")}
        reproduced = admission(historical, payload, read_bytes(store / generation["packet"], PACKET_LIMIT), evidence)
        if admitted != reproduced:
            raise Unverified("retained admission differs from authoritative assignment")
    for key, collection in state["collections"].items():
        fields(collection, {"admission_id", "artifacts", "summary"})
        if collection["admission_id"] != key or key not in state["admissions"]:
            raise Unverified("collection lacks admission")
        fields(collection["artifacts"], set(ARTIFACTS))
        for key in collection["artifacts"].values():
            if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
                raise Unverified("invalid artifact address")
            if digest(read_bytes(store / key)) != key:
                raise Unverified("retained runtime evidence is missing or changed")
        bundle = {name: read_bytes(store / key) for name, key in collection["artifacts"].items()}
        if verify_bundle(state["admissions"][collection["admission_id"]], bundle, runner) != collection["summary"]:
            raise Unverified("retained collection verdict differs from artifacts")
    seen: dict[tuple[str, str], int] = {}
    protocol_operations = record["review_protocol"]["operations"].values()
    revisions = {operation["result"]["resulting_revision"] for operation in protocol_operations}
    assignments = {
        (operation["result"]["generation"], operation["result"]["run_id"]): operation["result"]["resulting_revision"]
        for operation in record["review_protocol"]["operations"].values()
        if operation["result"]["status"] == "ASSIGNED"
    }
    for operation_id, operation in state["operations"].items():
        fields(operation, {"request", "request_sha256", "result"})
        request = operation["request"]
        request_header(request, evidence)
        if request["operation_id"] != operation_id or digest(canonical(request)) != operation["request_sha256"]:
            raise Unverified("operation request binding mismatch")
        result = operation["result"]
        if not isinstance(result, dict):
            raise Unverified("invalid collection result")
        revision = result.get("resulting_revision")
        if type(revision) is not int or not 1 <= revision <= record["revision"] or revision != request["expected_revision"] + 1 or revision in revisions:
            raise Unverified("operation revision mismatch")
        revisions.add(revision)
        key = result.get("admission_id")
        if not isinstance(key, str) or key not in state["admissions"]:
            raise Unverified("operation lacks retained admission")
        admitted = state["admissions"][key]
        if request["action"] == "admit":
            assigned_at = assignments.get((admitted["generation"], admitted["run_id"]))
            if assigned_at is None or assigned_at > request["expected_revision"]:
                raise Unverified("collection admission precedes its assignment")
            payload = {name: admitted[name] for name in ("generation", "run_id", "binary_sha256", "model", "agent", "cwd", "sources")}
            expected = {"status": "COLLECTION_ADMITTED", "admission_id": key, "resulting_revision": revision}
            if request["payload"] != payload or request["expected_revision"] != admitted["admission_revision"]:
                raise Unverified("admission operation differs from retained admission")
        else:
            if key not in state["collections"]:
                raise Unverified("collection receipt has no artifacts")
            collection = state["collections"][key]
            if request["payload"] != {"admission_id": key, "artifact_sha256": collection["artifacts"]}:
                raise Unverified("collection request differs from retained artifacts")
            expected = {**collection["summary"], "admission_id": key, "resulting_revision": revision}
        if result != expected or (request["action"], key) in seen:
            raise Unverified("operation result is inconsistent or duplicated")
        seen[(request["action"], key)] = revision
    expected_keys = {("admit", key) for key in state["admissions"]} | {("collect", key) for key in state["collections"]}
    if set(seen) != expected_keys:
        raise Unverified("retained collections lack operation receipts")
    for key in state["collections"]:
        if seen[("collect", key)] <= seen[("admit", key)]:
            raise Unverified("collection precedes admission")
    for key, admitted in state["admissions"].items():
        generations = record["review_protocol"]["generations"]
        number = admitted["generation"]
        if number < len(generations):
            superseded_at = generations[number]["admission_revision"] + 1
            if seen[("admit", key)] >= superseded_at or seen.get(("collect", key), 0) >= superseded_at:
                raise Unverified("collection operation mutated a superseded generation")


def apply(record: dict[str, Any], request: dict[str, Any], root: Path,
          packet: bytes | None = None, artifacts: dict[str, bytes] | None = None) -> tuple[dict[str, Any], dict[str, Any], bool]:
    evidence = load_module("review-evidence")
    runner = load_module("review-run")
    request_header(request, evidence)
    load_module("orchestrator-state").require_repair_settled(record, new_review=True, root=root)
    evidence.validate_protocol(record)
    store = ensure_store(root, Path(record["worktree"]))
    state = record.get("runtime_collections", {"schema_version": 1, "admissions": {}, "collections": {}, "operations": {}})
    validate_retained(state, store, record, evidence, runner)
    request_digest = digest(canonical(request))
    prior = state["operations"].get(request["operation_id"])
    if prior is not None:
        if prior["request_sha256"] != request_digest:
            raise Unverified("operation ID reused with changed request")
        return record, prior["result"], False
    if request["expected_revision"] != record["revision"] or record["state"] not in {"Claimed", "Implementing", "Reviewing", "Rework"}:
        raise Unverified("task is stale or no longer admitted")
    if record.get("transition_intent") is not None or len(state["operations"]) >= MAX_OPERATIONS:
        raise Unverified("pending transition or collection budget exhausted")
    generation = evidence.current(record)
    payload = request["payload"]
    updated = copy.deepcopy(record)
    target = updated.setdefault("runtime_collections", copy.deepcopy(state))
    if request["action"] == "admit":
        if packet is None:
            raise Unverified("packet bytes required for admission")
        admitted = admission(record, payload, packet, evidence)
        key = digest(canonical(admitted))
        if any(value["generation"] == admitted["generation"] and value["run_id"] == admitted["run_id"] for value in state["admissions"].values()):
            raise Unverified("attempt already admitted")
        publish(store, packet)
        target["admissions"][key] = admitted
        result = {"status": "COLLECTION_ADMITTED", "admission_id": key}
    else:
        fields(payload, {"admission_id", "artifact_sha256"})
        admitted = state["admissions"].get(payload["admission_id"])
        if admitted is None or artifacts is None:
            raise Unverified("missing admission or runtime bundle")
        if (admitted["generation"] != generation["number"] or admitted["material_epoch"] != generation["material_epoch"]
                or admitted["owner"] != record["owner"] or admitted["assignment"] != generation["assignments"].get(admitted["run_id"])):
            raise Unverified("runtime admission superseded")
        if payload["admission_id"] in state["collections"]:
            raise Unverified("attempt already collected")
        fields(payload["artifact_sha256"], set(ARTIFACTS))
        actual = {name: digest(data) for name, data in artifacts.items()}
        if actual != payload["artifact_sha256"]:
            raise Unverified("runtime bundle differs from requested digests")
        summary = verify_bundle(admitted, artifacts, runner)
        for data in artifacts.values():
            publish(store, data)
        target["collections"][payload["admission_id"]] = {
            "admission_id": payload["admission_id"], "artifacts": actual, "summary": summary}
        result = {**summary, "admission_id": payload["admission_id"]}
    result["resulting_revision"] = record["revision"] + 1
    target["operations"][request["operation_id"]] = {"request_sha256": request_digest,
                                                    "request": copy.deepcopy(request), "result": result}
    if len(canonical(updated)) > 900_000:
        raise Unverified("task evidence budget exceeded")
    validate_retained(target, store, {**updated, "revision": record["revision"] + 1}, evidence, runner)
    directory = os.open(store, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return updated, result, True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    try:
        if not sys.flags.isolated or not sys.dont_write_bytecode:
            raise Unverified("invoke with python3 -I -B")
        request = decode(read_bytes(args.request, 100_000))
        packet = read_bytes(args.packet, PACKET_LIMIT) if args.packet else None
        artifacts = {name: read_bytes(args.bundle / name) for name in ARTIFACTS} if args.bundle else None
        coordinator = load_module("orchestrator-state")
        root = coordinator.state_root(create=False)
        with coordinator.CoordinatorLock(root):
            record = coordinator.read_task(root, args.task_id)
            coordinator.verify_reservations(root, record)
            updated, result, changed = apply(record, request, root, packet, artifacts)
            if changed:
                coordinator.write_task(root, updated)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "UNVERIFIED", "reason": str(exc) if isinstance(exc, Unverified) else "collection unavailable"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
