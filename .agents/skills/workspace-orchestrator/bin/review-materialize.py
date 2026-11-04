#!/usr/bin/env python3
"""Materialize selected bytes only; emit a mount/argv plan, never mount or run.

Installed alongside review-handoff.py in the trusted guest tooling directory.
All filesystem creation is exclusive and descriptor-relative with no symlinks.
"""

import argparse
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path, PurePosixPath

spec = importlib.util.spec_from_file_location("review_handoff", Path(__file__).with_name("review-handoff.py"))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


def absolute(value):
    value = str(value)
    path = PurePosixPath(value)
    h.require(path.is_absolute() and str(path) == value and not value.startswith("//")
              and ".." not in path.parts and "\0" not in value and value != "/", "canonical absolute CLI path required")
    return value


def open_directory(path):
    """Walk every component using held descriptors, not check-then-open paths."""
    fd = os.open("/", DIRECTORY)
    try:
        for part in PurePosixPath(path).parts[1:]:
            child = os.open(part, DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_regular(parent, name, limit, immutable=False, durable=False):
    fd = os.open(name, READ, dir_fd=parent)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        h.require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= limit,
                  "bounded single-link regular file required")
        if immutable:
            h.require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o400,
                      "materialized file permissions differ")
        raw = handle.read(limit + 1)
        h.require(len(raw) <= limit, "file grew beyond bound")
        if durable:
            os.fsync(handle.fileno())
        return raw


def read_path(path, limit):
    path = PurePosixPath(absolute(path))
    fd = open_directory(str(path.parent))
    try:
        return read_regular(fd, path.name, limit)
    finally:
        os.close(fd)


def private(fd):
    info = os.fstat(fd)
    h.require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
              and stat.S_IMODE(info.st_mode) == 0o700, "owned private directory required")


def write_file(parent, name, raw):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=parent)
    with os.fdopen(fd, "wb") as handle:
        os.fchmod(handle.fileno(), 0o400)
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def plan(value, output_root, runner, binary, output, python, profile=None):
    """CLI paths are trusted configuration; no executable path comes from bundle."""
    for path in (output_root, runner, binary, output, python):
        absolute(path)
    root = PurePosixPath(output_root)
    h.require(not any(PurePosixPath(p).is_relative_to(root) for p in (runner, binary, output, python)),
              "runtime CLI paths must be outside materialization root")
    for path in (runner, binary, output, python, profile):
        if path is not None:
            absolute(path)
            h.require(not any(PurePosixPath(path).is_relative_to(PurePosixPath(mount))
                              for mount in ("/candidate", "/review-input")), "CLI path collides with fixed mount")
    runtime = value["runtime"]
    argv = [python, "-I", "-B", runner, "--binary", binary, "--binary-sha256", runtime["binary_sha256"],
            "--cwd", runtime["cwd"], "--model=" + runtime["model"], "--agent=" + runtime["agent"],
            "--session=" + runtime["session"], "--context", "/review-input/context.json", "--output", output,
            "--source-map", "/review-input/source-map.json",
            "--role", "review", "--isolated-guest"]
    if profile is not None:
        h.require(not PurePosixPath(profile).is_relative_to(root), "profile collides with materialization root")
        h.require(h.digest(read_path(profile, h.MAX_BUNDLE)) == runtime["profile_sha256"], "profile hash differs")
        argv += ["--profile", profile]
    for obligation in value["context"]["obligations"]:
        argv += ["--obligation=" + obligation]
    for source in value["sources"]:
        argv += ["--source", source["guest_path"]]
    return {"status": "MATERIALIZED_PLAN_ONLY", "mounts": [
        {"source": str(root / "candidate"), "destination": "/candidate", "readonly": True},
        {"source": str(root / "metadata"), "destination": "/review-input", "readonly": True}],
        "mkdir_guest": ["/candidate", "/review-input"] + (["/review"] if runtime["cwd"] == "/review" else []),
        "runner_argv": argv, "profile_verified": profile is not None,
        "candidate_ready": False, "execution_credit": False, "delivery_credit": False}


def tree(value, planned):
    files = {"candidate/" + source["guest_path"][len("/candidate/"):]: h.encoded(source["content_base64"])
             for source in value["sources"]}
    files["metadata/context.json"] = h.canonical(value["context"])
    files["metadata/source-map.json"] = h.canonical(h.load("review-source-map").from_bundle(value))
    files["metadata/plan.json"] = h.canonical(planned)
    manifest = {"status": "STAGED_NONREADY_UNLESS_COMPLETE_REPLAY_VALIDATES", "bundle_sha256": h.digest(h.canonical(value)),
                "files": {name: h.digest(raw) for name, raw in sorted(files.items())},
                "disposal": "Only this newly created output root belongs to this attempt. Preserve on failure; operator may dispose of it."}
    files["MANIFEST.json"] = h.canonical(manifest)
    files["READY.json"] = h.canonical({"status": "MATERIALIZED_PLAN_ONLY", "manifest_sha256": h.digest(files["MANIFEST.json"]),
                                       "candidate_ready": False, "execution_credit": False, "delivery_credit": False})
    directories = {"candidate", "metadata"}
    for name in files:
        directories.update(str(p) for p in PurePosixPath(name).parents if str(p) != ".")
    return files, directories


def verify_tree(fd, files, directories, prefix="", durable=False):
    private(fd)
    expected = {name[len(prefix):].split("/")[0] for name in files.keys() | directories if name.startswith(prefix)}
    h.require(set(os.listdir(fd)) == expected, "existing tree is incomplete or contains extras; no merge")
    for name in sorted(expected):
        relative = prefix + name
        if relative in directories:
            child = os.open(name, DIRECTORY, dir_fd=fd)
            try:
                verify_tree(child, files, directories, relative + "/", durable=durable)
            finally:
                os.close(child)
        else:
            h.require(read_regular(fd, name, h.MAX_BUNDLE, immutable=True, durable=durable) == files[relative],
                      "existing bytes differ; no overwrite")
    if durable:
        os.fsync(fd)


def materialize(value, output_root, runner, binary, output, python="/usr/bin/python3", profile=None):
    h.validate(value)
    output_root = absolute(output_root)
    planned = plan(value, output_root, runner, binary, output, python, profile)
    files, directories = tree(value, planned)  # Complete validation before any writes.
    path = PurePosixPath(output_root)
    parent = open_directory(str(path.parent))
    fd = None
    try:
        private(parent)
        try:
            os.mkdir(path.name, 0o700, dir_fd=parent)
        except FileExistsError:
            fd = os.open(path.name, DIRECTORY, dir_fd=parent)
            verify_tree(fd, files, directories)
            # An earlier READY write/final fsync may have failed after bytes became
            # visible. Complete all durability work, including the root's parent.
            verify_tree(fd, files, directories, durable=True)
            os.fsync(parent)
            return planned
        fd = os.open(path.name, DIRECTORY, dir_fd=parent)
        os.fchmod(fd, 0o700)
        private(fd)
        # First artifact documents disposal even if subsequent writes fail.
        write_file(fd, "MANIFEST.json", files["MANIFEST.json"])
        os.fsync(fd)
        os.fsync(parent)
        handles = {".": fd}
        try:
            for directory in sorted(directories, key=lambda name: (name.count("/"), name)):
                relative = PurePosixPath(directory)
                owner = handles[str(relative.parent)]
                os.mkdir(relative.name, 0o700, dir_fd=owner)
                child = os.open(relative.name, DIRECTORY, dir_fd=owner)
                os.fchmod(child, 0o700)
                handles[directory] = child
            for name, raw in sorted(files.items()):
                if name in {"MANIFEST.json", "READY.json"}:
                    continue
                relative = PurePosixPath(name)
                write_file(handles[str(relative.parent)], relative.name, raw)
            for handle in handles.values():
                os.fsync(handle)
            verify_tree(fd, {k: v for k, v in files.items() if k != "READY.json"}, directories)
            write_file(fd, "READY.json", files["READY.json"])
            os.fsync(fd)
        finally:
            for name, handle in handles.items():
                if name != ".":
                    os.close(handle)
        verify_tree(fd, files, directories)
        os.fsync(parent)
        return planned
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle", "output-root", "runner", "binary", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--python", default="/usr/bin/python3")
    parser.add_argument("--profile")
    args = parser.parse_args()
    try:
        h.require(sys.flags.isolated and sys.dont_write_bytecode, "invoke with python3 -I -B")
        value = h.decode(read_path(args.bundle, h.MAX_BUNDLE))
        result = materialize(value, args.output_root, args.runner, args.binary, args.output, args.python, args.profile)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        # Never echo candidate content, bundle-supplied paths, or execution claims.
        print(json.dumps({"status": "UNVERIFIED", "candidate_ready": False, "execution_credit": False,
                          "delivery_credit": False, "reason": "validation or materialization failed; preserve any partial output root and its MANIFEST.json for disposal; no merge or cleanup performed"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
