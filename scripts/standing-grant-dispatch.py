#!/usr/bin/env python3
"""Typed synthetic issue-create -> durable intake binding -> additive self-assignment.

The one synchronous effect gate spans the final authorization check, network,
evidence, settlement and core acknowledgement. No TTY is used by runtime.
"""

import argparse
import contextlib
import copy
import hashlib
import importlib.util
import os
import re
import time
import uuid
from pathlib import Path


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("ADAPTER_UNAVAILABLE")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def modules():
    source = Path(__file__).resolve().parents[1]
    adapter = load("grant_assignment_adapter", source / "scripts/assignment-dispatch.py")
    publisher = load("grant_terminal", source / "scripts/publish-github-assignment.py")
    grant = load("grant_policy", source / ".agents/skills/workspace-orchestrator/bin/standing-grant.py")
    return adapter, publisher, grant


def policy_digest():
    return hashlib.sha256((Path(__file__).resolve().parents[1] / "docs/SCOPED-AUTONOMY.md").read_bytes()).hexdigest()


def require_endpoint_qualification(store, db, grant, definition):
    """Controller-selected, human-installed offline qualification; no caller selector."""
    record = grant.require_qualification(db, definition)
    if "installation" in record:
        grant.require(store.physical_binding() == {key: value for key, value in record["installation"].items() if key != "new_store"},
                      "STORE_IDENTITY_CHANGED")
    controller = load("qualification_artifacts", Path(__file__).with_name("control-standing-grant.py"))
    controller.verify_artifacts(store, grant, record["manifest"], expected_report=record["report"])
    return record


def make_store(args, adapter):
    p, c, j, t, d, transport = adapter.modules()
    return adapter.Store(args, p, c, j, t, d), transport


def gate_path(store, identity):
    store.typed.token(identity)
    return store.root / "locks" / ("standing-effect-" + identity + ".lock")


def acquire_gate(store, identity):
    """Coordinator held. Persistent directory, never stale-owner auto-takeover."""
    token = uuid.uuid4().hex
    store.core.acquire_dir(gate_path(store, identity), {"token": token, "pid": os.getpid()})
    return token


def release_gate(store, identity, token):
    # Cooperative coordinator contention must not strand a live producer's gate
    # while revoke waits for it. Retry only acquiring the coordinator, bounded;
    # never change another gate's ownership or interpret owner death as release.
    until = time.monotonic() + 5
    while True:
        try:
            with store.locked():
                store.core.release_dir(gate_path(store, identity), token)
            return
        except store.core.BusyError:
            if time.monotonic() >= until:
                raise
            time.sleep(0.01)


@contextlib.contextmanager
def effect_gate(store, identity):
    with store.locked():
        token = acquire_gate(store, identity)
    try:
        yield
    finally:
        release_gate(store, identity, token)


def pending_targets(store, db, request):
    """Core marker fences survive even a failed SQLite reservation commit."""
    target = request["binding"]["target"]
    for task in store.core.command_list(store.root, allow_bound=True):
        marker = task.get("assignment_dispatch", {})
        if marker.get("phase") != "pending":
            continue
        if marker.get("operation_id") == request["binding"]["operation_id"]:
            continue
        if marker["version"] == 2:
            other = marker["target"]
            # No journal row means no durable budget reservation is provable.
            # Conservatively freeze this repository rather than create new risk
            # under a different objective/grant after a marker-only failure.
            if store.typed.get(db, "assignment_requests", marker["operation_id"]) is None:
                store.preflight.require(other["repository_id"] != target["repository_id"], "TARGET_PENDING")
            store.preflight.require(not (other["repository_id"] == target["repository_id"] and
                (other.get("issue") == target.get("issue") or marker["action"] == "issue-create"
                 or marker["logical_key"] == request["binding"]["logical_key"])), "TARGET_PENDING")
        else:
            store.preflight.require(not (task["repo"] == target["repository"] and
                task["tracker_number"] == target.get("issue")), "TARGET_PENDING")


def resolve(store, db, grant, epoch):
    current = grant.clock()
    try:
        return grant.resolve(db, epoch, current), current
    except grant.Invalid:
        # Continuity uncertainty is durable; renewal cannot silently erase it.
        selected = grant.selector(db)
        if selected["state"] == "active" and selected["epoch"] == epoch:
            selected["state"] = "paused"
            with db:
                db.execute("BEGIN IMMEDIATE")
                grant.put_selector(db, selected)
            store.durable(db)
        raise


def admitted(store, task, definition):
    t = store.typed
    t.require(task["kind"] == "intake" and task["state"] == "Claimed")
    t.require(task["repo"] == definition["repository"] and task["scope"] == definition["repository"] +
              ":intake:" + definition["objective"] + ":" + definition["work_item"])
    store.ownership(task)


def creation_for_task(store, db, task, logical):
    found = []
    for row in db.execute("SELECT document FROM assignment_requests"):
        request = store.typed.decode(row[0])
        if (request["version"] == 2 and request["binding"]["action"] == "issue-create"
                and request["binding"]["logical_key"] == logical
                and request["original_task"]["task_id"] == task["task_id"]
                and request["original_task"]["created_at"] == task["created_at"]):
            terminal = store.typed.get(db, "assignment_settlements", request["settlement_id"])
            store.typed.require(terminal is not None and terminal["outcome"] == "ISSUE_CREATED_OBSERVED"
                                and task["tracker_type"] == "issue" and task["tracker_number"] == terminal["issue"]["number"])
            found.append((request, terminal["issue"]))
    store.typed.require(len(found) == 1)
    return found[0]


def build(store, grant, definition, selected, task, action, prior, current, created):
    t = store.typed
    auth = {"source": "STANDING_GRANT", "grant_id": definition["grant_id"], "epoch": selected["epoch"],
            "definition_sha256": t.digest(definition)}
    target = {"repository": definition["repository"], "repository_id": definition["repository_id"],
              "repository_node_id": definition["repository_node_id"]}
    if action == "assignees-add":
        target.update(issue=created[1]["number"], issue_id=created[1]["id"], issue_node_id=created[1]["node_id"])
    payload = t.canonical(grant.payload(definition) if action == "issue-create" else {"assignees": [definition["publisher"]["login"]]})
    b = {"schema_version": 2, "action": action, "operation_id": uuid.uuid4().hex, "attempt_id": uuid.uuid4().hex,
         "store_id": selected["store_id"], "target": target, "publisher": definition["publisher"],
         "payload": payload, "payload_sha256": hashlib.sha256(payload.encode("ascii")).hexdigest(),
         "prior_assignee_ids": prior, "task_binding": None, "implementation_head": definition["implementation_head"],
         "logical_key": grant.logical_key(definition), "clock": current,
         "create_operation_id": created[0]["binding"]["operation_id"] if created is not None else None}
    marker = {"version": 2, "phase": "pending", "operation_id": b["operation_id"], "attempt_id": b["attempt_id"],
              "store_id": b["store_id"], "intent_sha256": t.digest(auth), "original_sha256": t.digest(task),
              "original_revision": task["revision"], "implementation_head": b["implementation_head"],
              "action": action, "grant_id": auth["grant_id"], "target": target, "logical_key": b["logical_key"]}
    reserved = dict(copy.deepcopy(task), revision=task["revision"] + 1, updated_at=store.core.now(), assignment_dispatch=marker)
    b["task_binding"] = t.task_binding(reserved)
    return {"version": 2, "authorization": auth, "binding": b, "original_task": task, "reserved_task": reserved,
            "evidence_id": uuid.uuid4().hex, "settlement_id": uuid.uuid4().hex}


def guard(store, db, request, *, original=False, recovering=False, closed_receipt=None):
    store.guard(db, request, original=original, recovery=recovering, closed_receipt=closed_receipt, standing=True)


def finish(store, request, receipt, outcome, *, recovering=False, observed_ids=None):
    adapter, _, _ = modules()
    return adapter._settle(store, request, receipt, outcome, observed_ids, recovery=recovering, standing=True)


def dispatch(args):
    token = os.environ.pop("GH_TOKEN", None)
    adapter, _, grant = modules()
    adapter.require(token is not None and not os.environ.get("GITHUB_TOKEN"), "EXPLICIT_GH_TOKEN_REQUIRED")
    store, transport = make_store(args, adapter)
    adapter.implementation_head(args.implementation_head)
    with store.locked() as db:
        selected, _ = resolve(store, db, grant, args.expected_epoch)
        definition = selected["definition"]
        adapter.require(definition["implementation_head"] == args.implementation_head
                        and definition["policy_sha256"] == policy_digest(), "IMPLEMENTATION_HEAD_CHANGED")
        require_endpoint_qualification(store, db, grant, definition)
        task = store.task()
        store.core.require_assignment_settled(task)
        admitted(store, task, definition)
        adapter.require(task["revision"] <= store.core.MAX_GENERATION - 2, "REVISION_LIMIT")
        grant.check_admission(selected, task)
        created = creation_for_task(store, db, task, grant.logical_key(definition)) if args.action == "assignees-add" else None
        selected["store_id"] = db.execute("SELECT store_id FROM meta").fetchone()[0]
    number = created[1]["number"] if created is not None else None
    observed = grant.observed(definition, created[1] if created else None)
    # Holding only the per-grant gate permits revoke-requested to commit promptly.
    with effect_gate(store, definition["grant_id"]):
        client = transport.Transport(definition["repository"], number, token)
        token = None
        try:
            prior = []
            if args.action == "issue-create":
                client.fresh_repository(observed)
                for issue in client.complete_issues():
                    adapter.require(issue["title"] != definition["title"] and
                                    grant.logical_key(definition) not in (issue["body"] or ""), "REMOTE_DUPLICATE_OR_CORRELATION")
            else:
                prior = client.fresh(observed)
            adapter.implementation_head(args.implementation_head)
            with store.locked() as db:
                require_endpoint_qualification(store, db, grant, definition)
                current_grant, current = resolve(store, db, grant, args.expected_epoch)
                adapter.require(current_grant["definition"] == definition and store.task() == task, "SELECTED_ROWS_CHANGED")
                admitted(store, task, definition)
                request = build(store, grant, definition, selected, task, args.action, prior, current, created)
                guard(store, db, request, original=True)
                pending_targets(store, db, request)
                store.typed.preflight(db, request)
                store.core.assignment_reserve(store.root, task, request["reserved_task"])
                store.typed.reserve(db, request)
                store.durable(db)
                guard(store, db, request)
            receipt = {"version": 3, "attempt_id": request["binding"]["attempt_id"], "completion": "NOT_SENT",
                       "result_ids": None, "producer": "SYNCHRONOUS_TRANSPORT_CLOSED", "diagnostics": [], "issue": None}
            outcome = None
            # Last selector check is inside the effect gate. A revoke request that
            # follows this check waits for this producer before acknowledging.
            with store.locked() as db:
                try:
                    require_endpoint_qualification(store, db, grant, definition)
                    resolve(store, db, grant, args.expected_epoch)
                except grant.Invalid:
                    outcome = "NOT_SENT"
            if outcome is None and args.action == "assignees-add" and definition["publisher"]["id"] in prior:
                receipt["result_ids"], outcome = prior, "SATISFIED_NO_POST"
            if outcome is None:
                receipt["completion"] = "UNKNOWN"
                try:
                    if args.action == "issue-create":
                        created_issue = client.create(grant.payload(definition), observed)
                        receipt["completion"] = "CONFIRMED"
                        receipt["issue"] = created_issue
                        client.observe_created(created_issue, grant.payload(definition), observed)
                        outcome = "ISSUE_CREATED_OBSERVED"
                    else:
                        client.assign(observed)
                        receipt["completion"] = "CONFIRMED"
                        receipt["result_ids"] = client.issue(observed)
                        actual, _ = transport.actual_result(prior, receipt["result_ids"], definition["publisher"]["id"])
                        outcome = "ASSIGNMENT_CONFIRMED_OBSERVED" if actual == "PRESERVED_ACTOR_PRESENT" else actual
                except Exception as exc:
                    receipt["diagnostics"] = [store.typed.diagnostic("POST" if receipt["completion"] == "UNKNOWN" else "OBSERVATION",
                        exc, getattr(exc, "http_status", client.http_status))]
            client.close()
            return finish(store, request, receipt, outcome)
        finally:
            client.close()


def recover(args):
    """Durable/GET-only settlement after expiry or revocation, never another POST."""
    token = os.environ.pop("GH_TOKEN", None)
    adapter, _, grant = modules()
    adapter.require(not os.environ.get("GITHUB_TOKEN"), "EXPLICIT_GH_TOKEN_REQUIRED")
    store, transport = make_store(args, adapter)
    adapter.implementation_head(args.implementation_head)
    with store.locked() as db:
        adapter.require(store.task()["revision"] == args.expected_revision, "REVISION_MISMATCH")
        request = store.typed.get(db, "assignment_requests", args.operation_id)
        adapter.require(request is not None and request["version"] == 2, "RESERVATION_NOT_FOUND")
        adapter.require(request["binding"]["implementation_head"] == args.implementation_head, "IMPLEMENTATION_HEAD_CHANGED")
        guard(store, db, request, recovering=True)
        receipt = store.typed.get(db, "assignment_evidence", request["evidence_id"])
        terminal = store.typed.get(db, "assignment_settlements", request["settlement_id"])
        adapter.require(receipt is not None and receipt["completion"] != "UNKNOWN", "PRODUCER_TERMINATION_PROOF_UNSUPPORTED")
        definition = grant.get(db, request["authorization"]["grant_id"])["definition"]
    # Acquiring the same persistent gate refuses a crash owner, even with evidence.
    with effect_gate(store, request["authorization"]["grant_id"]):
        if terminal is not None:
            return finish(store, request, receipt, terminal["outcome"], recovering=True, observed_ids=terminal["result_ids"])
        observed_ids = None
        if receipt["completion"] == "NOT_SENT":
            outcome = "NOT_SENT" if receipt["result_ids"] is None else "SATISFIED_NO_POST"
        elif receipt["issue"] is not None:
            adapter.require(token is not None, "EXPLICIT_GH_TOKEN_REQUIRED")
            client = transport.Transport(definition["repository"], receipt["issue"]["number"], token)
            try:
                client.fresh_repository(grant.observed(definition))
                client.observe_created(receipt["issue"], grant.payload(definition), grant.observed(definition))
            finally:
                client.close()
            outcome = "ISSUE_CREATED_OBSERVED"
        elif receipt["result_ids"] is not None:
            actual, _ = transport.actual_result(request["binding"]["prior_assignee_ids"], receipt["result_ids"], request["binding"]["publisher"]["id"])
            outcome = "ASSIGNMENT_CONFIRMED_OBSERVED" if actual == "PRESERVED_ACTOR_PRESENT" else actual
        elif request["binding"]["action"] == "assignees-add":
            adapter.require(token is not None, "EXPLICIT_GH_TOKEN_REQUIRED")
            target = request["binding"]["target"]
            observed = grant.observed(definition, {"id": target["issue_id"], "node_id": target["issue_node_id"]})
            client = transport.Transport(definition["repository"], target["issue"], token)
            try:
                observed_ids = client.fresh(observed, admission=False)
            finally:
                client.close()
            actual, _ = transport.actual_result(request["binding"]["prior_assignee_ids"], observed_ids, request["binding"]["publisher"]["id"])
            outcome = "ASSIGNMENT_CONFIRMED_OBSERVED" if actual == "PRESERVED_ACTOR_PRESENT" else actual
        else:
            outcome = None
        return finish(store, request, receipt, outcome, recovering=True, observed_ids=observed_ids)


def complete(args):
    """Local completion only; no active grant or credential required."""
    os.environ.pop("GH_TOKEN", None)
    adapter, _, _ = modules()
    store, _ = make_store(args, adapter)
    adapter.implementation_head(args.implementation_head)
    with store.locked() as db:
        task = store.task()
        adapter.require(task["revision"] == args.expected_revision, "REVISION_MISMATCH")
        worker = task["worker"]
        adapter.require(worker is not None and worker["worker_id"] == args.expected_worker_id
                        and worker["session_id"] == args.expected_session_id and worker["generation"] == args.expected_generation,
                        "OWNERSHIP_CHANGED")
        adapter.require(task.get("assignment_dispatch", {}).get("implementation_head") == args.implementation_head,
                        "IMPLEMENTATION_HEAD_CHANGED")
        if task["transition_intent"] is None:
            store.ownership(task)
        final = store.core.complete_intake(store.root, task, store.journal, db)
        return {"status": "INTAKE_COMPLETED", "reservation": "settled", "revision": final["revision"]}


def arguments(*, controller=False):
    adapter, _, _ = modules()

    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise adapter.Refusal("INVALID_ARGUMENTS")

    class Once(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            adapter.require(getattr(namespace, self.dest, None) is None, "DUPLICATE_ARGUMENT")
            setattr(namespace, self.dest, values)

    parser = Parser(allow_abbrev=False)
    parser.add_argument("action", choices=("activate", "revoke", "install-qualification", "revoke-qualification") if controller else ("issue-create", "assignees-add", "settle", "complete"))
    for key in ("authority-root", "invoking-root", "implementation-head", "expected-epoch"):
        parser.add_argument("--" + key, required=True, action=Once)
    if controller:
        parser.add_argument("--proposal", action=Once)
    else:
        parser.add_argument("--operation-id", action=Once)
    for key in ("task-id", "expected-revision", "expected-worker-id", "expected-session-id", "expected-generation"):
        parser.add_argument("--" + key, action=Once)
    args = parser.parse_args()
    for key in ("task_id", "expected_revision", "expected_worker_id", "expected_session_id", "expected_generation"):
        adapter.require(controller and args.action in {"install-qualification", "revoke-qualification"}
                        or getattr(args, key) is not None,
                        "INVALID_ARGUMENTS")
    for key, pattern in (("task_id", r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}"),
                         ("expected_session_id", r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"),
                         ("expected_worker_id", r"[0-9a-f]{32}"), ("implementation_head", r"[0-9a-f]{40}")):
        value = getattr(args, key)
        if value is not None:
            adapter.require(re.fullmatch(pattern, value) is not None, "INVALID_ARGUMENTS")
    for key in ("expected_epoch", "expected_revision", "expected_generation"):
        value = getattr(args, key)
        if value is None:
            continue
        adapter.require(re.fullmatch(r"0|[1-9][0-9]{0,18}", value) is not None and int(value) <= 2**63 - 1, "INVALID_ARGUMENTS")
        setattr(args, key, int(value))
    if controller:
        adapter.require((args.action in {"activate", "install-qualification"}) == (args.proposal is not None), "INVALID_ARGUMENTS")
    else:
        adapter.require((args.action == "settle") == (args.operation_id is not None), "INVALID_ARGUMENTS")
        if args.operation_id is not None:
            adapter.require(re.fullmatch(r"[0-9a-f]{32}", args.operation_id) is not None, "INVALID_ARGUMENTS")
    return args
