#!/usr/bin/env python3
"""Read-only pre-intent identity observation and unauthenticated text declaration."""

import contextlib
import json
import os
import re
import sys
import time


def report(status, reason):
    return {"schema_version": 1, "contract": "claim-identity-approval-declaration-v1",
            "status": status, "reason": reason, "mutation_authorized": False,
            "remote_effects_enabled": False, "atomic_snapshot": False,
            "absence_authorizing": False, "remote_coverage": "unmeasured",
            "native_session_authentication": "UNVERIFIED",
            "current_actor_authentication": "UNVERIFIED",
            "publisher_authority": "UNVERIFIED", "issuance_identity": "UNVERIFIED",
            "persisted": False, "private_correlatable": True,
            "bound_retained_snapshot": False}


class Refusal(Exception):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason


def arguments(prepare):
    codec = prepare.codec
    parser = codec.Parser(allow_abbrev=False, add_help=False)
    for name in ("expected-actor-id", "expected-repo-id", "expected-issue-id",
                 "reviewer", "approved-body-sha256"):
        parser.add_argument("--" + name, required=True, action=codec.StoreOnce)
    parser.add_argument("--approve-public-text", required=True, nargs=0, action=codec.StoreOnce)
    extra, remaining = parser.parse_known_args()
    # The downstream parser's help action exits 0 with prose, bypassing our contract.
    codec.require(not any(value in {"--help", "-h"} for value in remaining), "INVALID_ARGUMENTS")
    for key in ("expected_actor_id", "expected_repo_id", "expected_issue_id"):
        setattr(extra, key, codec.number(getattr(extra, key)))
    codec.require(codec.login(extra.reviewer)
                  and re.fullmatch(r"[0-9a-f]{64}", extra.approved_body_sha256) is not None,
                  "INVALID_ARGUMENTS")
    original = sys.argv
    try:
        sys.argv = [original[0], *remaining]
        args, claim = prepare.arguments()
    finally:
        sys.argv = original
    vars(args).update(vars(extra))
    return args, claim


def snapshot(args, claim, prepare):
    """Anchor actual preparation and lease reads to physical task/file metadata."""
    preflight = prepare.preflight
    with contextlib.ExitStack() as stack:
        retained = []
        task, root = prepare.selected(args, stack, retained)
        if root is None:
            raise Refusal("CONFLICT", "ROOT_MISMATCH")
        public = prepare.prepare(args, claim)
        if public["status"] != "PREPARED_RETAINED_MATCH":
            raise Refusal(public["status"], public["reason"])
        authority = preflight.physical_root(args.authority_root, stack)
        store = preflight.directory(authority, ".orchestrator", stack, private=True)
        leases = task["leases"]
        paths = [["scopes", task["scope_key"] + ".lock", "owner.json"],
                 ["slots", str(leases["global_slot"]) + ".lock", "owner.json"]]
        if leases["implementation_lane"] is not None:
            paths.append(["implementation", str(leases["implementation_lane"]) + ".lock", "owner.json"])
        lease_retained = []
        values = [preflight.read_selected(store, path, stack, lease_retained) for path in paths]
        preflight.require(prepare.prepare(args, claim) == public, "CHANGED_DURING_READ")
        reread = []
        preflight.require([preflight.read_selected(store, path, stack, reread) for path in paths] == values
                          and [stamp for _, stamp in reread] == [stamp for _, stamp in lease_retained],
                          "CHANGED_DURING_READ")
        prepare.unchanged(args, stack, retained, task, root)
        preflight.require(all(preflight.fingerprint(os.fstat(fd)) == stamp
                              for fd, stamp in retained + lease_retained), "CHANGED_DURING_READ")
        return (task, root, preflight.fingerprint(os.fstat(store)), values,
                tuple(stamp for _, stamp in retained + lease_retained)), public


def identities(args, claim, observer, transport):
    codec = observer.codec
    user, _ = transport.get(observer.API + "/user")
    repo, _ = transport.get(transport.repo_url)
    issue, _ = transport.get(transport.issue_url)
    for record in (user, repo, issue):
        codec.require(codec.positive(record.get("id"))
                      and type(record.get("node_id")) is str
                      and 0 < len(record["node_id"]) <= 256, "IMMUTABLE_IDENTITY_INVALID")
    codec.require(user.get("type") == "User" and user.get("login") == claim["actor"]
                  and user["id"] == args.expected_actor_id, "ACTOR_IDENTITY_MISMATCH")
    codec.require(repo["id"] == args.expected_repo_id and repo.get("full_name") == claim["repo"]
                  and repo.get("url") == transport.repo_url, "REPOSITORY_IDENTITY_MISMATCH")
    anchor = observer.issue_anchor(issue, transport, claim["issue"])
    codec.require(issue["id"] == args.expected_issue_id, "ISSUE_IDENTITY_MISMATCH")
    observer.timestamp(repo.get("updated_at"))
    if "updated_at" in user:
        observer.timestamp(user["updated_at"])
    return ((user["id"], user["node_id"], user["login"], user["type"], user.get("updated_at")),
            (repo["id"], repo["node_id"], repo["full_name"], repo["url"], repo["updated_at"]),
            (issue["node_id"], anchor))


def collect(args, claim, prepare, observer):
    before, public = snapshot(args, claim, prepare)
    prepare.codec.require(public["comment_sha256"] == args.approved_body_sha256
                          == prepare.codec.digest(prepare.codec.render(claim)),
                          "APPROVED_BODY_MISMATCH")
    transport = observer.Transport(claim["repo"], claim["issue"], time.monotonic() + 30)
    try:
        first = identities(args, claim, observer, transport)
        # Reprepare the prospective intent text after identifying the current actor.
        middle, fresh = snapshot(args, claim, prepare)
        prepare.codec.require(middle == before and fresh == public, "LOCAL_SNAPSHOT_CHANGED")
        second = identities(args, claim, observer, transport)
        observer.require(first == second, "REMOTE_IDENTITY_CHANGED")
    finally:
        try:
            after, fresh = snapshot(args, claim, prepare)
            if after != before or fresh != public:
                raise ValueError("changed")
        except (Refusal, prepare.codec.Unverified, prepare.preflight.Unverified,
                OSError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
            raise Refusal("UNVERIFIED", "LOCAL_SNAPSHOT_CHANGED") from exc
    output = report("IDENTITY_BOUND_DECLARATION", "PRE_INTENT_OBSERVATION_AND_DECLARATION")
    output.update(bound_retained_snapshot=True, remote_coverage="repeated_identity_gets",
                  actor_id=first[0][0], repository_id=first[1][0], issue_id=first[2][1][0],
                  issue_number=first[2][1][1], issue_closed=first[2][1][4] == "closed",
                  issue_locked=first[2][1][5], comment_sha256=public["comment_sha256"],
                  public_text_approval="DECLARED_UNAUTHENTICATED", reviewer_declared=True,
                  identity_at_preparation="OBSERVED", get_counts={"user": 2, "repository": 2, "issue": 2},
                  get_count=6, network_deadline_seconds=30, output_byte_limit=observer.MAX_BYTES)
    return output


def main():
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        print(json.dumps(report("UNVERIFIED", "ISOLATED_PYTHON_REQUIRED"),
                         sort_keys=True, separators=(",", ":")))
        return 3
    # Use the existing sibling loader without importing state-writing intent APIs.
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("approved_prepare", Path(__file__).with_name("prepare-task-claim.py"))
    assert spec and spec.loader
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    observer = prepare.sibling("approved_observer", "observe-github-claims.py")
    try:
        args, claim = arguments(prepare)
        output = collect(args, claim, prepare, observer)
    except Refusal as exc:
        output = report(exc.status, exc.reason)
    except (prepare.codec.Unverified, prepare.preflight.Unverified, observer.Unverified) as exc:
        output = report("UNVERIFIED", str(exc))
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        output = report("UNVERIFIED", "READ_UNAVAILABLE")
    print(prepare.codec.canonical(output))
    return 4 if output["status"] == "CONFLICT" else 3


if __name__ == "__main__":
    sys.exit(main())
