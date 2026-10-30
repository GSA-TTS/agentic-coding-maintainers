#!/usr/bin/env python3
"""Qualification retry and evidence-oracle checks; no model invocation."""

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("qualification", Path(__file__).with_name("qualify-review-repair.py"))
assert spec and spec.loader
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class DriverTests(unittest.TestCase):
    def test_exact_request_survives_revision_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            first = {"operation_id": "collect", "expected_revision": 1, "payload": {"digest": "a"}}
            driver.retain_request(path, first)
            before = path.read_bytes()
            self.assertEqual(driver.retain_request(path, {**first, "expected_revision": 2}), first)
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(ValueError):
                driver.retain_request(path, {**first, "payload": {"digest": "b"}})

    def test_unmeasured_baseline_never_counts_as_defect(self):
        expected = {"returncode": 0, "stderr": "", "stdout": "[4, -1, 1, 12]\n"}
        driver.require_seeded_baseline(expected)
        for changed in ({"returncode": 1}, {"stderr": "import failed"}, {"stdout": ""}, {"stdout": "[6, -4, 0, 22]\n"}):
            with self.assertRaises(ValueError):
                driver.require_seeded_baseline({**expected, **changed})

    def test_nonempty_findings_not_automatic_semantic_detection(self):
        assessment = {"unresolved_findings": ["unrelated-style-finding"]}
        for finding in (None, "seeded-defect"):
            with self.assertRaises(ValueError):
                driver.require_adjudication(finding, assessment)
        driver.require_adjudication("seeded-defect", {"unresolved_findings": ["seeded-defect"]})

    def test_resume_commit_already_created_before_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            def git(*args):
                env = {key:value for key,value in os.environ.items() if not key.startswith("GIT_")}
                env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
                return subprocess.check_output(["git","-C",str(root),"-c","user.name=Fixture","-c","user.email=fixture@example.invalid","-c","commit.gpgsign=false",*args],env=env).decode().strip()
            git("init","-q")
            (root/"calc.py").write_text("before")
            git("add","."); git("commit","-qm","before"); old=git("rev-parse","HEAD")
            (root/"calc.py").write_text("after")
            git("add","."); git("commit","-qm","repair"); new=git("rev-parse","HEAD")
            receipt=root/".git"/"qualification-commit.json"
            self.assertEqual(driver.reconcile_commit(git,old,receipt),new)
            self.assertEqual(driver.reconcile_commit(git,old,receipt),new)
            self.assertEqual(git("rev-list","--count","HEAD"),"2")

    def test_cached_qualification_rechecks_same_head_review(self):
        record = {"head_sha":"a"*40,"state":"Reviewing"}
        assessment = {"generation":2,"review_process":"CLAIMS_COMPLETE","missing_obligations":[],"unresolved_findings":[]}
        completed = {"head":"a"*40,"review":assessment}
        driver.require_current_qualification(record,completed,assessment)
        for changed in ({"unresolved_findings":["new-defect"]}, {"generation":3}, {"missing_obligations":["correctness"]}, {"review_process":"UNVERIFIED"}):
            with self.assertRaises(ValueError):
                driver.require_current_qualification(record,completed,{**assessment,**changed})
        with self.assertRaises(ValueError):
            driver.require_current_qualification({**record,"state":"Cancelled"},completed,assessment)


if __name__ == "__main__":
    unittest.main()
