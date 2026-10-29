#!/usr/bin/env python3
"""Capture bounded committed source without executing candidate checkout code."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import selectors
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

MAX_OUTPUT = 8_000_000
MAX_BLOB = 256_000
MAX_FILES = 200
OID = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
BASELINE = ("correctness", "acceptance", "test-adequacy", "maintainability", "baseline-security")


class Unverified(Exception):
    pass


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("ascii")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_bytes(repo: Path, *args: str, limit: int = MAX_OUTPUT) -> bytes:
    """Bound bytes and elapsed time while Git reads objects, never a shell."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1", GIT_OPTIONAL_LOCKS="0")
    command = ["git", "-c", "protocol.allow=never", "-c", "core.fsmonitor=false",
               "-c", "core.quotePath=true", "-c", "diff.orderFile=" + os.devnull,
               "-c", "diff.algorithm=myers", "-c", "diff.indentHeuristic=false",
               "-c", f"core.hooksPath={os.devnull}", "-C", str(repo), *args]
    result = bytearray()
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env) as child:
        assert child.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + 15
            try:
                while selector.get_map():
                    if time.monotonic() >= deadline:
                        raise Unverified("Git object read timed out")
                    for key, _ in selector.select(timeout=0.1):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                        else:
                            result.extend(chunk)
                            if len(result) > limit:
                                raise Unverified("Git output exceeds capture bound")
                if child.wait(timeout=max(0.01, deadline - time.monotonic())) != 0:
                    raise Unverified("Git object read failed; source coverage is unavailable")
            except BaseException:
                child.kill()
                child.wait()
                raise
    return bytes(result)


def commit(repo: Path, value: str) -> str:
    if not OID.fullmatch(value):
        raise Unverified("base and head must be full lowercase object IDs")
    actual = git_bytes(repo, "rev-parse", "--verify", f"{value}^{{commit}}", limit=100).decode().strip()
    if actual != value:
        raise Unverified("requested object is not a commit")
    return actual


def name_record(raw: bytes) -> dict[str, str | None]:
    if not raw or raw.startswith(b"/") or any(part in (b"", b".", b"..") for part in raw.split(b"/")):
        raise Unverified("invalid Git path")
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        text = None
    return {"path_base64": base64.b64encode(raw).decode("ascii"), "path_utf8": text}


def blob(repo: Path, mode: str, oid: str) -> dict[str, Any]:
    if mode == "000000":
        if set(oid) != {"0"}:
            raise Unverified("absent side has a nonzero object ID")
        return {"mode": mode, "oid": None, "kind": "absent"}
    if mode == "160000":
        return {"mode": mode, "oid": oid, "kind": "gitlink", "coverage": "UNVERIFIED"}
    if mode not in {"100644", "100755", "120000"}:
        raise Unverified("unsupported Git entry mode")
    data = git_bytes(repo, "cat-file", "blob", oid, limit=MAX_BLOB)
    result: dict[str, Any] = {"mode": mode, "oid": oid, "sha256": digest(data), "bytes": len(data)}
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        text = None
    if text is not None and "\0" not in text:
        result.update(encoding="utf-8", content=text)
    else:
        result.update(encoding="base64", content=base64.b64encode(data).decode("ascii"))
    result["kind"] = "symlink" if mode == "120000" else "blob"
    return result


def inventory(repo: Path, base: str, head: str) -> list[dict[str, Any]]:
    raw = git_bytes(repo, "diff-tree", "-r", "--no-commit-id", "--raw", "-z", "--no-renames",
                    "--ignore-submodules=none",
                    "--no-abbrev", base, head, "--")
    if not raw:
        return []
    parts = raw.split(b"\0")
    if parts.pop() != b"" or len(parts) % 2 or len(parts) // 2 > MAX_FILES:
        raise Unverified("changed-file inventory is malformed or oversized")
    files = []
    for index in range(0, len(parts), 2):
        fields = parts[index].decode("ascii").split()
        if len(fields) != 5 or not fields[0].startswith(":"):
            raise Unverified("invalid raw diff metadata")
        old_mode, new_mode, old_oid, new_oid, status = fields
        if not OID.fullmatch(old_oid) or not OID.fullmatch(new_oid) or status not in {"A", "D", "M", "T"}:
            raise Unverified("invalid raw diff identity")
        files.append({**name_record(parts[index + 1]), "status": status,
                      "before": blob(repo, old_mode[1:], old_oid),
                      "after": blob(repo, new_mode, new_oid)})
        if len(canonical(files)) > MAX_OUTPUT:
            raise Unverified("source inventory exceeds packet bound")
    return files


def obligations(files: list[dict[str, Any]]) -> list[dict[str, str]]:
    result = [{"id": item, "reason": "required for every change"} for item in BASELINE]
    paths = [item["path_utf8"] for item in files]
    triggers = {
        "trust-boundary": any(path is None or any(word in path.lower() for word in
                              ("agent", "permission", "auth", "policy", "sandbox", "workflow", "orchestrator"))
                              for path in paths),
        "dependency-supply-chain": any(path is not None and any(word in path.lower() for word in
                                      ("lock", "requirements", "package.json", "pyproject.toml")) for path in paths),
        "nonregular-source": any(side["kind"] in {"symlink", "gitlink"} or side.get("encoding") == "base64"
                                 for item in files for side in (item["before"], item["after"])),
    }
    result.extend({"id": name, "reason": "conservative source/path trigger; reviewer may add obligations"}
                  for name, triggered in triggers.items() if triggered)
    return result


def capture(repo: Path, repository: str, base: str, head: str, comparison: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise Unverified("invalid repository name")
    base, head = commit(repo, base), commit(repo, head)
    effective = base
    if comparison == "merge-base":
        candidates = git_bytes(repo, "merge-base", "--all", base, head, limit=200).decode().splitlines()
        if len(candidates) != 1:
            raise Unverified("comparison has no unique merge base")
        effective = commit(repo, candidates[0])
    elif comparison != "direct":
        raise Unverified("comparison must be direct or merge-base")
    files = inventory(repo, effective, head)
    diff = git_bytes(repo, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--binary",
                     "--ignore-submodules=none", "--submodule=short", "--no-relative",
                     "--full-index", "--no-color", "--src-prefix=a/", "--dst-prefix=b/", effective, head, "--")
    packet = {"schema_version": 1, "kind": "committed-local-source", "repository": repository,
              "repository_identity": "caller-declared; remote identity unverified",
              "base": base, "head": head, "comparison": comparison, "effective_base": effective,
              "files": files, "changed_inventory": "COMPLETE", "diff_base64": base64.b64encode(diff).decode("ascii"),
              "obligations": obligations(files), "policy_sha256": digest(Path(__file__).read_bytes()),
              "context_coverage": "UNVERIFIED", "limitations": [
                  "Unchanged dependency/context files are not captured.",
                  "Gitlinks contain identity only; binary and symlink entries need specialist assessment.",
                  "Committed objects do not include dirty checkout changes.",
                  "No review, execution, approval or delivery evidence is established by capture."]}
    if len(canonical(packet)) > MAX_OUTPUT:
        raise Unverified("packet exceeds capture bound")
    return packet


def publish(store: Path, repo: Path, packet: dict[str, Any]) -> str:
    """Immutable publication into an operator-selected store outside the candidate."""
    for component in (store, *store.parents):
        if component.is_symlink():
            raise Unverified("packet store path contains a symlink")
    store = store.resolve()
    checkout = Path(os.fsdecode(git_bytes(repo, "rev-parse", "--show-toplevel", limit=16384).rstrip(b"\n"))).resolve()
    if store.is_relative_to(checkout):
        raise Unverified("packet store must be outside the candidate checkout")
    store.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = store.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise Unverified("packet store must be private and current-user owned")
    data = canonical(packet)
    key = digest(data)
    path = store / f"{key}.json"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    except FileExistsError:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode) or handle.read(MAX_OUTPUT + 1) != data:
                raise Unverified("existing packet differs from its content address")
        return key
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(store, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--comparison", choices=("direct", "merge-base"), required=True)
    parser.add_argument("--store", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not sys.flags.isolated or not sys.dont_write_bytecode:
            raise Unverified("invoke with python3 -I -B")
        packet = capture(args.repo, args.repository, args.base, args.head, args.comparison)
        key = publish(args.store, args.repo, packet)
    except (Unverified, OSError, ValueError, subprocess.SubprocessError) as exc:
        reason = str(exc) if isinstance(exc, Unverified) else "source capture unavailable"
        print(json.dumps({"status": "UNVERIFIED", "reason": reason}))
        return 3
    print(json.dumps({"status": "CAPTURED", "packet": key, "files": len(packet["files"]),
                      "context_coverage": "UNVERIFIED", "review_credit": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
