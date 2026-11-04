#!/usr/bin/env python3
"""Durable reservation groundwork only. No consumer, executable route or launch grant.

One entry per admission forever; cancellation preserves the original export and
all references. Link validation is pure, artifact validation is read-only, and
neither calls a dispatcher or a mutation API.
"""

import copy
import importlib.util
import os
import re
import stat
from pathlib import Path

ACTIONS = {"reserve-review-attempt", "cancel-review-reservation"}


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(condition, message):
    if not condition:
        raise ValueError(message)


def destination(value):
    h = load("review-handoff")
    h.fields(value, {"backend", "sandbox_id", "created", "endpoint_sha256", "result_root"})
    require(value["backend"] in {"docker", "msb"}, "unsupported destination backend")
    h.token(value["sandbox_id"])
    h.hash_value(value["endpoint_sha256"])
    require(isinstance(value["created"], str) and re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z", value["created"]),
        "opaque creation identity required")
    require(isinstance(value["result_root"], str) and re.fullmatch(
        r"/review-results/[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value["result_root"]),
        "bounded guest result root required")


def ledger(record):
    return record.get("review_reservations", {"schema_version": 1, "admissions": {}})


def pending(record):
    return sum(item["phase"] == "RESERVED" for item in ledger(record)["admissions"].values())


def result(request):
    return {"status": "RESERVED" if request["action"] == "reserve-review-attempt" else "CANCELLED_UNCONSUMED",
            "admission_id": request["payload"]["admission_id"],
            "resulting_revision": request["expected_revision"] + 1,
            "replay_only": True, "launch_authorized": False, "launch_gate": "BLOCKED_PROFILE",
            "candidate_ready": False, "execution_credit": False, "delivery_credit": False}


def reference(key):
    return {"table": "review_reservations.admissions", "key": key}


def validate_links(record):
    h = load("review-handoff")
    state = ledger(record)
    h.fields(state, {"schema_version", "admissions"})
    marker = record.get("review_reservations_initialized")
    require(("review_reservations_initialized" not in record or marker is True)
            and ("review_reservations" in record) == (marker is True), "reservation marker/history loss")
    require(type(state["schema_version"]) is int and state["schema_version"] == 1
            and isinstance(state["admissions"], dict) and len(state["admissions"]) <= 32,
            "invalid reservation ledger")
    receipts = record.get("foreground_control", {}).get("receipts", {})
    receipt_ops = {op for op, r in receipts.items() if r["request"]["action"] in ACTIONS}
    for op, receipt in receipts.items():
        pointer = receipt.get("reference")
        require(pointer is None or isinstance(pointer, dict), "malformed foreground reference")
        if pointer is not None and pointer.get("table") == "review_reservations.admissions":
            receipt_ops.add(op)
    if not state["admissions"]:
        require(not receipt_ops, "orphan reservation receipt")
        return
    e = load("review-evidence")
    linked = set()
    identity = load("candidate-binding").incarnation(record)
    for key, item in state["admissions"].items():
        h.hash_value(key)
        h.fields(item, {"phase", "reserve_operation_id", "cancel_operation_id", "bundle_sha256",
                        "export_revision", "admit_operation_id", "owner", "worker", "destination"})
        h.token(item["reserve_operation_id"])
        require(record.get("foreground_initialized") is True, "reservation lost foreground control")
        require(item["phase"] in {"RESERVED", "CANCELLED_UNCONSUMED"}, "unsupported reservation phase")
        destination(item["destination"])
        h.hash_value(item["bundle_sha256"])
        h.number(item["export_revision"])
        admit = receipts[item["admit_operation_id"]]
        require(admit["request"]["action"] == "admit-prepared-review"
                and admit["result"]["domain_result"]["admission_id"] == key
                and admit["result"]["resulting_revision"] <= item["export_revision"], "reservation admission link differs")
        require(load("foreground-admission").retained(record, admit["request"], admit["reference"])
                == admit["result"]["domain_result"], "reservation lost domain admission")
        prepare, generation, _ = e.prepared_admission(record, admit["request"])
        adoption = receipts[prepare["request"]["payload"]["adopt_operation_id"]]
        app = record["foreground_repairs"]["applications"][adoption["request"]["payload"]["apply_operation_id"]]
        repair = record["repair_protocol"]["operations"][app["repair_operation_id"]]
        admitted = record["runtime_collections"]["admissions"][key]
        require(h.digest(h.canonical(admitted)) == key and item["worker"] == repair["worker"]
                and item["owner"] == generation["owner"] == item["worker"]["owner"], "reservation owner snapshot differs")
        require(key not in record["runtime_collections"]["collections"]
                and admitted["run_id"] not in generation["reports"], "reserved admission has unconsumed runtime evidence")
        require((item["cancel_operation_id"] is None) == (item["phase"] == "RESERVED"), "cancellation link differs")
        for action, op in (("reserve-review-attempt", item["reserve_operation_id"]),
                           ("cancel-review-reservation", item["cancel_operation_id"])):
            if op is None:
                continue
            h.token(op)
            require(op not in linked, "duplicate reservation receipt")
            linked.add(op)
            receipt = receipts[op]
            h.fields(receipt, {"request", "request_sha256", "reference", "result"})
            request = receipt["request"]
            h.fields(request, {"schema_version", "task_id", "incarnation", "expected_revision", "operation_id", "action", "payload"})
            h.number(request["expected_revision"])
            payload = {"admission_id": key}
            if action == "reserve-review-attempt":
                payload.update(bundle_sha256=item["bundle_sha256"], destination=item["destination"])
                require(request["expected_revision"] == item["export_revision"], "export revision changed")
            else:
                require(request["expected_revision"] > item["export_revision"], "cancellation precedes reservation")
            require(type(request["schema_version"]) is int and request["schema_version"] == 1
                    and request["operation_id"] == op and request["action"] == action
                    and request["task_id"] == record["task_id"] and request["incarnation"] == identity
                    and request["payload"] == payload and request["expected_revision"] < record["revision"]
                    and receipt["request_sha256"] == h.digest(h.canonical(request))
                    and receipt["reference"] == reference(key)
                    and receipt["result"] == load("foreground-delivery").acknowledgement(request, result(request)),
                    "reservation receipt differs")
    require(len(receipts) + load("foreground-repair").count(record) + pending(record) <= 64,
            "reserved cancellation capacity lost")
    require(linked == receipt_ops,
            "orphan reservation receipt")


def read_bundle(root, key):
    c, h = load("review-collect"), load("review-handoff")
    h.hash_value(key)
    store = root / "review-handoffs"
    load("foreground-review").private_directory(store)
    path = store / key
    c.no_links(path)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
            and stat.S_IMODE(info.st_mode) == 0o400, "handoff must be immutable private regular file")
    raw = c.read_bytes(path, h.MAX_BUNDLE)
    value = h.decode(raw)
    require(h.canonical(value) == raw and h.digest(raw) == key, "retained handoff bytes differ")
    return value


def validate_artifacts(record, root):
    h, review = load("review-handoff"), load("foreground-review")
    for key, item in ledger(record)["admissions"].items():
        value = read_bundle(root, item["bundle_sha256"])
        admitted = record["runtime_collections"]["admissions"][key]
        packet = review.read_packet(root, admitted["packet"])
        expected = h.build(admitted, packet, load("candidate-binding").incarnation(record),
                           item["export_revision"], key, item["admit_operation_id"])
        require(value == expected, "frozen handoff differs from retained domain context")


def validate_integrity(record, root=None):
    """Retained integrity, including current protocol order; not current applicability.

    validate_protocol replays only begin/assign/accept and pure link derivations.
    It never calls apply, a coordinator guard, or this reservation validator.
    Keep it here rather than in validate_links (used by prospective writes).
    """
    validate_links(record)
    load("review-evidence").validate_protocol(record)
    if root is not None:
        validate_artifacts(record, root)


def guard(record, root=None):
    validate_integrity(record, root)
    require(not pending(record), "cancel unconsumed review reservation before mutation")


def apply(record, request, root):
    key = request["payload"]["admission_id"]
    entries = ledger(record)["admissions"]
    if request["action"] == "cancel-review-reservation":
        item = entries[key]
        require(item["phase"] == "RESERVED", "reservation already cancelled")
        require(record["owner"] == item["owner"] and record["worker"] == item["worker"],
                "only original full worker/owner may cancel")
        item["phase"], item["cancel_operation_id"] = "CANCELLED_UNCONSUMED", request["operation_id"]
    else:
        require(key not in entries, "admission already reserved forever")
        exported = load("review-handoff").export_admitted(record, request, root)
        require(exported["bundle_sha256"] == request["payload"]["bundle_sha256"], "current exact export hash required")
        c, review = load("review-collect"), load("foreground-review")
        review.private_directory(root)
        store = root / "review-handoffs"
        store.mkdir(mode=0o700, exist_ok=True)
        review.private_directory(store)
        c.publish(store, c.canonical(exported["bundle"]))
        read_bundle(root, exported["bundle_sha256"])
        # publish's existing-content path does not fsync: retry must complete
        # file durability as well as directory durability before acknowledging.
        fd = os.open(store / exported["bundle_sha256"], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        for directory in (store, root):
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        read_bundle(root, exported["bundle_sha256"])
        record["review_reservations_initialized"] = True
        state = record.setdefault("review_reservations", copy.deepcopy(ledger(record)))
        state["admissions"][key] = {"phase": "RESERVED", "reserve_operation_id": request["operation_id"],
            "cancel_operation_id": None, "bundle_sha256": exported["bundle_sha256"],
            "export_revision": record["revision"], "admit_operation_id": exported["bundle"]["binding"]["admit_operation_id"],
            "owner": record["owner"], "worker": copy.deepcopy(record["worker"]),
            "destination": copy.deepcopy(request["payload"]["destination"])}
    return result(request), reference(key)


def cancellation_budget(record):
    """Serialize maximum-size cancellation receipts; never validate invented history."""
    c, fg, bridge, coordinator = (load(n) for n in ("review-collect", "foreground-delivery", "foreground-repair", "orchestrator-state"))
    projected = copy.deepcopy(record)
    control = projected["foreground_control"]["receipts"]
    for key, item in ledger(projected)["admissions"].items():
        if item["phase"] != "RESERVED":
            continue
        operation = "c" * 80
        while operation in control:
            operation = c.digest(operation.encode()) + operation[:16]
        request = {"schema_version": 1, "task_id": record["task_id"],
            "incarnation": load("candidate-binding").incarnation(record), "expected_revision": 2**53 - 2,
            "operation_id": operation, "action": "cancel-review-reservation", "payload": {"admission_id": key}}
        item["phase"], item["cancel_operation_id"] = "CANCELLED_UNCONSUMED", operation
        control[operation] = {"request": request, "request_sha256": c.digest(c.canonical(request)),
            "reference": reference(key), "result": fg.acknowledgement(request, result(request))}
    require(len(control) + bridge.count(projected) <= fg.MAX_RECEIPTS, "cancellation receipt capacity required")
    bridge.check_write_budget(projected, 2**53 - 1, c, coordinator)
