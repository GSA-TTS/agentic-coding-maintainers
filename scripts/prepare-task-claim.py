#!/usr/bin/env python3
"""Prepare an explicit public claim against read-only retained schema-3 evidence."""

import sys

if not sys.flags.isolated or not sys.dont_write_bytecode:
    print('{"status":"UNVERIFIED","reason":"ISOLATED_PYTHON_REQUIRED",'
          '"remote_coverage":"unmeasured","mutation_authorized":false,'
          '"native_session_authentication":"UNVERIFIED",'
          '"current_actor_authentication":"UNVERIFIED","bound_retained_snapshot":false}')
    sys.exit(3)

import contextlib
import importlib.util
import os
import re
from pathlib import Path


def sibling(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


codec = sibling("task_claim_codec", "native-claim.py")
preflight = sibling("task_claim_preflight", "check-native-ownership.py")


def report(status, reason):
    return dict(codec.report(status, reason), native_session_authentication="UNVERIFIED",
                current_actor_authentication="UNVERIFIED", bound_retained_snapshot=False)


def selected(args, stack, retained):
    """Use the preflight's physical-root, private-store and bounded-read contract."""
    authority = preflight.physical_root(args.authority_root, stack)
    invoking = preflight.physical_root(args.invoking_root, stack)
    left, right = os.fstat(authority), os.fstat(invoking)
    if (left.st_dev, left.st_ino) != (right.st_dev, right.st_ino):
        return None, None
    store = preflight.directory(authority, ".orchestrator", stack, private=True)
    task = preflight.read_selected(store, ["tasks", args.task_id, "task.json"], stack, retained)
    preflight.require(all(preflight.fingerprint(os.fstat(fd)) == before
                          for fd, before in retained), "CHANGED_DURING_READ")
    return task, (left.st_dev, left.st_ino)


def unchanged(args, stack, retained, task, root):
    observed, identity = selected(args, stack, retained)
    preflight.require(identity == root and observed == task
                      and all(before == retained[0][1] for _, before in retained),
                      "CHANGED_DURING_READ")


def private_tokens(task, args):
    # Include surviving prior-generation recovery identifiers, not just the worker.
    values = {args.expected_worker_id, args.expected_session_id, task["scope_key"]}
    for record in (task, task.get("transition_recovery", {})):
        worker = record.get("worker") or {}
        values.update(worker[key] for key in ("worker_id", "token", "session_id") if key in worker)
        leases = record.get("leases", {})
        if "scope_token" in leases:
            values.add(leases["scope_token"])
    values.add(task["cooperative_binding"]["session_id"])
    return values


def prepare(args, claim):
    with contextlib.ExitStack() as stack:
        retained = []
        task, root = selected(args, stack, retained)
        if root is None:
            return report("CONFLICT", "ROOT_MISMATCH")
        # The actual preflight performs schema/worker/session/slot/scope/lane checks.
        evidence = preflight.inspect(args)
        unchanged(args, stack, retained, task, root)
        if evidence["status"] != "STATIC_MATCH":
            return report(evidence["status"], evidence["reason"])
        if task is None:
            # A successful preflight cannot match a missing selected task.
            raise TypeError("matched preflight requires a selected task")
        if task["tracker_type"] != "issue" or task["tracker_number"] != claim["issue"]:
            return report("CONFLICT", "TRACKER_ISSUE_MISMATCH")
        if task["repo"] != claim["repo"] or task["branch"] != claim["branch"]:
            return report("CONFLICT", "REPOSITORY_OR_BRANCH_MISMATCH")
        if task["kind"] != claim["scope"]:
            return report("CONFLICT", "TASK_KIND_SCOPE_MISMATCH")
        tokens = private_tokens(task, args)
        codec.require(claim["claim_id"] not in tokens and claim["operation_id"] not in tokens,
                      "PRIVATE_IDENTIFIER_REUSE")
        output = codec.prepare(claim)
        codec.require(not any(token in output["comment"] for token in tokens),
                      "PRIVATE_IDENTIFIER_REUSE")
        unchanged(args, stack, retained, task, root)
        output.update(status="PREPARED_RETAINED_MATCH", bound_retained_snapshot=True,
                      native_session_authentication="UNVERIFIED",
                      current_actor_authentication="UNVERIFIED")
        return output


def arguments():
    parser = codec.Parser(description=__doc__, allow_abbrev=False)
    for name in ("authority-root", "invoking-root", "task-id", "expected-revision",
                 "expected-worker-id", "expected-session-id", "expected-generation",
                 "repo", "branch", "issue", "actor", "claim-id", "operation-id", "scope"):
        parser.add_argument("--" + name, required=True, action=codec.StoreOnce)
    args = parser.parse_args()
    for value, pattern in ((args.task_id, preflight.TASK_ID),
                           (args.expected_worker_id, preflight.HEX32),
                           (args.expected_session_id, preflight.SESSION_ID)):
        codec.require(pattern.fullmatch(value) is not None, "INVALID_ARGUMENTS")
    codec.require(re.fullmatch(r"0|[1-9][0-9]{0,18}", args.expected_revision) is not None,
                  "INVALID_ARGUMENTS")
    args.expected_revision = int(args.expected_revision)
    codec.require(args.expected_revision <= preflight.MAX_INT64, "INVALID_ARGUMENTS")
    args.expected_generation = codec.number(args.expected_generation)
    args.expected_repo, args.expected_branch = args.repo, args.branch
    issue = codec.number(args.issue)
    claim = codec.validate_claim({"version": 1, "action": "claim", "repo": args.repo,
                                  "branch": args.branch, "issue": issue,
                                  "task_ref": f"issue:{issue}", "actor": args.actor,
                                  "claim_id": args.claim_id, "operation_id": args.operation_id,
                                  "scope": args.scope})
    return args, claim


def main():
    try:
        codec.require(sys.flags.isolated and sys.dont_write_bytecode, "ISOLATED_PYTHON_REQUIRED")
        args, claim = arguments()
        output = prepare(args, claim)
    except (codec.Unverified, preflight.Unverified) as exc:
        output = report("UNVERIFIED", str(exc))
    except (OSError, ValueError, UnicodeError, TypeError, RecursionError):
        output = report("UNVERIFIED", "STORE_UNAVAILABLE")
    print(codec.canonical(output))
    return 4 if output["status"] == "CONFLICT" else 3


if __name__ == "__main__":
    sys.exit(main())
