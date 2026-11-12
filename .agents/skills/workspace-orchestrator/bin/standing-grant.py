#!/usr/bin/env python3
"""Standing authority on the existing journal, never a second dispatch outbox.

Historical validators deliberately do not consult today's active selector.
Only the controller writes selection; runtime resolves it from this fixed store.
Linux clocks are the initially supported continuity contract.
"""

import copy
import datetime
import hashlib
import importlib.util
import math
import re
import sys
import time
from functools import lru_cache
from pathlib import Path

TABLES = ("standing_grants", "standing_selector", "standing_qualifications", "standing_qualification_selector")
REPOSITORY = "GSA-TTS/agentic-coding-maintainers"
REPOSITORY_ID = 1422648445
ACTIONS = {"issue-create", "assignees-add"}
QUALIFICATION_CASES = frozenset("create_bind_assign intake_complete intake_complete_interrupted changed_implementation_head expired_before_reservation expired_after_reservation confirmed_settlement_after_expiry executor_daily_budget no_active_grant no_tty wrong_target wrong_fields wrong_epoch revocation_before_launch revocation_inflight budgets_restart clock_rollback unknown_no_replay marker_commit_failure legacy_v6_unknown_preserved manual_tty_required".split())


class Invalid(Exception):
    pass


def require(condition, reason="STANDING_GRANT_UNVERIFIED"):
    if not condition:
        raise Invalid(reason)


@lru_cache(maxsize=1)
def typed():
    # Cache this fixed source module, not any selector, grant or validation.
    # Loading is lazy, after this module's own initialization has completed.
    spec = importlib.util.spec_from_file_location("grant_typed", Path(__file__).with_name("assignment-journal.py"))
    require(spec is not None and spec.loader is not None)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clock():
    require(sys.platform == "linux" and hasattr(time, "CLOCK_BOOTTIME"), "CLOCK_PLATFORM_UNSUPPORTED")
    boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    require(re.fullmatch(r"[0-9a-f-]{36}", boot) is not None, "CLOCK_UNVERIFIED")
    return {"boot": boot, "wall": time.time(), "elapsed": time.clock_gettime(time.CLOCK_BOOTTIME),
            "awake": time.monotonic()}


def validate_clock(value):
    typed().fields(value, "boot wall elapsed awake")
    require(type(value["boot"]) is str and re.fullmatch(r"[0-9a-f-]{36}", value["boot"]) is not None)
    for key in ("wall", "elapsed", "awake"):
        require(type(value[key]) in {int, float} and math.isfinite(value[key]) and value[key] >= 0)


def continuity(previous, current):
    validate_clock(previous)
    validate_clock(current)
    wall, elapsed, awake = (current[key] - previous[key] for key in ("wall", "elapsed", "awake"))
    require(current["boot"] == previous["boot"] and min(wall, elapsed, awake) >= 0
            and abs(wall - elapsed) < 2 and abs(elapsed - awake) < 2, "CLOCK_CONTINUITY_LOST")


def day(value):
    return datetime.datetime.fromtimestamp(value["wall"], datetime.timezone.utc).date().isoformat()


def validate_definition(value):
    t = typed()
    t.fields(value, "version grant_id objective work_item repository repository_id repository_node_id publisher policy_sha256 implementation_head lifetime_seconds title body qualification workflow_effects")
    require(type(value["version"]) is int and value["version"] == 1)
    t.token(value["grant_id"])
    for key in ("objective", "work_item"):
        require(type(value[key]) is str and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", value[key]) is not None)
    require(value["repository"] == REPOSITORY and type(value["repository_id"]) is int
            and value["repository_id"] == REPOSITORY_ID)
    t.token(value["policy_sha256"], 64)
    t.token(value["implementation_head"], 40)
    t.fields(value["qualification"], "endpoint_evidence_sha256")
    t.token(value["qualification"]["endpoint_evidence_sha256"], 64)
    effects = value["workflow_effects"]
    t.fields(effects, "events decision evidence_sha256")
    require(effects["events"] == ["issues.opened", "issues.assigned"]
            and effects["decision"] == "AUTHORIZE_REVIEWED_SYNTHETIC_ISSUE_EVENT_WORKFLOWS_AND_COST")
    t.token(effects["evidence_sha256"], 64)
    p = value["publisher"]
    t.fields(p, "id node_id login")
    require(type(p["id"]) is int and 0 < p["id"] <= 2**63 - 1)
    require(type(p["login"]) is str and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", p["login"])
            and "--" not in p["login"])
    for node in (p["node_id"], value["repository_node_id"]):
        require(type(node) is str and re.fullmatch(r"[A-Za-z0-9_+/=-]{1,256}", node) is not None)
    require(type(value["lifetime_seconds"]) is int and 0 < value["lifetime_seconds"] <= 86400)
    # Initial qualification is synthetic-only. No free-form runtime prose, path,
    # private task/session identifier, label, milestone or assignee expansion.
    require(value["title"] == "Synthetic standing-grant tracking fixture: " + value["work_item"])
    require(value["body"] == "Synthetic fixture for the " + value["objective"] + " objective. No production change requested.")


def effective_scope(definition):
    """Complete enforced scope shown in, and hashed into, the human decision."""
    return {"actions": ["issue-create", "assignees-add"], "api_origin": "https://api.github.com",
            "fields": {"issue-create": ["title", "body"], "assignees-add": ["assignees"]},
            "assignee_ids": [definition["publisher"]["id"]], "text": "FIXED_SYNTHETIC_TEMPLATE_ONLY",
            "budgets": {"issues_per_utc_day": 5, "metadata_per_utc_day": 20, "cumulative_unknown_and_pending": 3,
                        "pending_per_target": 1, "maximum_lifetime_seconds": 86400,
                        "total_workers": 6, "implementation_lanes": 2,
                        "accounting_scope": "REPOSITORY_HISTORY_ACROSS_GRANTS_AND_OBJECTIVES"},
            "lifetime_seconds": definition["lifetime_seconds"], "workflow_effects": definition["workflow_effects"],
            "qualification": definition["qualification"], "selection": "SINGLE_ACTIVE_GRANT",
            "clock_platform": "LINUX_BOOT_BOOTTIME_MONOTONIC"}


def logical_key(definition):
    return typed().digest({key: definition[key] for key in ("repository_id", "objective", "work_item")})


def payload(definition):
    return {"title": definition["title"], "body": definition["body"] + "\n\n<!-- scoped-work:" + logical_key(definition) + " -->"}


def observed(definition, issue=None):
    value = {"repository_id": definition["repository_id"], "repository_node_id": definition["repository_node_id"],
             "actor_id": definition["publisher"]["id"], "actor_node_id": definition["publisher"]["node_id"],
             "actor_login": definition["publisher"]["login"]}
    if issue is not None:
        value.update(issue_id=issue["id"], issue_node_id=issue["node_id"])
    return value


def migrate(db):
    """Caller holds coordinator and transaction; retain all preexisting row bytes."""
    t = typed()
    version = db.execute("SELECT version FROM meta").fetchone()[0]
    require(version in {1, 2, 3, 4, 5, 6, 7})
    if version == 1:
        db.execute("CREATE TABLE binding_acks (incarnation TEXT PRIMARY KEY, task_id TEXT NOT NULL, operation_id TEXT NOT NULL, receipt TEXT NOT NULL, receipt_sha256 TEXT NOT NULL)")
    if version <= 2:
        db.execute("CREATE TABLE claim_intents (operation_id TEXT PRIMARY KEY NOT NULL, request TEXT NOT NULL, request_sha256 TEXT NOT NULL)")
    if version <= 3:
        db.execute("CREATE TABLE claim_observations (observation_id TEXT PRIMARY KEY NOT NULL, operation_id TEXT NOT NULL REFERENCES claim_intents(operation_id), request_sha256 TEXT NOT NULL, receipt TEXT NOT NULL, receipt_sha256 TEXT NOT NULL)")
    if version <= 5:
        for table in t.TABLES:
            db.execute("CREATE TABLE " + table + " (id TEXT PRIMARY KEY NOT NULL, document TEXT, sha256 TEXT, reserved BLOB NOT NULL)")  # nosec B608 - fixed typed.TABLES
    if version <= 6:
        db.execute("CREATE TABLE standing_grants (id TEXT PRIMARY KEY NOT NULL, document TEXT NOT NULL, sha256 TEXT NOT NULL)")
        db.execute("CREATE TABLE standing_selector (id INTEGER PRIMARY KEY NOT NULL, document TEXT NOT NULL, sha256 TEXT NOT NULL)")
        db.execute("CREATE TABLE standing_qualifications (id TEXT PRIMARY KEY NOT NULL, document TEXT NOT NULL, sha256 TEXT NOT NULL)")
        db.execute("CREATE TABLE standing_qualification_selector (id INTEGER PRIMARY KEY NOT NULL, document TEXT NOT NULL, sha256 TEXT NOT NULL)")
        db.execute("UPDATE meta SET version=7")


def get(db, identity):
    row = db.execute("SELECT document,sha256 FROM standing_grants WHERE id=?", (identity,)).fetchone()
    require(row is not None, "GRANT_NOT_FOUND")
    value = typed().decode(row[0])
    require(typed().digest(value) == row[1])
    return value


def selector(db):
    require(db.execute("SELECT version FROM meta").fetchone()[0] == 7, "NO_ACTIVE_GRANT")
    row = db.execute("SELECT document,sha256 FROM standing_selector WHERE id=1").fetchone()
    require(row is not None, "NO_ACTIVE_GRANT")
    value = typed().decode(row[0])
    require(typed().digest(value) == row[1])
    return value


def put_selector(db, value):
    t = typed()
    db.execute("INSERT INTO standing_selector VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document,sha256=excluded.sha256",
               (t.canonical(value), t.digest(value)))


def identifiers(db):
    return ({row[0] for row in db.execute("SELECT id FROM standing_grants")}
            | {row[0] for row in db.execute("SELECT id FROM standing_qualifications")})


def qualification_scope(definition):
    return {key: definition[key] for key in ("implementation_head", "policy_sha256", "repository", "repository_id",
            "repository_node_id", "publisher", "objective", "work_item", "workflow_effects")} | {
                "actions": ["issue-create", "assignees-add"], "platform": "LINUX_BOOT_BOOTTIME_MONOTONIC",
                "pilot_limits": {"create_attempts": 1, "assignment_attempts": 1, "maximum_grant_seconds": 86400,
                                 "issues_per_utc_day": 5, "metadata_per_utc_day": 20, "cumulative_unknown_and_pending": 3}}


def validate_qualification_manifest(manifest):
    t = typed()
    t.fields(manifest, "version qualification_id mode human_identity scope report transcript")
    require(type(manifest["version"]) is int and manifest["version"] == 1)
    t.token(manifest["qualification_id"])
    require(manifest["mode"] == "OFFLINE_REVIEWED_ONE_USE_LIVE_PILOT", "QUALIFICATION_MODE_UNSUPPORTED")
    require(type(manifest["human_identity"]) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", manifest["human_identity"]))
    scope = manifest["scope"]
    t.fields(scope, "implementation_head policy_sha256 repository repository_id repository_node_id publisher objective work_item workflow_effects actions platform pilot_limits")
    require(scope["actions"] == ["issue-create", "assignees-add"] and scope["platform"] == "LINUX_BOOT_BOOTTIME_MONOTONIC")
    # Reuse exact target/public-scope validation without treating the manifest as
    # an activated grant or allowing any qualification boolean.
    definition = {key: value for key, value in scope.items() if key not in {"actions", "platform", "pilot_limits"}}
    definition.update(version=1, grant_id=manifest["qualification_id"], lifetime_seconds=86400,
        title="Synthetic standing-grant tracking fixture: " + scope["work_item"],
        body="Synthetic fixture for the " + scope["objective"] + " objective. No production change requested.",
        qualification={"endpoint_evidence_sha256": manifest["report"]["sha256"]})
    validate_definition(definition)
    require(t.canonical(scope) == t.canonical(qualification_scope(definition)))
    for key in ("report", "transcript"):
        artifact = manifest[key]
        t.fields(artifact, "name sha256 size")
        require(type(artifact["name"]) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\.(json|txt)", artifact["name"]))
        t.token(artifact["sha256"], 64)
        require(type(artifact["size"]) is int and 0 < artifact["size"] <= (32768 if key == "report" else 1048576))
    require(manifest["report"]["name"] != manifest["transcript"]["name"])


def validate_qualification_report(manifest, report):
    t = typed()
    t.fields(report, "version scope cases independent_reviews assessment")
    require(type(report["version"]) is int and report["version"] == 1 and report["scope"] == manifest["scope"])
    require(report["assessment"] == "OFFLINE_FIXTURES_ONLY_HUMAN_MUST_ASSESS_ARTIFACT_MEANING")
    t.fields(report["cases"], " ".join(sorted(QUALIFICATION_CASES)))
    require(all(value == "PASS" for value in report["cases"].values()), "QUALIFICATION_CASE_FAILED")
    reviews = report["independent_reviews"]
    require(type(reviews) is list and len(reviews) == 2)
    require({item.get("role") for item in reviews} == {"qa", "security"})
    reviewers = set()
    for review in reviews:
        t.fields(review, "role reviewer inspected_head result evidence_sha256")
        require(type(review["reviewer"]) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", review["reviewer"]))
        require(review["reviewer"] != manifest["human_identity"] and review["reviewer"] not in reviewers)
        reviewers.add(review["reviewer"])
        require(review["inspected_head"] == manifest["scope"]["implementation_head"] and review["result"] == "PASS")
        t.token(review["evidence_sha256"], 64)
    require(t.digest(report) == manifest["report"]["sha256"]
            and len(t.canonical(report).encode("ascii")) == manifest["report"]["size"], "QUALIFICATION_ARTIFACT_CHANGED")


def qualification_selector(db):
    require(db.execute("SELECT version FROM meta").fetchone()[0] == 7, "ENDPOINT_QUALIFICATION_NOT_INSTALLED")
    row = db.execute("SELECT document,sha256 FROM standing_qualification_selector WHERE id=1").fetchone()
    require(row is not None, "ENDPOINT_QUALIFICATION_NOT_INSTALLED")
    value = typed().decode(row[0])
    require(typed().digest(value) == row[1])
    return value


def put_qualification_selector(db, value):
    t = typed()
    db.execute("INSERT INTO standing_qualification_selector VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document,sha256=excluded.sha256",
               (t.canonical(value), t.digest(value)))


def qualification_get(db, identity):
    row = db.execute("SELECT document,sha256 FROM standing_qualifications WHERE id=?", (identity,)).fetchone()
    require(row is not None, "ENDPOINT_QUALIFICATION_NOT_INSTALLED")
    value = typed().decode(row[0])
    require(typed().digest(value) == row[1])
    return value


def require_qualification(db, definition):
    selected = qualification_selector(db)
    require(selected["state"] == "active", "QUALIFICATION_REVOKED")
    record = qualification_get(db, selected["qualification_id"])
    require(record["epoch"] == selected["epoch"] and record["manifest"]["scope"] == qualification_scope(definition)
            and record["manifest"]["report"]["sha256"] == definition["qualification"]["endpoint_evidence_sha256"],
            "QUALIFICATION_BINDING_CHANGED")
    return record


def validate_qualifications(db):
    t = typed()
    for table, kind in (("standing_qualifications", "TEXT"), ("standing_qualification_selector", "INTEGER")):
        require([tuple(row)[1:6] for row in db.execute("PRAGMA table_info(" + table + ")")] ==
                [("id", kind, 1, None, 1), ("document", "TEXT", 1, None, 0), ("sha256", "TEXT", 1, None, 0)])
    rows = db.execute("SELECT id FROM standing_qualifications").fetchall()
    require(len(rows) <= 100)
    epochs = set()
    for row in rows:
        record = qualification_get(db, row[0])
        # Pre-bootstrap v7 receipts retain their exact historical binding.
        t.fields(record, "manifest report epoch store_id installed receipt" + (" installation" if "installation" in record else ""))
        if "installation" in record:
            installation = record["installation"]
            t.fields(installation, "new_store authority_root invoking_root directories")
            require(type(installation["new_store"]) is bool)
            for key in ("authority_root", "invoking_root"):
                path = installation[key]
                require(type(path) is str and path.startswith("/") and 1 < len(path.encode("utf-8")) <= 4096
                        and all(part not in {"", ".", ".."} for part in path[1:].split("/"))
                        and not any(ord(char) < 32 for char in path))
            pairs = installation["directories"]
            require(type(pairs) is list and len(pairs) == 4
                    and all(type(pair) is list and len(pair) == 2
                            and all(type(item) is int and item >= 0 for item in pair) for pair in pairs))
        validate_qualification_manifest(record["manifest"])
        validate_qualification_report(record["manifest"], record["report"])
        require(record["manifest"]["qualification_id"] == row[0] and type(record["epoch"]) is int and record["epoch"] > 0
                and record["epoch"] not in epochs and record["store_id"] == db.execute("SELECT store_id FROM meta").fetchone()[0])
        epochs.add(record["epoch"])
        validate_clock(record["installed"])
        binding = {key: value for key, value in record.items() if key != "receipt"} | {"action": "install-qualification"}
        validate_controller_receipt(record["receipt"], binding)
    selections = db.execute("SELECT id FROM standing_qualification_selector").fetchall()
    require(len(selections) <= 1 and (not selections or selections[0][0] == 1))
    if selections:
        selected = qualification_selector(db)
        t.fields(selected, "qualification_id epoch state revocation")
        require(selected["epoch"] == max(epochs) == qualification_get(db, selected["qualification_id"])["epoch"]
                and selected["state"] in {"active", "revoked"})
        if selected["state"] == "active":
            require(selected["revocation"] is None)
        else:
            t.fields(selected["revocation"], "binding receipt")
            binding = selected["revocation"]["binding"]
            t.fields(binding, "action qualification_id epoch store_id implementation_head")
            require(binding["action"] == "revoke-qualification" and binding["epoch"] == selected["epoch"]
                    and binding["qualification_id"] == selected["qualification_id"]
                    and binding["store_id"] == db.execute("SELECT store_id FROM meta").fetchone()[0])
            t.token(binding["implementation_head"], 40)
            validate_controller_receipt(selected["revocation"]["receipt"], binding)


def validate_controller_receipt(receipt, binding):
    typed().fields(receipt, "binding_sha256 interaction age_milliseconds maximum_age_seconds")
    require(receipt["binding_sha256"] == typed().digest(binding)
            and receipt["interaction"] == "CONTROLLING_TTY_GRANT_CHALLENGE"
            and type(receipt["age_milliseconds"]) is int and 0 <= receipt["age_milliseconds"] < 120000
            and type(receipt["maximum_age_seconds"]) is int and receipt["maximum_age_seconds"] == 120)


def validate(db):
    t = typed()
    validate_qualifications(db)
    require(not ({row[0] for row in db.execute("SELECT id FROM standing_grants")}
                 & {row[0] for row in db.execute("SELECT id FROM standing_qualifications")}))
    forbidden = t.identifiers(db) | {db.execute("SELECT store_id FROM meta").fetchone()[0]}
    journal = t.module("monitor-journal")
    for row in db.execute("SELECT request FROM claim_intents"):
        forbidden.update(journal.claim_intent_identifiers(journal.decode_intent(row[0])))
    for row in db.execute("SELECT incarnation,operation_id FROM binding_acks"):
        forbidden.update(row)
    forbidden.update(row[0] for row in db.execute("SELECT observation_id FROM claim_observations"))
    require(not identifiers(db) & forbidden)
    epochs = set()
    for table, kind in (("standing_grants", "TEXT"), ("standing_selector", "INTEGER")):
        require([tuple(row)[1:6] for row in db.execute("PRAGMA table_info(" + table + ")")] ==
                [("id", kind, 1, None, 1), ("document", "TEXT", 1, None, 0), ("sha256", "TEXT", 1, None, 0)])
    require(db.execute("SELECT count(*) FROM standing_grants").fetchone()[0] <= 100)
    for row in db.execute("SELECT id FROM standing_grants"):
        grant = get(db, row[0])
        t.fields(grant, "definition activation epoch activated expires admission store_id qualification_id")
        validate_definition(grant["definition"])
        qualification = qualification_get(db, grant["qualification_id"])
        require(qualification["manifest"]["scope"] == qualification_scope(grant["definition"])
                and qualification["manifest"]["report"]["sha256"] == grant["definition"]["qualification"]["endpoint_evidence_sha256"])
        require(row[0] == grant["definition"]["grant_id"] and type(grant["epoch"]) is int and grant["epoch"] > 0)
        require(grant["epoch"] not in epochs)
        epochs.add(grant["epoch"])
        validate_clock(grant["activated"])
        t.fields(grant["admission"], "task_id created_at task_sha256 revision generation session_id worker")
        t.token(grant["admission"]["task_sha256"], 64)
        require(type(grant["admission"]["revision"]) is int and grant["admission"]["revision"] > 0)
        require(type(grant["admission"]["worker"]) is dict)
        require(grant["store_id"] == db.execute("SELECT store_id FROM meta").fetchone()[0])
        require(grant["expires"] == grant["activated"]["wall"] + grant["definition"]["lifetime_seconds"])
        receipt = grant["activation"]
        t.fields(receipt, "binding_sha256 interaction age_milliseconds maximum_age_seconds")
        require(receipt["interaction"] == "CONTROLLING_TTY_GRANT_CHALLENGE"
                and type(receipt["age_milliseconds"]) is int and 0 <= receipt["age_milliseconds"] < 120000
                and receipt["maximum_age_seconds"] == 120)
        t.token(receipt["binding_sha256"], 64)
        require(receipt["binding_sha256"] == t.digest({"action": "activate", "definition": grant["definition"],
            "epoch": grant["epoch"], "store_id": grant["store_id"], "admission": grant["admission"], "activated": grant["activated"],
            "effective_scope": effective_scope(grant["definition"]), "qualification_id": grant["qualification_id"]}))
    rows = db.execute("SELECT id FROM standing_selector").fetchall()
    require(len(rows) <= 1 and (not rows or rows[0][0] == 1))
    if rows:
        selected = selector(db)
        t.fields(selected, "grant_id epoch state clock revocation")
        require(selected["state"] in {"active", "revoke-requested", "revoked", "paused"})
        require(selected["epoch"] == get(db, selected["grant_id"])["epoch"])
        require(selected["epoch"] == max(epochs))
        validate_clock(selected["clock"])
        if selected["state"] in {"revoke-requested", "revoked"}:
            t.fields(selected["revocation"], "binding receipt")
            binding, receipt = selected["revocation"]["binding"], selected["revocation"]["receipt"]
            t.fields(binding, "action selector implementation_head store_id")
            require(binding["action"] == "revoke" and binding["selector"]["grant_id"] == selected["grant_id"]
                    and binding["selector"]["epoch"] == selected["epoch"]
                    and binding["store_id"] == db.execute("SELECT store_id FROM meta").fetchone()[0])
            t.token(binding["implementation_head"], 40)
            t.fields(receipt, "binding_sha256 interaction age_milliseconds maximum_age_seconds")
            require(receipt["binding_sha256"] == t.digest(binding)
                    and receipt["interaction"] == "CONTROLLING_TTY_GRANT_CHALLENGE"
                    and type(receipt["age_milliseconds"]) is int and 0 <= receipt["age_milliseconds"] < 120000
                    and type(receipt["maximum_age_seconds"]) is int and receipt["maximum_age_seconds"] == 120)
        else:
            require(selected["revocation"] is None)


def resolve(db, epoch, current):
    selected = selector(db)
    require(selected["state"] == "active" and selected["epoch"] == epoch, "GRANT_INACTIVE_OR_EPOCH_CHANGED")
    grant = get(db, selected["grant_id"])
    qualification = require_qualification(db, grant["definition"])
    require(qualification["manifest"]["qualification_id"] == grant["qualification_id"], "QUALIFICATION_BINDING_CHANGED")
    continuity(selected["clock"], current)
    continuity(grant["activated"], current)
    require(current["wall"] < grant["expires"], "GRANT_EXPIRED")
    return grant


def check_admission(grant, task):
    expected = grant["admission"]
    current = typed().task_binding(task)
    require(all(current[key] == expected[key] for key in ("task_id", "created_at", "generation", "session_id", "worker"))
            and current["revision"] >= expected["revision"], "ACTIVATED_ADMISSION_CHANGED")


def validate_request(db, request):
    t = typed()
    t.fields(request, "version authorization binding original_task reserved_task evidence_id settlement_id")
    require(type(request["version"]) is int and request["version"] == 2)
    auth = request["authorization"]
    t.fields(auth, "source grant_id epoch definition_sha256")
    require(auth["source"] == "STANDING_GRANT")
    grant = get(db, auth["grant_id"])
    definition = grant["definition"]
    require(type(auth["epoch"]) is int and auth["epoch"] == grant["epoch"] and auth["definition_sha256"] == t.digest(definition))
    b = request["binding"]
    t.fields(b, "schema_version action operation_id attempt_id store_id target publisher payload payload_sha256 prior_assignee_ids task_binding implementation_head logical_key clock create_operation_id")
    require(type(b["schema_version"]) is int and b["schema_version"] == 2 and b["action"] in ACTIONS)
    for key in ("operation_id", "attempt_id", "store_id"):
        t.token(b[key])
    for key in ("evidence_id", "settlement_id"):
        t.token(request[key])
    require(len({b["operation_id"], b["attempt_id"], request["evidence_id"], request["settlement_id"]}) == 4)
    require(b["store_id"] == db.execute("SELECT store_id FROM meta").fetchone()[0]
            and b["implementation_head"] == definition["implementation_head"]
            and b["logical_key"] == logical_key(definition) and b["publisher"] == definition["publisher"])
    validate_clock(b["clock"])
    continuity(grant["activated"], b["clock"])
    require(grant["activated"]["wall"] <= b["clock"]["wall"] < grant["expires"])
    original, reserved = request["original_task"], request["reserved_task"]
    core = t.module("orchestrator-state")
    for task in (original, reserved):
        core.validate_record(task, allow_bound=True)
        require(task["schema_version"] == 3 and task["state"] == "Claimed" and task["kind"] == "intake"
                and task["worker"] is not None and task["transition_intent"] is None
                and task.get("transition_recovery", {}).get("phase") != "pending")
    core.require_assignment_settled(original)
    check_admission(grant, original)
    require(original["repo"] == definition["repository"] and original["scope"] ==
            definition["repository"] + ":intake:" + definition["objective"] + ":" + definition["work_item"])
    require(b["task_binding"] == t.task_binding(reserved))
    target = {"repository": definition["repository"], "repository_id": definition["repository_id"],
              "repository_node_id": definition["repository_node_id"]}
    if b["action"] == "issue-create":
        require(original["tracker_type"] == "none" and original["tracker_number"] == 0
                and b["create_operation_id"] is None and b["prior_assignee_ids"] == [])
        expected_payload = t.canonical(payload(definition))
    else:
        create = t.get(db, "assignment_requests", b["create_operation_id"])
        require(create is not None and create["version"] == 2 and create["binding"]["action"] == "issue-create"
                and create["binding"]["logical_key"] == b["logical_key"])
        settlement = t.get(db, "assignment_settlements", create["settlement_id"])
        require(settlement is not None and settlement["outcome"] == "ISSUE_CREATED_OBSERVED")
        issue = settlement["issue"]
        require(original["tracker_type"] == "issue" and original["tracker_number"] == issue["number"]
                and original["task_id"] == create["original_task"]["task_id"]
                and original["created_at"] == create["original_task"]["created_at"])
        target.update(issue=issue["number"], issue_id=issue["id"], issue_node_id=issue["node_id"])
        t.validate_ids(b["prior_assignee_ids"])
        require(b["publisher"]["id"] in b["prior_assignee_ids"] or len(b["prior_assignee_ids"]) < 10)
        expected_payload = t.canonical({"assignees": [definition["publisher"]["login"]]})
    require(b["target"] == target and b["payload"] == expected_payload
            and b["payload_sha256"] == hashlib.sha256(expected_payload.encode("ascii")).hexdigest())
    marker = {"version": 2, "phase": "pending", "operation_id": b["operation_id"], "attempt_id": b["attempt_id"],
              "store_id": b["store_id"], "intent_sha256": t.digest(auth), "original_sha256": t.digest(original),
              "original_revision": original["revision"], "implementation_head": b["implementation_head"],
              "action": b["action"], "grant_id": auth["grant_id"], "target": target, "logical_key": b["logical_key"]}
    require(reserved == dict(original, revision=original["revision"] + 1, updated_at=reserved["updated_at"], assignment_dispatch=marker))


def validate_issue(issue):
    typed().fields(issue, "id node_id number title body")
    for key in ("id", "number"):
        require(type(issue[key]) is int and 0 < issue[key] <= 2**63 - 1)
    require(type(issue["node_id"]) is str and re.fullmatch(r"[A-Za-z0-9_+/=-]{1,256}", issue["node_id"]) is not None)
    require(type(issue["title"]) is str and type(issue["body"]) is str)


def validate_evidence(request, evidence):
    t = typed()
    t.fields(evidence, "version attempt_id completion result_ids producer diagnostics issue")
    require(type(evidence["version"]) is int and evidence["version"] == 3)
    legacy = dict(evidence, version=2)
    del legacy["issue"]
    t.validate_evidence(dict(request, version=1), legacy)
    if request["binding"]["action"] == "issue-create":
        require(evidence["result_ids"] is None)
    elif request["binding"]["publisher"]["id"] in request["binding"]["prior_assignee_ids"]:
        require(evidence["completion"] == "NOT_SENT")
    if evidence["issue"] is not None:
        require(request["binding"]["action"] == "issue-create" and evidence["completion"] == "CONFIRMED")
        validate_issue(evidence["issue"])
        expected = t.decode(request["binding"]["payload"])
        require(all(evidence["issue"][key] == expected[key] for key in ("title", "body")))


def validate_settlement(request, evidence, settlement):
    t = typed()
    t.fields(settlement, "version attempt_id evidence_sha256 outcome completion satisfaction result_ids issue")
    require(type(settlement["version"]) is int and settlement["version"] == 2
            and settlement["attempt_id"] == request["binding"]["attempt_id"]
            and settlement["evidence_sha256"] == t.digest(evidence))
    if request["binding"]["action"] == "issue-create":
        require(settlement["outcome"] in {"ISSUE_CREATED_OBSERVED", "NOT_SENT"})
        confirmed = settlement["outcome"] == "ISSUE_CREATED_OBSERVED"
        require(settlement["completion"] == evidence["completion"] == ("CONFIRMED" if confirmed else "NOT_SENT")
                and settlement["satisfaction"] is confirmed and settlement["result_ids"] is None)
        require(settlement["issue"] == evidence["issue"] and (settlement["issue"] is not None) == confirmed)
    else:
        require(settlement["issue"] is None and evidence["issue"] is None)
        legacy = dict(settlement, version=1)
        del legacy["issue"]
        t.validate_settlement(dict(request, version=1), evidence, legacy)


def reserve_budget(db, request):
    """Shared transaction; charge attempts, never refund uncertain effects.

    Daily and cumulative risk history spans all grants in this repository.
    Every unresolved launch reserves one possible future UNKNOWN before network.
    """
    t = typed()
    b = request["binding"]
    grant = resolve(db, request["authorization"]["epoch"], b["clock"])
    require(grant["definition"]["grant_id"] == request["authorization"]["grant_id"])
    issues, metadata, risk = 0, 0, 0
    for row in db.execute("SELECT document FROM assignment_requests"):
        old = t.decode(row[0])
        prior = old["binding"]
        terminal = t.get(db, "assignment_settlements", old["settlement_id"])
        if terminal is None and prior["target"].get("repository_id") == b["target"]["repository_id"]:
            require(not (prior["target"].get("issue") == b["target"].get("issue") or
                         prior["action"] == "issue-create"), "TARGET_PENDING")
        if old["version"] != 2:
            continue
        if prior["logical_key"] == b["logical_key"] and prior["action"] == b["action"]:
            raise Invalid("LOGICAL_WORK_ALREADY_ATTEMPTED")
        definition = get(db, old["authorization"]["grant_id"])["definition"]
        if definition["repository_id"] != grant["definition"]["repository_id"]:
            continue
        receipt = t.get(db, "assignment_evidence", old["evidence_id"])
        risk += int(terminal is None or (receipt is not None and receipt["completion"] == "UNKNOWN"))
        # Only durable synchronous NOT_SENT evidence AND terminal settlement
        # release remote quota. Pending/marker-only and UNKNOWN remain charged;
        # preserve the rows and dedup history rather than deleting an attempt.
        proven_unlaunched = (receipt is not None and receipt["completion"] == "NOT_SENT"
                             and terminal is not None and terminal.get("completion") == "NOT_SENT"
                             and terminal.get("outcome") in {"NOT_SENT", "SATISFIED_NO_POST"})
        # Shared repository daily ceiling prevents renewals/objective hopping.
        if day(prior["clock"]) == day(b["clock"]) and not proven_unlaunched:
            metadata += 1
            issues += int(prior["action"] == "issue-create")
    # Already-satisfied additive requests cannot launch: dispatch must retain
    # NOT_SENT. They need evidence/core acknowledgement but no remote capacity.
    no_post = (b["action"] == "assignees-add" and b["publisher"]["id"] in b["prior_assignee_ids"])
    require(no_post or (metadata < 20 and (b["action"] != "issue-create" or issues < 5)), "DAILY_BUDGET_EXHAUSTED")
    require(no_post or risk < 3, "UNRESOLVED_BUDGET_EXHAUSTED")
    selected = selector(db)
    selected["clock"] = copy.deepcopy(b["clock"])
    put_selector(db, selected)
