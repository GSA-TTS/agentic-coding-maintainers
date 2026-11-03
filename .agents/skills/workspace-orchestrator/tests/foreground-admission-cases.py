"""Prepared-review bridges, using the existing real CLI fixture and diagnostics."""

import base64
import contextlib
import copy
import io
import json
import os
import sys
from unittest import mock


def install(base, delivery, c):
    class AdmissionTests(base):
        @classmethod
        def setUpClass(cls):
            # Amortize the unchanged repair/preparation prefix. Each case restores
            # task bytes; immutable artifacts may accumulate but confer no credit.
            cls.fixture = base("test_fresh_cli_original_base_union_one_revision_and_historical_replay")
            cls.addClassCleanup(cls.fixture.doCleanups)
            cls.fixture.setUp()
            cls.prepare_request = cls.fixture.prepare_fresh()
            cls.prepare_result = cls.fixture.dispatch(cls.prepare_request)
            cls.prepared_record = cls.fixture.record()

        def setUp(self):
            self.__dict__.update({k: v for k, v in self.fixture.__dict__.items()
                                 if not k.startswith("_test") and k != "_cleanups"})
            self.store_record(copy.deepcopy(self.prepared_record))
            self.addCleanup(self.store_record, copy.deepcopy(self.prepared_record))

        def assign_request(self, operation="assign-fresh"):
            request = self.request("assign-prepared-review", operation)
            request["payload"] = {"prepare_operation_id": "fresh", "run_id": "fresh-run", "reviewer": "independent",
                                  "profile": "e" * 64, "session": "ses_fresh"}
            return request

        def admit_request(self, operation="admit-fresh"):
            request = self.request("admit-prepared-review", operation)
            request["payload"] = {"assign_operation_id": "assign-fresh", "binary_sha256": "f" * 64,
                "model": "fixture/model", "agent": "reviewer", "cwd": "/review",
                "sources": {"/candidate/source.py": {"path_base64": base64.b64encode(b"source.py").decode(), "side": "after"}}}
            return request

        def admitted(self):
            assignment = self.assign_request()
            assigned = self.dispatch(assignment)
            admission = self.admit_request()
            admitted = self.dispatch(admission)
            self.admission_id = admitted["domain_result"]["admission_id"]
            return assignment, assigned, admission, admitted

        def fresh_bundle(self, findings=None):
            admitted = self.record()["runtime_collections"]["admissions"][self.admission_id]
            final = json.dumps({"schema_version": 1, "coverage": dict.fromkeys(admitted["assignment"]["obligations"], "reviewed"),
                "findings": findings or [], "dispositions": [{"finding_id": "F1", "resolution": "fixed",
                "counterevidence": "synthetic fresh source inspection"}], "limitations": ["synthetic claims only"]})
            session = admitted["assignment"]["session"]
            events = [{"type": "tool_use", "sessionID": session, "part": {"tool": "read", "state": {
                "status": "completed", "input": {"path": "/candidate/source.py"},
                "output": "Read file /candidate/source.py, lines 1-1\n1: result = 2"}}},
                {"type": "text", "sessionID": session, "part": {"text": final}},
                {"type": "step_finish", "sessionID": session, "part": {"reason": "stop", "tokens": {"input": 100, "output": 10}}}]
            transcript = b"".join(c.canonical(event) for event in events)
            exported = c.canonical({"info": {"id": session, "outcome": "succeeded", "agent": "reviewer",
                "model": {"providerID": "fixture", "id": "model"}, "tokens": {"input": 100, "output": 10}},
                "messages": [{"type": "assistant", "finish": "stop", "content": [{"type": "text", "text": final}]}]})
            receipt = {name: admitted[name] for name in ("binary_sha256", "model", "agent", "source_sha256")}
            receipt.update(profile_sha256=admitted["assignment"]["profile"], context_sha256=c.digest(c.canonical(admitted["context"])),
                sessions=[session], transcript_sha256=c.digest(transcript), stderr_sha256=c.digest(b""), returncode=0,
                status="REVIEW_OBSERVED", execution_credit=False, candidate_ready=False,
                source_reads=["/candidate/source.py"], final_text=final, tokens={"input": 100, "output": 10})
            self.bundle = {"receipt.json": c.canonical(receipt), "transcript.jsonl": transcript,
                           "session-export.json": exported, "stderr.txt": b"", "export-stderr.txt": b""}
            self.write_bundle()

        def test_admission_cli_distinct_revisions_context_and_fresh_disposition(self):
            before = self.record()
            self.assertEqual(self.dispatch()["preparation_progress"]["next_action"], "ASSIGN_PREPARED_REVIEW")
            assignment = self.assign_request()
            assigned = self.dispatch(assignment)
            self.assertEqual(self.dispatch()["preparation_progress"]["pending_assign_operation_ids"], ["assign-fresh"])
            admission = self.admit_request()
            admitted = self.dispatch(admission)
            self.admission_id = admitted["domain_result"]["admission_id"]
            retained = self.record()["runtime_collections"]["admissions"][self.admission_id]
            e = delivery.dependency("review-evidence")
            self.assertEqual(retained["context"]["finding_history"], e.finding_history(before))
            self.assertEqual(retained["context"]["acceptance_criteria"], before["acceptance_criteria"])
            self.assertEqual(retained["context"]["obligations"], before["review_protocol"]["generations"][-1]["obligations"])
            self.assertEqual(retained["assignment"]["adapter"], "native-session")
            self.assertEqual(self.dispatch()["preparation_progress"]["admission_count"], 1)
            self.assertEqual(self.dispatch()["preparation_progress"]["next_action"], "PREPARATION_COMPLETE")
            self.fresh_bundle()
            collected = self.dispatch(self.request("collect-review", "fresh-collect"), bundle=True)
            accepted = self.dispatch(self.request("accept-review", "fresh-accept"))
            self.assertEqual([r["resulting_revision"] for r in (self.prepare_result, assigned, admitted, collected, accepted)],
                             list(range(before["revision"], before["revision"] + 5)))
            self.assertEqual(e.assess(self.record())["unresolved_findings"], [])
            self.assertEqual(self.record()["review_protocol"]["generations"][0], before["review_protocol"]["generations"][0])
            for field in ("worker", "leases", "state", "head_sha", "base_sha"):
                self.assertEqual(self.record()[field], before[field])

        def test_admission_changed_binding_and_owner_session_refused(self):
            request = self.assign_request()
            for field, value in (("reviewer", "writer"), ("session", "ses_owner"), ("prepare_operation_id", "adopt"),
                                 ("obligations", ["security"]), ("profile", "invalid")):
                self.dispatch({**request, "payload": {**request["payload"], field: value}}, expected=3)
            self.dispatch(request)
            for field, value in (("profile", "d" * 64), ("session", "ses_changed"), ("reviewer", "changed")):
                self.dispatch({**request, "payload": {**request["payload"], field: value}}, expected=3)
            admit = self.admit_request()
            self.dispatch({**admit, "payload": {**admit["payload"], "context": {}}}, expected=3)
            self.dispatch({**admit, "payload": {**admit["payload"], "assign_operation_id": "fresh"}}, expected=3)
            self.dispatch(admit)
            for field, value in (("model", "other/model"), ("cwd", "/other"), ("sources", {})):
                self.dispatch({**admit, "payload": {**admit["payload"], field: value}}, expected=3)

        def test_admission_current_guards_pause_stale_worker_source(self):
            helper = delivery.dependency("foreground-admission")
            for assigned in (False, True):
                self.store_record(copy.deepcopy(self.prepared_record))
                if assigned:
                    self.dispatch(self.assign_request())
                request = self.admit_request() if assigned else self.assign_request()
                saved = self.record()
                for field in ("worker", "owner", "epoch", "generation", "acceptance", "scope", "head"):
                    changed = copy.deepcopy(saved)
                    if field == "worker":
                        changed["worker"]["worker_id"] = "d" * 32
                    elif field == "owner":
                        changed["owner"] = "other"
                    elif field == "epoch":
                        changed["review_protocol"]["material_epoch"] += 1
                    elif field == "generation":
                        changed["review_protocol"]["generations"].append(copy.deepcopy(changed["review_protocol"]["generations"][-1]))
                        changed["review_protocol"]["generations"][-1]["number"] += 1
                    elif field == "acceptance":
                        changed["acceptance_criteria"] = ["changed"]
                    elif field == "scope":
                        changed["owned_paths"] = ["elsewhere"]
                    else:
                        changed["head_sha"] = self.head
                    with self.subTest(assigned=assigned, field=field), self.assertRaises(Exception):
                        helper.apply(changed, request, self.state_root)
                self.dispatch({**request, "expected_revision": saved["revision"] - 1}, expected=3)
                self.dispatch(self.request("pause", "pause-admission"))
                self.dispatch({**request, "expected_revision": self.record()["revision"]}, expected=3)
                self.store_record(saved)
                path = self.worktree / "auth-policy.txt"
                original = path.read_bytes()
                try:
                    path.write_bytes(b"changed outside selected source\n")
                    self.dispatch(request, expected=3)
                finally:
                    path.write_bytes(original)
                changed = copy.deepcopy(saved)
                changed["worker"]["process_start"] = "lost"
                self.store_record(changed)
                self.dispatch(request, expected=3)

        def test_admission_missing_replaced_links_both_directions(self):
            assignment, _, admission, _ = self.admitted()
            saved = self.record()
            e = delivery.dependency("review-evidence")
            for operation, table, prefix in (("assign-fresh", "review_protocol", "fgassign."),
                                              ("admit-fresh", "runtime_collections", "fgadmit.")):
                key = saved["foreground_control"]["receipts"][operation]["reference"]["key"]
                for damage in ("receipt", "domain", "parent", "packet", "request", "result"):
                    changed = copy.deepcopy(saved)
                    receipt = changed["foreground_control"]["receipts"][operation]
                    if damage == "receipt":
                        del changed["foreground_control"]["receipts"][operation]
                        with self.assertRaises(Exception):
                            e.validate_prepared_links(changed, changed[table]["operations"], prefix)
                    elif damage == "domain":
                        del changed[table]["operations"][key]
                    elif damage == "parent":
                        field = "prepare_operation_id" if table == "review_protocol" else "assign_operation_id"
                        receipt["request"]["payload"][field] = "other"
                    elif damage == "packet":
                        receipt["reference"]["packet"] = "a" * 64
                    elif damage == "request":
                        changed[table]["operations"][key]["request"]["payload"]["run_id"] = "other"
                    else:
                        receipt["result"]["domain_result"]["resulting_revision"] -= 1
                    with self.subTest(operation=operation, damage=damage), self.assertRaises(Exception):
                        delivery.validate_retained(changed, self.state_root, c, e)
            self.store_record(saved)
            packet = self.state_root / "review-packets" / (saved["review_protocol"]["generations"][-1]["packet"] + ".json")
            moved = packet.with_suffix(".missing")
            packet.rename(moved)
            try:
                self.dispatch(admission, expected=3)
            finally:
                moved.rename(packet)
            for prefix in ("fgassign.", "fgadmit."):
                self.dispatch({**assignment, "operation_id": prefix + "reserved"}, expected=3)
            # A shared revision exception cannot bless a second control action.
            changed = copy.deepcopy(saved)
            collision = self.request("pause", "colliding-pause")
            collision["expected_revision"] = admission["expected_revision"]
            changed["foreground_control"]["paused"] = True
            changed["foreground_control"]["receipts"]["colliding-pause"] = {
                "request": collision, "request_sha256": c.digest(c.canonical(collision)), "reference": None,
                "result": delivery.acknowledgement(collision, {"status": "PAUSED"})}
            with self.assertRaises(Exception):
                delivery.validate_retained(changed, self.state_root, c, e)

        def test_admission_later_report_replay_uses_historical_context(self):
            assignment, assigned, admission, admitted = self.admitted()
            context = copy.deepcopy(self.record()["runtime_collections"]["admissions"][self.admission_id]["context"])
            self.fresh_bundle([{"id": "F2", "invariant": "fresh invariant", "trigger": "inspection", "path": "source.py:1",
                                "impact": "fresh defect", "evidence": "synthetic fresh observation"}])
            self.dispatch(self.request("collect-review", "fresh-collect"), bundle=True)
            self.dispatch(self.request("accept-review", "fresh-accept"))
            status = self.dispatch()
            self.assertEqual(status["next_action"], "OWNER_REWORK_ADMISSION_REQUIRED")
            self.assertEqual(status["review_claims"]["unresolved_findings"], ["F2"])
            self.assertNotIn("F2", context["finding_history"])
            self.assertEqual(self.record()["runtime_collections"]["admissions"][self.admission_id]["context"], context)
            self.dispatch(self.request("pause", "later-pause"))
            path = self.worktree / "source.py"
            raw = path.read_bytes()
            self.git("commit", "--allow-empty", "-qm", "test: later replay head")
            self.cli("state", "update-head", "fixture", self.git("rev-parse", "HEAD").strip())
            self.git("remote", "set-url", "origin", "https://github.com/other/project")
            try:
                path.write_bytes(b"later dirty source\n")
                self.assertEqual(self.dispatch(assignment), assigned)
                self.assertEqual(self.dispatch(admission), admitted)
                helper = delivery.dependency("foreground-review")
                capture = helper.load("review-packet")
                original_load, original_dependency = helper.load, delivery.dependency
                with mock.patch.object(capture, "capture", side_effect=AssertionError("no recapture")), \
                        mock.patch.object(helper, "load", side_effect=lambda name: capture if name == "review-packet" else original_load(name)), \
                        mock.patch.object(delivery, "dependency", side_effect=lambda name: helper if name == "foreground-review" else original_dependency(name)):
                    _, replay, changed = delivery.dispatch(self.record(), admission, self.state_root)
                    self.assertEqual(replay, admitted)
                    self.assertFalse(changed)
            finally:
                path.write_bytes(raw)
                self.git("reset", "--hard", self.adopted_head)
                self.git("remote", "set-url", "origin", "https://github.com/fixture/project.git")

        def test_admission_context_bound_refuses_without_truncation(self):
            self.dispatch(self.assign_request())
            e = delivery.dependency("review-evidence")
            generation = self.record()["review_protocol"]["generations"][-1]
            self.domain("review-evidence", "assign", {"generation": 2, "run_id": "context-run", "reviewer": "context-reviewer",
                "profile": "d" * 64, "session": "ses_context", "adapter": "native-session",
                "obligations": generation["obligations"]}, "context-assign")
            finding = e.finding_history(self.record())["F1"]["finding"]
            self.domain("review-evidence", "accept", {"generation": 2, "run_id": "context-run", "packet": generation["packet"],
                "policy": generation["policy"], "profile": "d" * 64, "session": "ses_context",
                "coverage": dict.fromkeys(generation["obligations"], "reviewed"), "dispositions": [], "limitations": [],
                "findings": [{**finding, "id": "large-" + str(i), "evidence": "x" * 2000} for i in range(30)]}, "context-accept")
            saved = self.record()
            with self.assertRaisesRegex(Exception, "no truncation"):
                e.prepared_admission(saved, self.admit_request())
            self.dispatch(self.admit_request(), expected=3)
            self.assertEqual(self.record(), saved)
            self.assertEqual(self.dispatch()["preparation_progress"]["next_action"], "ADMIT_PREPARED_REVIEW")

        def test_admission_one_write_failure_preserves_assignment(self):
            self.dispatch(self.assign_request())
            saved = self.record()
            request = self.admit_request()
            coordinator = delivery.dependency("orchestrator-state")
            dependency = delivery.dependency
            path = self.root / "admission-failure.json"
            path.write_bytes(c.canonical(request))
            with mock.patch.dict(os.environ, self.env, clear=True), \
                    mock.patch.object(sys, "argv", ["foreground-delivery", "fixture", "--request", str(path)]), \
                    mock.patch.object(delivery, "dependency", side_effect=lambda name: coordinator if name == "orchestrator-state" else dependency(name)), \
                    contextlib.redirect_stdout(io.StringIO()):
                with mock.patch.object(coordinator, "write_task", side_effect=OSError("injected task failure")) as writes:
                    self.assertEqual(delivery.main(), 3)
                    self.assertEqual(writes.call_count, 1)
                self.assertEqual(self.record(), saved)
                with mock.patch.object(coordinator, "write_task", wraps=coordinator.write_task) as writes:
                    self.assertEqual(delivery.main(), 0)
                    self.assertEqual(writes.call_count, 1)
            self.assertEqual(self.record()["revision"], saved["revision"] + 1)

        def test_admission_source_narrowing_never_removes_obligations(self):
            self.dispatch(self.assign_request())
            request = self.admit_request()
            invalid = copy.deepcopy(request)
            invalid["payload"]["sources"]["/candidate/source.py"]["path_base64"] = base64.b64encode(b"not-in-packet").decode()
            self.dispatch(invalid, expected=3)
            result = self.dispatch(request)
            self.admission_id = result["domain_result"]["admission_id"]
            admitted = self.record()["runtime_collections"]["admissions"][self.admission_id]
            generation = self.record()["review_protocol"]["generations"][-1]
            self.assertEqual(len(admitted["sources"]), 1)
            self.assertEqual(admitted["assignment"]["obligations"], generation["obligations"])
            self.assertTrue({"trust-boundary", "historical-specialist"} <= set(admitted["context"]["obligations"]))
            self.fresh_bundle()
            original = copy.deepcopy(self.bundle)
            for field, value in (("context_sha256", "0" * 64), ("sessions", ["ses_other"]),
                                 ("profile_sha256", "0" * 64), ("source_sha256", {})):
                self.bundle = copy.deepcopy(original)
                receipt = c.decode(self.bundle["receipt.json"])
                receipt[field] = value
                self.bundle["receipt.json"] = c.canonical(receipt)
                self.write_bundle()
                self.dispatch(self.request("collect-review", "bad-collection"), expected=3, bundle=True)
            self.bundle = original
            self.write_bundle()
            self.dispatch(self.request("collect-review", "fresh-collect"), bundle=True)
            self.dispatch(self.request("accept-review", "fresh-accept"))

    return AdmissionTests
