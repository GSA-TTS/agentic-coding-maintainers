#!/usr/bin/env python3
"""Actual core/independent-reader fixtures. Run only in an isolated validation guest."""

import copy
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SKILL = Path(__file__).resolve().parents[1]
REPO = SKILL.parents[2]
IDENTITY = {"schema_version": 1, "backend": "linux-procfs",
            "boot_id": "01234567-89ab-cdef-0123-456789abcdef",
            "pid_namespace_inode": "4026531836", "start_ticks": "123456"}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DualFormatCoreTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dual-format-core-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.core = load("dual_core", SKILL / "bin/orchestrator-state.py")
        self.reader = load("dual_reader", REPO / "scripts/check-native-ownership.py")
        env = mock.patch.dict(os.environ, {"ORCHESTRATOR_TEST_MODE": "1",
                                          "ORCHESTRATOR_STATE_DIR": str(self.root / "state")})
        env.start()
        self.addCleanup(env.stop)
        self.state = self.core.state_root()
        probe = mock.patch.object(self.core._observation, "native_process_identity", return_value=("alive", IDENTITY))
        self.native_probe = probe.start()
        self.addCleanup(probe.stop)
        legacy = mock.patch.object(self.core, "process_identity", return_value=("alive", "arbitrary\nlegacy start"))
        self.legacy_probe = legacy.start()
        self.addCleanup(legacy.stop)

    def call(self, *words):
        args = self.core.parser().parse_args(list(words))
        return getattr(self.core, "command_" + args.command.replace("-", "_"))(args, self.state)

    def create(self, name="native", native=True):
        record = self.call("create", name, "--scope", "fixture:" + name, "--kind", "implementation",
                           "--head-sha", "a" * 40)
        self.assertEqual(record["schema_version"], 2)
        if native:
            # Explicit fixture only: no supported creation or conversion route.
            record["schema_version"] = 4
            self.core.atomic_json(self.core.task_path(self.state, name), record)
        return record

    def claim(self, name="native", bound=False, generation=0, revision=0):
        options = ["--session-id", "fixture-session", "--expected-generation", str(generation),
                   "--expected-revision", str(revision)] if bound else []
        return self.call("claim", name, "--owner", "fixture-owner", "--pid", "123", *options)

    def owned(self, record):
        if not self.core.is_cooperative_task(record):
            return []
        return ["--expected-session-id", record["worker"]["session_id"],
                "--expected-worker-id", record["worker"]["worker_id"],
                "--expected-generation", str(record["cooperative_binding"]["generation"]),
                "--expected-revision", str(record["revision"])]

    def transition(self, record, state):
        if state == "Implementing" and self.core.is_native_task(record):
            # Successful lifecycle setup uses a qualified native observation.
            # Refusal tests invoke the command directly with adversarial probes.
            with mock.patch.object(self.core._observation, "_native_observation", return_value=("alive", IDENTITY)):
                return self.call("transition", record["task_id"], state, *self.owned(record))
        return self.call("transition", record["task_id"], state, *self.owned(record))

    def snapshot(self):
        return {str(path.relative_to(self.state)): path.read_bytes()
                for path in self.state.rglob("*") if path.is_file()}

    def assert_no_effect(self, function, exception=None):
        before = self.snapshot()
        with self.assertRaises(exception or self.core.UnknownError):
            function()
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.state / "locks/coordinator.lock").exists())

    def validate(self, record):
        self.core.validate_record(record, allow_bound=True, allow_native=True)
        self.reader.validate_task(record)

    def test_finite_formats_default_fences_and_creation_stays_legacy(self):
        for native in (False, True):
            for bound in (False, True):
                name = f"task-{native}-{bound}"
                self.create(name, native=native)
                record = self.claim(name, bound=bound)
                self.assertEqual(record["schema_version"], 2 + int(bound) + 2 * int(native))
                self.validate(record)
                self.assertEqual(self.core.is_native_task(record), native)
                self.assertEqual(self.core.is_cooperative_task(record), bound)
                if native:
                    self.assert_no_effect(lambda: self.core.read_task(self.state, name, allow_bound=True))
                if bound:
                    self.assert_no_effect(lambda: self.core.read_task(self.state, name, allow_native=True))
        for schema in (True, False, 0, 1, 6, "4", 4.0):
            with self.assertRaises(self.core.UnknownError):
                self.core.task_schema({"schema_version": schema})
        self.assertEqual(len(self.core.command_list(self.state, allow_bound=True, allow_native=True)), 4)
        self.assert_no_effect(lambda: self.core.command_list(self.state, allow_bound=True))

    def test_cross_format_workers_and_strict_native_shape(self):
        self.create()
        record = self.claim(bound=True)
        variants = []
        legacy = copy.deepcopy(record)
        legacy["worker"]["process_start"] = "legacy"
        variants.append(legacy)
        absent = copy.deepcopy(record)
        absent["worker"].pop("process_identity")
        variants.append(absent)
        cross = copy.deepcopy(record)
        cross["schema_version"] = 3
        variants.append(cross)
        for key, value in (("schema_version", True), ("backend", "other"), ("start_ticks", "01"),
                           ("pid_namespace_inode", "0"), ("start_ticks", str(2**64)), ("extra", 1)):
            invalid = copy.deepcopy(record)
            invalid["worker"]["process_identity"][key] = value
            variants.append(invalid)
        for invalid in variants:
            with self.assertRaises(self.core.UnknownError):
                self.core.validate_record(invalid, allow_bound=True, allow_native=True)
            with self.assertRaises(self.reader.Unverified):
                self.reader.validate_task(invalid)

    def test_unsupported_profiles_refuse_before_probe_and_effects(self):
        original = self.create()
        for field in ("identity_migration", "foreground", "review_protocol", "repair_protocol",
                      "execution_observations", "candidate_binding", "review_reservations",
                      "standing_grant", "intake_completion", "unknown_extension"):
            record = dict(original, **{field: {}})
            self.core.atomic_json(self.core.task_path(self.state, "native"), record)
            self.assert_no_effect(lambda: self.claim())
        for kind in ("monitor", "intake"):
            self.core.atomic_json(self.core.task_path(self.state, "native"), dict(original, kind=kind))
            self.assert_no_effect(lambda: self.claim())
        self.native_probe.assert_not_called()
        self.legacy_probe.assert_not_called()

    def test_qualification_before_capacity_and_claim_crash(self):
        self.create()
        for observation in (("unknown", None), ("absent", None), ("alive", "legacy"), ("alive", {})):
            self.native_probe.return_value = observation
            with mock.patch.object(self.core, "reserve_first", side_effect=AssertionError("capacity touched")):
                self.assert_no_effect(lambda: self.claim(bound=True))
        self.native_probe.return_value = ("alive", IDENTITY)
        with mock.patch.dict(os.environ, {"ORCHESTRATOR_TEST_FAIL_CLAIM_WRITE": "1"}):
            self.assert_no_effect(lambda: self.claim(bound=True), OSError)
        self.assertEqual(self.core.read_task(self.state, "native", allow_native=True)["schema_version"], 4)
        self.validate(self.claim(bound=True))
        self.legacy_probe.assert_not_called()

    def test_ambiguous_native_claim_retains_committed_owner_and_capacity(self):
        self.create()
        atomic = self.core.atomic_json

        def ambiguous(path, value):
            atomic(path, value)
            if path.name == "task.json" and value["state"] == "Claimed":
                raise self.core.AmbiguousWriteError("fixture directory barrier failure")

        with mock.patch.object(self.core, "atomic_json", side_effect=ambiguous), self.assertRaises(self.core.AmbiguousWriteError):
            self.claim(bound=True)
        committed = self.core.read_task(self.state, "native", allow_bound=True, allow_native=True)
        self.validate(committed)
        self.core.verify_reservations(self.state, committed)
        self.assertEqual(committed["schema_version"], 5)
        self.assertEqual(committed["cooperative_binding"]["generation"], 1)

    def test_ordinary_native_lifecycle_and_exact_release(self):
        self.create()
        record = self.transition(self.claim(), "Implementing")
        lane = self.state / "implementation" / f"{record['leases']['implementation_lane']}.lock" / "owner.json"
        changed = copy.deepcopy(record["worker"])
        changed["process_identity"]["start_ticks"] = "999"
        self.core.atomic_json(lane, changed)
        self.assert_no_effect(lambda: self.transition(record, "Reviewing"))
        self.core.atomic_json(lane, record["worker"])
        record = self.transition(record, "Reviewing")
        self.assertIsNone(record["leases"]["implementation_lane"])
        record = self.transition(record, "Rework")
        self.assertIsNone(record["worker"])
        record = self.claim()
        self.assertEqual(record["schema_version"], 4)
        self.validate(self.transition(record, "Cancelled"))

    def test_native_implementation_requalifies_before_any_lane_or_task_effect(self):
        for bound in (False, True):
            name = f"qualification-{bound}"
            self.create(name)
            record = self.claim(name, bound=bound)
            context = {key: IDENTITY[key] for key in ("boot_id", "pid_namespace_inode")}

            def implement():
                return self.call("transition", name, "Implementing", *self.owned(record))

            for result in (("unknown", None), ("absent", None), ("alive", None),
                           ("alive", dict(IDENTITY, start_ticks="999")),
                           ("alive", dict(IDENTITY, boot_id="ffffffff-ffff-ffff-ffff-ffffffffffff")),
                           ("alive", dict(IDENTITY, pid_namespace_inode="42"))):
                with (self.subTest(schema=record["schema_version"], result=result),
                      mock.patch.object(self.core._observation, "_native_observation", return_value=result) as observe,
                      mock.patch.object(self.core, "reserve_first", side_effect=AssertionError("lane allocation attempted")),
                      mock.patch.object(self.core, "write_task", side_effect=AssertionError("task write attempted"))):
                    self.assert_no_effect(implement)
                    observe.assert_called_once_with(record["worker"]["pid"], context)
                    self.assertEqual(list((self.state / "implementation").iterdir()), [])
            with (mock.patch.object(self.core.socket, "gethostname", return_value=record["worker"]["hostname"] + "-other"),
                  mock.patch.object(self.core, "observe_worker_process") as observe,
                  mock.patch.object(self.core, "reserve_first", side_effect=AssertionError("lane allocation attempted"))):
                self.assert_no_effect(implement)
                observe.assert_not_called()
            with mock.patch.object(self.core._observation, "_native_observation", return_value=("alive", IDENTITY)) as observe:
                implementing = implement()
                observe.assert_called_once_with(record["worker"]["pid"], context)
            self.validate(implementing)
            self.assertEqual(implementing["worker"], record["worker"])
            self.transition(implementing, "Blocked")
        self.legacy_probe.assert_not_called()

    def test_native_implementation_wrong_context_wire_absence_has_no_effect(self):
        import json

        observation = self.core._observation
        context = {key: IDENTITY[key] for key in ("boot_id", "pid_namespace_inode")}
        for bound in (False, True):
            name = f"context-{bound}"
            self.create(name)
            record = self.claim(name, bound=bound)
            for key, changed in (("boot_id", "ffffffff-ffff-ffff-ffff-ffffffffffff"),
                                 ("pid_namespace_inode", "42")):
                def collect(command, key=key, changed=changed):
                    request = json.loads(command[-1])
                    self.assertEqual(request["expected_context"], context)
                    return json.dumps({"version": 1, "pid": request["pid"],
                                       "caller_tgid": request["caller_tgid"], "caller_tid": request["caller_tid"],
                                       "status": "absent", "identity": None,
                                       "context": dict(context, **{key: changed})}).encode("ascii")

                with (self.subTest(schema=record["schema_version"], context_key=key),
                      mock.patch.object(observation.sys, "platform", "linux"),
                      mock.patch.object(observation, "_trusted_helper", return_value=(Path("/fixture/helper"), b"fixture")),
                      mock.patch.object(observation, "_collect", side_effect=collect) as probe,
                      mock.patch.object(self.core, "reserve_first", side_effect=AssertionError("lane allocation attempted"))):
                    self.assert_no_effect(lambda: self.call("transition", name, "Implementing", *self.owned(record)))
                    probe.assert_called_once()
                    self.assertEqual(list((self.state / "implementation").iterdir()), [])
        self.legacy_probe.assert_not_called()

    def test_legacy_implementation_does_not_add_process_observation(self):
        for bound in (False, True):
            name = f"legacy-implementation-{bound}"
            self.create(name, native=False)
            record = self.claim(name, bound=bound)
            with mock.patch.object(self.core, "observe_worker_process", side_effect=AssertionError("legacy behavior changed")):
                implementing = self.transition(record, "Implementing")
            self.assertEqual(implementing["state"], "Implementing")
            self.validate(implementing)
            self.transition(implementing, "Blocked")

    def test_record_directed_absence_and_wrong_context_no_release(self):
        self.create()
        record = self.claim()
        expected_context = {key: IDENTITY[key] for key in ("boot_id", "pid_namespace_inode")}
        with mock.patch.object(self.core._observation, "_native_observation", return_value=("unknown", None)) as probe:
            self.assert_no_effect(lambda: self.call("reconcile", "native"))
            probe.assert_called_once_with(123, expected_context)
        changed = dict(IDENTITY, start_ticks="999")
        with mock.patch.object(self.core._observation, "_native_observation", return_value=("alive", changed)):
            self.assert_no_effect(lambda: self.call("reconcile", "native"))
        with mock.patch.object(self.core._observation, "_native_observation", return_value=("absent", None)):
            result = self.call("reconcile", "native")[0]
        self.assertEqual(result["state"], "Blocked")
        self.assertIsNone(result["worker"])
        self.assertFalse((self.state / "slots" / f"{record['leases']['global_slot']}.lock").exists())
        self.legacy_probe.assert_not_called()

    def test_wrong_boot_or_namespace_absence_reply_refuses_before_release(self):
        import json

        self.create()
        self.claim()
        observation = self.core._observation
        context = {key: IDENTITY[key] for key in ("boot_id", "pid_namespace_inode")}
        for key, changed in (("boot_id", "ffffffff-ffff-ffff-ffff-ffffffffffff"),
                             ("pid_namespace_inode", "42")):
            def collect(command, key=key, changed=changed):
                request = json.loads(command[-1])
                self.assertEqual(request["expected_context"], context)
                return json.dumps({"version": 1, "pid": request["pid"],
                                   "caller_tgid": request["caller_tgid"], "caller_tid": request["caller_tid"],
                                   "status": "absent", "identity": None,
                                   "context": dict(context, **{key: changed})}).encode("ascii")

            with (mock.patch.object(observation.sys, "platform", "linux"),
                  mock.patch.object(observation, "_trusted_helper", return_value=(Path("/fixture/helper"), b"fixture")),
                  mock.patch.object(observation, "_collect", side_effect=collect)):
                self.assert_no_effect(lambda: self.call("reconcile", "native"))
        self.legacy_probe.assert_not_called()

    def test_ordinary_intent_crash_reconciles_with_full_native_leases(self):
        self.create()
        record = self.transition(self.claim(), "Implementing")
        write = self.core.write_task

        def crash(root, value, **kwargs):
            write(root, value, **kwargs)
            if value["transition_intent"] == "Reviewing":
                raise RuntimeError("fixture ordinary crash")

        with mock.patch.object(self.core, "write_task", side_effect=crash), self.assertRaises(RuntimeError):
            self.transition(record, "Reviewing")
        with mock.patch.object(self.core._observation, "observe_worker_process", return_value=("unknown", None)):
            self.assert_no_effect(lambda: self.call("reconcile", "native"))
        with mock.patch.object(self.core._observation, "observe_worker_process", return_value=("alive", IDENTITY)):
            recovered = self.call("reconcile", "native")[0]
        self.assertEqual(recovered["state"], "Reviewing")
        self.assertEqual(recovered["schema_version"], 4)
        self.assertIsNone(recovered["leases"]["implementation_lane"])
        self.validate(recovered)

    def terminal_release_crash(self, *, bound=False, boundary="scopes"):
        """Crash after the real selected release, before the final task write."""
        self.create()
        record = self.transition(self.claim(bound=bound), "Implementing")
        release = self.core.release_dir

        def crash(path, token):
            release(path, token)
            if path.parent.name == boundary:
                raise RuntimeError("fixture terminal release crash")

        with mock.patch.object(self.core, "release_dir", side_effect=crash), self.assertRaisesRegex(RuntimeError, "terminal release crash"):
            self.transition(record, "Cancelled")
        interrupted = self.core.read_task(self.state, "native", allow_bound=True, allow_native=True)
        self.assertEqual(interrupted["state"], "Implementing")
        self.assertEqual(interrupted["transition_intent"], "Cancelled")
        self.assertEqual(interrupted["worker"], record["worker"])
        self.assertEqual(interrupted["revision"], record["revision"] + 1)
        self.assertEqual(list((self.state / "slots").iterdir()), [])
        self.assertEqual(list((self.state / "implementation").iterdir()), [])
        return interrupted

    def test_ordinary_terminal_scope_release_crash_stays_unverified(self):
        record = self.terminal_release_crash()
        scope = self.state / "scopes" / f"{record['scope_key']}.lock"
        self.assertFalse(scope.exists())
        with mock.patch.object(self.core, "observe_worker_process") as observe:
            self.assert_no_effect(lambda: self.call("reconcile", "native"))
            observe.assert_not_called()
        self.assertFalse(scope.exists())
        self.assert_no_effect(lambda: self.transition(record, "Cancelled"))
        # Reappearing or foreign metadata is not a substitute for the exact
        # retained scope; neither may be deleted by the recovery attempt.
        owner = {"schema_version": 2, "task_id": "native", "scope": record["scope"],
                 "token": record["leases"]["scope_token"]}
        scope.mkdir(mode=0o700)
        for changed in (dict(owner, token="f" * 32), dict(owner, task_id="foreign-task"),
                        dict(owner, scope="foreign:scope")):
            self.core.atomic_json(scope / "owner.json", changed)
            with mock.patch.object(self.core, "observe_worker_process") as observe:
                self.assert_no_effect(lambda: self.call("reconcile", "native"))
                observe.assert_not_called()
        # Exact metadata replay is indistinguishable from a retained scope in
        # this format. It must still pass the independent process guard; this
        # fixture does not claim authenticated scope continuity or replay proof.
        self.core.atomic_json(scope / "owner.json", owner)
        with mock.patch.object(self.core._observation, "observe_worker_process", return_value=("unknown", None)) as observe:
            self.assert_no_effect(lambda: self.call("reconcile", "native"))
            observe.assert_called_once_with(record["worker"], environment=None)

    def test_ordinary_terminal_capacity_release_with_retained_scope_can_finish(self):
        record = self.terminal_release_crash(boundary="implementation")
        scope = self.state / "scopes" / f"{record['scope_key']}.lock"
        self.assertTrue(scope.is_dir())
        with mock.patch.object(self.core._observation, "observe_worker_process", return_value=("alive", IDENTITY)):
            finished = self.call("reconcile", "native")[0]
        self.assertEqual(finished["state"], "Cancelled")
        self.assertIsNone(finished["transition_intent"])
        self.assertIsNone(finished["worker"])
        self.assertFalse(scope.exists())
        self.validate(finished)

    def test_cooperative_missing_scope_recovery_remains_refused(self):
        record = self.terminal_release_crash(bound=True)
        scope = self.state / "scopes" / f"{record['scope_key']}.lock"

        def recover():
            return self.call("reconcile", "--recover", "native", "--operator-action",
                             "--operator-reason", "fixture recovery", "--expected-generation", "1",
                             "--expected-revision", str(record["revision"]))

        with mock.patch.object(self.core._observation, "observe_worker_process", return_value=("absent", None)):
            self.assert_no_effect(recover)
            self.assertFalse(scope.exists())
            scope.mkdir(mode=0o700)
            self.core.atomic_json(scope / "owner.json", {
                "schema_version": 2, "task_id": "native", "scope": record["scope"], "token": "f" * 32})
            self.assert_no_effect(recover)
        unchanged = self.core.read_task(self.state, "native", allow_bound=True, allow_native=True)
        self.assertEqual(unchanged, record)
        self.assertNotIn("transition_recovery", unchanged)

    def test_cooperative_cancel_requires_contextual_absence(self):
        self.create()
        record = self.claim(bound=True)
        flags = ["--operator-action", "--operator-reason", "fixture cancellation",
                 "--expected-generation", "1", "--expected-revision", str(record["revision"])]
        with mock.patch.object(self.core._observation, "observe_worker_process", return_value=("unknown", None)):
            self.assert_no_effect(lambda: self.call("transition", "native", "Cancelled", *flags))
        with mock.patch.object(self.core._observation, "observe_worker_process", return_value=("absent", None)) as probe:
            cancelled = self.call("transition", "native", "Cancelled", *flags)
            self.assertEqual(probe.call_args.args[0], record["worker"])
        self.validate(cancelled)

    def test_mixed_capacity_and_reverse_native_leases(self):
        for index in range(6):
            name = f"task-{index}"
            self.create(name, native=index % 2 == 0)
            self.claim(name, bound=index % 3 == 0)
        self.create("overflow")
        self.assert_no_effect(lambda: self.claim("overflow"), self.core.BusyError)
        native = self.core.read_task(self.state, "task-0", allow_bound=True, allow_native=True)
        extra = self.state / "implementation/1.lock"
        self.core.acquire_dir(extra, native["worker"])
        self.assert_no_effect(lambda: self.claim("overflow"))

    def test_native_recovery_crash_receipt_and_reclaim(self):
        self.create()
        record = self.transition(self.claim(bound=True), "Implementing")
        write = self.core.write_task

        def crash(root, value, **kwargs):
            write(root, value, **kwargs)
            if value["transition_intent"] == "Blocked":
                raise RuntimeError("fixture durable intent crash")

        with mock.patch.object(self.core, "write_task", side_effect=crash), self.assertRaises(RuntimeError):
            self.transition(record, "Blocked")
        interrupted = self.core.read_task(self.state, "native", allow_bound=True, allow_native=True)

        def recover(value):
            return self.call("reconcile", "--recover", "native", "--operator-action",
                             "--operator-reason", "fixture recovery", "--expected-generation", "1",
                             "--expected-revision", str(value["revision"]))[0]

        with mock.patch.object(self.core._observation, "observe_worker_process", return_value=("unknown", None)):
            self.assert_no_effect(lambda: recover(interrupted))
        release = self.core.release_dir

        def release_crash(path, token):
            release(path, token)
            if path.parent.name == "slots":
                raise RuntimeError("fixture release crash")

        with (mock.patch.object(self.core._observation, "observe_worker_process", return_value=("absent", None)),
              mock.patch.object(self.core, "release_dir", side_effect=release_crash), self.assertRaises(RuntimeError)):
            recover(interrupted)
        pending = self.core.read_task(self.state, "native", allow_bound=True, allow_native=True)
        self.validate(pending)
        self.assertEqual(pending["transition_recovery"]["version"], 1)
        self.assertEqual(pending["transition_recovery"]["task_schema_version"], 5)
        with mock.patch.object(self.core._observation, "observe_worker_process", return_value=("absent", None)):
            settled = recover(pending)
        self.validate(settled)
        for field in ("version", "task_schema_version"):
            broken = copy.deepcopy(settled)
            broken["transition_recovery"].pop(field)
            with self.assertRaises(self.core.UnknownError):
                self.core.validate_record(broken, allow_bound=True, allow_native=True)
        ready = self.call("transition", "native", "Ready", "--operator-action", "--operator-reason", "fixture retry",
                          "--expected-generation", "1", "--expected-revision", str(settled["revision"]))
        reclaimed = self.claim(bound=True, generation=1, revision=ready["revision"])
        self.assertEqual(reclaimed["schema_version"], 5)
        self.assertEqual(reclaimed["cooperative_binding"]["generation"], 2)
        self.validate(reclaimed)

    def test_legacy_observation_seam_and_global_cooperative_fence(self):
        self.create("legacy", native=False)
        record = self.claim("legacy")
        self.assertEqual(record["worker"]["process_start"], "arbitrary\nlegacy start")
        self.core.observe_worker_process(record["worker"], environment={"LC_ALL": "C"})
        self.legacy_probe.assert_called_with(123, environment={"LC_ALL": "C"})
        self.create()
        self.claim(bound=True)
        self.legacy_probe.return_value = ("absent", None)
        self.assert_no_effect(lambda: self.call("reconcile", "legacy"))


if __name__ == "__main__":
    unittest.main()
