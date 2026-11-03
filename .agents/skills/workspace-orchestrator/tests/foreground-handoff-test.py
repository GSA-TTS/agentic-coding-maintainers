#!/usr/bin/env python3
"""Three real foreground CLI cases; explicitly select tests, no inherited suites."""

import copy
import importlib.util
import unittest
from pathlib import Path


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = load("foreground-delivery-test")
adopt = load("foreground-adopt-cases").install(fixture.ForegroundTests, fixture.delivery, fixture.c)
fresh = load("foreground-review-cases").install(adopt, fixture.delivery, fixture.c)
admission = load("foreground-admission-cases").install(fresh, fixture.delivery, fixture.c)


class HandoffCLI(admission):
    def export_request(self):
        request = self.request("export-admitted-review", "export")
        request["payload"] = {"admission_id": self.admission_id}
        return request

    def test_handoff_exact_context_no_task_write(self):
        self.admitted()
        before = self.task_path.read_bytes()
        result = self.dispatch(self.export_request())
        self.assertEqual(result["status"], "REVIEW_HANDOFF_EXPORTED")
        self.assertEqual(self.task_path.read_bytes(), before)
        value = result["bundle"]
        admitted = self.record()["runtime_collections"]["admissions"][self.admission_id]
        self.assertEqual(fixture.c.canonical(value["context"]), fixture.c.canonical(admitted["context"]))
        self.assertEqual(value["binding"]["admission_revision"], admitted["admission_revision"])
        self.assertEqual(value["binding"]["export_revision"], self.record()["revision"])
        self.assertEqual(result, self.dispatch(self.export_request()))
        self.assertEqual(self.task_path.read_bytes(), before)
        self.assertNotIn(str(self.worktree), fixture.c.canonical(value).decode())
        self.assertEqual(len(value["sources"]), 1)
        generation = self.record()["review_protocol"]["generations"][-1]
        self.domain("review-evidence", "assign", {"generation": 2, "run_id": "later", "reviewer": "later-reviewer",
            "profile": "d" * 64, "session": "ses_later", "adapter": "native-session",
            "obligations": generation["obligations"]}, "later-assign")
        self.domain("review-evidence", "accept", {"generation": 2, "run_id": "later", "packet": generation["packet"],
            "policy": generation["policy"], "profile": "d" * 64, "session": "ses_later",
            "coverage": dict.fromkeys(generation["obligations"], "reviewed"), "dispositions": [], "limitations": [],
            "findings": [{"id": "F2", "invariant": "later", "trigger": "inspection", "path": "source.py:1",
                          "impact": "later defect", "evidence": "synthetic"}]}, "later-accept")
        later = self.dispatch(self.export_request())["bundle"]
        self.assertEqual(later["context"], value["context"])
        self.assertNotIn("F2", later["context"]["finding_history"])
        self.fresh_bundle()
        self.dispatch(self.request("collect-review", "collected"), bundle=True)
        self.dispatch(self.export_request(), expected=3)

    def test_handoff_stale_pause_owner_source_origin_and_links(self):
        self.admitted()
        request = self.export_request()
        self.dispatch({**request, "expected_revision": request["expected_revision"] - 1}, expected=3)
        self.dispatch({**request, "incarnation": "0" * 64}, expected=3)
        saved = self.record()
        for field in ("owner", "worker", "scope", "epoch", "link"):
            changed = copy.deepcopy(saved)
            if field == "worker":
                changed["worker"]["worker_id"] = "d" * 32
            elif field == "owner":
                changed["owner"] = "other"
            elif field == "scope":
                changed["owned_paths"] = ["other.py"]
            elif field == "epoch":
                changed["review_protocol"]["material_epoch"] += 1
            else:
                del changed["foreground_control"]["receipts"]["admit-fresh"]
            self.store_record(changed)
            self.dispatch(request, expected=3)
            self.store_record(saved)
        path = self.worktree / "source.py"
        raw = path.read_bytes()
        path.write_bytes(b"changed\n")
        self.dispatch(request, expected=3)
        path.write_bytes(raw)
        self.git("remote", "set-url", "origin", "https://github.com/other/project")
        self.dispatch(request, expected=3)
        self.git("remote", "set-url", "origin", "https://github.com/fixture/project.git")
        self.dispatch(self.request("pause", "pause-export"))
        self.dispatch(self.export_request(), expected=3)

    def test_handoff_unexportable_admission_refused_without_rewrite(self):
        self.dispatch(self.assign_request())
        request = self.admit_request()
        request["payload"]["cwd"] = "/home/node/review"
        selection = request["payload"]["sources"].pop("/candidate/source.py")
        request["payload"]["sources"]["/somewhere/source.py"] = selection
        result = self.dispatch(request)
        self.admission_id = result["domain_result"]["admission_id"]
        self.dispatch(self.export_request(), expected=3)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(HandoffCLI(name) for name in loader.getTestCaseNames(HandoffCLI)
                              if name.startswith("test_handoff_"))


if __name__ == "__main__":
    unittest.main()
