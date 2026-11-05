#!/usr/bin/env python3
"""Offline fixtures. Execute only in the reviewed workspace sandbox."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/workspace-cleanup.py"
SPEC = importlib.util.spec_from_file_location("workspace_cleanup", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
cleanup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cleanup)


class CleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "repo"
        self.root.mkdir()
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                        GIT_AUTHOR_NAME="Fixture", GIT_AUTHOR_EMAIL="fixture@example.invalid",
                        GIT_COMMITTER_NAME="Fixture", GIT_COMMITTER_EMAIL="fixture@example.invalid")
        self.git("init", "-q", "--template=")
        (self.root / ".gitignore").write_text("/tmp/\n")
        (self.root / "tracked.txt").write_text("tracked bytes\n")
        self.git("add", ".")
        self.git("commit", "-qm", "test: fixture")
        (self.root / "loose.txt").write_bytes(b"loose\x00bytes\n")
        (self.root / "loose.txt").chmod(0o640)

    def git(self, *args: str) -> bytes:
        return subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
             "-C", str(self.root), *args], env=self.env, check=True,
            capture_output=True, timeout=15,
        ).stdout

    def cli(self, *args: str, ok: bool = True) -> str:
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = cleanup.main(["--workspace", str(self.root), *args])
        self.assertEqual(result, 0 if ok else 3, errors.getvalue())
        return output.getvalue().strip()

    def snapshot(self) -> dict[str, tuple[int, bytes | str]]:
        result: dict[str, tuple[int, bytes | str]] = {}
        for path in self.root.rglob("*"):
            info = path.lstat()
            content: bytes | str = "directory"
            if path.is_symlink():
                content = os.readlink(path)
            elif path.is_file():
                content = path.read_bytes()
            result[str(path.relative_to(self.root))] = (info.st_mode, content)
        return result

    def quarantine(self) -> Path:
        entry_id = self.cli("quarantine", "loose.txt", "--reason", "owner reviewed fixture", "--apply")
        self.assertEqual(str(uuid.UUID(entry_id)), entry_id)
        return self.root / "tmp/cleanup" / entry_id

    def rewrite(self, entry: Path, **changes: object) -> None:
        manifest = entry / "manifest.json"
        data = json.loads(manifest.read_text())
        data.update(changes)
        manifest.write_text(json.dumps(data))

    def test_default_inventory_and_previews_write_nothing(self) -> None:
        before = self.snapshot()
        report = json.loads(self.cli())
        self.assertIn({"name": "loose.txt", "status": "needs-owner-review"}, report["root_entries"])
        self.cli("quarantine", "loose.txt", "--reason", "preview")
        self.cli("allocate-sync", "--skill", "cross-repo-epic")
        self.assertEqual(before, self.snapshot())
        entry = self.quarantine()
        before = self.snapshot()
        self.cli("restore", entry.name)
        self.assertEqual(before, self.snapshot())

    def test_roundtrip_and_verified_repeat(self) -> None:
        entry = self.quarantine()
        self.assertFalse((self.root / "loose.txt").exists())
        self.assertEqual((entry / "payload").read_bytes(), b"loose\x00bytes\n")
        for path in (entry.parent.parent, entry.parent, entry):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((entry / "manifest.json").stat().st_mode), 0o600)
        self.cli("restore", entry.name, "--apply")
        self.assertEqual((self.root / "loose.txt").read_bytes(), b"loose\x00bytes\n")
        self.assertEqual(stat.S_IMODE((self.root / "loose.txt").stat().st_mode), 0o640)
        self.assertIn("already restored", self.cli("restore", entry.name, "--apply"))
        (self.root / "loose.txt").write_text("changed")
        self.cli("restore", entry.name, "--apply", ok=False)

    def test_protected_paths_and_types(self) -> None:
        for name in (".hidden", "orchestrator.json", "HEAD", "config", "deleteme"):
            (self.root / name).write_text("keep")
        (self.root / "directory").mkdir()
        (self.root / "link").symlink_to("loose.txt")
        os.link(self.root / "loose.txt", self.root / "hardlink")
        os.mkfifo(self.root / "pipe")
        for name in (".hidden", "orchestrator.json", "HEAD", "config", "deleteme",
                     "directory", "link", "hardlink", "loose.txt", "pipe", "../escape",
                     str(self.root / "loose.txt"), "work", "clones", "tmp"):
            with self.subTest(name=name):
                self.cli("quarantine", name, "--reason", "test", "--apply", ok=False)
        self.assertFalse((self.root / "tmp").exists())
        self.assertEqual((self.root / "loose.txt").read_bytes(), b"loose\x00bytes\n")

    def test_tracked_head_index_and_staged_deletion(self) -> None:
        self.cli("quarantine", "tracked.txt", "--reason", "test", "--apply", ok=False)
        self.git("rm", "--cached", "tracked.txt")
        self.cli("quarantine", "tracked.txt", "--reason", "test", "--apply", ok=False)
        self.git("add", "loose.txt")
        self.cli("quarantine", "loose.txt", "--reason", "test", "--apply", ok=False)
        self.assertFalse((self.root / "tmp").exists())

    def test_missing_ignore_and_tracked_tmp(self) -> None:
        (self.root / ".gitignore").write_text("")
        self.cli("quarantine", "loose.txt", "--reason", "test", "--apply", ok=False)
        self.assertFalse((self.root / "tmp").exists())
        (self.root / ".gitignore").write_text("/tmp/\n")
        (self.root / "tmp").mkdir(mode=0o700)
        (self.root / "tmp/keep").write_text("keep")
        self.git("add", "-f", "tmp/keep")
        self.git("commit", "-qm", "test: tracked tmp")
        self.git("rm", "--cached", "tmp/keep")
        self.cli("quarantine", "loose.txt", "--reason", "test", "--apply", ok=False)
        self.assertFalse((self.root / "tmp/cleanup").exists())

    def test_case_only_disk_rename_preserves_index_and_head_protection(self) -> None:
        # Two steps emulate a case-only disk rename on Linux and macOS without
        # updating the index. Exact spelling checks alone cannot protect this.
        (self.root / "tracked.txt").rename(self.root / "rename-intermediate")
        (self.root / "rename-intermediate").rename(self.root / "TRACKED.TXT")
        self.assertIn(b"tracked.txt\0", self.git("ls-files", "-z"))
        self.cli("quarantine", "TRACKED.TXT", "--reason", "test", "--apply", ok=False)
        self.git("rm", "--cached", "tracked.txt")
        self.assertNotIn(b"tracked.txt\0", self.git("ls-files", "-z"))
        self.cli("quarantine", "TRACKED.TXT", "--reason", "test", "--apply", ok=False)
        self.assertEqual((self.root / "TRACKED.TXT").read_text(), "tracked bytes\n")
        self.assertFalse((self.root / "tmp").exists())

    def test_case_only_index_addition_is_protected(self) -> None:
        self.git("add", "loose.txt")
        (self.root / "loose.txt").rename(self.root / "rename-intermediate")
        (self.root / "rename-intermediate").rename(self.root / "LOOSE.TXT")
        self.assertIn(b"loose.txt\0", self.git("ls-files", "-z"))
        self.cli("quarantine", "LOOSE.TXT", "--reason", "test", "--apply", ok=False)
        self.assertFalse((self.root / "tmp").exists())

    def test_case_folded_tmp_descendants_block_allocation(self) -> None:
        (self.root / "TMP").mkdir(mode=0o700)
        (self.root / "TMP/keep").write_text("keep")
        self.git("add", "-f", "TMP/keep")
        self.assertIn(b"TMP/keep\0", self.git("ls-files", "-z"))
        (self.root / "TMP").rename(self.root / "rename-intermediate")
        (self.root / "rename-intermediate").rename(self.root / "tmp")
        self.cli("allocate-sync", "--skill", "cross-repo-epic", "--apply", ok=False)
        self.cli("quarantine", "loose.txt", "--reason", "test", "--apply", ok=False)
        self.git("commit", "-qm", "test: upper-case tmp in HEAD")
        self.git("rm", "--cached", "TMP/keep")
        self.assertNotIn(b"TMP/keep\0", self.git("ls-files", "-z"))
        self.cli("allocate-sync", "--skill", "cross-repo-epic", "--apply", ok=False)
        self.assertEqual((self.root / "tmp/keep").read_text(), "keep")
        self.assertFalse((self.root / "tmp/cleanup").exists())

    def test_case_folded_restore_destination_is_protected(self) -> None:
        entry = self.quarantine()
        (self.root / "LOOSE.TXT").write_text("tracked upper-case destination")
        self.git("add", "LOOSE.TXT")
        (self.root / "LOOSE.TXT").unlink()
        self.cli("restore", entry.name, "--apply", ok=False)
        self.git("commit", "-qm", "test: upper-case restore destination")
        self.git("rm", "--cached", "LOOSE.TXT")
        self.cli("restore", entry.name, "--apply", ok=False)
        self.assertTrue((entry / "payload").is_file())

    def test_tracking_root_match_is_literal_not_glob_or_prefix(self) -> None:
        for name in ("reportA.txt", "report[ab].txt", "report*.txt", "report?.txt", ":(glob)report*"):
            (self.root / name).write_text("fixture")
        self.git("--literal-pathspecs", "add", "--", "reportA.txt", "report[ab].txt")
        self.git("commit", "-qm", "test: literal metacharacters")
        self.assertTrue(cleanup.tracked(self.root, "REPORT[AB].TXT"))
        self.git("--literal-pathspecs", "rm", "--cached", "--", "report[ab].txt")
        self.assertTrue(cleanup.tracked(self.root, "REPORT[AB].TXT"))
        for name in ("report*.txt", "report?.txt", ":(glob)report*", "report"):
            self.assertFalse(cleanup.tracked(self.root, name), name)
        self.cli("quarantine", "report*.txt", "--reason", "literal preview")

    def test_root_ignore_is_anchored(self) -> None:
        (self.root / "nested/tmp").mkdir(parents=True)
        (self.root / "nested/tmp/keep").write_text("visible")
        self.assertIn(b"nested/tmp/keep", self.git("ls-files", "--others", "--exclude-standard"))

    def test_ignored_files_still_require_explicit_selection(self) -> None:
        with (self.root / ".gitignore").open("a") as output:
            output.write("/loose.txt\n")
        self.assertIn("needs-owner-review", self.cli())
        entry = self.quarantine()
        self.cli("restore", entry.name, "--apply")

    def test_reserved_case_aliases_are_refused(self) -> None:
        for name in ("head", "CONFIG", "Orchestrator.json", "TMP"):
            self.cli("quarantine", name, "--reason", "test", "--apply", ok=False)

    def test_restore_head_staged_deletion(self) -> None:
        entry = self.quarantine()
        (self.root / "loose.txt").write_text("new tracked file")
        self.git("add", "loose.txt")
        self.git("commit", "-qm", "test: destination now tracked")
        self.git("rm", "-q", "loose.txt")
        self.cli("restore", entry.name, "--apply", ok=False)
        self.assertTrue((entry / "payload").exists())

    def test_unsafe_store_refused_without_touching_target(self) -> None:
        target = Path(self.temp.name) / "outside"
        target.mkdir()
        (self.root / "tmp").symlink_to(target, target_is_directory=True)
        self.cli("quarantine", "loose.txt", "--reason", "test", "--apply", ok=False)
        self.assertEqual(list(target.iterdir()), [])
        (self.root / "tmp").unlink()
        (self.root / "tmp").mkdir(mode=0o700)
        (self.root / "tmp/cleanup").symlink_to(target, target_is_directory=True)
        self.cli("quarantine", "loose.txt", "--reason", "test", ok=False)
        (self.root / "tmp/cleanup").unlink()
        (self.root / "tmp").chmod(0o755)
        self.cli("quarantine", "loose.txt", "--reason", "test", "--apply", ok=False)
        self.assertFalse((self.root / "tmp/cleanup").exists())

    def test_conflict_corruption_and_root_binding(self) -> None:
        entry = self.quarantine()
        original = (entry / "manifest.json").read_bytes()
        (self.root / "loose.txt").write_text("conflict")
        self.cli("restore", entry.name, "--apply", ok=False)
        self.assertEqual((self.root / "loose.txt").read_text(), "conflict")
        (self.root / "loose.txt").unlink()
        self.rewrite(entry, root={"dev": 0, "ino": 0})
        self.cli("restore", entry.name, "--apply", ok=False)
        (entry / "manifest.json").write_bytes(original)
        (entry / "payload").write_text("corrupt")
        self.cli("restore", entry.name, "--apply", ok=False)
        self.assertTrue((entry / "payload").exists())

    def test_restore_tracked_and_symlink_destinations(self) -> None:
        entry = self.quarantine()
        (self.root / "loose.txt").write_text("tracked now")
        self.git("add", "loose.txt")
        (self.root / "loose.txt").unlink()
        self.cli("restore", entry.name, "--apply", ok=False)
        self.git("reset", "-q", "--", "loose.txt")
        (self.root / "loose.txt").symlink_to("absent")
        self.cli("restore", entry.name, "--apply", ok=False)
        self.assertTrue((self.root / "loose.txt").is_symlink())

    def test_prepared_before_and_after_rename(self) -> None:
        with patch.object(cleanup.os, "rename", side_effect=OSError("injected before rename")):
            self.cli("quarantine", "loose.txt", "--reason", "test", "--apply", ok=False)
        first = next((self.root / "tmp/cleanup").iterdir())
        self.assertEqual(json.loads((first / "manifest.json").read_text())["state"], "prepared")
        self.assertTrue((self.root / "loose.txt").exists())
        self.cli("restore", first.name, "--apply", ok=False)
        original_write = cleanup.write_manifest

        def fail_update(entry: int, data: dict[str, object], initial: bool = False) -> None:
            if not initial:
                raise OSError("injected after rename")
            original_write(entry, data, initial)

        with patch.object(cleanup, "write_manifest", side_effect=fail_update):
            self.cli("quarantine", "loose.txt", "--reason", "test", "--apply", ok=False)
        second = next(path for path in first.parent.iterdir() if path != first)
        self.assertTrue((second / "payload").exists())
        self.assertFalse((self.root / "loose.txt").exists())
        self.assertEqual(json.loads((second / "manifest.json").read_text())["state"], "prepared")
        self.cli("restore", second.name, "--apply")

    def test_restore_crash_preserves_bytes_and_reports_partial_state(self) -> None:
        entry = self.quarantine()
        with patch.object(cleanup, "write_manifest", side_effect=OSError("journal failure")):
            self.cli("restore", entry.name, "--apply", ok=False)
        self.assertEqual((self.root / "loose.txt").read_bytes(), b"loose\x00bytes\n")
        self.cli("restore", entry.name, "--apply", ok=False)

    def test_manifest_limits_and_artifact_validation(self) -> None:
        entry = self.quarantine()
        manifest = entry / "manifest.json"
        original = manifest.read_bytes()
        for raw in (b"{" * (cleanup.MAX_MANIFEST + 1), b"[]", b'{"schema":1,"schema":1}'):
            manifest.write_bytes(raw)
            self.cli("restore", entry.name, "--apply", ok=False)
        manifest.write_bytes(original)
        self.rewrite(entry, name="../escape")
        self.cli("restore", entry.name, "--apply", ok=False)
        manifest.write_bytes(original)
        (entry / "manifest.next").write_bytes(original)
        self.cli("restore", entry.name, "--apply", ok=False)
        (entry / "manifest.next").unlink()
        manifest.chmod(0o644)
        self.cli("restore", entry.name, "--apply", ok=False)
        manifest.chmod(0o600)
        manifest.rename(entry / "saved")
        manifest.symlink_to("saved")
        self.cli("restore", entry.name, "--apply", ok=False)
        manifest.unlink()
        (entry / "saved").rename(manifest)
        (entry / "payload").rename(entry / "saved-payload")
        (entry / "payload").symlink_to("saved-payload")
        self.cli("restore", entry.name, "--apply", ok=False)
        self.cli("restore", "../escape", "--apply", ok=False)

    def test_hash_reason_limits_and_revalidation(self) -> None:
        with patch.object(cleanup, "MAX_FILE", 4):
            self.cli("quarantine", "loose.txt", "--reason", "test", "--apply", ok=False)
        self.cli("quarantine", "loose.txt", "--reason", "x" * 1025, "--apply", ok=False)
        self.cli("quarantine", "loose.txt", "--reason", " ", "--apply", ok=False)
        with patch.object(cleanup, "recheck", side_effect=cleanup.Refused("changed")):
            self.cli("quarantine", "loose.txt", "--reason", "test", "--apply", ok=False)
        self.assertTrue((self.root / "loose.txt").exists())

    def test_sync_inventory_lock_and_legacy(self) -> None:
        (self.root / "deleteme").mkdir()
        (self.root / "deleteme/MANIFEST.md").write_text("legacy evidence")
        entry = Path(self.cli("allocate-sync", "--skill", "cross-repo-epic", "--apply"))
        report = json.loads(self.cli())
        self.assertIn({"name": "deleteme", "status": "migration-needed; never auto-moved"}, report["root_entries"])
        self.assertTrue(any(row.get("kind") == "sync" for row in report["cleanup_entries"]))
        before = self.snapshot()
        self.cli("quarantine", "loose.txt", "--reason", "test", "--apply", ok=False)
        self.assertEqual(before, self.snapshot())
        (entry.parent / ".lock").rename(entry / "cleanup-lock")  # sync trap's handoff
        self.cli("restore", entry.name, "--apply", ok=False)
        self.assertEqual((self.root / "deleteme/MANIFEST.md").read_text(), "legacy evidence")

    def test_git_redirection_and_timeout(self) -> None:
        with patch.dict(os.environ, {"GIT_DIR": "/missing", "GIT_WORK_TREE": "/missing",
                                    "GIT_INDEX_FILE": "/missing/index", "GIT_CONFIG_COUNT": "1",
                                    "GIT_CONFIG_KEY_0": "core.worktree", "GIT_CONFIG_VALUE_0": "/missing"}):
            self.cli("quarantine", "loose.txt", "--reason", "test")
            self.cli("quarantine", "tracked.txt", "--reason", "test", ok=False)
        with patch.object(cleanup.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 15)):
            self.cli(ok=False)

    def test_linked_worktree_and_nested_root(self) -> None:
        linked = Path(self.temp.name) / "linked"
        self.git("worktree", "add", "-q", "-b", "fixture-linked", str(linked))
        (linked / "loose.txt").write_text("linked artifact")
        self.root = linked
        entry = self.quarantine()
        self.cli("restore", entry.name, "--apply")
        nested = linked / "nested"
        nested.mkdir()
        self.root = nested
        self.cli(ok=False)

    def test_nongit_sync_and_git_required_for_file_moves(self) -> None:
        self.root = Path(self.temp.name) / "nongit"
        self.root.mkdir()
        (self.root / "loose.txt").write_text("keep")
        self.cli("quarantine", "loose.txt", "--reason", "test", "--apply", ok=False)
        entry = Path(self.cli("allocate-sync", "--skill", "workspace-orchestrator", "--apply"))
        self.assertTrue((entry / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
