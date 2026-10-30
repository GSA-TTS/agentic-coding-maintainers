#!/usr/bin/env python3
"""Read-only explicit PR-batch report. Check summaries are not review or merge approval."""

from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import subprocess
import sys
import time
from pathlib import Path

FIELDS = "number,state,isDraft,headRefOid,baseRefName,baseRefOid,headRefName,statusCheckRollup,reviewDecision,url,mergeCommit"
MAX_BYTES = 2_000_000


class Unverified(Exception):
    pass


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise Unverified("duplicate JSON key")
        value[key] = item
    return value


def decode(data: bytes):
    if not data or len(data) > MAX_BYTES:
        raise Unverified("missing or oversized JSON")
    try:
        return json.loads(data, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(Unverified("nonfinite JSON")))
    except (RecursionError, ValueError) as exc:
        raise Unverified("malformed or excessively nested JSON") from exc


def object_fields(value, fields):
    if not isinstance(value, dict) or set(value) != fields:
        raise Unverified("unexpected or missing fields")


def validate_manifest(value):
    object_fields(value, {"schema_version", "repo", "default_branch", "prs"})
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise Unverified("unsupported manifest")
    if not isinstance(value["repo"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value["repo"]) or any(x in {".",".."} for x in value["repo"].split("/")):
        raise Unverified("invalid repository")
    if not isinstance(value["default_branch"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,199}", value["default_branch"]):
        raise Unverified("invalid expected default branch")
    if not isinstance(value["prs"], list) or not 1 <= len(value["prs"]) <= 20:
        raise Unverified("batch must name 1-20 PRs")
    numbers = set()
    for item in value["prs"]:
        object_fields(item, {"number", "head", "depends_on", "review_evidence"})
        if type(item["number"]) is not int or item["number"] < 1 or item["number"] in numbers:
            raise Unverified("invalid or duplicate PR")
        numbers.add(item["number"])
        if not isinstance(item["head"], str) or not re.fullmatch(r"[0-9a-f]{40}", item["head"]):
            raise Unverified("full inspected head required")
        if not isinstance(item["depends_on"], list) or len(item["depends_on"]) > 20 or any(type(x) is not int or x < 1 for x in item["depends_on"]):
            raise Unverified("invalid dependency list")
        if len(set(item["depends_on"])) != len(item["depends_on"]) or item["number"] in item["depends_on"]:
            raise Unverified("duplicate or self dependency")
        # These are operator-provided references, not machine-verified review credit.
        if not isinstance(item["review_evidence"], list) or len(item["review_evidence"]) > 10 or any(not isinstance(x, str) or not x.strip() or len(x) > 500 or "\0" in x for x in item["review_evidence"]):
            raise Unverified("invalid evidence references")
    remaining = {item["number"]: set(item["depends_on"]) for item in value["prs"]}
    if any(not dependencies <= numbers for dependencies in remaining.values()):
        raise Unverified("include every dependency PR explicitly in this bounded batch")
    order = []
    while remaining:
        ready = sorted(number for number, dependencies in remaining.items() if not dependencies)
        if not ready:
            raise Unverified("dependency cycle")
        order.extend(ready)
        for number in ready:
            remaining.pop(number)
        for dependencies in remaining.values():
            dependencies.difference_update(ready)
    return order


def read_gh(args, deadline):
    output, errors = bytearray(), bytearray()
    with subprocess.Popen(["gh", *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
        assert child.stdout is not None and child.stderr is not None
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ, output)
                selector.register(child.stderr, selectors.EVENT_READ, errors)
                while selector.get_map():
                    if time.monotonic() >= deadline:
                        raise Unverified("GitHub read budget exhausted")
                    for key, _ in selector.select(0.1):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                        else:
                            key.data.extend(chunk)
                            if len(output) + len(errors) > MAX_BYTES:
                                raise Unverified("GitHub response exceeds bound")
                child.wait(timeout=max(0.01, deadline-time.monotonic()))
            if child.returncode != 0:
                raise Unverified("GitHub query failed")
            return decode(bytes(output))
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()


def check_summary(checks):
    if not isinstance(checks, list) or not checks or len(checks) > 500:
        return "UNVERIFIED"
    statuses = []
    for check in checks:
        if not isinstance(check, dict):
            return "UNVERIFIED"
        if check.get("__typename") == "CheckRun":
            status, conclusion = check.get("status"), check.get("conclusion")
            if status not in {"QUEUED","IN_PROGRESS","COMPLETED","WAITING","PENDING","REQUESTED"}:
                return "UNVERIFIED"
            statuses.append(conclusion if status == "COMPLETED" else "PENDING")
        elif check.get("__typename") == "StatusContext":
            statuses.append(check.get("state"))
        else:
            return "UNVERIFIED"
    if any(item not in {"SUCCESS","FAILURE","ERROR","TIMED_OUT","CANCELLED","NEUTRAL","SKIPPED","ACTION_REQUIRED","STALE","STARTUP_FAILURE","PENDING","EXPECTED"} for item in statuses):
        return "UNVERIFIED"
    if any(item in {"FAILURE","ERROR","TIMED_OUT","CANCELLED","STARTUP_FAILURE"} for item in statuses):
        return "FAILED"
    if any(item in {"PENDING","EXPECTED"} for item in statuses):
        return "PENDING"
    return "GREEN_OBSERVED" if all(item == "SUCCESS" for item in statuses) else "UNVERIFIED"


def valid_pr(value, number, repo):
    if not isinstance(value, dict) or type(value.get("number")) is not int or value["number"] != number:
        raise Unverified("wrong PR identity")
    if value.get("state") not in {"OPEN","MERGED","CLOSED"} or type(value.get("isDraft")) is not bool:
        raise Unverified("unavailable PR lifecycle")
    if not isinstance(value.get("headRefOid"), str) or not re.fullmatch(r"[0-9a-f]{40}", value["headRefOid"]):
        raise Unverified("unavailable PR head")
    for field in ("baseRefName","headRefName"):
        if not isinstance(value.get(field), str) or not value[field] or len(value[field]) > 200:
            raise Unverified("unavailable branch identity")
    if not isinstance(value.get("baseRefOid"), str) or not re.fullmatch(r"[0-9a-f]{40}", value["baseRefOid"]):
        raise Unverified("unavailable PR base")
    if "reviewDecision" not in value or value["reviewDecision"] not in (None, "", "REVIEW_REQUIRED", "CHANGES_REQUESTED", "APPROVED"):
        raise Unverified("unavailable or malformed review decision")
    expected_url = f"https://github.com/{repo}/pull/{number}"
    if not isinstance(value.get("url"), str) or value["url"].casefold() != expected_url.casefold():
        raise Unverified("PR URL does not match owning repository and number")
    return value


def report(manifest, snapshots, repository):
    order = validate_manifest(manifest)
    default = repository.get("defaultBranchRef", {}) if isinstance(repository, dict) else {}
    if (not isinstance(default, dict) or default.get("name") != manifest["default_branch"]
            or not isinstance(repository.get("nameWithOwner"), str)
            or repository.get("nameWithOwner", "").casefold() != manifest["repo"].casefold()):
        raise Unverified("owning repository/default branch differs from batch")
    metadata = {item["number"]: item for item in manifest["prs"]}
    output, merge_observed = [], set()
    for number in order:
        definition = metadata[number]
        row = {"number":number,"expected_head":definition["head"],"depends_on":definition["depends_on"],
               "review_evidence":definition["review_evidence"],"review_evidence_status":"UNVERIFIED_REFERENCES_ONLY",
               "status":"UNVERIFIED","checks":"UNVERIFIED","approval_required":"HUMAN","merge_authorized":False,
               "waiting_for":[item for item in definition["depends_on"] if item not in merge_observed]}
        try:
            pr = valid_pr(snapshots.get(number), number, manifest["repo"])
            row.update(observed_head=pr["headRefOid"],base=pr["baseRefName"],base_sha=pr["baseRefOid"],state=pr["state"],draft=pr["isDraft"])
            row.update(url=pr["url"], review_decision=pr["reviewDecision"] or "NONE",
                       review_attention="CHANGES_REQUESTED" if pr["reviewDecision"] == "CHANGES_REQUESTED" else "NONE_OBSERVED")
            row["checks"] = check_summary(pr.get("statusCheckRollup"))
            row["waiting_for"] = [item for item in definition["depends_on"] if item not in merge_observed]
            if pr["headRefOid"] != definition["head"]:
                row["status"] = "HEAD_CHANGED"
            elif pr["baseRefName"] != manifest["default_branch"]:
                row["status"] = "NONDEFAULT_BASE"
            elif pr["state"] == "MERGED":
                commit = pr.get("mergeCommit")
                if isinstance(commit,dict) and isinstance(commit.get("oid"),str) and re.fullmatch(r"[0-9a-f]{40}",commit["oid"]):
                    row.update(status="MERGED_OBSERVED",merge_commit=commit["oid"])
                    merge_observed.add(number)
            elif pr["state"] == "CLOSED":
                row["status"] = "CLOSED_UNMERGED"
            elif row["waiting_for"]:
                row["status"] = "WAITING_FOR_PREDECESSOR"
            elif pr["isDraft"]:
                row["status"] = "DRAFT"
            elif pr["reviewDecision"] == "CHANGES_REQUESTED":
                row["status"] = "CHANGES_REQUESTED"
            else:
                row["status"] = "INTEGRATION_REVIEW_REQUIRED" if definition["depends_on"] and row["checks"] == "GREEN_OBSERVED" else row["checks"]
            row["next_action"] = "Human reviews exact head, agent evidence, current native rules and dependency acceptance before approval."
            if pr["state"] == "OPEN" and pr["reviewDecision"] == "CHANGES_REQUESTED":
                row["next_action"] = "Resolve reviewer findings with the implementation owner and obtain fresh fixed-head re-review; green checks alone do not resolve requested changes."
            if definition["depends_on"]:
                row["dependency_integration"] = "UNVERIFIED: merge status alone does not prove successor includes or validates predecessor changes"
        except (Unverified, TypeError, ValueError):
            row["reason"] = "owning PR evidence unavailable"
        output.append(row)
    return {"schema_version":1,"repo":manifest["repo"],"default_branch":manifest["default_branch"],"merge_order":order,
            "prs":output,"status":"OBSERVED" if all(row["status"] in {"GREEN_OBSERVED","MERGED_OBSERVED"} for row in output) else "ATTENTION",
            "rules_and_codeowner_approval":"UNVERIFIED: this report is not a merge gate",
            "branch_policy":"Independent PRs target default branch; refresh dependent work after predecessors merge. No PR-to-PR base required."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest",type=Path)
    args = parser.parse_args()
    try:
        if not sys.flags.isolated or not sys.dont_write_bytecode:
            raise Unverified("invoke with python3 -I -B")
        with args.manifest.open("rb") as stream:
            raw = stream.read(100_001)
        if len(raw) > 100_000:
            raise Unverified("manifest exceeds bound")
        manifest = decode(raw)
        validate_manifest(manifest)
        deadline = time.monotonic()+120
        repo = read_gh(["repo","view",manifest["repo"],"--json","nameWithOwner,defaultBranchRef"],deadline)
        snapshots = {}
        for item in manifest["prs"]:
            try:
                first = read_gh(["pr","view",str(item["number"]),"--repo",manifest["repo"],"--json",FIELDS],deadline)
                second = read_gh(["pr","view",str(item["number"]),"--repo",manifest["repo"],"--json",FIELDS],deadline)
                # Avoid presenting a known changed check/lifecycle snapshot.
                if first == second:
                    snapshots[item["number"]] = first
            except (Unverified, OSError, ValueError, subprocess.SubprocessError):
                continue
        result = report(manifest,snapshots,repo)
        print(json.dumps(result,sort_keys=True,indent=2))
        return 0 if result["status"] == "OBSERVED" else 3
    except (Unverified, OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status":"UNVERIFIED","reason":str(exc) if isinstance(exc,Unverified) else "batch observation unavailable"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
