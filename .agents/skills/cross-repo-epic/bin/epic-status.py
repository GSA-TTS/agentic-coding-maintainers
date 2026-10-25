#!/usr/bin/env python3
"""Fetch one epic, its board metadata, and all direct cross-repo children.

Which repositories and which Project v2 board are configured, not hardcoded;
see portfolio_config.py.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_config  # noqa: E402  (sibling module, path set above)

CONFIG = portfolio_config.load("epic")
ALLOWED = set(CONFIG["repositories"])
ALIASES = portfolio_config.short_names(CONFIG["repositories"])

MAX_ISSUE_NUMBER = 2_147_483_647
MAX_PAGES = 20
GH_TIMEOUT_SECONDS = 60.0
TEST_TIMEOUT_ENV = "CROSS_REPO_EPIC_TEST_TIMEOUT_SECONDS"
QUERY = r"""query($owner:String!,$repo:String!,$number:Int!,$after:String){
  repository(owner:$owner,name:$repo){
    issue(number:$number){
      __typename number title state url
      labels(first:20){totalCount pageInfo{hasNextPage endCursor} nodes{name}}
      subIssues(first:100,after:$after){
        totalCount pageInfo{hasNextPage endCursor}
        nodes{number title state url repository{nameWithOwner}}
      }
      projectItems(first:20){
        totalCount pageInfo{hasNextPage endCursor}
        nodes{
          project{id number title owner{__typename ... on Organization{login} ... on User{login}}}
          fieldValues(first:20){
            totalCount pageInfo{hasNextPage endCursor}
            nodes{... on ProjectV2ItemFieldSingleSelectValue{name field{... on ProjectV2SingleSelectField{name}}}}
          }
        }
      }
    }
  }
}
"""


def fail(message: str, code: int = 3) -> None:
    prefix = "usage" if code == 2 else "epic: UNVERIFIED"
    print(f"{prefix} — {message}", file=sys.stderr)
    raise SystemExit(code)


def parse_ref(value: str) -> tuple[str, int]:
    """Resolve a reference to (owner/name, issue number).

    Accepts a configured short alias (`patterns#357`), a full `owner/name#N`,
    or an issue URL. The accepted set is built from the CONFIGURED repositories
    and aliases, so this stays a scope-confinement check and not just parsing:
    a syntactically valid reference to an unconfigured repository is refused
    before any network call. Alternations are escaped so a repository name
    containing regex metacharacters cannot widen the pattern.
    """
    alias_re = "|".join(re.escape(a) for a in sorted(ALIASES, key=len, reverse=True))
    full_re = "|".join(re.escape(r) for r in sorted(ALLOWED, key=len, reverse=True))
    short = re.fullmatch(rf"({alias_re})#([1-9][0-9]*)", value) if alias_re else None
    qualified = re.fullmatch(rf"({full_re})#([1-9][0-9]*)", value) if full_re else None
    url = (
        re.fullmatch(rf"https://github\.com/({full_re})/issues/([1-9][0-9]*)/?", value)
        if full_re
        else None
    )
    match = short or qualified or url
    if match:
        digits = match.group(2)
        if len(digits) > 10:
            fail("issue number is out of range", 2)
        number = int(digits)
        if number > MAX_ISSUE_NUMBER:
            fail("issue number is out of range", 2)
        if short:
            return ALIASES[match.group(1)], number
        return match.group(1), number
    hint = ", ".join(f"{a}#N" for a in sorted(ALIASES)) or "owner/name#N"
    fail(f"expected {hint}, a configured owner/name#N, or an issue URL", 2)


def matches_configured_board(project: dict) -> bool:
    """True when this project item belongs to the board named in config."""
    board = CONFIG["project"]
    if board is None:
        return False
    if project.get("number") != board["number"]:
        return False
    owner = project.get("owner")
    if not isinstance(owner, dict):
        fail("board owner metadata is not an object")
    login = owner.get("login")
    kind = owner.get("__typename")
    if not isinstance(login, str) or not isinstance(kind, str):
        fail("board owner login or type is not a string")
    expected_kind = "Organization" if board["owner_type"] == "organization" else "User"
    return login == board["owner"] and kind == expected_kind


def safe_text(value: object, limit: int = 240) -> str:
    text = str(value or "")
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    text = "".join("?" if unicodedata.category(ch).startswith("C") else ch for ch in text)
    return text[:limit] + ("..." if len(text) > limit else "")


def check_connection(connection: object, name: str) -> dict:
    if not isinstance(connection, dict):
        fail(f"{name} is not an object")
    nodes = connection.get("nodes")
    info = connection.get("pageInfo")
    total = connection.get("totalCount")
    if not isinstance(nodes, list) or not isinstance(info, dict) or type(total) is not int:
        fail(f"{name} has malformed nodes/pageInfo/totalCount")
    if type(info.get("hasNextPage")) is not bool:
        fail(f"{name}.pageInfo.hasNextPage is not boolean")
    if not all(isinstance(node, dict) for node in nodes):
        fail(f"{name} contains a non-object node")
    return connection


def operation_timeout() -> float:
    raw = os.environ.get(TEST_TIMEOUT_ENV)
    if raw is None:
        return GH_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        value = 0
    if not 0.05 <= value <= 5:
        fail(f"invalid {TEST_TIMEOUT_ENV}")
    return value


def query(full_repo: str, number: int, after: str | None, deadline: float) -> dict:
    owner, name = full_repo.split("/", 1)
    command = [
        "gh", "api", "graphql", "-f", f"query={QUERY}", "-f", f"owner={owner}",
        "-f", f"repo={name}", "-F", f"number={number}",
    ]
    if after:
        command += ["-f", f"after={after}"]
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        fail("GitHub operation exceeded 60 seconds")
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=remaining,
        )
    except subprocess.TimeoutExpired:
        fail("GitHub operation exceeded 60 seconds")
    except OSError as exc:
        fail(f"could not execute gh: {exc}")
    if result.returncode != 0:
        fail(safe_text(result.stderr.strip() or f"gh exited {result.returncode}"))
    try:
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            fail("top-level GitHub response is not an object")
    except json.JSONDecodeError as exc:
        fail(f"malformed GitHub response: {exc}")
    if "errors" in payload:
        errors = payload["errors"]
        if not isinstance(errors, list):
            fail("GraphQL errors is not a list")
        if errors:
            fail(f"GitHub returned GraphQL errors: {safe_text(errors)}")
    try:
        issue = payload["data"]["repository"]["issue"]
    except (KeyError, TypeError) as exc:
        fail(f"malformed issue response: {exc}")
    if issue is None:
        fail("issue does not exist or is inaccessible")
    if not isinstance(issue, dict) or issue.get("__typename") != "Issue":
        fail("requested object is not an issue")
    return issue


full_repo, number = parse_ref(sys.argv[1] if len(sys.argv) == 2 else "")
# Defense in depth, and NOT dead code — this was verified by mutation rather
# than assumed. parse_ref builds its patterns from ALLOWED, so it normally
# refuses an out-of-portfolio reference first. But if its regex escaping
# regresses, a name like `acme/a.i` becomes the pattern `a.i`, `acme/aXi`
# matches, and THIS check is the only thing that still refuses it. The two
# guards fail independently, which is the point of keeping both.
#
# Removing THIS line alone is not detectable by the suite, because parse_ref
# still refuses first — mutation testing reports it as surviving. Removing it
# TOGETHER with the escaping is detected (rc moves 2 -> 3, and the reference
# reaches the network path). So it is a real second layer, not dead code, and
# its survival as a single mutant is expected rather than a coverage gap.
if full_repo not in ALLOWED:
    fail("unsupported repository", 2)

children = []
child_ids: set[tuple[str, int]] = set()
seen_cursors: set[str] = set()
cursor = None
issue = None
expected_children = None
epic_identity = None
deadline = time.monotonic() + operation_timeout()
for page_number in range(1, MAX_PAGES + 1):
    page_issue = query(full_repo, number, cursor, deadline)
    if type(page_issue.get("number")) is not int or page_issue["number"] != number:
        fail("returned epic identity does not match the requested issue")
    if page_issue.get("state") not in {"OPEN", "CLOSED"}:
        fail("returned epic state is invalid")
    if not isinstance(page_issue.get("title"), str) or not isinstance(page_issue.get("url"), str):
        fail("returned epic title/url has unexpected type")
    page_identity = (
        page_issue.get("number"), page_issue.get("title"),
        page_issue.get("url"), page_issue.get("state"),
    )
    if epic_identity is None:
        epic_identity = page_identity
    elif page_identity != epic_identity:
        fail("epic identity changed during sub-issue pagination")
    if issue is None:
        issue = page_issue
        labels = check_connection(issue.get("labels"), "labels")
        if not all(isinstance(node.get("name"), str) for node in labels["nodes"]):
            fail("issue label name is not a string")
        if labels["pageInfo"].get("hasNextPage") or len(labels["nodes"]) != labels["totalCount"]:
            fail("issue labels were truncated")
        project_items = check_connection(issue.get("projectItems"), "projectItems")
        if project_items["pageInfo"].get("hasNextPage") or len(project_items["nodes"]) != project_items["totalCount"]:
            fail("project items were truncated")
    connection = check_connection(page_issue.get("subIssues"), "subIssues")
    if expected_children is None:
        expected_children = connection["totalCount"]
    elif connection["totalCount"] != expected_children:
        fail("sub-issue total changed during pagination")
    for child in connection["nodes"]:
        repository = child.get("repository")
        if not isinstance(repository, dict) or not isinstance(repository.get("nameWithOwner"), str):
            fail("subIssues contains malformed repository identity")
        child_number = child.get("number")
        if type(child_number) is not int or not (1 <= child_number <= MAX_ISSUE_NUMBER) or child.get("state") not in {"OPEN", "CLOSED"}:
            fail("subIssues contains malformed issue identity/state")
        child_repo = repository["nameWithOwner"]
        if child_repo not in ALLOWED:
            fail(f"sub-issue repository is outside the allowed portfolio: {safe_text(child_repo)}")
        child_id = (child_repo, child_number)
        if child_id in child_ids:
            fail(f"duplicate sub-issue returned during pagination: {child_repo}#{child['number']}")
        child_ids.add(child_id)
    children.extend(connection["nodes"])
    info = connection["pageInfo"]
    if not info.get("hasNextPage"):
        if len(children) != expected_children:
            fail(f"sub-issue count mismatch: expected {expected_children}, retrieved {len(children)}")
        break
    next_cursor = info.get("endCursor")
    if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
        fail("sub-issue pagination cursor is missing or repeated")
    seen_cursors.add(next_cursor)
    cursor = next_cursor
else:
    fail(f"sub-issue pagination exceeded {MAX_PAGES} pages")

assert issue is not None
label_names = {node["name"] for node in issue["labels"]["nodes"]}
title = safe_text(issue.get("title"))
is_epic = "epic" in label_names or title.lower().startswith(("epic:", "[epic]")) or expected_children > 0
if not is_epic:
    fail("requested issue is not an epic candidate by label, title or sub-issues", 2)

project_fields = {}
project_matches = 0
for item in issue["projectItems"]["nodes"]:
    project = item.get("project")
    if not isinstance(project, dict):
        fail("project item project metadata is not an object")
    # Match the CONFIGURED board. A bare number is ambiguous — two owners can
    # each have a project #120 — so compare owner login and kind as well. This
    # keeps the match exact without a second round-trip to resolve a node id.
    if not matches_configured_board(project):
        continue
    project_matches += 1
    values = check_connection(item.get("fieldValues"), "board fieldValues")
    if values["pageInfo"].get("hasNextPage") or len(values["nodes"]) != values["totalCount"]:
        fail("board fields were truncated")
    for value in values["nodes"]:
        field = value.get("field")
        if field is not None and not isinstance(field, dict):
            fail("board field metadata is not an object")
        if not isinstance(field, dict):
            continue
        field_name = field.get("name")
        if field_name is not None and not isinstance(field_name, str):
            fail("board field name is not a string")
        if field_name:
            field_value = value.get("name")
            if field_value is not None and not isinstance(field_value, str):
                fail("board field value is not a string")
            project_fields[field_name] = safe_text(field_value or "")

if project_matches == 0:
    fail("epic is not present on the configured board")
if project_matches > 1:
    fail("epic has duplicate items on the configured board")

board_status = project_fields.get("Status") or "UNAVAILABLE"
live_state = safe_text(issue.get("state"))
mismatch = (live_state == "CLOSED" and board_status not in {"Done", "Cancelled"}) or (
    live_state == "OPEN" and board_status in {"Done", "Cancelled"}
)
open_children = [child for child in children if child.get("state") == "OPEN"]
closed_children = [child for child in children if child.get("state") == "CLOSED"]

timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
print(f"Evidence timestamp: {timestamp}")
if expected_children > 0 and "epic" not in label_names and not title.lower().startswith(("epic:", "[epic]")):
    print(f"EPIC CANDIDATE (sub-issues): {expected_children} direct child(ren); confirm role with the owning issue")
else:
    print("EPIC CANDIDATE (label/title): confirm role with the owning issue")
print(f"Epic: {full_repo}#{number} — {title}")
print(f"URL: https://github.com/{full_repo}/issues/{number}")
print(f"Live state: {live_state}")
print(f"Board Status: {safe_text(board_status)}" + (" [BOARD/LIVE MISMATCH]" if mismatch else ""))
for field in ("Work Type", "Area", "Flag"):
    print(f"Board {field}: {safe_text(project_fields.get(field) or 'UNAVAILABLE')}")
print("Board Parent/Sub-issues progress: UNAVAILABLE from API")
print(f"Direct sub-issues: {len(children)} total; {len(open_children)} open; {len(closed_children)} closed")

for heading, subset in (("Open", open_children), ("Closed", closed_children)):
    print(f"{heading}:")
    if not subset:
        print("  (none)")
    for child in sorted(subset, key=lambda node: ((node.get("repository") or {}).get("nameWithOwner", ""), node.get("number", 0))):
        child_repo = safe_text((child.get("repository") or {}).get("nameWithOwner"))
        print(f"  {child_repo}#{child.get('number')} — {safe_text(child.get('title'))}")
        print(f"    https://github.com/{child_repo}/issues/{child.get('number')}")

print("Coverage: COMPLETE for epic, board metadata, and direct sub-issues")
print("PR reviews/checks/mergeability: NOT CHECKED — verify directly before acting")
