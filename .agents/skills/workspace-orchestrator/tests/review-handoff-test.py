#!/usr/bin/env python3
"""Pure transport and filesystem cases; no subprocess, model, or network."""

import base64
import copy
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("materialize", ROOT / "bin/review-materialize.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
h = m.h


def bundle():
    context = {"acceptance_criteria": ["bounded result"], "obligations": sorted(h.BASELINE), "finding_history": {
        "F1": {"finding": {"id": "F1", "invariant": "bounded", "trigger": "call", "path": "source.py:1",
                           "impact": "incorrect", "evidence": "observed"}, "generation": 1, "run_id": "prior", "dispositions": [
            {"finding_id": "F1", "resolution": "refuted", "counterevidence": "inspection", "generation": 2, "run_id": "other"}]}}}
    sources = []
    for side, raw in (("before", b"\xff\0before\n"), ("after", b"result = 2\n")):
        sources.append({"guest_path": "/candidate/" + side + "/source.py", "path_base64": "c291cmNlLnB5",
                        "side": side, "bytes": len(raw), "sha256": h.digest(raw),
                        "content_base64": base64.b64encode(raw).decode()})
    return {"schema_version": 1, "kind": "admitted-review-handoff", "binding": {
        "task_id": "task", "incarnation": "a" * 64, "admission_id": "b" * 64, "export_revision": 12,
        "admission_revision": 11, "admit_operation_id": "admit", "generation": 2, "material_epoch": 1,
        "base": "c" * 40, "head": "d" * 40, "packet": "e" * 64, "policy": "f" * 64},
        "runtime": {"run_id": "run", "reviewer": "independent", "session": "ses_review", "profile_sha256": h.digest(b"profile"),
                    "binary_sha256": "0" * 64, "model": "provider/model", "agent": "reviewer", "cwd": "/review"},
        "context": context, "context_sha256": h.digest(h.canonical(context)), "sources": sources}


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.root = self.parent / "materialized"
        self.value = bundle()

    def run_materialize(self, value=None, **kwargs):
        return m.materialize(value or self.value, str(self.root), "/trusted/review-run.py", "/trusted/opencode",
                             "/runtime/results", **kwargs)

    def test_bytes_readonly_complete_replay_and_separate_metadata(self):
        planned = self.run_materialize()
        before = {str(p): (p.stat().st_ino, p.read_bytes()) for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(planned, self.run_materialize())
        self.assertEqual(before, {str(p): (p.stat().st_ino, p.read_bytes()) for p in self.root.rglob("*") if p.is_file()})
        for source in self.value["sources"]:
            path = self.root / source["guest_path"].lstrip("/")
            self.assertEqual(path.read_bytes(), h.encoded(source["content_base64"]))
            self.assertEqual(path.stat().st_mode & 0o777, 0o400)
        self.assertEqual((self.root / "metadata/context.json").read_bytes(), h.canonical(self.value["context"]))
        self.assertEqual([item["destination"] for item in planned["mounts"]], ["/candidate", "/review-input"])
        self.assertIn("/review", planned["mkdir_guest"])
        self.assertFalse(planned["candidate_ready"])

    def test_nested_extras_all_rejected_before_writes(self):
        paths = [(), ("binding",), ("runtime",), ("context",), ("context", "finding_history", "F1"),
                 ("context", "finding_history", "F1", "finding"),
                 ("context", "finding_history", "F1", "dispositions", 0), ("sources", 0)]
        for path in paths:
            value = copy.deepcopy(self.value)
            target = value
            for key in path:
                target = target[key]
            target["unexpected"] = "refused"
            with self.subTest(path=path), self.assertRaises(Exception):
                self.run_materialize(value)
            self.assertFalse(self.root.exists())

    def test_paths_collisions_and_hashes_refused(self):
        for path in ("/etc/source", "/candidate/../escape", "/candidate/.git/config", "/candidate/a//b", "/candidate", "/review-input/context.json"):
            value = copy.deepcopy(self.value)
            value["sources"][0]["guest_path"] = path
            with self.subTest(path=path), self.assertRaises(Exception):
                self.run_materialize(value)
        for damage in ("duplicate", "prefix", "hash", "bytes", "cwd", "context"):
            value = copy.deepcopy(self.value)
            if damage == "duplicate":
                value["sources"][1]["guest_path"] = value["sources"][0]["guest_path"]
            elif damage == "prefix":
                value["sources"][1]["guest_path"] = value["sources"][0]["guest_path"] + "/nested"
            elif damage in {"hash", "bytes"}:
                value["sources"][0]["sha256" if damage == "hash" else "bytes"] = "0" * 64 if damage == "hash" else True
            elif damage == "cwd":
                value["runtime"]["cwd"] = "/home/node/review"
            else:
                value["context_sha256"] = "0" * 64
            with self.subTest(damage=damage), self.assertRaises(Exception):
                self.run_materialize(value)
        self.assertFalse(self.root.exists())

    def test_bounds_and_strict_json(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b"x" * (h.MAX_BUNDLE + 1)):
            with self.assertRaises(Exception):
                h.decode(raw)
        for damage in ("count", "context", "bundle"):
            value = copy.deepcopy(self.value)
            if damage == "count":
                value["sources"] *= 11
            elif damage == "context":
                value["context"]["acceptance_criteria"] = ["x" * 2000] * 26
            else:
                value["sources"][0]["content_base64"] = "A" * h.MAX_BUNDLE
            with self.assertRaises(Exception):
                self.run_materialize(value)
        self.assertEqual(h.decode(h.canonical(self.value)), self.value)

    def test_existing_empty_extra_symlink_and_hardlink_refused(self):
        self.root.mkdir(mode=0o700)
        with self.assertRaises(Exception):
            self.run_materialize()
        self.root.rmdir()
        self.run_materialize()
        extra = self.root / "extra"
        extra.write_bytes(b"unrelated")
        with self.assertRaises(Exception):
            self.run_materialize()
        self.assertEqual(extra.read_bytes(), b"unrelated")
        extra.unlink()
        source = self.root / "candidate/after/source.py"
        source.unlink()
        source.symlink_to(self.root / "candidate/before/source.py")
        with self.assertRaises(Exception):
            self.run_materialize()
        source.unlink()
        os.link(self.root / "candidate/before/source.py", source)
        with self.assertRaises(Exception):
            self.run_materialize()

    def test_symlink_parent_and_root_refused(self):
        link = self.parent / "link"
        link.symlink_to(self.parent, target_is_directory=True)
        self.root = link / "output"
        with self.assertRaises(Exception):
            self.run_materialize()
        self.root = self.parent / "root-link"
        self.root.symlink_to(self.parent, target_is_directory=True)
        with self.assertRaises(Exception):
            self.run_materialize()

    def test_interruption_preserves_manifest_and_never_ready(self):
        original = m.write_file
        def fail(parent, name, raw):
            if name == "source.py":
                raise OSError("injected disk failure")
            original(parent, name, raw)
        with mock.patch.object(m, "write_file", side_effect=fail), self.assertRaises(OSError):
            self.run_materialize()
        self.assertTrue((self.root / "MANIFEST.json").is_file())
        self.assertFalse((self.root / "READY.json").exists())
        with self.assertRaises(Exception):
            self.run_materialize()

    def test_trusted_profile_and_argument_data(self):
        profile = self.parent / "profile.json"
        profile.write_bytes(b"wrong")
        with self.assertRaises(Exception):
            self.run_materialize(profile=str(profile))
        self.assertFalse(self.root.exists())
        profile.write_bytes(b"profile")
        self.value["runtime"]["model"] = "--untrusted-option"
        result = self.run_materialize(profile=str(profile))
        self.assertIn("--model=--untrusted-option", result["runner_argv"])
        self.assertTrue(result["profile_verified"])


if __name__ == "__main__":
    unittest.main()
