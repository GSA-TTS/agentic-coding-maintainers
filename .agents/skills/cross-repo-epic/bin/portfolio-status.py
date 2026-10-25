#!/usr/bin/env python3
"""Read a configured Project v2 board and print its cross-repo epic view.

Which board and which repositories come from the portfolio config (see
portfolio_config.py); nothing here is specific to one organization.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_config  # noqa: E402  (sibling module, path set above)

MAX_PAGES = 20
GH_TIMEOUT_SECONDS = 60.0
TEST_TIMEOUT_ENV = "CROSS_REPO_EPIC_TEST_TIMEOUT_SECONDS"
MAX_ISSUE_NUMBER = 2_147_483_647
QUERY = r"""query($id:ID!,$after:String){
  node(id:$id){... on ProjectV2{
    items(first:100,after:$after){
      pageInfo{hasNextPage endCursor}
      nodes{
        content{
          __typename
           ... on Issue{number title state url repository{nameWithOwner} labels(first:20){totalCount pageInfo{hasNextPage endCursor} nodes{name}} subIssues(first:1){totalCount pageInfo{hasNextPage endCursor} nodes{number}}}
          ... on PullRequest{number title state url repository{nameWithOwner} labels(first:20){totalCount pageInfo{hasNextPage endCursor} nodes{name}}}
        }
        fieldValues(first:20){totalCount pageInfo{hasNextPage endCursor} nodes{
          ... on ProjectV2ItemFieldSingleSelectValue{name field{... on ProjectV2SingleSelectField{name}}}
        }}
      }
    }
  }}
}
"""


def safe_text(value: object, limit: int = 240) -> str:
    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
    text = "".join(
        "?" if unicodedata.category(ch).startswith("C") else ch
        for ch in text
    )
    return text[:limit] + ("..." if len(text) > limit else "")


def operation_timeout() -> float:
    raw = os.environ.get(TEST_TIMEOUT_ENV)
    if raw is None:
        return GH_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        value = 0
    if not 0.05 <= value <= 5:
        print(f"portfolio: UNVERIFIED — invalid {TEST_TIMEOUT_ENV}", file=sys.stderr)
        raise SystemExit(3)
    return value


def resolve_project_id(project: dict, deadline: float) -> str:
    """Turn configured owner+number into the board's node id.

    Shares the paging deadline: resolution plus paging must fit one budget, or
    a slow resolve would silently extend the overall timeout.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        print("portfolio: UNVERIFIED — GitHub operation exceeded its deadline", file=sys.stderr)
        raise SystemExit(3)
    try:
        result = subprocess.run(
            portfolio_config.project_id_command(project),
            capture_output=True,
            text=True,
            check=False,
            timeout=remaining,
        )
    except subprocess.TimeoutExpired:
        print("portfolio: UNVERIFIED — resolving the project board exceeded its deadline", file=sys.stderr)
        raise SystemExit(3)
    except OSError as exc:
        print(f"portfolio: UNVERIFIED — could not execute gh: {exc}", file=sys.stderr)
        raise SystemExit(3)
    if result.returncode != 0:
        detail = safe_text(result.stderr.strip() or f"gh exited {result.returncode}")
        print(f"portfolio: UNVERIFIED — could not resolve the project board: {detail}", file=sys.stderr)
        raise SystemExit(3)
    try:
        payload = json.loads(result.stdout)
    except Exception as exc:  # noqa: BLE001
        print(f"portfolio: UNVERIFIED — malformed project-resolve response: {safe_text(exc)}", file=sys.stderr)
        raise SystemExit(3)
    return portfolio_config.project_id_from_payload("portfolio", project, payload)


def query_page(project_id: str, after: str | None, deadline: float) -> dict:
    command = ["gh", "api", "graphql", "-f", f"query={QUERY}", "-f", f"id={project_id}"]
    if after:
        command += ["-f", f"after={after}"]
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        print("portfolio: UNVERIFIED — GitHub operation exceeded 60 seconds", file=sys.stderr)
        raise SystemExit(3)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=remaining,
        )
    except subprocess.TimeoutExpired:
        print(
            "portfolio: UNVERIFIED — GitHub operation exceeded 60 seconds",
            file=sys.stderr,
        )
        raise SystemExit(3)
    except OSError as exc:
        print(f"portfolio: UNVERIFIED — could not execute gh: {exc}", file=sys.stderr)
        raise SystemExit(3)
    if result.returncode != 0:
        detail = safe_text(result.stderr.strip() or f"gh exited {result.returncode}")
        print(f"portfolio: UNVERIFIED — could not read the project board: {detail}", file=sys.stderr)
        raise SystemExit(3)
    try:
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise TypeError("top-level GraphQL response is not an object")
        if "errors" in payload:
            errors = payload["errors"]
            if not isinstance(errors, list):
                raise TypeError("GraphQL errors is not a list")
            if errors:
                raise ValueError(f"GraphQL errors: {safe_text(errors)}")
        items = payload["data"]["node"]["items"]
        if not isinstance(items, dict) or not isinstance(items.get("pageInfo"), dict) or not isinstance(items.get("nodes"), list):
            raise TypeError("items/pageInfo/nodes have unexpected types")
        if not all(isinstance(node, dict) for node in items["nodes"]):
            raise TypeError("project item node is not an object")
        if type(items["pageInfo"].get("hasNextPage")) is not bool:
            raise TypeError("pageInfo.hasNextPage is not boolean")
        return items
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"portfolio: UNVERIFIED — malformed project-board response: {exc}", file=sys.stderr)
        raise SystemExit(3)


CONFIG = portfolio_config.load("portfolio")
ALLOWED = set(CONFIG["repositories"])
ALIASES = portfolio_config.short_names(CONFIG["repositories"])
ALIAS_OF = {full: alias for alias, full in ALIASES.items()}
if CONFIG["project"] is None:
    print(
        "portfolio: UNVERIFIED — the portfolio config declares no project board, "
        f"so there is nothing to read ({CONFIG['path']})",
        file=sys.stderr,
    )
    raise SystemExit(3)

deadline = time.monotonic() + operation_timeout()
PROJECT_ID = resolve_project_id(CONFIG["project"], deadline)

items = []
cursor = None
seen_cursors: set[str] = set()
for _page_number in range(1, MAX_PAGES + 1):
    page = query_page(PROJECT_ID, cursor, deadline)
    items.extend(page.get("nodes") or [])
    info = page.get("pageInfo") or {}
    if not info.get("hasNextPage"):
        break
    cursor = info.get("endCursor")
    if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
        print("portfolio: UNVERIFIED — project pagination cursor is missing or repeated", file=sys.stderr)
        raise SystemExit(3)
    seen_cursors.add(cursor)
else:
    print(f"portfolio: UNVERIFIED — project pagination exceeded {MAX_PAGES} pages", file=sys.stderr)
    raise SystemExit(3)


def complete_connection(value: object, name: str) -> list[dict]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} is not an object")
    nodes = value.get("nodes")
    info = value.get("pageInfo")
    total = value.get("totalCount")
    if not isinstance(nodes, list) or not isinstance(info, dict) or type(total) is not int:
        raise ValueError(f"{name} has malformed nodes/pageInfo/totalCount")
    if type(info.get("hasNextPage")) is not bool:
        raise ValueError(f"{name}.pageInfo.hasNextPage is not boolean")
    if info.get("hasNextPage") or len(nodes) != total:
        raise ValueError(f"{name} is truncated")
    if not all(isinstance(node, dict) for node in nodes):
        raise ValueError(f"{name} contains a non-object node")
    return nodes

rows = []
for item in items:
    try:
        content = item.get("content")
        if content is None:
            continue  # A ProjectV2 draft item has no repository-backed content.
        if not isinstance(content, dict):
            raise ValueError("project item content is not an object")
        if content.get("__typename") != "Issue":
            continue  # Draft items and PRs are not epics.
        if not isinstance(content.get("repository"), dict):
            raise ValueError("project item content/repository is not an object")
        repo = content["repository"].get("nameWithOwner")
        number = content.get("number")
        if not isinstance(repo, str) or type(number) is not int or not (1 <= number <= MAX_ISSUE_NUMBER):
            raise ValueError("project item repository/number has unexpected type")
        if content.get("state") not in {"OPEN", "CLOSED"}:
            raise ValueError("project item live state is invalid")
        raw_title = content.get("title")
        if not isinstance(raw_title, str):
            raise ValueError("project item title is not a string")
        title = safe_text(raw_title)
        label_nodes = complete_connection(content.get("labels"), "labels")
        if not all(isinstance(node.get("name"), str) for node in label_nodes):
            raise ValueError("label name is not a string")
        labels = {node["name"] for node in label_nodes}
        field_nodes = complete_connection(item.get("fieldValues"), "fieldValues")
        sub_issues = content.get("subIssues")
        if not isinstance(sub_issues, dict) or type(sub_issues.get("totalCount")) is not int or sub_issues["totalCount"] < 0:
            raise ValueError("subIssues count is unavailable or malformed")
        sub_info = sub_issues.get("pageInfo")
        sub_nodes = sub_issues.get("nodes")
        if not isinstance(sub_info, dict) or type(sub_info.get("hasNextPage")) is not bool or not isinstance(sub_nodes, list):
            raise ValueError("subIssues pageInfo/nodes are malformed")
        # first:1 is only a presence probe. Count consistency for a single
        # probe item is enough to refuse contradictory or truncated evidence;
        # epic-status fetches and validates the full child list separately.
        if len(sub_nodes) != min(sub_issues["totalCount"], 1):
            raise ValueError("subIssues presence probe contradicts totalCount")
        expected_more = sub_issues["totalCount"] > 1
        if sub_info["hasNextPage"] != expected_more:
            raise ValueError("subIssues pagination contradicts totalCount")
        child_cursor = sub_info.get("endCursor")
        if expected_more and (not isinstance(child_cursor, str) or not child_cursor):
            raise ValueError("subIssues pagination cursor is unavailable")
        if sub_issues["totalCount"] and (
            not isinstance(sub_nodes[0], dict) or
            type(sub_nodes[0].get("number")) is not int or
            not 1 <= sub_nodes[0]["number"] <= MAX_ISSUE_NUMBER
        ):
            raise ValueError("subIssues presence probe has no valid issue identity")
    except (AttributeError, TypeError, ValueError) as exc:
        print(f"portfolio: UNVERIFIED — malformed project item: {exc}", file=sys.stderr)
        raise SystemExit(3)
    is_epic = "epic" in labels or title.lower().startswith(("epic:", "[epic]")) or sub_issues["totalCount"] > 0
    if repo not in ALLOWED or not is_epic:
        continue
    fields = {}
    for value in field_nodes:
        field = value.get("field")
        if field is not None and not isinstance(field, dict):
            print("portfolio: UNVERIFIED — malformed project field metadata", file=sys.stderr)
            raise SystemExit(3)
        field_name = (field or {}).get("name")
        if field_name is not None and not isinstance(field_name, str):
            print("portfolio: UNVERIFIED — project field name is not a string", file=sys.stderr)
            raise SystemExit(3)
        if field_name:
            field_value = value.get("name")
            if field_value is not None and not isinstance(field_value, str):
                print("portfolio: UNVERIFIED — project field value is not a string", file=sys.stderr)
                raise SystemExit(3)
            fields[field_name] = field_value or ""
    rows.append(
        (
            ALIAS_OF.get(repo, repo),
            number,
            safe_text(fields.get("Status") or "UNSET"),
            safe_text(content.get("state") or "UNVERIFIED"),
            safe_text(fields.get("Work Type") or ""),
            safe_text(fields.get("Area") or ""),
            safe_text(fields.get("Flag") or ""),
            title,
            f"https://github.com/{repo}/issues/{number}",
            sub_issues["totalCount"],
            "sub-issues" if sub_issues["totalCount"] > 0 and "epic" not in labels and
                not title.lower().startswith(("epic:", "[epic]")) else "label/title",
        )
    )

if not rows:
    configured = ", ".join(sorted(ALLOWED))
    print(
        "portfolio: UNVERIFIED — the board returned zero epic issues for the "
        f"configured repositories ({configured}). A candidate needs an `epic` label, "
        "an `Epic:`/`[EPIC]` title prefix, or a sub-issue; this is not evidence of no work.",
        file=sys.stderr,
    )
    raise SystemExit(3)

order = {"In Progress": 0, "Needs Review": 1, "Todo": 2, "Done": 3, "Cancelled": 4, "UNSET": 5}
rows.sort(key=lambda row: (order.get(row[2], 9), row[0], int(row[1]) if str(row[1]).isdigit() else 0))

timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
print(f"Evidence timestamp: {timestamp}")
board = CONFIG["project"]
print(
    f"Project v2 {board['owner']}/#{board['number']} epic coordination view "
    "(verify live PR/check state before decisions):"
)
for repo, number, status, live_state, work_type, area, flag, title, url, children_count, signal in rows:
    mismatch = (live_state == "CLOSED" and status not in {"Done", "Cancelled"}) or (
        live_state == "OPEN" and status in {"Done", "Cancelled"}
    )
    suffix = f" [{flag}]" if flag else ""
    mismatch_note = " [BOARD/LIVE MISMATCH]" if mismatch else ""
    print(f"  {status:<12} {repo}#{number}{suffix} — {title}{mismatch_note}")
    print(f"               {url}; live={live_state}")
    if signal == "sub-issues":
        print(f"               EPIC CANDIDATE (sub-issues): {children_count} child(ren); confirm with the owning issue")
    else:
        print("               EPIC CANDIDATE (label/title): confirm role with the owning issue")
    details = []
    if work_type:
        details.append(f"type={work_type}")
    if area:
        details.append(f"area={area}")
    if details:
        print(f"               {'; '.join(details)}")

covered = {row[0] for row in rows}
expected = set(ALIASES)
print(f"Coverage: {len(rows)} epic candidate(s) across {len(covered)} repo(s)")
missing = sorted(expected - covered)
if missing:
    print(f"Coverage note: no epic candidate on the board for {', '.join(missing)}")
print("Parent/Sub-issues progress: unavailable from the Project v2 API; inspect active epic issues directly.")
