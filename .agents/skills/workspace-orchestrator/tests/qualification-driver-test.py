#!/usr/bin/env python3
"""Qualification retry and evidence-oracle checks; no model invocation."""

import importlib.util
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


if __name__ == "__main__":
    unittest.main()
