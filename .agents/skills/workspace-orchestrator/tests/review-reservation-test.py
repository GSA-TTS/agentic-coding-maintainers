#!/usr/bin/env python3
"""Focused production CLI reservation groundwork; synthetic fixtures, no model."""

import contextlib
import copy
import importlib.util
import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


spec = importlib.util.spec_from_file_location("handoff_fixture", Path(__file__).with_name("foreground-handoff-test.py"))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
c, delivery = fixture.fixture.c, fixture.fixture.delivery


class ReservationCLI(fixture.HandoffCLI):
    def setUp(self):
        self.worker_process = None
        if "dead_worker" in self._testMethodName:
            self.worker_process = subprocess.Popen([sys.executable, "-I", "-B", "-c", "import time; time.sleep(600)"])
            self.addCleanup(self.stop_worker)
        super().setUp()

    def stop_worker(self):
        if self.worker_process is not None:
            self.worker_process.terminate()
            self.worker_process.wait(timeout=10)

    def cli(self, *args, expected=0):
        if self.worker_process is not None and args[:2] == ("state", "claim"):
            args = list(args)
            args[args.index("--pid") + 1] = str(self.worker_process.pid)
        return super().cli(*args, expected=expected)

    def reserve_request(self):
        self.exported = self.dispatch(self.export_request())
        request = self.request("reserve-review-attempt", "reserve")
        request["payload"] = {"admission_id": self.admission_id, "bundle_sha256": self.exported["bundle_sha256"],
            "destination": {"backend": "docker", "sandbox_id": "a" * 64,
                "created": "2026-11-04T00:00:00Z", "endpoint_sha256": "b" * 64,
                "result_root": "/review-results/attempt"}}
        return request

    def cancel_request(self):
        request = self.request("cancel-review-reservation", "cancel")
        request["payload"] = {"admission_id": self.admission_id}
        return request

    def test_reservation_replay_frozen_export_pause_cancel_and_supersession(self):
        self.admitted()
        request = self.reserve_request()
        result = self.dispatch(request)
        self.assertEqual(result["status"], "RESERVED")
        self.assertFalse(result["domain_result"]["launch_authorized"])
        before = self.task_path.read_bytes()
        alternate = self.root / "alternate-request.json"
        alternate.write_bytes(c.canonical(request))
        self.assertEqual(self.cli("foreground-delivery", "fixture", "--request", str(alternate)), result)
        self.assertEqual(self.task_path.read_bytes(), before)
        for changed in ({**request, "operation_id": "again", "expected_revision": self.record()["revision"]},
                        {**request, "payload": {**request["payload"], "destination": {
                            **request["payload"]["destination"], "result_root": "/review-results/other"}}}):
            self.dispatch(changed, expected=3)
        self.assertEqual(self.dispatch(self.export_request()), self.exported)
        self.cli("state", "update-head", "fixture", self.adopted_head, expected=3)
        self.cli("state", "record", "fixture", "validation", "unexpected", expected=3)
        self.cli("state", "transition", "fixture", "Reviewing", expected=3)
        self.fresh_bundle()
        self.dispatch(self.request("collect-review", "no-spawn"), expected=3, bundle=True)
        self.dispatch(self.request("pause", "pause-reserved"))
        self.assertEqual(self.dispatch(self.export_request()), self.exported)
        cancel = self.cancel_request()
        cancelled = self.dispatch(cancel)
        self.assertEqual(cancelled["status"], "CANCELLED_UNCONSUMED")
        self.assertEqual(self.dispatch(cancel), cancelled)
        self.dispatch(self.request("resume", "resume-cancelled"))
        self.dispatch(self.request("collect-review", "still-no-consumer"), expected=3, bundle=True)
        self.dispatch({**self.request("consume-review-attempt"), "payload": {"admission_id": self.admission_id}}, expected=3)
        self.dispatch({**request, "operation_id": "new-reserve", "expected_revision": self.record()["revision"]}, expected=3)
        self.git("commit", "--allow-empty", "-qm", "test: supersede reserved head")
        self.cli("state", "update-head", "fixture", self.git("rev-parse", "HEAD").strip())
        self.assertEqual(self.dispatch(self.export_request()), self.exported)
        self.cli("state", "transition", "fixture", "Reviewing")
        self.cli("state", "transition", "fixture", "Rework")
        self.cli("state", "claim", "fixture", "--owner", "writer", "--pid", str(os.getpid()))
        self.cli("state", "transition", "fixture", "Implementing")
        self.assertEqual(self.dispatch(self.export_request()), self.exported)

    def test_reservation_metadata_links_artifact_and_origin_loss(self):
        self.admitted()
        request = self.reserve_request()
        self.dispatch({**request, "payload": {**request["payload"], "bundle_sha256": "0" * 64}}, expected=3)
        for field, value in (("endpoint", "http://localhost"), ("backend", "shell"), ("sandbox_id", "--flag"),
                             ("result_root", "/tmp/other"), ("created", "bad")):
            self.dispatch({**request, "payload": {**request["payload"], "destination": {
                **request["payload"]["destination"], field: value}}}, expected=3)
        self.git("remote", "set-url", "origin", "https://github.com/other/project")
        self.dispatch(request, expected=3)
        self.git("remote", "set-url", "origin", "https://github.com/fixture/project.git")
        saved = self.record()
        for damage in ("owner", "worker", "scope", "epoch", "head"):
            changed = copy.deepcopy(saved)
            if damage == "owner":
                changed["owner"] = "other"
            elif damage == "worker":
                changed["worker"]["worker_id"] = "0" * 32
            elif damage == "scope":
                changed["owned_paths"] = ["elsewhere"]
            elif damage == "epoch":
                changed["review_protocol"]["material_epoch"] += 1
            else:
                changed["head_sha"] = self.head
            self.store_record(changed)
            self.dispatch(request, expected=3)
            self.store_record(saved)
        self.dispatch(request)
        saved = self.record()
        for damage in ("marker", "ledger", "receipt", "reverse", "schema", "pointer", "worker"):
            changed = copy.deepcopy(saved)
            if damage == "marker":
                del changed["review_reservations_initialized"]
            elif damage == "ledger":
                del changed["review_reservations"]
            elif damage == "receipt":
                del changed["foreground_control"]["receipts"]["reserve"]
            elif damage == "reverse":
                changed["review_reservations"]["admissions"] = {}
            elif damage == "schema":
                changed["review_reservations"]["schema_version"] = True
            else:
                item = changed["review_reservations"]["admissions"][self.admission_id]
                if damage == "pointer":
                    item["bundle_sha256"] = "0" * 64
                else:
                    item["worker"]["worker_id"] = "0" * 32
            self.store_record(changed)
            self.dispatch(self.cancel_request(), expected=3)
            self.store_record(saved)
        for path in (self.state_root / "review-handoffs" / self.exported["bundle_sha256"],
                     self.state_root / "review-packets" / (self.exported["bundle"]["binding"]["packet"] + ".json")):
            moved = path.with_suffix(".missing")
            path.rename(moved)
            try:
                self.dispatch(self.cancel_request(), expected=3)
                self.dispatch(self.export_request(), expected=3)
            finally:
                moved.rename(path)
        self.dispatch(self.cancel_request())

    def test_reservation_capacity_write_failure_and_dead_worker_recovery(self):
        self.admitted()
        request = self.reserve_request()
        coordinator = delivery.dependency("orchestrator-state")
        dependency = delivery.dependency
        path = self.root / "failure-request.json"
        path.write_bytes(c.canonical(request))
        before = self.task_path.read_bytes()
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(sys, "argv", ["foreground-delivery", "fixture", "--request", str(path)]), \
                mock.patch.object(delivery, "dependency", side_effect=lambda name: coordinator if name == "orchestrator-state" else dependency(name)), \
                mock.patch.object(coordinator, "write_task", side_effect=OSError("injected write failure")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(delivery.main(), 3)
        self.assertEqual(self.task_path.read_bytes(), before)
        reservation = delivery.dependency("review-reservation")
        with mock.patch.object(reservation.os, "fsync", side_effect=OSError("injected artifact fsync failure")):
            with self.assertRaises(OSError):
                reservation.apply(copy.deepcopy(self.record()), request, self.state_root)
        self.assertEqual(self.task_path.read_bytes(), before)
        # Fill via the real dispatcher in-process (compiled-cache fixture), then
        # exercise capacity and cancellation through fresh public CLI processes.
        while len(self.record()["foreground_control"]["receipts"]) + delivery.dependency("foreground-repair").count(self.record()) < 62:
            current = self.record()
            pause = self.request("resume", "fill-" + str(current["revision"]))
            updated, _, changed = delivery.dispatch(current, pause, self.state_root)
            self.assertTrue(changed)
            coordinator.write_task(self.state_root, updated)
        request = self.reserve_request()
        # At 63 occupied receipts the proposed reservation cannot also retain its
        # cancellation. Exercise the actual dispatcher budget, without a write.
        current = self.record()
        updated, _, _ = delivery.dispatch(current, self.request("resume", "too-full"), self.state_root)
        updated["revision"] += 1
        overfull = {**request, "expected_revision": updated["revision"]}
        exported = delivery.dependency("review-handoff").export_admitted(updated, overfull, self.state_root)
        overfull["payload"] = {**overfull["payload"], "bundle_sha256": exported["bundle_sha256"]}
        with self.assertRaisesRegex(Exception, "capacity"):
            delivery.dispatch(updated, overfull, self.state_root)
        self.dispatch(request)
        # Exact production wire-size check, with large but valid task metadata.
        large = self.record()
        large["validation"] = ["x" * 1000] * 200
        large["findings"] = ["y" * 1000] * 200
        large["dependencies"] = ["z" * 1000] * 200
        large["reviewers"] = ["w" * 1000] * 200
        large["restricted_paths"] = ["r" * 1000] * 200
        large["next_action"] = "n" * 2000
        with self.assertRaises(Exception):
            reservation.cancellation_budget(large)
        self.dispatch(self.request("pause", "capacity-pause"), expected=3)
        cancel = self.cancel_request()
        self.stop_worker()
        self.cli("state", "reconcile", "fixture", expected=3)
        self.assertIsNotNone(self.record()["worker"])
        # Cancellation write failure must preserve the blocking reservation.
        path.write_bytes(c.canonical(cancel))
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(sys, "argv", ["foreground-delivery", "fixture", "--request", str(path)]), \
                mock.patch.object(delivery, "dependency", side_effect=lambda name: coordinator if name == "orchestrator-state" else dependency(name)), \
                mock.patch.object(coordinator, "write_task", side_effect=OSError("injected cancel failure")), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(Exception):
                coordinator.require_repair_settled(self.record(), root=self.state_root)
            self.assertEqual(delivery.main(), 3)
        self.assertEqual(self.record()["review_reservations"]["admissions"][self.admission_id]["phase"], "RESERVED")
        self.dispatch(cancel)
        self.assertEqual(self.record()["review_reservations"]["admissions"][self.admission_id]["phase"], "CANCELLED_UNCONSUMED")
        self.assertEqual(len(self.record()["foreground_control"]["receipts"]) + delivery.dependency("foreground-repair").count(self.record()), 64)
        self.assertEqual(self.dispatch(self.export_request()), self.exported)
        self.cli("state", "reconcile", "fixture")
        self.assertIsNone(self.record()["worker"])
        self.assertEqual(self.record()["state"], "Blocked")


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(ReservationCLI(name) for name in loader.getTestCaseNames(ReservationCLI)
                              if name.startswith("test_reservation_"))


if __name__ == "__main__":
    unittest.main()
