#!/usr/bin/env python3
"""Compare an operator-created repair commit; never create or check out a commit.

The foreground caller owns the lock and the single task/receipt write. Retention
rechecks immutable objects, not today's index, branch, or filesystem. Exclusive
cooperative ownership is required: these observations are not a filesystem lock.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import os
import re
import stat
import time
from pathlib import Path

ACTION = "adopt-owner-repair-head"
MAX_FILES = 512
MAX_BYTES = 16_000_000
MAX_CALLS = 1100
MAX_SECONDS = 60
OID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Git:
    """Reuse the installed bounded, no-network raw-object reader, with a total budget."""

    def __init__(self, path):
        self.path = Path(path)
        self.reader = load("review-packet")
        self.calls = self.bytes = 0
        self.inventories = {}
        self.deadline = time.monotonic() + MAX_SECONDS

    def charge(self, size):
        self.bytes += size
        require(self.bytes <= MAX_BYTES and time.monotonic() <= self.deadline,
                "adoption comparison byte/time budget exceeded")

    def run(self, *args, limit=262_144):
        self.calls += 1
        require(self.calls <= MAX_CALLS, "adoption Git operation budget exceeded")
        self.charge(0)
        raw = self.reader.git_bytes(self.path, *args, limit=min(limit, MAX_BYTES - self.bytes))
        self.charge(len(raw))
        return raw

    def obj(self, oid, kind, limit=262_144):
        require(isinstance(oid, str) and OID.fullmatch(oid), "full object ID required")
        # cat-file <type> alone can peel tags; check the actual type first.
        require(self.run("cat-file", "-t", oid, limit=16) == (kind + "\n").encode(),
                "wrong raw object type")
        raw = self.run("cat-file", kind, oid, limit=limit)
        algorithm = hashlib.sha1 if len(oid) == 40 else hashlib.sha256
        require(algorithm(kind.encode() + b" " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == oid,
                "raw object hash mismatch")
        return raw


def tree_inventory(git, commit):
    """Derive paths only from hash-verified root and descendant raw trees."""
    headers = commit.split(b"\n\n", 1)
    require(len(headers) == 2, "malformed raw commit")
    roots = [line[5:] for line in headers[0].split(b"\n") if line.startswith(b"tree ")]
    require(len(roots) == 1, "one raw commit tree required")
    root = roots[0].decode("ascii")
    if root in git.inventories:
        return git.inventories[root]
    files, trees = {}, 0

    def walk(oid, prefix=b"", depth=0):
        nonlocal trees
        trees += 1
        require(trees <= MAX_FILES and depth <= 32, "tree inventory exceeds bound")
        raw = git.obj(oid, "tree")
        require(raw or not prefix, "empty descendant tree unsupported")
        offset, names, previous = 0, set(), None
        width = len(oid) // 2
        while offset < len(raw):
            git.charge(0)
            space = raw.index(b" ", offset)
            end = raw.index(b"\0", space + 1)
            mode, name = raw[offset:space], raw[space + 1:end]
            require(mode in {b"40000", b"100644", b"100755"} and name
                    and b"/" not in name and name not in {b".", b".."}
                    and name.lower() != b".git" and name not in names,
                    "unsupported raw tree entry")
            order = name + (b"/" if mode == b"40000" else b"\0")
            require(previous is None or previous < order, "noncanonical tree ordering")
            previous = order
            names.add(name)
            require(end + 1 + width <= len(raw), "truncated tree object ID")
            child = raw[end + 1:end + 1 + width].hex()
            offset = end + 1 + width
            path = prefix + name
            if mode == b"40000":
                walk(child, path + b"/", depth + 1)
            else:
                require(len(files) < MAX_FILES, "tree file inventory exceeds bound")
                files[path] = (mode, child)
    walk(root)
    git.inventories[root] = files
    return files


def verify_origin(git, repository):
    # Read configured values, not get-url (which applies insteadOf rewrites).
    raw = git.run("config", "--null", "--get-all", "remote.origin.url", limit=4096)
    values = raw.split(b"\0")
    require(len(values) == 2 and values[1] == b"", "exactly one origin URL required")
    url = values[0].decode("ascii")
    match = re.fullmatch(r"(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)"
                         r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?", url)
    require(match is not None and match[1].casefold() == repository.casefold(),
            "current GitHub origin differs from task repository")


def links(record, request):
    key = request["payload"]["apply_operation_id"]
    app = record.get("foreground_repairs", {}).get("applications", {}).get(key)
    require(app is not None and app["final"] is not None, "final foreground application required")
    item = record["repair_protocol"]["operations"][app["repair_operation_id"]]
    require(item["phase"] == app["final"]["result"]["status"] == "APPLIED_UNREVIEWED",
            "applied unreviewed outcome required")
    proposal = record["repair_proposals"][app["request"]["payload"]["admission_id"]]
    correction = record["repair_protocol"]["corrections"][item["correction_id"]]
    require(app["final"]["resulting_revision"] <= request["expected_revision"], "adoption precedes application")
    require(proposal == max((p for p in record["repair_proposals"].values()
                            if p["admission"]["correction_id"] == item["correction_id"]),
                           key=lambda p: p["resulting_revision"]), "latest proposal required")
    return app, item, proposal, correction


def comparison(git, item, head):
    original = item["head"]
    require(head != original, "new repair head required")
    old_commit = git.obj(original, "commit")
    commit = git.obj(head, "commit")
    headers = commit.split(b"\n\n", 1)
    require(len(headers) == 2, "malformed raw commit")
    parents = [line[7:] for line in headers[0].split(b"\n") if line.startswith(b"parent ")]
    require(parents == [original.encode()], "repair commit must have exactly the original head as parent")
    old_tree, new_tree = tree_inventory(git, old_commit), tree_inventory(git, commit)
    require(old_tree.keys() == new_tree.keys(), "repair adds or removes paths")
    changes = {}
    raw = b""
    for path in sorted(old_tree):
        if old_tree[path] == new_tree[path]:
            continue
        (mode1, before), (mode2, after) = old_tree[path], new_tree[path]
        require(mode1 == mode2 == b"100644",
                "only retained ordinary modified files permitted")
        changes[path.decode("ascii")] = (before, after)
        raw += b":100644 100644 " + before.encode() + b" " + after.encode() + b" M\0" + path + b"\0"
    require(set(changes) == {entry["path"] for entry in item["entries"]}, "repair paths differ")
    files = []
    for entry, saved in zip(item["entries"], item["before"]):
        before_oid, after_oid = changes[entry["path"]]
        before, after = git.obj(before_oid, "blob"), git.obj(after_oid, "blob")
        require(hashlib.sha256(before).hexdigest() == entry["before_sha256"]
                and after == base64.b64decode(entry["after_base64"], validate=True)
                and hashlib.sha256(after).hexdigest() == entry["after_sha256"], "repair blob bytes differ")
        files.append({"path": entry["path"], "git_mode": "100644", "filesystem_mode": saved["mode"],
                      "before_oid": before_oid, "after_oid": after_oid,
                      "before_sha256": entry["before_sha256"], "after_sha256": entry["after_sha256"]})
    return {"schema_version": 1, "head": head, "parent": original,
            "commit_sha256": hashlib.sha256(commit).hexdigest(),
            "diff_sha256": hashlib.sha256(raw).hexdigest(), "files": files}


def clean_checkout(git, record, head, item):
    c, repair = load("review-collect"), load("repair-apply")
    c.no_links(git.path)
    require(git.run("rev-parse", "--show-toplevel").rstrip(b"\n") == os.fsencode(git.path),
            "actual worktree root differs")
    require(git.run("symbolic-ref", "--quiet", "HEAD") == ("refs/heads/" + record["branch"] + "\n").encode(),
            "actual worktree branch differs")
    require(git.run("rev-parse", "--verify", "HEAD", limit=100) == (head + "\n").encode(), "actual HEAD differs")
    expected = tree_inventory(git, git.obj(head, "commit"))
    index = git.run("ls-files", "--stage", "-z", limit=262_144)
    indexed = {}
    parts = index.split(b"\0")
    require(parts.pop() == b"" and len(parts) <= MAX_FILES, "checkout inventory exceeds bound")
    for part in parts:
        metadata, path = part.split(b"\t", 1)
        fields = metadata.split()
        require(len(fields) == 3 and fields[2] == b"0" and fields[0] in {b"100644", b"100755"},
                "unsupported index entry")
        git.reader.name_record(path)
        require(path not in indexed, "duplicate checkout path")
        indexed[path] = (fields[0], fields[1].decode("ascii"))
    require(expected == indexed, "index differs from committed tree")
    seen, count = set(), 0
    # Include ignored and untracked files; never invoke status, clean/smudge, or
    # attributes. Refuse links, special files and nested repositories explicitly.
    def walk(directory, prefix=b""):
        nonlocal count
        with os.scandir(directory) as entries:
            for entry in entries:
                path = prefix + os.fsencode(entry.name)
                if path == b".git":
                    continue
                count += 1
                git.charge(0)
                require(count <= MAX_FILES * 2, "filesystem inventory exceeds bound")
                if entry.is_dir(follow_symlinks=False):
                    require(any(p.startswith(path + b"/") for p in expected), "untracked directory")
                    walk(entry.path, path + b"/")
                    continue
                require(path in expected, "untracked or ignored file")
                mode, oid = expected[path]
                with repair.parent_fd(git.path, os.fsdecode(path)) as (parent, name, device):
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                    with os.fdopen(fd, "rb") as handle:
                        info = os.fstat(handle.fileno())
                        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_dev == device
                                and stat.S_IMODE(info.st_mode) in ({0o600, 0o644} if mode == b"100644" else {0o700, 0o755}),
                                "unsupported tracked filesystem entry")
                        raw = handle.read(1_000_001)
                require(len(raw) <= 1_000_000, "tracked file exceeds bound")
                git.charge(len(raw))
                require(raw == git.obj(oid, "blob", limit=1_000_000), "tracked raw bytes differ")
                seen.add(path)
    walk(git.path)
    require(seen == set(expected), "missing tracked file")
    observed = repair.inspect_targets(git.path, item["entries"])
    require(observed == [{"path": e["path"], "sha256": e["after_sha256"], "mode": b["mode"]}
                         for e, b in zip(item["entries"], item["before"])], "retained filesystem modes/bytes differ")


def result(request, item, witness):
    return {"status": "REPAIR_HEAD_ADOPTED_UNREVIEWED", "head": request["payload"]["head"],
            "original_head": item["head"], "material_epoch": item["epoch"] + 1,
            "comparison_sha256": hashlib.sha256(load("review-collect").canonical(witness)).hexdigest()}


def retained(record, request, reference):
    c = load("review-collect")
    c.fields(reference, {"table", "key", "repair_operation_id", "proposal_id", "bundle_sha256", "comparison"})
    app, item, _, _ = links(record, request)
    require(reference["table"] == "foreground_repairs.applications"
            and reference["key"] == request["payload"]["apply_operation_id"]
            and reference["repair_operation_id"] == app["repair_operation_id"]
            and reference["proposal_id"] == app["request"]["payload"]["admission_id"]
            and reference["bundle_sha256"] == item["bundle_sha256"], "adoption references changed")
    matches = [receipt for receipt in record["foreground_control"]["receipts"].values()
               if receipt["request"]["action"] == ACTION
               and receipt["request"]["payload"]["apply_operation_id"] == reference["key"]]
    require(len(matches) == 1, "application adopted more than once")
    witness = comparison(Git(record["worktree"]), item, request["payload"]["head"])
    require(c.canonical(witness) == c.canonical(reference["comparison"]), "retained comparison differs")
    return result(request, item, witness)


def adopt(record, request, root):
    coordinator = load("orchestrator-state")
    coordinator.verify_reservations(root, record)
    app, item, proposal, correction = links(record, request)
    require(record["state"] == "Implementing" and record["kind"] == "implementation"
            and record["worker"] == item["worker"] == proposal["admission"]["worker"]
            and record["owner"] == correction["owner"] == item["worker"]["owner"]
            and record["rework_count"] == item["cycle"]
            and record["review_protocol"]["material_epoch"] == item["epoch"]
            and record["review_protocol"]["generations"][-1]["number"] == correction["generation"]
            and all(type(record["leases"].get(k)) is int for k in ("global_slot", "implementation_lane")),
            "current original owner, worker, leases, cycle or epoch differs")
    for field in ("head", "base", "repo", "branch", "worktree", "owned_paths", "restricted_paths", "acceptance_criteria"):
        require(record[{"head": "head_sha", "base": "base_sha"}.get(field, field)] == correction[field],
                "current correction scope differs")
    require(not any(r["request"]["action"] == ACTION and r["request"]["payload"]["apply_operation_id"]
                    == request["payload"]["apply_operation_id"]
                    for r in record["foreground_control"]["receipts"].values()), "application already adopted")
    git = Git(record["worktree"])
    verify_origin(git, record["repo"])
    witness = comparison(git, item, request["payload"]["head"])
    clean_checkout(git, record, request["payload"]["head"], item)
    record["head_sha"] = request["payload"]["head"]
    record["review_protocol"]["material_epoch"] += 1
    if "legacy_finding_dispositions" in record:
        record["legacy_finding_dispositions"]["epoch"] += 1
    record["reviewed_sha"], record["reviewers"], record["validation"] = "", [], []
    record["next_action"] = "fresh execution and independent review at adopted repair head"
    reference = {"table": "foreground_repairs.applications", "key": request["payload"]["apply_operation_id"],
                 "repair_operation_id": app["repair_operation_id"],
                 "proposal_id": app["request"]["payload"]["admission_id"],
                 "bundle_sha256": item["bundle_sha256"], "comparison": witness}
    return result(request, item, witness), reference
