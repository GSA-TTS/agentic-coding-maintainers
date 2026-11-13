#!/usr/bin/env python3
"""Assignment-only trusted runner adapter. All interactions/network outside locks.

Cooperative, local fences; neither GitHub CAS nor hostile same-UID isolation.
There is exactly one launch site. Recovery never reaches it. Unknown arbitration
refuses without a qualified containment/termination proof, never ps/boot/booleans.
"""

import argparse
import contextlib
import copy
import hashlib
import importlib.util
import os
import re
import socket
import sqlite3
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

# Only settlement lock acquisition retries; never transport or durability work.
SETTLEMENT_LOCK_ATTEMPTS = 21
SETTLEMENT_LOCK_DELAY = 0.1


class Refusal(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise Refusal(reason)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Refusal("ADAPTER_UNAVAILABLE")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def modules():
    source = Path(__file__).resolve().parents[1]
    installed = source / ".agents/skills/workspace-orchestrator/bin"
    return (load("dispatch_preflight", source / "scripts/check-native-ownership.py"),
            load("dispatch_core", installed / "orchestrator-state.py"),
            load("dispatch_journal", installed / "monitor-journal.py"),
            load("dispatch_typed", installed / "assignment-journal.py"),
            load("dispatch_durability", source / "scripts/journal-claim-intent.py"),
            load("dispatch_transport", source / "scripts/github-assignment-transport.py"))


def implementation_head(expected):
    """Raw-byte whole-checkout verification; no configured filters/hooks/fetch.

    Reuse the core verifier with a private module's credential-free Git probe.
    Inspect ignored/untracked files too: a path-limited status could miss an
    extra imported module, and status itself may invoke checkout clean filters.
    """
    source = Path(__file__).resolve().parents[1]
    core = load("dispatch_clean_checkout", source / ".agents/skills/workspace-orchestrator/bin/orchestrator-state.py")

    def git(worktree, *args):
        return subprocess.run(["/usr/bin/git", "-c", "protocol.allow=never", "-c", "core.fsmonitor=false",
                               "-c", "core.untrackedCache=false", "-c", "core.hooksPath=" + os.devnull,
                               "-C", str(worktree), *args],
                                env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                                     "GIT_NO_LAZY_FETCH": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1"},
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                close_fds=True, timeout=5, check=False, text=True)

    head = git(source, "rev-parse", "HEAD")
    require(head.returncode == 0 and head.stdout.strip() == expected, "IMPLEMENTATION_HEAD_CHANGED")
    setattr(core, "git_probe", git)
    core.verify_clean_checkout(str(source))
    return expected


class Store:
    def __init__(self, args, preflight, core, journal, typed, durability):
        self.args, self.preflight, self.core = args, preflight, core
        self.journal, self.typed, self.durability = journal, typed, durability
        self.root = Path(args.authority_root) / ".orchestrator"
        self.monitor = self.root / "monitor"
        self.identity = None
        self.directory_identity = None

    @contextlib.contextmanager
    def directories(self, *, prepare=False):
        p = self.preflight
        with contextlib.ExitStack() as stack:
            authority = p.physical_root(self.args.authority_root, stack)
            invoking = p.physical_root(self.args.invoking_root, stack)
            require((os.fstat(authority).st_dev, os.fstat(authority).st_ino)
                    == (os.fstat(invoking).st_dev, os.fstat(invoking).st_ino), "ROOT_MISMATCH")
            store = p.directory(authority, ".orchestrator", stack, private=True)
            locks = p.directory(store, "locks", stack, private=True)
            if prepare:
                # Empty infrastructure only: no store identity or authority.
                with self.core.CoordinatorLock(self.root):
                    try:
                        os.mkdir("monitor", mode=0o700, dir_fd=store)
                        os.fsync(store)
                    except FileExistsError:
                        pass
            monitor = p.directory(store, "monitor", stack, private=True)
            identities = tuple((os.fstat(fd).st_dev, os.fstat(fd).st_ino) for fd in (authority, store, locks, monitor))
            yield identities

    def physical_binding(self):
        with self.directories() as identities:
            require(identities == self.directory_identity, "STORE_IDENTITY_CHANGED")
        return {"authority_root": self.args.authority_root, "invoking_root": self.args.invoking_root,
                "directories": [list(pair) for pair in identities]}

    @contextlib.contextmanager
    def locked(self) -> Iterator[sqlite3.Connection]:
        with self._locked() as db:
            if db is None:
                raise Refusal("EXISTING_JOURNAL_REQUIRED")
            yield db

    @contextlib.contextmanager
    def qualification_locked(self, *, initial_store_id: str | None = None) -> Iterator[sqlite3.Connection | None]:
        """Controller installation only; missing stores remain absent until approval."""
        with self._locked(qualification=True, initial_store_id=initial_store_id) as db:
            yield db

    @contextlib.contextmanager
    def _locked(self, *, qualification: bool = False, initial_store_id: str | None = None) -> Iterator[sqlite3.Connection | None]:
        with self.directories(prepare=qualification and self.directory_identity is None) as directories:
            if self.directory_identity is None:
                self.directory_identity = directories
            require(directories == self.directory_identity, "STORE_IDENTITY_CHANGED")
            with self.core.CoordinatorLock(self.root):
                self.physical_binding()
                exists = self.journal.check_path(self.monitor).is_file()
                if qualification and not exists:
                    # Orphan sidecars are human recovery state, never fresh setup.
                    require(not any(self.monitor.glob("history.sqlite3-*")), "JOURNAL_RECOVERY_REQUIRED")
                if qualification and initial_store_id is None and not exists:
                    require(self.identity is None, "STORE_IDENTITY_CHANGED")
                    yield None
                    self.physical_binding()
                    require(not self.journal.check_path(self.monitor).exists(), "STORE_IDENTITY_CHANGED")
                    return
                require(exists or qualification and initial_store_id is not None, "EXISTING_JOURNAL_REQUIRED")
                require(initial_store_id is None or not exists and self.identity is None, "STORE_IDENTITY_CHANGED")
                db = self.journal.open_store(self.monitor, writable=True, initial_store_id=initial_store_id)
                try:
                    identity = (directories, db.file_identity, db.execute("SELECT store_id FROM meta").fetchone()[0])
                    if self.identity is None:
                        self.identity = identity
                    require(identity == self.identity, "STORE_IDENTITY_CHANGED")
                    yield db
                    self.physical_binding()
                    selected = self.journal.check_path(self.monitor).lstat()
                    require(db.file_identity == (selected.st_dev, selected.st_ino), "STORE_IDENTITY_CHANGED")
                finally:
                    db.close()

    def task(self):
        with contextlib.ExitStack() as stack:
            p = self.preflight
            authority = p.physical_root(self.args.authority_root, stack)
            store = p.directory(authority, ".orchestrator", stack, private=True)
            retained = []
            task = p.read_selected(store, ["tasks", self.args.task_id, "task.json"], stack, retained)
            self.core.validate_record(task, self.args.task_id, allow_bound=True)
            require(all(p.fingerprint(os.fstat(fd)) == before for fd, before in retained), "TASK_CHANGED")
            return task

    def ownership(self, task, *, active=True, expected_revision=None):
        c, args = self.core, self.args
        if expected_revision is None:
            expected_revision = args.expected_revision
        c.verify_reservations(self.root, task)
        require(task["schema_version"] == 3 and task["state"] in c.ACTIVE
                and task["transition_intent"] is None and task.get("transition_recovery", {}).get("phase") != "pending",
                "OWNERSHIP_UNVERIFIED")
        worker = task["worker"]
        if worker is None or worker["hostname"] != socket.gethostname():
            raise Refusal("WORKER_HOST_CHANGED")
        require((task["leases"]["implementation_lane"] is not None) == (task["state"] == "Implementing")
                and (task["state"] != "Implementing" or task["kind"] == "implementation"), "LANE_CHANGED")
        # Core semantic validation plus no-symlink, private, single-link physical
        # selection of EVERY lease. No old DB mtime is carried over network calls.
        with contextlib.ExitStack() as stack:
            p = self.preflight
            authority = p.physical_root(args.authority_root, stack)
            root = p.directory(authority, ".orchestrator", stack, private=True)
            paths = [("scopes", task["scope_key"], {"schema_version": 2, "task_id": task["task_id"],
                      "scope": task["scope"], "token": task["leases"]["scope_token"]}),
                     ("slots", str(task["leases"]["global_slot"]), worker)]
            if task["leases"]["implementation_lane"] is not None:
                paths.append(("implementation", str(task["leases"]["implementation_lane"]), worker))
            retained = []
            for group, key, expected in paths:
                require(p.read_selected(root, [group, key + ".lock", "owner.json"], stack, retained) == expected,
                        "LEASE_CHANGED")
            require(all(p.fingerprint(os.fstat(fd)) == before for fd, before in retained), "LEASE_CHANGED")
        require(task["revision"] == expected_revision
                and worker["worker_id"] == args.expected_worker_id
                and worker["session_id"] == args.expected_session_id
                and worker["generation"] == args.expected_generation, "OWNERSHIP_CHANGED")
        if active:
            require(c.process_identity(worker["pid"], environment={"PATH": "/usr/bin:/bin"})
                    == ("alive", worker["process_start"]), "WORKER_NOT_ACTIVE")

    def intent(self, db):
        version = db.execute("SELECT version FROM meta").fetchone()[0]
        require(version in {5, 6, 7}, "IDENTITY_BOUND_INTENT_REQUIRED")
        row = db.execute("SELECT request,request_sha256 FROM claim_intents WHERE operation_id=?",
                         (self.args.intent_operation_id,)).fetchone()
        require(row is not None, "INTENT_NOT_FOUND")
        intent = self.journal.decode_intent(row[0])
        self.journal.validate_claim_intent(intent)
        require(intent["schema_version"] == 2 and row[1] == self.typed.digest(intent), "INTENT_CHANGED")
        return intent

    def guard(self, db, request, *, original=False, recovery=False, closed_receipt=None, standing=False):
        """One guard sequence, retaining each entrypoint's refusal vocabulary.

        The compatibility branch changes only refusals; request/evidence version
        validation remains the typed journal's responsibility.
        """
        self.journal.validate_store(db)
        self.typed.validate_request(db, request)
        if closed_receipt is not None:
            # Private synchronous dispatch continuation only, after client.close().
            # This is not recovery authority: no CLI/file/worker-death inference.
            self._guard_require(not original and not recovery, "RECOVERY_BINDING_INVALID", standing)
            self.typed.validate_evidence(request, closed_receipt)
        if recovery:
            self._guard_require(not original, "RECOVERY_BINDING_INVALID", standing)
            receipt = self.typed.get(db, "assignment_evidence", request["evidence_id"])
            self._guard_require(receipt is not None and receipt["completion"] in {"CONFIRMED", "NOT_SENT"},
                                "PRODUCER_TERMINATION_PROOF_UNSUPPORTED", standing)
            self.typed.validate_evidence(request, receipt)
        task = self.task()
        expected = request["original_task" if original else "reserved_task"]
        self._guard_require(task == expected, "TASK_CHANGED", standing)
        # Reserve advances only revision; original command's counters stay explicit.
        self.ownership(task, active=not recovery and closed_receipt is None, expected_revision=expected["revision"])
        if not original:
            self._guard_require(self.typed.get(db, "assignment_requests", request["binding"]["operation_id"]) == request,
                                "RESERVATION_REQUEST_CHANGED", standing)

    def _guard_require(self, condition, reason, standing):
        if standing:
            self.typed.require(condition)
        else:
            require(condition, reason)

    def durable(self, db):
        self.durability.durable(self.journal, db, self.monitor)


def build(store, intent, task, ids, head):
    t = store.typed
    operation, attempt = uuid.uuid4().hex, uuid.uuid4().hex
    reserved = copy.deepcopy(task)
    reserved.update(revision=task["revision"] + 1, updated_at=store.core.now(), assignment_dispatch={
        "version": 1, "phase": "pending", "operation_id": operation, "attempt_id": attempt,
        "store_id": intent["store_id"], "intent_sha256": t.digest(intent), "original_sha256": t.digest(task),
        "original_revision": task["revision"], "implementation_head": head})
    observed, claim = intent["identity_observation"], intent["claim"]
    payload = t.canonical({"assignees": [observed["actor_login"]]})
    binding = {"schema_version": 1, "action": "add-assignee", "intent_operation_id": intent["operation_id"],
               "operation_id": operation, "attempt_id": attempt, "intent_sha256": t.digest(intent),
               "store_id": intent["store_id"], "target": {"repository": claim["repo"], "issue": claim["issue"],
                   **{key: observed[key] for key in ("repository_id", "repository_node_id", "issue_id", "issue_node_id")}},
               "publisher": {"id": observed["actor_id"], "node_id": observed["actor_node_id"], "login": observed["actor_login"]},
               "payload": payload, "payload_sha256": hashlib.sha256(payload.encode("ascii")).hexdigest(),
               "prior_assignee_ids": ids, "task_binding": t.task_binding(reserved), "implementation_head": head}
    return {"version": 1, "binding": binding, "original_task": task, "reserved_task": reserved,
            "approval": None, "evidence_id": uuid.uuid4().hex, "settlement_id": uuid.uuid4().hex}


def evidence(request, completion, result_ids, diagnostics):
    return {"version": 2, "attempt_id": request["binding"]["attempt_id"], "completion": completion,
             "result_ids": result_ids, "producer": "SYNCHRONOUS_TRANSPORT_CLOSED", "diagnostics": diagnostics}


def standing_target_fence(store, db, repository_id, issue):
    """Manual assignment cannot cross a standing create's repository-wide fence."""
    if db.execute("SELECT version FROM meta").fetchone()[0] == 7:
        for row in db.execute("SELECT document FROM assignment_requests"):
            request = store.typed.decode(row[0])
            binding = request["binding"]
            if request["version"] == 2 and store.typed.get(db, "assignment_settlements", request["settlement_id"]) is None:
                require(not (binding["target"]["repository_id"] == repository_id and
                             (binding["action"] == "issue-create" or binding["target"].get("issue") == issue)), "TARGET_PENDING")
    for other in store.core.command_list(store.root, allow_bound=True):
        marker = other.get("assignment_dispatch", {})
        if marker.get("version") == 2 and marker.get("phase") == "pending":
            require(not (marker["target"]["repository_id"] == repository_id and
                         (marker["action"] == "issue-create" or marker["target"].get("issue") == issue)), "TARGET_PENDING")


@contextlib.contextmanager
def settlement_lock(store):
    # Catch contention only while entering: errors from guards/writes/exit must
    # propagate without retry. Each attempt reselects physical roots and store.
    with contextlib.ExitStack() as stack:
        for attempt in range(SETTLEMENT_LOCK_ATTEMPTS):
            try:
                db = stack.enter_context(store.locked())
            except store.core.BusyError:
                if attempt + 1 == SETTLEMENT_LOCK_ATTEMPTS:
                    raise
                time.sleep(SETTLEMENT_LOCK_DELAY)
                continue
            yield db
            return


def settle(store, request, receipt, outcome, result_ids=None, *, recovery=False):
    return _settle(store, request, receipt, outcome, result_ids, recovery=recovery, standing=False)


def _settle(store, request, receipt, outcome, result_ids=None, *, recovery=False, standing=False):
    """Retain the closed producer's result in memory while acquiring coordinator.

    Manual and standing wrappers select only their historical compatibility
    branch. Both follow this fixed ordering and the same core release reproof.
    Exhaustion/crash before evidence durability can still lose that result. Never
    retry a guard, write, barrier or release failure, nor infer durability from it.
    """
    t = store.typed
    with settlement_lock(store) as db:
        store.guard(db, request, recovery=recovery, closed_receipt=None if recovery else receipt, standing=standing)
        if recovery:
            store._guard_require(t.get(db, "assignment_evidence", request["evidence_id"]) == receipt,
                                 "RECOVERY_EVIDENCE_CHANGED", standing)
        t.fill(db, "assignment_evidence", request["evidence_id"], receipt)
        store.durable(db)
        if outcome is None:
            if standing:
                return {"status": "UNKNOWN", "completion": receipt["completion"], "reservation": "pending"}
            return {"status": "UNKNOWN", "reservation": "pending", "completion": receipt["completion"],
                    **({"diagnostics": receipt["diagnostics"]} if receipt["version"] == 2 else {})}
        completion, satisfaction = (("CONFIRMED", True) if standing and outcome == "ISSUE_CREATED_OBSERVED" else t.OUTCOMES[outcome])
        terminal = {"version": 2 if standing else 1, "attempt_id": request["binding"]["attempt_id"],
                    "evidence_sha256": t.digest(receipt), "outcome": outcome,
                    "completion": completion, "satisfaction": satisfaction,
                    "result_ids": receipt["result_ids"] if result_ids is None else result_ids}
        if standing:
            terminal["issue"] = receipt["issue"]
        t.fill(db, "assignment_settlements", request["settlement_id"], terminal)
        store.durable(db)
        store.guard(db, request, recovery=recovery, closed_receipt=None if recovery else receipt, standing=standing)
        final = store.core.assignment_release(store.root, request["reserved_task"])
        if standing:
            return {"status": outcome, "completion": completion, "reservation": "settled", "revision": final["revision"]}
        return {"status": outcome, "reservation": "settled", "completion": completion,
                "satisfaction": satisfaction,
                **({"diagnostics": receipt["diagnostics"]} if receipt["version"] == 2 else {})}


def dispatch(args, publisher):
    # Remove the dispatch credential before module/probe work. Every subprocess
    # additionally receives an explicit environment allowlist, including ps.
    token = os.environ.pop("GH_TOKEN", None)
    require(token is not None and not os.environ.get("GITHUB_TOKEN"), "EXPLICIT_GH_TOKEN_REQUIRED")
    p, c, j, t, durability, transport = modules()
    store = Store(args, p, c, j, t, durability)
    head = implementation_head(args.implementation_head)
    with store.locked() as db:
        task = store.task()
        c.require_assignment_settled(task)
        store.ownership(task)
        require(task["revision"] <= c.MAX_GENERATION - 2, "REVISION_LIMIT")
        intent = store.intent(db)
        standing_target_fence(store, db, intent["identity_observation"]["repository_id"], intent["claim"]["issue"])
        require(intent["binding"] == t.task_binding(task), "ORIGINAL_INTENT_BINDING_CHANGED")
        if db.execute("SELECT version FROM meta").fetchone()[0] in {6, 7}:
            require(not any(t.decode(row[0])["binding"].get("intent_operation_id") == intent["operation_id"]
                            for row in db.execute("SELECT document FROM assignment_requests")), "POST_REPLAY_REFUSED")
    claim, observed = intent["claim"], intent["identity_observation"]
    client = transport.Transport(claim["repo"], claim["issue"], token)
    try:
        ids = client.fresh(observed)
    finally:
        client.close()
    with store.locked() as db:
        require(store.task() == task and store.intent(db) == intent, "SELECTED_ROWS_CHANGED")
        store.ownership(task)
        request = build(store, intent, task, ids, head)
    approval = publisher.collect_approval(request["binding"])
    # Recreate budget after interaction, then repeat actor/target/permission GETs.
    client = transport.Transport(claim["repo"], claim["issue"], token)
    token = None
    try:
        require(client.fresh(observed) == ids, "PRIOR_ASSIGNEES_CHANGED")
        implementation_head(head)
        request["approval"] = approval.validate(request["binding"])
        with store.locked() as db:
            store.guard(db, request, original=True)
            approval.validate(request["binding"])
            t.preflight(db, request)
            standing_target_fence(store, db, observed["repository_id"], claim["issue"])
            approval.validate(request["binding"])
            # Never clear this marker on failed/ambiguous DB commit.
            c.assignment_reserve(store.root, task, request["reserved_task"])
            t.reserve(db, request)
            store.durable(db)
            store.guard(db, request)
        completion, result_ids, outcome = "NOT_SENT", None, None
        diagnostics = []
        try:
            approval.validate(request["binding"])
        except publisher.Refusal as exc:
            diagnostics.append(t.diagnostic("APPROVAL", exc))
            outcome = "NOT_SENT"
        else:
            if observed["actor_id"] in ids:
                result_ids, outcome = ids, "SATISFIED_NO_POST"
            else:
                # From this point every exception is UNKNOWN, never proven not-sent.
                completion = "UNKNOWN"
                try:
                    client.assign(observed)
                    completion = "CONFIRMED"
                    result_ids = client.issue(observed)
                    actual, _ = transport.actual_result(ids, result_ids, observed["actor_id"])
                    outcome = "ASSIGNMENT_CONFIRMED_OBSERVED" if actual == "PRESERVED_ACTOR_PRESENT" else actual
                except Exception as exc:
                    primary = t.diagnostic("POST" if completion == "UNKNOWN" else "OBSERVATION",
                                           exc, getattr(exc, "http_status", getattr(client, "http_status", None)))
                    diagnostics.append(primary)
                    # Correlation only after a lost response; no automatic replay.
                    if completion == "UNKNOWN" and primary["reason"] not in {"RATE_LIMITED", "DEADLINE_EXCEEDED"}:
                        try:
                            result_ids = client.issue(observed)
                        except Exception as correlation_error:
                            diagnostics.append(t.diagnostic("CORRELATION", correlation_error,
                                getattr(correlation_error, "http_status", getattr(client, "http_status", None))))
        client.close()  # Actual synchronous producer has returned, sockets closed.
        return settle(store, request, evidence(request, completion, result_ids, diagnostics), outcome)
    finally:
        client.close()


def recover(args, publisher):
    if args.action == "arbitrate":
        # No declaration/file, caller boolean, ps absence, or boot-ID comparison
        # proves containment. This refusal performs no writes, GETs or release.
        raise Refusal("PRODUCER_TERMINATION_PROOF_UNSUPPORTED")
    token = os.environ.pop("GH_TOKEN", None)
    require(not os.environ.get("GITHUB_TOKEN"), "EXPLICIT_GH_TOKEN_REQUIRED")
    p, c, j, t, durability, transport = modules()
    store = Store(args, p, c, j, t, durability)
    implementation_head(args.implementation_head)
    with store.locked() as db:
        require(db.execute("SELECT version FROM meta").fetchone()[0] in {6, 7}, "RESERVATION_NOT_FOUND")
        request = t.get(db, "assignment_requests", args.assignment_operation_id)
        if (request is None or request["version"] != 1 or request["binding"]["implementation_head"] != args.implementation_head
                or request["binding"]["intent_operation_id"] != args.intent_operation_id):
            raise Refusal("RESERVATION_REQUEST_CHANGED")
        require(store.task()["revision"] == args.expected_revision, "REVISION_MISMATCH")
        store.guard(db, request, recovery=True)
        receipt = t.get(db, "assignment_evidence", request["evidence_id"])
        terminal = t.get(db, "assignment_settlements", request["settlement_id"])
        if terminal is not None:
            store.durable(db)
            c.assignment_release(store.root, request["reserved_task"])
            return {"status": terminal["outcome"], "reservation": "settled", "completion": terminal["completion"],
                    "satisfaction": terminal["satisfaction"]}
        if receipt is None or receipt["completion"] == "UNKNOWN":
            raise Refusal("PRODUCER_TERMINATION_PROOF_UNSUPPORTED")
        if receipt["completion"] == "NOT_SENT":
            outcome = "NOT_SENT" if receipt["result_ids"] is None else "SATISFIED_NO_POST"
        elif receipt["result_ids"] is not None:
            actual, _ = transport.actual_result(request["binding"]["prior_assignee_ids"], receipt["result_ids"],
                                                 request["binding"]["publisher"]["id"])
            outcome = "ASSIGNMENT_CONFIRMED_OBSERVED" if actual == "PRESERVED_ACTOR_PRESENT" else actual
        else:
            outcome = None
        intent = store.intent(db)
    if outcome is not None:
        return settle(store, request, receipt, outcome, recovery=True)
    # Confirmed transport with incomplete observation: bounded GET-only recovery.
    require(token is not None, "EXPLICIT_GH_TOKEN_REQUIRED")
    client = transport.Transport(intent["claim"]["repo"], intent["claim"]["issue"], token)
    token = None
    try:
        ids = client.fresh(intent["identity_observation"], admission=False)
    finally:
        client.close()
    actual, _ = transport.actual_result(request["binding"]["prior_assignee_ids"], ids, request["binding"]["publisher"]["id"])
    outcome = "ASSIGNMENT_CONFIRMED_OBSERVED" if actual == "PRESERVED_ACTOR_PRESENT" else actual
    return settle(store, request, receipt, outcome, ids, recovery=True)


def arguments():
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise Refusal("INVALID_ARGUMENTS")

    class Once(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            require(getattr(namespace, self.dest, None) is None, "DUPLICATE_ARGUMENT")
            setattr(namespace, self.dest, values)

    parser = Parser(allow_abbrev=False)
    parser.add_argument("action", choices=("assign", "settle", "arbitrate"))
    for name in ("authority-root", "invoking-root", "task-id", "expected-revision", "expected-worker-id",
                 "expected-session-id", "expected-generation", "intent-operation-id", "implementation-head"):
        parser.add_argument("--" + name, required=True, action=Once)
    parser.add_argument("--assignment-operation-id", action=Once)
    args = parser.parse_args()
    for key, pattern in (("task_id", r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}"),
                         ("expected_session_id", r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"),
                         ("expected_worker_id", r"[0-9a-f]{32}"), ("intent_operation_id", r"[0-9a-f]{32}"),
                         ("implementation_head", r"[0-9a-f]{40}")):
        require(re.fullmatch(pattern, getattr(args, key)) is not None, "INVALID_ARGUMENTS")
    for key in ("expected_revision", "expected_generation"):
        value = getattr(args, key)
        require(re.fullmatch(r"[1-9][0-9]{0,18}", value) is not None and int(value) <= 2**63 - 1, "INVALID_ARGUMENTS")
        setattr(args, key, int(value))
    require((args.action == "assign") == (args.assignment_operation_id is None), "INVALID_ARGUMENTS")
    if args.assignment_operation_id is not None:
        require(re.fullmatch(r"[0-9a-f]{32}", args.assignment_operation_id) is not None, "INVALID_ARGUMENTS")
    return args
