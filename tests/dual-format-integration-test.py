#!/usr/bin/env python3
"""Connected dual-format producers and pinned old readers; isolated guest only.

The PTY and fake HTTP harness is shared with the dispatch suite. No approval,
task validator, lease guard, journal parser or settlement producer is mocked.
Native kernel observation is synthetic: this is not backend qualification.
"""

import contextlib
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BASE = "638763a521d2c86f8d453b603d3bdcb983eba116"
BIN = ".agents/skills/workspace-orchestrator/bin/"
IDENTITY = {"schema_version": 1, "backend": "linux-procfs",
            "boot_id": "11111111-2222-3333-4444-555555555555",
            "pid_namespace_inode": "4026531836", "start_ticks": "12345"}
LEGACY_SOURCES = {BIN + name + ".py" for name in (
    "orchestrator-state", "runtime-observation", "monitor-journal",
    "assignment-journal", "standing-grant", "reservation-history")}
LEGACY_SOURCES.update({"scripts/check-native-ownership.py", "scripts/publish-github-assignment.py"})


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dispatch = load("integration_dispatch_fixtures", ROOT / "tests/assignment-dispatch-test.py")
local_fixtures = dispatch.fixture_module.fixtures.local
adapter, publisher = dispatch.adapter, dispatch.publisher
core_fixtures = load("integration_core_fixtures", ROOT / BIN / "../tests/dual-format-core-test.py")


class PackagedCoreTests(unittest.TestCase):
    def test_actual_copied_skill_only_suite_without_repository_scripts(self):
        with tempfile.TemporaryDirectory(prefix="installed-dual-core-") as directory:
            root = Path(directory).resolve()
            skill = root / "installed-skill"
            shutil.copytree(ROOT / ".agents/skills/workspace-orchestrator", skill,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            self.assertFalse((root / "scripts").exists())
            environment = {key: value for key, value in os.environ.items()
                           if not key.startswith(("ORCHESTRATOR_", "WORKSPACE_ORCHESTRATOR_", "PYTHON", "GIT_"))}
            result = subprocess.run([sys.executable, "-I", "-B", str(skill / "tests/dual-format-core-test.py")],
                                    cwd=root, env=environment, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("OK", result.stderr)
            self.assertFalse((root / "scripts").exists())


class IndependentCoreReaderTests(core_fixtures.DualFormatCoreTest):
    """Reapply independent comparisons to every packaged lifecycle validation.

    This intentionally reruns the core matrix in the maintainer suite, while
    the distributed suite has no dependency on this reader or repository layout.
    """

    def setUp(self):
        core_fixtures.DualFormatCoreTest.setUp(self)
        self.reader = load("independent_dual_reader", ROOT / "scripts/check-native-ownership.py")

    def validate(self, record):
        self.core.validate_record(record, allow_bound=True, allow_native=True)
        self.reader.validate_task(record)

    def reader_args(self, record):
        return SimpleNamespace(authority_root=str(self.root), invoking_root=str(self.root),
            task_id=record["task_id"], expected_revision=record["revision"],
            expected_worker_id=record["worker"]["worker_id"], expected_repo=None, expected_branch=None,
            expected_session_id=record["worker"].get("session_id"),
            expected_generation=record["worker"].get("generation"))

    def test_both_readers_refuse_raw_native_duplicates_without_effects(self):
        # The packaged fixture's custom state location has no reader authority
        # semantics. Move its empty state into the actual .orchestrator layout.
        self.state.rename(self.root / ".orchestrator")
        self.state = self.root / ".orchestrator"
        for bound in (False, True):
            name = f"reader-{bound}"
            self.create(name)
            record = self.transition(self.claim(name, bound=bound), "Implementing")
            args = self.reader_args(record)
            self.assertEqual(self.reader.inspect(args)["status"], "STATIC_MATCH")
            cases = [(self.core.task_path(self.state, name), list(core_fixtures.duplicate_json_cases(record)))]
            for group, field in (("slots", "global_slot"), ("implementation", "implementation_lane")):
                cases.append((self.state / group / f"{record['leases'][field]}.lock" / "owner.json",
                              list(core_fixtures.duplicate_worker_cases(record["worker"]))))
            scope = self.state / "scopes" / f"{record['scope_key']}.lock" / "owner.json"
            raw = scope.read_text().replace('"token":', '"token":"wrong", "t\\u006fken":', 1)
            cases.append((scope, [("scope-token", raw)]))
            for path, variants in cases:
                original = path.read_bytes()
                try:
                    for case, raw in variants:
                        path.write_text(raw)
                        with self.subTest(schema=record["schema_version"], path=path.name, case=case):
                            self.assert_no_effect(lambda: self.transition(record, "Reviewing"))
                            self.assert_no_effect(lambda: self.reader.inspect(args), self.reader.Unverified)
                finally:
                    path.write_bytes(original)
            # Semantic cross-family failures are independent of raw parsing.
            for mutate in (lambda r: r["worker"].update(process_start="legacy"),
                           lambda r: r["worker"]["process_identity"].update(start_ticks=True),
                           lambda r: r.update(schema_version=3 if bound else 2)):
                invalid = copy.deepcopy(record)
                mutate(invalid)
                with self.assertRaises(self.core.UnknownError):
                    self.core.validate_record(invalid, allow_bound=True, allow_native=True)
                with self.assertRaises(self.reader.Unverified):
                    self.reader.validate_task(invalid)
            self.transition(record, "Cancelled")

    def test_both_readers_refuse_symlinked_slot_and_lane(self):
        self.state.rename(self.root / ".orchestrator")
        self.state = self.root / ".orchestrator"
        for bound in (False, True):
            name = f"links-{bound}"
            self.create(name)
            record = self.transition(self.claim(name, bound=bound), "Implementing")
            for group, field in (("slots", "global_slot"), ("implementation", "implementation_lane")):
                path = self.state / group / f"{record['leases'][field]}.lock"
                external = self.root / f"external-{group}-{bound}"
                path.rename(external)
                path.symlink_to(external, target_is_directory=True)
                before = (external / "owner.json").read_bytes()
                try:
                    self.assert_no_effect(lambda: self.reader.inspect(self.reader_args(record)), OSError)
                    for target in ("Reviewing", "Cancelled"):
                        self.assert_no_effect(lambda: self.transition(record, target))
                    self.assertEqual((external / "owner.json").read_bytes(), before)
                finally:
                    path.unlink()
                    external.rename(path)
            self.transition(record, "Cancelled")


class ConnectedPreparation(unittest.TestCase):
    """Supply only a native Ready input; claim/transition are actual core calls."""

    setUp = local_fixtures.PreparationTest.setUp
    owned = local_fixtures.PreparationTest.owned
    options = local_fixtures.PreparationTest.options
    write = local_fixtures.PreparationTest.write
    snapshot = local_fixtures.PreparationTest.snapshot

    def core_cli(self, *words):
        core = load("integration_producer_core", self.core)
        with (mock.patch.dict(os.environ, self.env, clear=True),
              mock.patch.object(core._observation, "native_process_identity", return_value=("alive", IDENTITY)),
              mock.patch.object(core._observation, "_native_observation", return_value=("alive", IDENTITY))):
            state = core.state_root()
            args = core.parser().parse_args(list(words))
            record = getattr(core, "command_" + args.command.replace("-", "_"))(args, state)
            if words[0] == "create":
                self.assertEqual(record["schema_version"], 2)
                # Explicit inert fixture input, NOT a conversion/creation API.
                record["schema_version"] = 4
                core.atomic_json(core.task_path(state, record["task_id"]), record)
                self.native_input = copy.deepcopy(record)
            elif words[0] == "claim":
                self.claimed = copy.deepcopy(record)
            return record


class ConnectedHarness(unittest.TestCase):
    # Share mechanics, not inherited test methods (avoid rediscovering the matrix).
    run_vertical = dispatch.DispatchTest.run_vertical
    task = dispatch.DispatchTest.task
    native = True

    def setUp(self):
        self.fixture = dispatch.fixture_module.ApprovedIntentTests()
        factory = ConnectedPreparation if self.native else local_fixtures.PreparationTest
        with mock.patch.object(local_fixtures, "PreparationTest", factory):
            self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.local = self.fixture.fixture.local
        self.parts = adapter.modules()
        if self.native:
            self.assertEqual(self.local.native_input["schema_version"], 4)
            self.assertIsNone(self.local.native_input["worker"])
            self.assertEqual(self.local.claimed["schema_version"], 5)
            self.assertNotIn("process_start", self.local.claimed["worker"])
        probe = mock.patch.object(self.parts[1]._observation, "_native_observation",
                                  return_value=("alive", IDENTITY))
        probe.start()
        self.addCleanup(probe.stop)
        self.fixture.assert_recorded()
        self.intent = self.fixture.request()
        self.select_args()
        self.trace = self.local.root / "transport-trace"

    def select_args(self):
        task = self.local.task
        self.args = SimpleNamespace(action="assign", authority_root=str(self.local.root),
            invoking_root=str(self.local.root), task_id=task["task_id"], expected_revision=task["revision"],
            expected_worker_id=task["worker"]["worker_id"], expected_session_id=task["worker"]["session_id"],
            expected_generation=task["worker"]["generation"], intent_operation_id=self.intent["operation_id"],
            implementation_head="6" * 40, assignment_operation_id=None)

    def rows(self):
        journal, typed = self.parts[2:4]
        db = journal.open_store(self.fixture.monitor)
        try:
            version = db.execute("SELECT version FROM meta").fetchone()[0]
            if version < 6:
                return version, None, None, None
            requests = [typed.decode(row[0]) for row in db.execute("SELECT document FROM assignment_requests")]
            selected = [r for r in requests if r["binding"]["intent_operation_id"] == self.args.intent_operation_id]
            if not selected:
                return version, None, None, None
            self.assertEqual(len(selected), 1)
            request = selected[0]
            return (version, request, typed.get(db, "assignment_evidence", request["evidence_id"]),
                    typed.get(db, "assignment_settlements", request["settlement_id"]))
        finally:
            db.close()

    def core_call(self, *words):
        core = self.parts[1]
        args = core.parser().parse_args(list(words))
        with mock.patch.dict(os.environ, self.local.env, clear=True):
            return getattr(core, "command_" + args.command.replace("-", "_"))(args, self.local.state)

    def transition(self, target):
        self.local.task = self.task()
        self.local.task = self.core_call("transition", self.local.task["task_id"], target, *self.local.owned())
        return self.local.task

    def second_intent(self, native):
        """Create/claim a different task in the SAME authority, then journal it."""
        core = self.parts[1]
        checkout = self.local.root / "second-checkout"
        checkout.mkdir()
        task = self.core_call("create", "second-task", "--scope", "fixture:second", "--kind", "implementation",
            "--repo", "example/project", "--branch", "feat/second", "--worktree", str(checkout),
            "--base-sha", "a" * 40, "--head-sha", "a" * 40, "--tracker-type", "issue", "--tracker-number", "117")
        self.assertEqual(task["schema_version"], 2)
        if native:
            task["schema_version"] = 4
            core.atomic_json(core.task_path(self.local.state, task["task_id"]), task)
        with mock.patch.object(core._observation, "native_process_identity", return_value=("alive", IDENTITY)):
            task = self.core_call("claim", task["task_id"], "--owner", "fixture-owner", "--pid", str(os.getpid()),
                                 "--session-id", "second-session", "--expected-generation", "0", "--expected-revision", "0")
        self.assertEqual(task["schema_version"], 5 if native else 3)
        self.local.task = task
        self.local.task_path = core.task_path(self.local.state, task["task_id"])
        self.transition("Implementing")
        self.fixture.fixture.options.update(self.local.options())
        claim = dict(self.intent["claim"], branch="feat/second", operation_id=dispatch.fixture_module.OPERATION)
        self.fixture.fixture.options.update({"branch": claim["branch"], "operation-id": claim["operation_id"],
            "approved-body-sha256": self.fixture.prepare.codec.digest(self.fixture.prepare.codec.render(claim))})
        self.fixture.assert_recorded()
        db = self.parts[2].open_store(self.fixture.monitor)
        try:
            self.intent = self.parts[2].decode_intent(db.execute(
                "SELECT request FROM claim_intents WHERE operation_id=?",
                (self.fixture.fixture.options["operation-id"],)).fetchone()[0])
        finally:
            db.close()
        self.assertEqual(self.intent["schema_version"], 4 if native else 2)
        self.select_args()

    def snapshot(self):
        return {str(p.relative_to(self.local.state)): p.read_bytes()
                for p in self.local.state.rglob("*") if p.is_file()}

    @contextlib.contextmanager
    def database(self):
        db = self.parts[2].open_store(self.fixture.monitor, writable=True)
        try:
            yield db
        finally:
            db.close()

    def proposed(self):
        # Guard-only rehearsal, never supplied to the publisher as approval.
        # Actual dispatch below always collects a new challenge on a real PTY.
        typed = self.parts[3]
        request = adapter.build(adapter.Store(self.args, *self.parts[:-1]), self.intent,
                                self.local.task, [], self.args.implementation_head)
        request["approval"] = {"binding_sha256": typed.digest(request["binding"]),
            "interaction": "CONTROLLING_TTY_EXACT_CHALLENGE", "age_milliseconds": 0, "maximum_age_seconds": 120}
        return request

    def weak_intent(self):
        options = self.local.options()
        options["operation-id"] = "f1" * 16
        argv = ["journal-claim-intent.py", *[part for key, value in options.items()
                                           for part in ("--" + key, value)]]
        with mock.patch.object(sys, "argv", argv):
            args, claim = self.fixture.prepare.arguments()
        with mock.patch.dict(os.environ, self.local.env, clear=True):
            result = self.fixture.intent.record(args, claim, self.fixture.prepare,
                                                self.fixture.core, self.fixture.journal)
        self.assertEqual(result["status"], "INTENT_RECORDED")
        with self.database() as db:
            weak = self.parts[2].decode_intent(db.execute(
                "SELECT request FROM claim_intents WHERE operation_id=?", (options["operation-id"],)).fetchone()[0])
        self.assertEqual(weak["schema_version"], 3)
        return weak


class ConnectedTests(ConnectedHarness):
    def test_native_claim_to_intent_to_pty_settlement_to_lifecycle(self):
        core, reader = self.parts[1], self.parts[0]
        self.assertEqual(self.intent["schema_version"], 4)
        self.assertEqual(self.intent["binding"]["worker"], self.local.claimed["worker"])
        reader.validate_task(self.local.task)
        expected = SimpleNamespace(**vars(self.args), expected_branch="feat/public", expected_repo="example/project")
        before = self.snapshot()
        self.assertEqual(reader.inspect(expected)["status"], "STATIC_MATCH")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.run_vertical(), "ASSIGNMENT_CONFIRMED_OBSERVED")
        version, request, evidence, terminal = self.rows()
        self.assertEqual((version, request["version"], request["binding"]["schema_version"]), (6, 3, 3))
        self.assertEqual(request["binding"]["task_binding"]["task_schema_version"], 5)
        self.assertEqual(request["original_task"], self.local.task)
        self.assertEqual(request["original_task"]["worker"], self.local.claimed["worker"])
        self.assertEqual((evidence["version"], terminal["version"]), (2, 1))
        self.assertEqual(self.trace.read_text(), "POST")
        with self.database() as db:
            with self.assertRaisesRegex(self.parts[3].Invalid, "POST_REPLAY_REFUSED"):
                self.parts[3].preflight(db, self.proposed())
        for state in ("Reviewing", "Cancelled"):
            task = self.transition(state)
            self.assertEqual(task["schema_version"], 5)
            core.validate_record(task, allow_bound=True, allow_native=True)
            reader.validate_task(task)
        self.assertIsNone(task["worker"])
        self.assertEqual(list((self.local.state / "slots").iterdir()), [])
        self.assertEqual(list((self.local.state / "implementation").iterdir()), [])
        self.assertEqual(list((self.local.state / "scopes").iterdir()), [])
        self.assertEqual(self.rows(), (version, request, evidence, terminal))

    def test_native_pending_blocks_real_legacy_producer(self):
        self.pending_other_family(False)

    def pending_other_family(self, native):
        self.assertEqual(self.run_vertical("lost"), "UNKNOWN")
        first = self.rows()
        with self.database() as db:
            with self.assertRaisesRegex(self.parts[3].Invalid, "POST_REPLAY_REFUSED"):
                self.parts[3].preflight(db, self.proposed())
        self.second_intent(native)
        before = self.snapshot()
        with self.database() as db:
            with self.assertRaisesRegex(self.parts[3].Invalid, "TARGET_PENDING"):
                self.parts[3].preflight(db, self.proposed())
            self.assertEqual(db.execute("SELECT count(*) FROM claim_intents").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 6)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.trace.read_text(), "POST")
        self.assertEqual(first[2]["completion"], "UNKNOWN")
        self.assertIsNone(first[3])

    def test_mixed_completed_rows_capacity_and_consumed_opportunities(self):
        self.assertEqual(self.run_vertical("present"), "SATISFIED_NO_POST")
        first_request = self.rows()[1]
        self.second_intent(False)
        self.assertEqual(self.run_vertical("ignored"), "FAILED_ACTUAL_RESULT")
        typed, journal = self.parts[3], self.parts[2]
        before = self.snapshot()
        with self.database() as db:
            requests = [typed.decode(row[0]) for row in db.execute("SELECT document FROM assignment_requests")]
            self.assertEqual({r["version"] for r in requests}, {1, 3})
            for table in typed.TABLES:
                self.assertEqual(db.execute("SELECT count(*) FROM " + table).fetchone()[0], 2)  # nosec B608 - fixed TABLES
            self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 6)
            journal.validate_store(db)
            # Both no-POST success and failed actual result consume the intent.
            for old in requests:
                intent = journal.decode_intent(db.execute("SELECT request FROM claim_intents WHERE operation_id=?",
                    (old["binding"]["intent_operation_id"],)).fetchone()[0])
                store = adapter.Store(self.args, *self.parts[:-1])
                replay = adapter.build(store, intent, old["original_task"], [], self.args.implementation_head)
                replay["approval"] = dict(old["approval"], binding_sha256=typed.digest(replay["binding"]))
                with self.assertRaisesRegex(typed.Invalid, "POST_REPLAY_REFUSED"):
                    typed.preflight(db, replay)
                with mock.patch.object(typed, "CAPACITY", 2), self.assertRaisesRegex(typed.Invalid, "CAPACITY"):
                    typed.preflight(db, replay)
            self.assertEqual(typed.get(db, "assignment_requests", first_request["binding"]["operation_id"]), first_request)
        self.assertEqual(self.snapshot(), before)


class LegacyFirstTests(ConnectedHarness):
    native = False
    pending_other_family = ConnectedTests.pending_other_family

    def test_legacy_pending_blocks_real_native_producer(self):
        self.pending_other_family(True)


def materialize_baseline(test, destination):
    """Only pinned inert bytes, with no fallback to current code or downloads."""
    fixtures = ROOT / "tests/fixtures/dual-format-legacy"
    manifest = json.loads((fixtures / "manifest.json").read_text(encoding="utf-8"))
    test.assertEqual(set(manifest), {"version", "source_revision", "files"})
    test.assertIs(type(manifest["version"]), int)
    test.assertEqual((manifest["version"], manifest["source_revision"]), (1, BASE))
    test.assertEqual(len(manifest["files"]), len(LEGACY_SOURCES))
    test.assertEqual({entry["source_path"] for entry in manifest["files"]}, LEGACY_SOURCES)
    for entry in manifest["files"]:
        test.assertEqual(set(entry), {"source_path", "file", "sha256", "size"})
        source = Path(entry["source_path"])
        test.assertEqual(entry["file"], source.name + ".txt")
        raw = (fixtures / entry["file"]).read_bytes()
        test.assertIs(type(entry["size"]), int)
        test.assertEqual(len(raw), entry["size"])
        test.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"])
        target = destination / source
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)


class PinnedOldReaderTests(ConnectedHarness):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory(prefix="pinned-dual-readers-")
        self.addCleanup(temporary.cleanup)
        old = Path(temporary.name)
        materialize_baseline(self, old)
        self.old_core = load("pinned_dual_core", old / BIN / "orchestrator-state.py")
        self.old_reader = load("pinned_dual_reader", old / "scripts/check-native-ownership.py")
        self.old_journal = load("pinned_dual_journal", old / BIN / "monitor-journal.py")
        self.old_typed = load("pinned_dual_typed", old / BIN / "assignment-journal.py")
        self.old_publisher = load("pinned_dual_publisher", old / "scripts/publish-github-assignment.py")

    def test_actual_old_task_readers_refuse_native_with_and_without_worker(self):
        original = self.local.task_path.read_bytes()
        # Ready 4 and real claimed 5, plus their real lifecycle released forms.
        records = [self.local.native_input, self.local.claimed]
        # The ordinary active record is produced by claim, not schema relabeling.
        ordinary = self.core_call("create", "ordinary-old-reader", "--scope", "fixture:ordinary", "--kind", "implementation")
        ordinary["schema_version"] = 4
        core = self.parts[1]
        core.atomic_json(core.task_path(self.local.state, ordinary["task_id"]), ordinary)
        with mock.patch.object(core._observation, "native_process_identity", return_value=("alive", IDENTITY)):
            ordinary = self.core_call("claim", ordinary["task_id"], "--owner", "fixture-owner", "--pid", str(os.getpid()))
        records.append(ordinary)
        released = self.transition("Blocked")
        self.assertIsNone(released["worker"])
        records.append(released)
        try:
            for record in records:
                with self.subTest(schema=record["schema_version"], worker=record["worker"] is not None):
                    path = core.task_path(self.local.state, record["task_id"])
                    previous = path.read_bytes()
                    core.validate_record(record, allow_bound=True, allow_native=True)
                    self.parts[0].validate_task(record)
                    core.atomic_json(path, record)
                    before = self.snapshot()
                    args = SimpleNamespace(**vars(self.args))
                    args.task_id = record["task_id"]
                    with self.assertRaises(self.old_core.UnknownError):
                        self.old_core.read_task(self.local.state, record["task_id"], allow_bound=True)
                    with self.assertRaises(self.old_reader.Unverified):
                        self.old_reader.inspect(args)
                    self.assertEqual(self.snapshot(), before)
                    path.write_bytes(previous)
        finally:
            self.local.task_path.write_bytes(original)

    def test_actual_old_intent_request_publisher_and_mixed_store_refusals(self):
        weak = self.weak_intent()
        self.assertEqual(self.run_vertical(), "ASSIGNMENT_CONFIRMED_OBSERVED")
        request = self.rows()[1]
        native_intent = copy.deepcopy(self.intent)
        self.second_intent(False)
        self.parts[2].validate_claim_intent(weak)
        # Positive legacy controls ensure the historical modules/dependencies
        # themselves work, rather than counting an import failure as refusal.
        self.old_journal.validate_claim_intent(self.intent)
        self.old_core.read_task(self.local.state, self.local.task["task_id"], allow_bound=True)
        self.old_reader.validate_task(self.local.task)
        legacy_request = self.proposed()
        self.old_publisher.validate_binding(legacy_request["binding"])
        before = self.snapshot()
        with (mock.patch.object(self.old_publisher.os, "open", side_effect=AssertionError("TTY opened")),
              self.assertRaises(self.old_publisher.Refusal)):
            self.old_publisher.collect_approval(request["binding"])
        for intent in (weak, native_intent):
            with self.assertRaises(self.old_journal.JournalError):
                self.old_journal.validate_claim_intent(intent)
        with self.database() as db:
            self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 6)
            self.assertEqual({json.loads(row[0])["schema_version"] for row in db.execute("SELECT request FROM claim_intents")}, {2, 3, 4})
            with self.assertRaises(self.old_typed.Invalid):
                self.old_typed.validate_request(db, request)
            self.old_typed.validate_request(db, legacy_request)
            for intent in (weak, native_intent):
                with self.assertRaises(self.old_journal.JournalError):
                    self.old_journal.record_claim_intent(db, intent)
            with self.assertRaises(self.old_typed.module("monitor-journal").JournalError):
                self.old_typed.preflight(db, request)
            self.assertFalse(db.in_transaction)
        with self.assertRaises(self.old_journal.JournalError):
            self.old_journal.open_store(self.fixture.monitor)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.trace.read_text(), "POST")
        with self.database() as db:
            # Existing standing table migration, not native-format migration or
            # activation. All original manual rows must remain byte-identical.
            rows = {table: [tuple(row) for row in db.execute("SELECT * FROM " + table)]
                    for table in ("claim_intents", *self.parts[3].TABLES)}  # nosec B608 - fixed inventory
            with db:
                db.execute("BEGIN IMMEDIATE")
                self.parts[3].module("standing-grant").migrate(db)
            self.parts[2].validate_store(db)
            self.assertEqual(db.execute("SELECT version FROM meta").fetchone()[0], 7)
            self.assertEqual(rows, {table: [tuple(row) for row in db.execute("SELECT * FROM " + table)]
                                    for table in rows})  # nosec B608 - fixed inventory above
        before = self.snapshot()
        with self.assertRaises(self.old_journal.JournalError):
            self.old_journal.open_store(self.fixture.monitor)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
