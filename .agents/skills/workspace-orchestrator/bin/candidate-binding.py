#!/usr/bin/env python3
"""Task-authoritative association of a retained PR observation to an existing review."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


class Unverified(Exception):
    pass


class Refused(Exception):
    pass


def load(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise Unverified("installed binding dependency missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def fields(value: Any, expected: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise Unverified("binding fields missing or unknown")


def request_check(request: dict[str, Any]) -> None:
    fields(request, {"schema_version", "action", "operation_id", "task_id", "incarnation", "expected_revision", "candidate", "poll_seq", "config_sha256"})
    if type(request["schema_version"]) is not int or request["schema_version"] != 1 or request["action"] != "bind-candidate":
        raise Unverified("unsupported binding request")
    for name in ("task_id", "operation_id"):
        if not isinstance(request[name], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", request[name]):
            raise Unverified("invalid task/operation identity")
    for name in ("incarnation", "config_sha256"):
        if not isinstance(request[name], str) or not re.fullmatch(r"[0-9a-f]{64}", request[name]):
            raise Unverified("invalid binding digest")
    if type(request["expected_revision"]) is not int or request["expected_revision"] < 0 or type(request["poll_seq"]) is not int or request["poll_seq"] < 1:
        raise Unverified("invalid expected revisions")
    candidate = request["candidate"]
    fields(candidate, {"store_id", "repo", "number", "generation", "head", "fingerprint"})
    for name, length in (("store_id",32), ("head",40), ("fingerprint",64)):
        if not isinstance(candidate[name], str) or not re.fullmatch(r"[0-9a-f]{" + str(length) + "}", candidate[name]):
            raise Unverified("invalid candidate identity")
    if not isinstance(candidate["repo"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", candidate["repo"]) or any(part in {".",".."} for part in candidate["repo"].split("/")):
        raise Unverified("invalid candidate repository")
    if any(type(candidate[name]) is not int or candidate[name] < 1 for name in ("number","generation")):
        raise Unverified("invalid PR number/generation")


def incarnation(record: dict[str, Any]) -> str:
    return digest({"task_id":record["task_id"], "created_at":record["created_at"], "scope_token":record["leases"]["scope_token"]})


def reference(candidate: dict[str, Any]) -> str:
    return f"{candidate['store_id']}:{candidate['repo']}#{candidate['number']}:{candidate['generation']}"


def validate_binding(record: dict[str, Any]) -> None:
    binding = record.get("candidate_binding")
    if binding is None:
        if "candidate_binding" in record:
            raise Unverified("null candidate binding")
        return
    fields(binding, {"schema_version", "request", "request_sha256", "observation", "as_of", "result"})
    request = binding["request"]
    request_check(request)
    candidate = request["candidate"]
    if (binding["schema_version"] != 1 or type(binding["schema_version"]) is not int or request["task_id"] != record["task_id"]
            or request["incarnation"] != incarnation(record) or binding["request_sha256"] != digest(request)
            or record["kind"] != "review" or record["repo"] != candidate["repo"]
            or record["tracker_type"] != "pr" or record["tracker_number"] != candidate["number"]):
        raise Unverified("binding identity differs from task authority")
    observation = binding["observation"]
    fields(observation, {"event_seq", "payload"})
    if type(observation["event_seq"]) is not int or not 1 <= observation["event_seq"] <= request["poll_seq"]:
        raise Unverified("binding event chronology invalid")
    journal = load("monitor-journal")
    payload = observation["payload"]
    if (journal.fingerprint(payload) != candidate["fingerprint"] or payload.get("head") != candidate["head"]
            or payload.get("presence") != "OPEN_SET" or journal.material(payload) != payload):
        raise Unverified("binding observation substituted")
    as_of = binding["as_of"]
    fields(as_of, {"poll_seq","config_sha256","finished_at","source_status","overall_status"})
    if (as_of["poll_seq"] != request["poll_seq"] or as_of["config_sha256"] != request["config_sha256"]
            or type(as_of["poll_seq"]) is not int
            or as_of["source_status"] != "OBSERVED" or as_of["overall_status"] not in {"CURRENT","CHANGED","UNVERIFIED"}
            or not isinstance(as_of["finished_at"], str) or not as_of["finished_at"]):
        raise Unverified("binding coverage evidence invalid")
    expected = {"status":"CANDIDATE_BOUND", "task_id":record["task_id"], "incarnation":request["incarnation"],
                "candidate_reference":reference(candidate), "resulting_revision":request["expected_revision"]+1,
                "candidate_ready":False,"remote_authority":False}
    if (binding["result"] != expected or type(binding["result"]["resulting_revision"]) is not int
            or binding["result"]["candidate_ready"] is not False or binding["result"]["remote_authority"] is not False
            or expected["resulting_revision"] > record["revision"]):
        raise Unverified("binding receipt disagrees with mutation")


def resolve(db, request, config, journal):
    if db.in_transaction:
        raise Unverified("independent observation snapshot required")
    db.execute("BEGIN")
    try:
        journal.validate_store(db)
        candidate = request["candidate"]
        if db.execute("SELECT store_id FROM meta").fetchone()[0] != candidate["store_id"]:
            raise Refused("journal incarnation differs")
        latest = db.execute("SELECT * FROM polls ORDER BY seq DESC LIMIT 1").fetchone()
        if latest is None or latest["status"] in {"STARTED","INTERRUPTED"} or latest["seq"] != request["poll_seq"]:
            raise Refused("latest poll does not match requested observation")
        if latest["config"] != request["config_sha256"] or journal.fingerprint(config) != request["config_sha256"]:
            raise Refused("configured observation scope changed")
        if candidate["repo"] not in config["repositories"]:
            raise Refused("repository is out of configured scope")
        coverage = db.execute("SELECT * FROM coverage WHERE seq=? AND source=?", (latest["seq"], "repo:"+candidate["repo"])).fetchone()
        if coverage is None or coverage["status"] != "OBSERVED":
            raise Unverified("target repository coverage unavailable")
        row = db.execute("SELECT e.* FROM candidates c JOIN events e ON e.id=c.event_id WHERE c.repo=? AND c.number=?", (candidate["repo"],candidate["number"])).fetchone()
        if row is None or row["generation"] != candidate["generation"] or row["fingerprint"] != candidate["fingerprint"]:
            raise Refused("candidate generation is absent or superseded")
        payload = json.loads(row["payload"])
        if payload["presence"] != "OPEN_SET" or payload["head"] != candidate["head"]:
            raise Refused("candidate is not the requested open head")
        return {"event_seq":row["seq"], "payload":payload}, {"poll_seq":latest["seq"], "config_sha256":latest["config"],
            "finished_at":latest["finished"], "source_status":"OBSERVED", "overall_status":latest["status"]}
    finally:
        db.rollback()


def prepare(record, request, observation, as_of):
    validate_binding(record)
    request_check(request)
    prior = record.get("candidate_binding")
    if prior:
        if prior["request"] != request:
            raise Refused("task already bound or operation conflicts")
        return record, prior["result"], False
    candidate = request["candidate"]
    if (record["task_id"] != request["task_id"] or incarnation(record) != request["incarnation"]
            or record["revision"] != request["expected_revision"] or record["kind"] != "review"
            or record["state"] not in {"Ready","Claimed","Reviewing"} or record.get("transition_intent")
            or record["repo"] != candidate["repo"] or record["tracker_type"] != "pr"
            or record["tracker_number"] != candidate["number"] or record["head_sha"] != candidate["head"]):
        raise Refused("binding does not match existing review task identity/revision")
    result = {"status":"CANDIDATE_BOUND", "task_id":record["task_id"], "incarnation":incarnation(record),
              "candidate_reference":reference(candidate), "resulting_revision":record["revision"]+1,
              "candidate_ready":False, "remote_authority":False}
    updated = copy.deepcopy(record)
    updated["candidate_binding"] = {"schema_version":1,"request":copy.deepcopy(request),"request_sha256":digest(request),
                                    "observation":observation,"as_of":as_of,"result":result}
    validate_binding({**updated,"revision":record["revision"]+1})
    if len(canonical(updated).encode()) > 900_000:
        raise Unverified("task evidence budget exceeded")
    return updated, result, True


def acknowledge(db, binding):
    journal = load("monitor-journal")
    journal.validate_store(db)
    request = binding["request"]
    candidate = request["candidate"]
    if db.execute("SELECT store_id FROM meta").fetchone()[0] != candidate["store_id"]:
        raise Unverified("acknowledgment store differs from task receipt")
    row = db.execute("SELECT fingerprint FROM events WHERE repo=? AND number=? AND generation=?", (candidate["repo"],candidate["number"],candidate["generation"])).fetchone()
    if row is None or row[0] != candidate["fingerprint"]:
        raise Unverified("acknowledgment lacks original observation")
    receipt = canonical(binding)
    key = request["incarnation"]
    with db:
        db.execute("BEGIN IMMEDIATE")
        version = db.execute("SELECT version FROM meta").fetchone()[0]
        if version == 1:
            db.execute("CREATE TABLE binding_acks (incarnation TEXT PRIMARY KEY, task_id TEXT NOT NULL, operation_id TEXT NOT NULL, receipt TEXT NOT NULL, receipt_sha256 TEXT NOT NULL)")
            db.execute("UPDATE meta SET version=2")
        prior = db.execute("SELECT receipt,receipt_sha256 FROM binding_acks WHERE incarnation=?", (key,)).fetchone()
        if prior:
            if prior[0] != receipt or prior[1] != digest(binding):
                raise Unverified("journal acknowledgment conflicts with task authority")
        else:
            if db.execute("SELECT count(*) FROM binding_acks").fetchone()[0] >= 10_000:
                raise Unverified("acknowledgment capacity reached")
            db.execute("INSERT INTO binding_acks VALUES(?,?,?,?,?)", (key,request["task_id"],request["operation_id"],receipt,digest(binding)))
    return {"status":"ACKNOWLEDGED", "authority":"task receipt, not journal row"}


def bind(root: Path, task_id: str, request: dict[str, Any], config_path: Path) -> dict[str, Any]:
    request_check(request)
    if task_id != request["task_id"]:
        raise Refused("CLI task differs from request")
    state, monitor, journal = load("orchestrator-state"),load("orchestrator-monitor"),load("monitor-journal")
    # Receipt lookup precedes source freshness and journal availability checks.
    with state.CoordinatorLock(root):
        record = state.read_task(root,task_id)
        prior = record.get("candidate_binding")
        if prior:
            _, result, _ = prepare(record,request,None,None)
        else:
            result = None
    lock = root/"monitor"/"poll.lock"
    held, db = False, None
    try:
        monitor.acquire(lock)
        held = True
        with state.CoordinatorLock(root):
            record = state.read_task(root,task_id)
            if record.get("candidate_binding"):
                _, result, _ = prepare(record,request,None,None)
                # Re-establish the durability barrier after a prior uncertain
                # replacement without changing revision or rewriting task bytes.
                result = None
                path = state.task_path(root,task_id)
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
                directory = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
                result = record["candidate_binding"]["result"]
            else:
                state.verify_reservations(root,record)
                state.verify_review_identity(record)
                config = monitor.load_config(config_path)
                if not (root/"monitor/history.sqlite3").is_file():
                    raise Unverified("existing observation journal required")
                db = journal.open_store(root/"monitor",writable=True)
                observation, as_of = resolve(db,request,config,journal)
                if monitor.load_config(config_path) != config:
                    raise Refused("configuration changed during binding")
                updated, result, changed = prepare(record,request,observation,as_of)
                if changed:
                    result = None  # Never acknowledge a write whose durability barrier failed.
                    state.write_task(root,updated)
                    record = state.read_task(root,task_id)
                    result = record["candidate_binding"]["result"]
            # Once the task receipt is committed, ack failure cannot undo it.
            try:
                if db is None:
                    if not (root/"monitor/history.sqlite3").is_file():
                        raise Unverified("journal unavailable")
                    db = journal.open_store(root/"monitor",writable=True)
                ack = acknowledge(db,record["candidate_binding"])
            except Exception:
                ack = {"status":"UNVERIFIED", "reason":"journal acknowledgment unavailable; task receipt retained"}
            return {"result":result,"journal_ack":ack,"live_github_freshness":"UNVERIFIED"}
    except (Refused, Unverified):
        raise
    except Exception:
        if result is not None:
            return {"result":result,"journal_ack":{"status":"UNVERIFIED","reason":"journal/lock unavailable"},"live_github_freshness":"UNVERIFIED"}
        raise
    finally:
        if db is not None:
            db.close()
        if held:
            os.rmdir(lock)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not sys.flags.isolated or not sys.dont_write_bytecode:
            raise Unverified("invoke with python3 -I -B")
        state, reader = load("orchestrator-state"), load("review-collect")
        request = reader.decode(reader.read_bytes(args.request,100_000))
        result = bind(state.state_root(create=False),args.task_id,request,args.config)
        print(json.dumps(result,sort_keys=True))
        return 0
    except Refused as exc:
        print(json.dumps({"status":"REFUSED","reason":str(exc)}))
        return 4
    except Exception:
        print(json.dumps({"status":"UNVERIFIED","reason":"binding not established; inspect retained task before retry"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
