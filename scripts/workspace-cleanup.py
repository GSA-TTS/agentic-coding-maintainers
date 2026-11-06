#!/usr/bin/env python3
"""Foreground, owner-reviewed cleanup; owning-user journals are not authenticated."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, cast

MAX_FILE = 256 * 1024 * 1024
MAX_MANIFEST = 16 * 1024
GIT_TIMEOUT = 15
PROTECTED = frozenset(name.casefold() for name in {
    "orchestrator.json", "work", "clones", "tmp", "deleteme", "HEAD",
    "objects", "refs", "config", "description", "hooks", "info", "logs",
    "index", "packed-refs", "shallow", "commondir", "gitdir",
})
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


class Refused(Exception):
    """An unsafe or uncertain operation, requiring owner inspection."""


def git(root: Path, *args: str, allowed: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[bytes]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_OPTIONAL_LOCKS="0")
    result = subprocess.run(  # no shell, hooks or inherited Git redirection
        ["git", *([] if args[0] == "check-ignore" else ["--literal-pathspecs"]),
         "-c", "core.fsmonitor=false", "-c",
         f"core.hooksPath={os.devnull}", "-C", str(root), *args],
        env=env, capture_output=True, timeout=GIT_TIMEOUT, check=False,
    )
    if result.returncode not in allowed:
        raise Refused(f"Git {args[0]} failed (exit {result.returncode})")
    return result


def git_workspace(root: Path, required: bool) -> bool:
    present = any(os.path.lexists(parent / ".git") for parent in (root, *root.parents))
    present = present or (root / "objects").exists() or (root / "HEAD").exists()
    if not present and not required:
        return False
    top = os.fsdecode(git(root, "rev-parse", "--show-toplevel").stdout).rstrip("\n")
    if Path(top).resolve() != root:
        raise Refused("--workspace must be the actual Git top level")
    return True


def contains_root_name(names: bytes, name: str) -> bool:
    """Compare literal root components, conservatively even on case-sensitive hosts."""
    folded = name.casefold()
    return any(os.fsdecode(path.split(b"/", 1)[0]).casefold() == folded
               for path in names.split(b"\0") if path)


def tracked(root: Path, name: str) -> bool:
    # No user-supplied pathspec: ls-tree lacks icase/literal magic support.
    # The index needs all names (including descendants); HEAD only needs root
    # entries, including trees/gitlinks. NUL framing preserves metacharacters.
    if contains_root_name(git(root, "ls-files", "--cached", "--full-name", "-z").stdout, name):
        return True
    head = git(root, "rev-parse", "--verify", "--quiet", "HEAD", allowed=(0, 1))
    if head.returncode == 0:
        return contains_root_name(git(root, "ls-tree", "--name-only", "-z", "HEAD").stdout, name)
    # Only a verifiably unborn symbolic branch may have no HEAD tree.
    branch = git(root, "symbolic-ref", "HEAD").stdout.decode().strip()
    if git(root, "show-ref", "--verify", "--quiet", branch, allowed=(0, 1)).returncode != 1:
        raise Refused("HEAD is unavailable, but branch exists")
    return False


def storage_policy(root: Path, is_git: bool) -> None:
    if is_git:
        if tracked(root, "tmp"):
            raise Refused("tmp contains HEAD/index paths (including staged deletions)")
        if git(root, "check-ignore", "-q", "--", "tmp/", allowed=(0, 1)).returncode:
            raise Refused("add root /tmp/ to the consumer ignore policy before mutation")


def basename(name: str) -> str:
    if (not name or len(os.fsencode(name)) > 255 or name.startswith(".")
            or name.casefold() in PROTECTED or "/" in name or "\\" in name
            or any(ord(char) < 32 or ord(char) == 127 for char in name)):
        raise Refused("select one nonhidden, nonprotected root basename")
    return name


def identity(value: os.stat_result) -> dict[str, int]:
    return {"dev": value.st_dev, "ino": value.st_ino, "size": value.st_size,
            "mode": stat.S_IMODE(value.st_mode), "mtime_ns": value.st_mtime_ns}


def private_dir(fd: int, device: int) -> None:
    value = os.fstat(fd)
    if value.st_uid != os.getuid() or stat.S_IMODE(value.st_mode) != 0o700 or value.st_dev != device:
        raise Refused("cleanup directories must be owner-owned, mode 0700, and on the root filesystem")


@contextmanager
def directory(parent: int, name: str, device: int, create: bool = False) -> Iterator[int]:
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
    fd = os.open(name, DIR_FLAGS, dir_fd=parent)
    try:
        private_dir(fd, device)
        yield fd
    finally:
        os.close(fd)


@contextmanager
def store(root_fd: int, create: bool = False) -> Iterator[int]:
    device = os.fstat(root_fd).st_dev
    with directory(root_fd, "tmp", device, create) as tmp:
        with directory(tmp, "cleanup", device, create) as cleanup:
            yield cleanup


def preview_store(root_fd: int) -> None:
    """Validate every existing ancestor without creating missing directories."""
    device = os.fstat(root_fd).st_dev
    try:
        with directory(root_fd, "tmp", device) as tmp:
            try:
                with directory(tmp, "cleanup", device) as cleanup:
                    if exists(cleanup, ".lock"):
                        raise Refused("cleanup lock exists; inspect before manual recovery")
            except FileNotFoundError:
                pass
    except FileNotFoundError:
        pass


@contextmanager
def lock(cleanup: int, transfer: bool = False) -> Iterator[None]:
    try:
        os.mkdir(".lock", 0o700, dir_fd=cleanup)
    except FileExistsError as exc:
        raise Refused("cleanup lock exists; no stale-lock takeover") from exc
    complete = False
    try:
        os.fsync(cleanup)
        yield
        complete = True
    finally:
        # allocate-sync transfers the empty lock to the calling sync trap.
        if not (transfer and complete):
            os.rmdir(".lock", dir_fd=cleanup)
            os.fsync(cleanup)


def exists(parent: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def fingerprint(parent: int, name: str) -> dict[str, object]:
    path_info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISREG(path_info.st_mode) or path_info.st_nlink != 1:
        raise Refused("file must be regular and single-link")
    fd = os.open(name, FILE_FLAGS, dir_fd=parent)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size > MAX_FILE):
            raise Refused("file must be regular, single-link and at most 256 MiB")
        if identity(path_info) != identity(before) or path_info.st_ctime_ns != before.st_ctime_ns:
            raise Refused("file identity changed while opening")
        # Overlayfs may report different devices for directories and files.
        # Bind the file's own identity; only the actual rename proves movability.
        digest = hashlib.sha256()
        total = 0
        while chunk := os.read(fd, 1024 * 1024):
            total += len(chunk)
            if total > MAX_FILE:
                raise Refused("file grew beyond hash limit")
            digest.update(chunk)
        after = os.fstat(fd)
        if (identity(before) != identity(after) or before.st_ctime_ns != after.st_ctime_ns
                or after.st_nlink != 1 or total != before.st_size):
            raise Refused("file changed while hashing")
        return {**identity(before), "sha256": digest.hexdigest()}
    finally:
        os.close(fd)


def recheck(parent: int, name: str, expected: dict[str, object]) -> None:
    current = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
            or identity(current) != {key: expected[key] for key in identity(current)}):
        raise Refused("file identity changed before rename")


def write_manifest(entry: int, data: dict[str, object], initial: bool = False) -> None:
    raw = (json.dumps(data, sort_keys=True, ensure_ascii=True) + "\n").encode()
    if len(raw) > MAX_MANIFEST:
        raise Refused("manifest exceeds limit")
    name = "manifest.json" if initial else "manifest.next"
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=entry)
    with os.fdopen(fd, "wb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    if not initial:
        os.replace(name, "manifest.json", src_dir_fd=entry, dst_dir_fd=entry)
    os.fsync(entry)


def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise Refused("duplicate manifest field")
        result[key] = value
    return result


def read_manifest(entry: int, root_fd: int, entry_id: str) -> dict[str, object]:
    fd = os.open("manifest.json", FILE_FLAGS, dir_fd=entry)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > MAX_MANIFEST):
            raise Refused("unsafe manifest")
        raw = source.read(MAX_MANIFEST + 1)
    if len(raw) > MAX_MANIFEST:
        raise Refused("manifest exceeds limit")
    value: object = json.loads(raw, object_pairs_hook=unique_pairs)
    if not isinstance(value, dict):
        raise Refused("manifest must be an object")
    data = cast(dict[str, object], value)
    common = {"schema", "id", "kind", "root", "created", "state"}
    kind = data.get("kind")
    extra = {"name", "reason", "file"} if kind == "file" else {"skill"}
    root = os.fstat(root_fd)
    binding = data.get("root")
    if (not isinstance(binding, dict) or set(binding) != {"dev", "ino"}
            or any(type(value) is not int for value in binding.values())):
        raise Refused("invalid root identity")
    if (set(data) != common | extra or type(data.get("schema")) is not int or data["schema"] != 1
            or data.get("id") != entry_id or data.get("root") != {"dev": root.st_dev, "ino": root.st_ino}
            or not isinstance(data.get("created"), str)):
        raise Refused("invalid manifest fields or root binding")
    created = str(data["created"])
    if datetime.fromisoformat(created).utcoffset() != timezone.utc.utcoffset(None):
        raise Refused("manifest timestamp must be UTC")
    if kind == "sync":
        if data.get("skill") not in ("cross-repo-epic", "workspace-orchestrator") or data.get("state") != "allocated":
            raise Refused("invalid sync manifest")
    elif kind == "file":
        basename(str(data.get("name", "")))
        reason(data.get("reason"))
        details = data.get("file")
        if (not isinstance(data.get("name"), str) or data.get("state") not in ("prepared", "quarantined", "restored")
                or not isinstance(details, dict)):
            raise Refused("invalid file manifest")
        file = cast(dict[str, object], details)
        integers = {"dev", "ino", "size", "mode", "mtime_ns"}
        if (set(file) != integers | {"sha256"}
                or any(type(file[key]) is not int for key in integers)
                or not 0 <= cast(int, file["size"]) <= MAX_FILE
                or not 0 <= cast(int, file["mode"]) <= 0o7777
                or not isinstance(file["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", str(file["sha256"]))):
            raise Refused("invalid file identity/hash")
    else:
        raise Refused("unknown entry kind")
    return data


def reason(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > 1024:
        raise Refused("reason must contain 1–1024 UTF-8 bytes; do not include sensitive data")
    return value


def new_manifest(root_fd: int, entry_id: str, kind: str) -> dict[str, object]:
    root = os.fstat(root_fd)
    return {"schema": 1, "id": entry_id, "kind": kind,
            "root": {"dev": root.st_dev, "ino": root.st_ino},
            "created": datetime.now(timezone.utc).isoformat(), "state": "allocated"}


def allocate(cleanup: int, root_fd: int, data: dict[str, object]) -> str:
    entry_id = str(data["id"])
    os.mkdir(entry_id, 0o700, dir_fd=cleanup)
    os.fsync(cleanup)
    with directory(cleanup, entry_id, os.fstat(root_fd).st_dev) as entry:
        write_manifest(entry, data, initial=True)
    return entry_id


def sync_filesystem(root_fd: int, skill: str) -> None:
    """The sync caller moves trees itself; reject existing cross-device ancestors."""
    device = os.fstat(root_fd).st_dev
    opened: list[int] = []
    parent = root_fd
    try:
        for name in (".agents", "skills", skill):
            try:
                fd = os.open(name, DIR_FLAGS, dir_fd=parent)
            except FileNotFoundError:
                break
            opened.append(fd)
            if os.fstat(fd).st_dev != device:
                raise Refused("sync source/destination must share the cleanup filesystem")
            parent = fd
    finally:
        for fd in reversed(opened):
            os.close(fd)


def quarantine(root: Path, root_fd: int, name: str, why: str, apply: bool) -> str:
    basename(name)
    reason(why)
    if name not in os.listdir(root_fd):
        raise Refused("select the exact directory-entry spelling, not a filesystem alias")
    if tracked(root, name):
        raise Refused("source is tracked in HEAD or index")
    details = fingerprint(root_fd, name)
    if not apply:
        return f"would quarantine {name!r}; no writes"
    with store(root_fd, True) as cleanup, lock(cleanup):
        storage_policy(root, True)
        if tracked(root, name):
            raise Refused("source became tracked")
        recheck(root_fd, name, details)
        entry_id = str(uuid.uuid4())
        data = new_manifest(root_fd, entry_id, "file")
        data.update(name=name, reason=why, file=details, state="prepared")
        allocate(cleanup, root_fd, data)
        with directory(cleanup, entry_id, os.fstat(root_fd).st_dev) as entry:
            if tracked(root, name) or exists(entry, "payload"):
                raise Refused("source became tracked or payload destination is occupied")
            recheck(root_fd, name, details)
            os.rename(name, "payload", src_dir_fd=root_fd, dst_dir_fd=entry)
            os.fsync(root_fd)
            os.fsync(entry)
            data["state"] = "quarantined"
            write_manifest(entry, data)
        return entry_id


def restore_entry(root: Path, root_fd: int, cleanup: int, entry_id: str, apply: bool) -> str:
    if str(uuid.UUID(entry_id)) != entry_id:
        raise Refused("entry ID must be a canonical UUID")
    device = os.fstat(root_fd).st_dev
    with directory(cleanup, entry_id, device) as entry:
        data = read_manifest(entry, root_fd, entry_id)
        if data["kind"] != "file":
            raise Refused("sync entries require MANIFEST.md and skill-specific recovery")
        if exists(entry, "manifest.next"):
            raise Refused("unfinished journal update; inspect manifest.next before recovery")
        name = cast(str, data["name"])
        if tracked(root, name):
            raise Refused("restore destination is tracked in HEAD or index")
        details = cast(dict[str, object], data["file"])
        payload = exists(entry, "payload")
        destination = exists(root_fd, name)
        if data["state"] == "restored" and not payload and destination:
            if fingerprint(root_fd, name) == details:
                return "already restored (identity and bytes verified)"
            raise Refused("restored file changed")
        if destination or not payload or data["state"] == "restored":
            raise Refused("conflict or partial state; inspect source, payload and journal")
        if fingerprint(entry, "payload") != details:
            raise Refused("payload identity/hash mismatch")
        if not apply:
            return f"would restore {name!r}; no writes"
        if tracked(root, name) or exists(root_fd, name):
            raise Refused("restore destination became occupied or tracked")
        recheck(entry, "payload", details)
        os.rename("payload", name, src_dir_fd=entry, dst_dir_fd=root_fd)
        os.fsync(entry)
        os.fsync(root_fd)
        data["state"] = "restored"
        write_manifest(entry, data)
        return f"restored {name!r}"


def inventory(root: Path, root_fd: int, is_git: bool) -> dict[str, object]:
    rows: list[dict[str, str]] = []
    for name in sorted(os.listdir(root_fd)):
        info = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        label = "protected/runtime-or-directory"
        if name == "deleteme":
            label = "migration-needed; never auto-moved"
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            try:
                basename(name)
            except Refused:
                pass
            else:
                label = "tracked" if is_git and tracked(root, name) else "needs-owner-review"
        rows.append({"name": name, "status": label})
    entries: list[dict[str, str]] = []
    try:
        with store(root_fd) as cleanup:
            for entry_id in sorted(os.listdir(cleanup)):
                try:
                    if str(uuid.UUID(entry_id)) != entry_id:
                        raise Refused("lock or non-UUID entry; inspect manually")
                    with directory(cleanup, entry_id, os.fstat(root_fd).st_dev) as entry:
                        data = read_manifest(entry, root_fd, entry_id)
                        entries.append({"id": entry_id, "kind": str(data["kind"]),
                                        "state": str(data["state"]), "note": "journal only; inspect artifacts"})
                except (OSError, ValueError, RecursionError, Refused) as exc:
                    entries.append({"id": entry_id, "status": f"inspection-needed: {exc}"})
    except FileNotFoundError:
        pass
    return {"root": str(root), "root_entries": rows, "cleanup_entries": entries}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(
        "Owner-reviewed cleanup. Requires exclusive cooperative access to selected artifacts. "
        "Owning-user manifests are trusted, not authenticated. No purge or automatic selection."))
    parser.add_argument("--workspace", required=True, type=Path)
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("inventory", help="read-only root and shared-store inventory (default)")
    move = commands.add_parser("quarantine")
    move.add_argument("name")
    move.add_argument("--reason", required=True)
    move.add_argument("--apply", action="store_true")
    undo = commands.add_parser("restore")
    undo.add_argument("id")
    undo.add_argument("--apply", action="store_true")
    sync = commands.add_parser("allocate-sync", help="internal: allocate metadata only; caller owns lock until finalization")
    sync.add_argument("--skill", choices=("cross-repo-epic", "workspace-orchestrator"), required=True)
    sync.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = args.workspace.resolve(strict=True)
        is_git = git_workspace(root, args.command in ("quarantine", "restore"))
        root_fd = os.open(root, DIR_FLAGS)
        try:
            if args.command in (None, "inventory"):
                print(json.dumps(inventory(root, root_fd, is_git), indent=2, ensure_ascii=True))
            else:
                storage_policy(root, is_git)
                preview_store(root_fd)
                if args.command == "allocate-sync":
                    sync_filesystem(root_fd, args.skill)
                if args.command == "quarantine":
                    print(quarantine(root, root_fd, args.name, args.reason, args.apply))
                elif args.command == "restore":
                    with store(root_fd) as cleanup:
                        if args.apply:
                            with lock(cleanup):
                                storage_policy(root, is_git)
                                print(restore_entry(root, root_fd, cleanup, args.id, True))
                        else:
                            print(restore_entry(root, root_fd, cleanup, args.id, False))
                elif not args.apply:
                    print("would allocate sync entry; no writes")
                else:
                    with store(root_fd, True) as cleanup, lock(cleanup, transfer=True):
                        storage_policy(root, is_git)
                        data = new_manifest(root_fd, str(uuid.uuid4()), "sync")
                        data["skill"] = args.skill
                        entry_id = allocate(cleanup, root_fd, data)
                        print(root / "tmp" / "cleanup" / entry_id, flush=True)
        finally:
            os.close(root_fd)
    except (OSError, ValueError, RecursionError, Refused, subprocess.SubprocessError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
