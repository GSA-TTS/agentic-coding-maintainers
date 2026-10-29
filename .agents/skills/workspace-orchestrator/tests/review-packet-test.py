#!/usr/bin/env python3
"""Object-capture acceptance tests; run only in an isolated execution environment."""

import base64
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "bin" / "review-packet.py"
spec = importlib.util.spec_from_file_location("review_packet", SOURCE)
assert spec and spec.loader
packet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packet)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "candidate"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        (self.repo / "example.py").write_text("result = 1\n")
        self.base = self.save()
        (self.repo / "example.py").write_text("result = 2\n")
        self.head = self.save()

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        return subprocess.check_output(["git", "-C", str(self.repo), *args], env=env).decode().strip()

    def save(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def capture(self, **changes):
        args = dict(repo=self.repo, repository="fixture/project", base=self.base,
                    head=self.head, comparison="direct")
        args.update(changes)
        return packet.capture(**args)

    def test_positive_exact_source_and_deterministic_publication(self):
        value = self.capture()
        self.assertEqual(value["files"][0]["before"]["content"], "result = 1\n")
        self.assertEqual(value["files"][0]["after"]["content"], "result = 2\n")
        self.assertEqual(value["changed_inventory"], "COMPLETE")
        self.assertEqual(value["context_coverage"], "UNVERIFIED")
        self.assertEqual({item["id"] for item in value["obligations"]}, set(packet.BASELINE))
        store = self.root / "store"
        key = packet.publish(store, self.repo, value)
        self.assertEqual(packet.publish(store, self.repo, self.capture()), key)
        self.assertEqual(json.loads((store / f"{key}.json").read_bytes()), value)

    def test_dirty_worktree_does_not_change_committed_packet(self):
        before = self.capture()
        (self.repo / "example.py").write_text("uncommitted\n")
        self.assertEqual(before, self.capture())

    def test_unusual_paths_binary_symlink_and_gitlink(self):
        odd = "tab\tline\nname"
        (self.repo / odd).write_bytes(b"\0\xff")
        (self.repo / "link").symlink_to("../../not-mounted")
        self.git("add", ".")
        self.git("update-index", "--add", "--cacheinfo", f"160000,{self.base},nested")
        self.git("commit", "-qm", "nonregular fixture")
        self.head = self.git("rev-parse", "HEAD")
        self.git("config", "diff.ignoreSubmodules", "all")
        value = self.capture()
        entries = {item["path_utf8"]: item for item in value["files"]}
        self.assertEqual(base64.b64decode(entries[odd]["path_base64"]), odd.encode())
        self.assertEqual(base64.b64decode(entries[odd]["after"]["content"]), b"\0\xff")
        self.assertEqual(entries["link"]["after"]["content"], "../../not-mounted")
        self.assertEqual(entries["nested"]["after"]["coverage"], "UNVERIFIED")

    def test_external_diff_and_textconv_do_not_execute(self):
        marker = self.root / "executed"
        hook = self.root / "hook.sh"
        hook.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
        hook.chmod(0o700)
        self.git("config", "diff.external", str(hook))
        self.git("config", "diff.poison.textconv", str(hook))
        (self.repo / ".gitattributes").write_text("*.py diff=poison\n")
        self.head = self.save()
        self.capture()
        self.assertFalse(marker.exists())

    def test_replace_refs_do_not_substitute_source(self):
        original = self.capture()
        self.git("replace", self.head, self.base)
        self.assertEqual(self.capture(), original)

    def test_subdirectory_and_relative_diff_configuration(self):
        (self.repo / "nested").mkdir()
        (self.repo / "nested" / "source").write_text("nested source\n")
        self.head = self.save()
        original = self.capture()
        self.git("config", "diff.relative", "true")
        self.assertEqual(self.capture(repo=self.repo / "nested"), original)

    def test_missing_and_oversized_objects_fail_closed(self):
        with self.assertRaises(packet.Unverified):
            self.capture(head="f" * 40)
        (self.repo / "large").write_bytes(b"a" * (packet.MAX_BLOB + 1))
        self.head = self.save()
        with self.assertRaises(packet.Unverified):
            self.capture()

    def test_store_cannot_be_candidate_or_symlink(self):
        value = self.capture()
        with self.assertRaises(packet.Unverified):
            packet.publish(self.repo / "evidence", self.repo, value)
        (self.root / "alias").symlink_to(self.repo, target_is_directory=True)
        with self.assertRaises(packet.Unverified):
            packet.publish(self.root / "alias" / "evidence", self.repo, value)
        (self.repo / "nested").mkdir()
        with self.assertRaises(packet.Unverified):
            packet.publish(self.repo / "sibling-store", self.repo / "nested", value)

    def test_corrupted_existing_packet_is_not_replaced(self):
        value = self.capture()
        store = self.root / "store"
        key = packet.publish(store, self.repo, value)
        path = store / f"{key}.json"
        path.chmod(0o600)
        path.write_bytes(b"incomplete")
        with self.assertRaises(packet.Unverified):
            packet.publish(store, self.repo, value)
        self.assertEqual(path.read_bytes(), b"incomplete")

    def test_cli_requires_isolated_python(self):
        result = subprocess.run([sys.executable, str(SOURCE), "--repo", str(self.repo),
                                 "--repository", "fixture/project", "--base", self.base,
                                 "--head", self.head, "--comparison", "direct",
                                 "--store", str(self.root / "store")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stdout)["status"], "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
