#!/usr/bin/env python3
"""Typed v6 extension to the existing private journal; no network or approval API.

Old rows are immutable. Each dispatch preallocates bounded evidence and settlement
space in the same transaction, so ordinary monitor growth cannot consume it.
Only reserved placeholders may be filled, once. No replay API exists.
"""

import hashlib
import importlib.util
import json
import re
from pathlib import Path

TABLES = ("assignment_requests", "assignment_attempts", "assignment_evidence", "assignment_settlements")
CAPACITY = 100
RESERVE_BYTES = 32768
MAX_DOCUMENT = 1_000_000
OUTCOMES = {"NOT_SENT": ("NOT_SENT", False),
            "SATISFIED_NO_POST": ("NOT_SENT", True),
            "ASSIGNMENT_CONFIRMED_OBSERVED": ("CONFIRMED", True),
            "DRIFT": ("CONFIRMED", False),
            "FAILED_ACTUAL_RESULT": ("CONFIRMED", False)}


class Invalid(Exception):
    pass


def require(condition):
    if not condition:
        raise Invalid("assignment journal unverified")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("ascii")).hexdigest()


def module(name):
    spec = importlib.util.spec_from_file_location("assignment_" + name, Path(__file__).with_name(name + ".py"))
    require(spec is not None and spec.loader is not None)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def fields(value, names):
    require(type(value) is dict and set(value) == set(names.split()))


def token(value, size=32):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{" + str(size) + "}", value) is not None)


def decode(raw):
    require(type(raw) is str and len(raw.encode("ascii")) <= MAX_DOCUMENT)
    value = json.loads(raw)
    require(type(value) is dict and canonical(value) == raw)
    return value


def task_binding(task):
    return {"task_id": task["task_id"], "created_at": task["created_at"],
            "task_sha256": digest(task), "revision": task["revision"],
            "generation": task["cooperative_binding"]["generation"],
            "session_id": task["cooperative_binding"]["session_id"], "worker": task["worker"]}


def identifiers(db):
    # Identifier comes only from the fixed TABLES tuple, never from retained data.
    return {row[0] for table in TABLES for row in db.execute("SELECT id FROM " + table)}  # nosec B608


def get(db, table, identity):
    require(table in TABLES)
    # table passed the exact TABLES allowlist above; data remains parameterized.
    row = db.execute("SELECT document,sha256 FROM " + table + " WHERE id=?", (identity,)).fetchone()  # nosec B608
    if row is None or row[0] is None:
        return None
    value = decode(row[0])
    require(digest(value) == row[1])
    return value


def validate_request(db, request):
    fields(request, "version binding original_task reserved_task approval evidence_id settlement_id")
    require(type(request["version"]) is int and request["version"] == 1)
    binding = request["binding"]
    fields(binding, "schema_version action intent_operation_id operation_id attempt_id intent_sha256 store_id target publisher payload payload_sha256 prior_assignee_ids task_binding implementation_head")
    require(type(binding["schema_version"]) is int and binding["schema_version"] == 1
            and binding["action"] == "add-assignee")
    for key in ("intent_operation_id", "operation_id", "attempt_id", "store_id"):
        token(binding[key])
    for key in ("intent_sha256", "payload_sha256"):
        token(binding[key], 64)
    token(binding["implementation_head"], 40)
    for key in ("evidence_id", "settlement_id"):
        token(request[key])
    require(len({binding["operation_id"], binding["attempt_id"], request["evidence_id"], request["settlement_id"]}) == 4)
    row = db.execute("SELECT request,request_sha256 FROM claim_intents WHERE operation_id=?",
                     (binding["intent_operation_id"],)).fetchone()
    require(row is not None)
    journal = module("monitor-journal")
    intent = journal.decode_intent(row[0])
    journal.validate_claim_intent(intent)
    require(intent["schema_version"] == 2 and row[1] == binding["intent_sha256"] == digest(intent)
            and binding["store_id"] == intent["store_id"] == db.execute("SELECT store_id FROM meta").fetchone()[0])
    original, reserved = request["original_task"], request["reserved_task"]
    core = module("orchestrator-state")
    for task in (original, reserved):
        core.validate_record(task, allow_bound=True)
        require(task["schema_version"] == 3 and task["state"] in core.ACTIVE
                and task["worker"] is not None and task["transition_intent"] is None
                and task.get("transition_recovery", {}).get("phase") != "pending")
    core.require_assignment_settled(original)
    # Exact v2 intent equality is preserved, including the original full digest.
    require(intent["binding"] == task_binding(original) and binding["task_binding"] == task_binding(reserved))
    marker = reserved["assignment_dispatch"]
    require(marker == {"version": 1, "phase": "pending", "operation_id": binding["operation_id"],
                       "attempt_id": binding["attempt_id"], "store_id": binding["store_id"],
                       "intent_sha256": digest(intent), "original_sha256": digest(original),
                       "original_revision": original["revision"], "implementation_head": binding["implementation_head"]})
    expected = dict(original, revision=original["revision"] + 1, updated_at=reserved["updated_at"], assignment_dispatch=marker)
    require(reserved == expected)
    observed, claim = intent["identity_observation"], intent["claim"]
    require(original["repo"] == claim["repo"] and original["branch"] == claim["branch"]
            and original["tracker_type"] == "issue" and original["tracker_number"] == claim["issue"]
            and original["kind"] == claim["scope"])
    require(binding["publisher"] == {"id": observed["actor_id"], "node_id": observed["actor_node_id"], "login": observed["actor_login"]}
            and binding["target"] == {"repository": claim["repo"], "repository_id": observed["repository_id"],
                                      "repository_node_id": observed["repository_node_id"], "issue": claim["issue"],
                                      "issue_id": observed["issue_id"], "issue_node_id": observed["issue_node_id"]})
    payload = canonical({"assignees": [observed["actor_login"]]})
    require(binding["payload"] == payload and binding["payload_sha256"] == hashlib.sha256(payload.encode("ascii")).hexdigest())
    ids = binding["prior_assignee_ids"]
    validate_ids(ids)
    require(observed["actor_id"] in ids or len(ids) < 10)
    approval = request["approval"]
    fields(approval, "binding_sha256 interaction age_milliseconds maximum_age_seconds")
    require(approval["binding_sha256"] == digest(binding)
            and approval["interaction"] == "CONTROLLING_TTY_EXACT_CHALLENGE"
            and type(approval["age_milliseconds"]) is int and 0 <= approval["age_milliseconds"] < 120000
            and type(approval["maximum_age_seconds"]) is int and approval["maximum_age_seconds"] == 120)
    require(len(canonical(request).encode("ascii")) <= MAX_DOCUMENT)


def validate_ids(ids):
    require(type(ids) is list and len(ids) <= 10
            and all(type(item) is int and 0 < item <= 2**63 - 1 for item in ids)
            and ids == sorted(set(ids)))


def validate_evidence(request, evidence):
    fields(evidence, "version attempt_id completion result_ids producer")
    require(type(evidence["version"]) is int and evidence["version"] == 1
            and evidence["attempt_id"] == request["binding"]["attempt_id"]
            and evidence["completion"] in {"NOT_SENT", "CONFIRMED", "UNKNOWN"}
            and evidence["producer"] == "SYNCHRONOUS_TRANSPORT_CLOSED")
    if evidence["result_ids"] is not None:
        validate_ids(evidence["result_ids"])


def validate_settlement(request, evidence, settlement):
    fields(settlement, "version attempt_id evidence_sha256 outcome completion satisfaction result_ids")
    require(type(settlement["version"]) is int and settlement["version"] == 1
            and settlement["attempt_id"] == request["binding"]["attempt_id"]
            and settlement["evidence_sha256"] == digest(evidence)
            and settlement["outcome"] in OUTCOMES and type(settlement["satisfaction"]) is bool)
    completion, satisfaction = OUTCOMES[settlement["outcome"]]
    require((settlement["completion"], settlement["satisfaction"]) == (completion, satisfaction)
            and evidence["completion"] == completion)
    ids, prior = settlement["result_ids"], request["binding"]["prior_assignee_ids"]
    if ids is not None:
        validate_ids(ids)
    if evidence["result_ids"] is not None:
        require(ids == evidence["result_ids"])
    actor = request["binding"]["publisher"]["id"]
    outcome = settlement["outcome"]
    if outcome == "NOT_SENT":
        require(ids is None)
    else:
        require(ids is not None)
        if outcome == "DRIFT":
            require(not set(prior) <= set(ids))
        elif outcome == "FAILED_ACTUAL_RESULT":
            require(set(prior) <= set(ids) and actor not in ids)
        else:
            require(set(prior) <= set(ids) and actor in ids)


def validate(db):
    columns = [("id", "TEXT", 1, None, 1), ("document", "TEXT", 0, None, 0),
               ("sha256", "TEXT", 0, None, 0), ("reserved", "BLOB", 1, None, 0)]
    seen = set()
    counts = []
    for table in TABLES:
        require([tuple(row)[1:6] for row in db.execute("PRAGMA table_info(" + table + ")")] == columns)
        rows = db.execute("SELECT * FROM " + table).fetchall()  # nosec B608 - fixed TABLES iteration
        counts.append(len(rows))
        require(len(rows) <= CAPACITY)
        for row in rows:
            token(row["id"])
            require(row["id"] not in seen)
            seen.add(row["id"])
            if row["document"] is None:
                require(table in TABLES[2:] and row["sha256"] is None and row["reserved"] == bytes(RESERVE_BYTES))
            else:
                value = decode(row["document"])
                require(row["sha256"] == digest(value) and row["reserved"] == b"")
    require(len(set(counts)) == 1)
    journal = module("monitor-journal")
    forbidden = {db.execute("SELECT store_id FROM meta").fetchone()[0]}
    for row in db.execute("SELECT request FROM claim_intents"):
        forbidden.update(journal.claim_intent_identifiers(journal.decode_intent(row[0])))
    for row in db.execute("SELECT incarnation,operation_id FROM binding_acks"):
        forbidden.update(row)
    forbidden.update(row[0] for row in db.execute("SELECT observation_id FROM claim_observations"))
    require(not seen & forbidden)
    linked = set()
    for row in db.execute("SELECT id,document FROM assignment_requests"):
        request = decode(row["document"])
        validate_request(db, request)
        binding = request["binding"]
        require(row["id"] == binding["operation_id"])
        attempt = get(db, "assignment_attempts", binding["attempt_id"])
        require(attempt == {"version": 1, "phase": "DISPATCHING", "operation_id": binding["operation_id"],
                            "request_sha256": digest(request), "producer": "DIRECT_HTTPS_NO_DESCENDANTS"})
        links = {binding["operation_id"], binding["attempt_id"], request["evidence_id"], request["settlement_id"]}
        require(len(links) == 4 and not linked & links and links <= seen)
        linked.update(links)
        evidence = get(db, "assignment_evidence", request["evidence_id"])
        settlement = get(db, "assignment_settlements", request["settlement_id"])
        if evidence is not None:
            validate_evidence(request, evidence)
        if settlement is not None:
            require(evidence is not None)
            validate_settlement(request, evidence, settlement)
    require(linked == seen)


def reservation_rows(db, request):
    """Exact insertion checks shared by the rollback preflight and actual commit."""
    require(db.in_transaction)
    journal = module("monitor-journal")
    journal.validate_store(db)
    version = db.execute("SELECT version FROM meta").fetchone()[0]
    require(version in {5, 6})
    validate_request(db, request)
    if version == 5:
        for table in TABLES:
            db.execute("CREATE TABLE " + table + " (id TEXT PRIMARY KEY NOT NULL, document TEXT, sha256 TEXT, reserved BLOB NOT NULL)")
        db.execute("UPDATE meta SET version=6")
    require(db.execute("SELECT count(*) FROM assignment_requests").fetchone()[0] < CAPACITY)
    binding = request["binding"]
    # One assignment per intent; all prior outcomes, including UNKNOWN, refuse replay.
    for row in db.execute("SELECT document FROM assignment_requests"):
        require(decode(row[0])["binding"]["intent_operation_id"] != binding["intent_operation_id"])
    attempt = {"version": 1, "phase": "DISPATCHING", "operation_id": binding["operation_id"],
               "request_sha256": digest(request), "producer": "DIRECT_HTTPS_NO_DESCENDANTS"}
    for table, identity, document in ((TABLES[0], binding["operation_id"], request),
                                      (TABLES[1], binding["attempt_id"], attempt)):
        db.execute("INSERT INTO " + table + " VALUES(?,?,?,?)", (identity, canonical(document), digest(document), b""))  # nosec B608 - fixed TABLES entries
    for table, identity in ((TABLES[2], request["evidence_id"]), (TABLES[3], request["settlement_id"])):
        db.execute("INSERT INTO " + table + " VALUES(?,NULL,NULL,zeroblob(?))", (identity, RESERVE_BYTES))  # nosec B608 - fixed TABLES entries
    journal.validate_store(db)


def preflight(db, request):
    """Coordinator-held rollback rehearsal BEFORE writing the task marker.

    Exercise actual schema, retention, ID namespace and page-allocation checks.
    No rows/migration survive. Actual reservation repeats every check, because
    unrelated monitor writes may occur after this transaction is rolled back.
    """
    require(not db.in_transaction)
    try:
        db.execute("BEGIN IMMEDIATE")
        reservation_rows(db, request)
    finally:
        db.rollback()


def reserve(db, request):
    """Caller holds coordinator; task marker must ALREADY be durable."""
    require(not db.in_transaction)
    with db:
        db.execute("BEGIN IMMEDIATE")
        reservation_rows(db, request)


def fill(db, table, identity, document):
    require(table in TABLES[2:] and len(canonical(document).encode("ascii")) < RESERVE_BYTES // 2)
    with db:
        db.execute("BEGIN IMMEDIATE")
        module("monitor-journal").validate_store(db)
        prior = get(db, table, identity)
        if prior is not None:
            require(prior == document)
            return
        # table passed the exact TABLES[2:] allowlist; all row values are bound.
        cursor = db.execute("UPDATE " + table + " SET document=?,sha256=?,reserved=? WHERE id=? AND document IS NULL",  # nosec B608
                            (canonical(document), digest(document), b"", identity))
        require(cursor.rowcount == 1)
        module("monitor-journal").validate_store(db)
