#!/usr/bin/env python3
"""Authenticated fresh comparison and durable packet; caller owns the task write."""

from __future__ import annotations

import base64
import copy
import importlib.util
import os
import stat
from pathlib import Path

ACTION = "prepare-repaired-review"
PREFIX = "fgreview."
MAX_PACKET = 8_000_000


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(condition, message):
    if not condition:
        raise ValueError(message)


def links(record, request):
    adoption = record.get("foreground_control", {}).get("receipts", {}).get(request["payload"]["adopt_operation_id"])
    require(adoption is not None and adoption["request"]["action"] == "adopt-owner-repair-head"
            and adoption["result"]["resulting_revision"] <= request["expected_revision"],
            "prior foreground adoption required")
    _, item, proposal, correction = load("foreground-adopt").links(record, adoption["request"])
    return adoption, item, proposal, correction


def verify_packet(packet, git, repository, base, head):
    """Do not trust diff-tree/capture as the source of paths or blob identity."""
    c, e, adopt = load("review-collect"), load("review-evidence"), load("foreground-adopt")
    c.fields(packet, {"schema_version", "kind", "repository", "repository_identity", "base", "head",
                      "comparison", "effective_base", "files", "changed_inventory", "diff_base64",
                      "obligations", "policy_sha256", "context_coverage", "limitations"})
    require(type(packet["schema_version"]) is int and packet["schema_version"] == 1
            and packet["kind"] == "committed-local-source" and packet["repository"] == repository
            and packet["base"] == packet["effective_base"] == base and packet["head"] == head
            and packet["comparison"] == "direct" and packet["changed_inventory"] == "COMPLETE"
            and packet["context_coverage"] == "UNVERIFIED"
            and packet["repository_identity"] == "caller-declared; remote identity unverified",
            "packet comparison differs")
    e.hash_value(packet["policy_sha256"])
    require(isinstance(packet["limitations"], list) and len(packet["limitations"]) <= 32, "invalid limitations")
    for text in packet["limitations"]:
        e.text(text)
    base64.b64decode(packet["diff_base64"], validate=True)
    require(isinstance(packet["obligations"], list) and 5 <= len(packet["obligations"]) <= 32, "invalid packet obligations")
    ids = []
    for obligation in packet["obligations"]:
        c.fields(obligation, {"id", "reason"})
        ids.append(e.token(obligation["id"]))
        e.text(obligation["reason"])
    require(len(ids) == len(set(ids)) and e.BASELINE <= set(ids), "packet obligation loss")
    old = adopt.tree_inventory(git, git.obj(base, "commit"))
    new = adopt.tree_inventory(git, git.obj(head, "commit"))
    paths = sorted(path for path in old.keys() | new.keys() if old.get(path) != new.get(path))
    require(len(paths) <= git.reader.MAX_FILES, "changed inventory exceeds bound")
    expected = []
    def side(entry):
        if entry is None:
            return {"mode": "000000", "oid": None, "kind": "absent"}
        mode, oid = entry
        raw = git.obj(oid, "blob", limit=git.reader.MAX_BLOB)
        try:
            text = raw.decode("utf-8")
        except UnicodeError:
            text = None
        utf8 = text is not None and "\0" not in text
        return {"mode": mode.decode("ascii"), "oid": oid, "kind": "blob", "bytes": len(raw),
                "sha256": c.digest(raw), "encoding": "utf-8" if utf8 else "base64",
                "content": text if utf8 else base64.b64encode(raw).decode("ascii")}
    for path in paths:
        expected.append({**git.reader.name_record(path), "status": "A" if path not in old else "D" if path not in new else "M",
                         "before": side(old.get(path)), "after": side(new.get(path))})
    require(c.canonical(packet["files"]) == c.canonical(expected), "packet source differs from authenticated raw objects")
    require(len(c.canonical(packet)) <= MAX_PACKET, "canonical packet exceeds bound")


def private_directory(path):
    load("review-collect").no_links(path)
    info = path.stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077,
            "packet directory must be private and owned")


def packet_file(root, key):
    load("review-evidence").hash_value(key)
    private_directory(root)
    private_directory(root / "review-packets")
    path = root / "review-packets" / (key + ".json")
    load("review-collect").no_links(path)
    return path


def read_packet(root, key):
    c = load("review-collect")
    path = packet_file(root, key)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o400, "packet must be private immutable regular file")
    raw = c.read_bytes(path, MAX_PACKET)
    require(c.digest(raw) == key, "retained packet digest differs")
    packet = c.decode(raw)
    require(c.canonical(packet) == raw, "retained packet is not canonical")
    return packet


def retain(root, packet):
    c = load("review-collect")
    private_directory(root)
    store = root / "review-packets"
    store.mkdir(mode=0o700, exist_ok=True)
    private_directory(store)
    raw = c.canonical(packet)
    require(len(raw) <= MAX_PACKET, "packet byte budget exceeded")
    key = c.digest(raw)
    path = packet_file(root, key)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    except FileExistsError:
        require(c.canonical(read_packet(root, key)) == raw, "existing packet differs")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            os.fsync(handle.fileno())
    else:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    # Retry also completes durability of a previously created file/directory.
    for directory in (store, root):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return key


def obligation_union(record, packet, number):
    e = load("review-evidence")
    ids = e.BASELINE | {item["id"] for item in packet["obligations"]}
    for generation in record["review_protocol"]["generations"][:number]:
        ids.update(generation["obligations"])
    require(len(ids) <= 32, "obligation union exceeds bound; no waiver permitted")
    return sorted(ids)


def retained(record, request, reference, root):
    c, adopt = load("review-collect"), load("foreground-adopt")
    c.fields(reference, {"table", "key", "adopt_operation_id", "packet"})
    adoption, _, _, correction = links(record, request)
    key = PREFIX + c.digest(c.canonical(request))
    require(reference["table"] == "review_protocol.operations" and reference["key"] == key
            and reference["adopt_operation_id"] == request["payload"]["adopt_operation_id"], "review reference differs")
    domain = record["review_protocol"]["operations"][key]
    generation = record["review_protocol"]["generations"][domain["result"]["generation"] - 1]
    packet = read_packet(root, reference["packet"])
    verify_packet(packet, adopt.Git(correction["worktree"]), correction["repo"], correction["base"], adoption["request"]["payload"]["head"])
    require(generation["packet"] == reference["packet"] and generation["policy"] == packet["policy_sha256"]
            and generation["obligations"] == obligation_union(record, packet, generation["number"] - 1),
            "retained review plan differs")
    return domain["result"]


def prepare(record, request, root):
    c, e, adopt = load("review-collect"), load("review-evidence"), load("foreground-adopt")
    adoption, item, proposal, correction = links(record, request)
    require(record["state"] == "Implementing" and record["kind"] == "implementation"
            and record["worker"] == item["worker"] == proposal["admission"]["worker"]
            and record["owner"] == correction["owner"] == item["worker"]["owner"]
            and record["rework_count"] == item["cycle"]
            and record["review_protocol"]["material_epoch"] == item["epoch"] + 1
            and record["review_protocol"]["generations"][-1]["number"] == correction["generation"]
            and all(type(record["leases"].get(k)) is int for k in ("global_slot", "implementation_lane")),
            "current original owner, worker, cycle, epoch or generation differs")
    head = adoption["request"]["payload"]["head"]
    require(record["head_sha"] == head, "adopted head differs")
    for field in ("base", "repo", "branch", "worktree", "owned_paths", "restricted_paths", "acceptance_criteria"):
        require(record[{"base": "base_sha"}.get(field, field)] == correction[field], "current correction scope differs")
    require(not any(r["request"]["action"] == ACTION and r["request"]["payload"] == request["payload"]
                    for r in record["foreground_control"]["receipts"].values()), "adoption already prepared")
    load("orchestrator-state").verify_reservations(root, record)
    git = adopt.Git(record["worktree"])
    adopt.verify_origin(git, record["repo"])
    adopt.clean_checkout(git, record, head, item)
    capture = load("review-packet")
    packet = capture.capture(git.path, record["repo"], record["base_sha"], head, "direct",
        read=lambda repo, *args, limit=capture.MAX_OUTPUT: git.run(*args, limit=limit))
    verify_packet(packet, git, record["repo"], record["base_sha"], head)
    obligations = obligation_union(record, packet, len(record["review_protocol"]["generations"]))
    packet_key = retain(root, packet)
    adopt.verify_origin(git, record["repo"])
    adopt.clean_checkout(git, record, head, item)
    domain_key = PREFIX + c.digest(c.canonical(request))
    domain_request = {"schema_version": 1, "operation_id": domain_key,
        "expected_revision": request["expected_revision"], "action": "begin", "payload": {
            "base": record["base_sha"], "head": head, "packet": packet_key,
            "policy": packet["policy_sha256"], "obligations": obligations}}
    reference = {"table": "review_protocol.operations", "key": domain_key,
                 "adopt_operation_id": request["payload"]["adopt_operation_id"], "packet": packet_key}
    expected = {"status": "BEGUN", "generation": len(record["review_protocol"]["generations"]) + 1,
                "evidence_kind": "claims-only", "resulting_revision": record["revision"] + 1}
    # Stage both links before the normal domain API's prospective validation.
    staged = copy.deepcopy(record)
    staged["foreground_control"]["receipts"][request["operation_id"]] = {
        "request": copy.deepcopy(request), "request_sha256": c.digest(c.canonical(request)), "reference": reference,
        "result": load("foreground-delivery").acknowledgement(request, expected)}
    updated, result, changed = e.apply(staged, domain_request)
    require(changed and result == expected, "unlinked domain replay cannot acquire a foreground receipt")
    return updated, result, reference
