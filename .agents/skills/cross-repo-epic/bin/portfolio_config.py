#!/usr/bin/env python3
"""Resolve which repositories and Project v2 board this skill operates on.

The skill used to hardcode one organization's three repositories and one
board's node id. That made a generic capability — ingest a Project board,
identify epics, reconcile cross-repo children — usable by exactly one
engagement. The logic was never engagement-specific; only the constants were.

Configuration comes from the SAME file the workspace-orchestrator monitor
reads, so an operator describes their portfolio once:

    {"schema_version": 1,
     "repositories": ["owner/repo-a", "owner/repo-b"],
     "project": {"owner": "owner", "number": 7}}

Resolution order: $CROSS_REPO_EPIC_CONFIG, then ./orchestrator.json relative to
the consumer workspace ($WORKSPACE_ORCHESTRATOR_ROOT or cwd).

DESIGN NOTES

`repositories` is not cosmetic — it is a scope-confinement control. The caller
supplies an epic reference and the board returns arbitrary items; both are
filtered against this set, so a board item or a crafted reference naming an
unconfigured repository is refused rather than fetched. Deriving the set from
config keeps that control and makes it operator-scoped instead of frozen.

Every failure path exits 3 (UNVERIFIED) and says which file and which field.
A missing or malformed config must never degrade to "no epics found": an empty
portfolio and an unreadable portfolio look identical in output and mean
opposite things.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
OWNER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
CONFIG_ENV = "CROSS_REPO_EPIC_CONFIG"
WORKSPACE_ENV = "WORKSPACE_ORCHESTRATOR_ROOT"
DEFAULT_BASENAME = "orchestrator.json"
MAX_CONFIG_BYTES = 100_000


def fail(tool: str, message: str) -> "None":
    print(f"{tool}: UNVERIFIED — {message}", file=sys.stderr)
    raise SystemExit(3)


def config_path() -> Path:
    raw = os.environ.get(CONFIG_ENV)
    if raw:
        return Path(raw).expanduser()
    root = os.environ.get(WORKSPACE_ENV)
    base = Path(root).expanduser() if root else Path.cwd()
    return base / DEFAULT_BASENAME


def load(tool: str) -> dict:
    """Return {"repositories": [...], "project": {...}|None, "path": Path}."""
    path = config_path()
    # Bounded regular file only. A symlink or a FIFO here would let whatever
    # can write the workspace redirect which repositories this skill reads.
    # "Absent" is the most common case and needs the most actionable message, so
    # check it before the generic guards — `is_file()` is false for a missing
    # path too, and would otherwise swallow it as "not a regular file".
    if not path.exists() and not path.is_symlink():
        fail(
            tool,
            f"no portfolio config at {path}. Copy orchestrator.example.json to "
            f"{DEFAULT_BASENAME} and name the repositories and Project board to "
            f"read, or set {CONFIG_ENV}.",
        )
    try:
        if path.is_symlink():
            raise ValueError("config must not be a symlink")
        if not path.is_file():
            raise ValueError("not a regular file")
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise ValueError(f"larger than {MAX_CONFIG_BYTES} bytes")
        config = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - reported verbatim, bounded below
        fail(tool, f"portfolio config at {path} is unreadable: {str(exc)[:200]}")

    if not isinstance(config, dict) or config.get("schema_version") != 1:
        fail(tool, f"{path}: config must be a schema-version 1 object")
    if not set(config).issubset({"schema_version", "repositories", "project"}):
        unknown = sorted(set(config) - {"schema_version", "repositories", "project"})
        fail(tool, f"{path}: unsupported field(s): {', '.join(unknown)}")

    repositories = config.get("repositories")
    if not isinstance(repositories, list) or not 1 <= len(repositories) <= 50:
        fail(tool, f"{path}: repositories must be a list of 1-50 entries")
    if len(set(repositories)) != len(repositories):
        fail(tool, f"{path}: repositories contains duplicates")
    for entry in repositories:
        if not isinstance(entry, str) or not REPO_RE.fullmatch(entry):
            fail(tool, f"{path}: {entry!r} is not a valid owner/name repository")

    project = config.get("project")
    if project is not None:
        if not isinstance(project, dict) or not {"owner", "number"} <= set(project):
            fail(tool, f"{path}: project must contain owner and number")
        if not set(project) <= {"owner", "number", "owner_type"}:
            unknown = sorted(set(project) - {"owner", "number", "owner_type"})
            fail(tool, f"{path}: project has unsupported field(s): {', '.join(unknown)}")
        if not isinstance(project["owner"], str) or not OWNER_RE.fullmatch(project["owner"]):
            fail(tool, f"{path}: project owner is invalid")
        if type(project["number"]) is not int or project["number"] <= 0:
            fail(tool, f"{path}: project number must be a positive integer")
        owner_type = project.get("owner_type", "organization")
        if owner_type not in {"organization", "user"}:
            fail(tool, f"{path}: project owner_type must be organization or user")
        project = dict(project)
        project["owner_type"] = owner_type

    return {"repositories": list(repositories), "project": project, "path": path}


# One GraphQL field per owner kind. GitHub exposes projectV2 under separate
# `organization` and `user` roots with no neutral one, and a combined query
# returns data PLUS a NOT_FOUND error for the wrong kind. Tolerating that error
# would mean relaxing the all-GraphQL-errors-are-fatal rule the callers rely on
# to reject partial responses, so the owner kind is declared in config instead
# of probed. Default is "organization".
PROJECT_ID_QUERY = {
    "organization": "query($owner:String!,$number:Int!){organization(login:$owner){projectV2(number:$number){id}}}",
    "user": "query($owner:String!,$number:Int!){user(login:$owner){projectV2(number:$number){id}}}",
}
PROJECT_ID_RE = re.compile(r"^PVT_[A-Za-z0-9_-]{1,64}$")


def project_id_command(project: dict) -> list[str]:
    """`gh` argv that resolves this project's node id. Caller runs it."""
    return [
        "gh", "api", "graphql",
        "-f", f"query={PROJECT_ID_QUERY[project['owner_type']]}",
        "-f", f"owner={project['owner']}",
        "-F", f"number={project['number']}",
    ]


def project_id_from_payload(tool: str, project: dict, payload: object) -> str:
    """Extract and validate the node id from the resolve query's response."""
    if not isinstance(payload, dict) or "errors" in payload:
        fail(tool, "could not resolve the Project v2 node id: GraphQL returned errors")
    data = payload.get("data")
    if not isinstance(data, dict):
        fail(tool, "could not resolve the Project v2 node id: response has no data")
    holder = data.get(project["owner_type"])
    if not isinstance(holder, dict):
        fail(
            tool,
            f"no {project['owner_type']} named {project['owner']!r} is readable — "
            f"check project.owner_type (it defaults to organization)",
        )
    node = holder.get("projectV2")
    if not isinstance(node, dict):
        fail(
            tool,
            f"{project['owner']} has no readable Project v2 number {project['number']}",
        )
    node_id = node.get("id")
    # Shape-check before it is interpolated into the next query.
    if not isinstance(node_id, str) or not PROJECT_ID_RE.fullmatch(node_id):
        fail(tool, "resolved Project v2 node id has an unexpected shape")
    return node_id


def short_names(repositories: list[str]) -> dict[str, str]:
    """Map a short alias to each full owner/name.

    Operators refer to `patterns#357`, not
    `GSA-TTS/agentic-coding-patterns#357`. Rather than a hardcoded alias table,
    strip the longest common prefix shared by every repository name — but only
    at a `-` or `_` boundary, so a prefix can never cut a word in half and
    produce a misleading stub. `{acme/api, acme/web}` share no prefix and keep
    their full names; `{org/x-one, org/x-two}` become `one` and `two`.

    Collisions are resolved by WIDENING, never by dropping. Two repositories in
    different owners can share a name (`a/x` and `b/x`), so a name-keyed map
    silently loses one — the first version of this function did exactly that,
    returning a single entry for `{a/x-dup, b/x-dup}`. Fall back through
    progressively less ambiguous keys and verify at each step that every
    repository is still reachable; the final fallback keys by the full
    `owner/name`, which is unique by construction.
    """
    names = [r.split("/", 1)[1] for r in repositories]
    prefix = ""
    if len(names) > 1:
        common = os.path.commonprefix(names)
        cut = max(common.rfind("-"), common.rfind("_"))
        if cut >= 0:
            prefix = common[: cut + 1]

    def keyed(fn) -> dict[str, str] | None:
        out: dict[str, str] = {}
        for name, full in zip(names, repositories):
            key = fn(name, full)
            if not key or key in out:
                return None  # ambiguous or empty: reject this keying entirely
            out[key] = full
        return out

    for strategy in (
        lambda name, full: name[len(prefix):] if prefix and name != prefix else name,
        lambda name, full: name,
        lambda name, full: full,
    ):
        candidate = keyed(strategy)
        if candidate is not None:
            return candidate
    # Unreachable: full owner/name is unique because load() rejects duplicates.
    return {full: full for full in repositories}
