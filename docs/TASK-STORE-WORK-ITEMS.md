---
title: "Task-store seam: tracked work items for inventory steps 1 to 5"
description: "Durable tracking record, without GitHub issues, for the conditional migration steps in docs/TASK-STORE-INVENTORY.md, with each item's blocking dependency and unblock trigger"
status: proposed
tier: 2
date: "2026-11-13"
inventory_head: a64e483e4db70701a48234410271c2fd630a5045
delta_head: 55c1721250f0c8c1b20c057e1791f21f99bc4244
---

# Task-store seam: tracked work items

## 1. Purpose and status

The repository's tracking rule is that identified work, including deferred work, must be
captured in a durable record and not only in a PR bullet, a code comment or a conversation.
`docs/TASK-STORE-INVENTORY.md` (decision D7) names migration steps 1 to 5 as conditional
possibilities and defaults to filing no issues. The operator chose to record those steps in
one reviewed document instead of GitHub issues. This file is that record.

**What this file is.** A list of work items, each with its blocking dependency and the trigger
that unblocks it. It is the tracking record for inventory steps 1 to 5 and for the re-pin and
refresh work that precedes them.

**What this file is not.** It does not approve the proposed seam, admit or prioritize any item,
assign an owner, choose answers for decisions D1 to D10, or change code, tests, schemas or
runtime behavior. Every item below is **Blocked** until its trigger holds. A maintainer may
later copy any item into a GitHub issue; doing so is a separate authorization.

Sources: the inventory at `a64e483e4db70701a48234410271c2fd630a5045` (pin
`159bc1fc7593fc420d0d6d580199ddc7edea08dc`) and the re-pin delta at
`55c1721250f0c8c1b20c057e1791f21f99bc4244` (source `5b137bade94121e63ba6a80284e6ee03d11ced4f`).
Consumer, decision and unknown IDs (S, R, G, F, D, U, X) refer to those two documents. Facts
are restated from them and were not re-derived; nothing was executed.

## 2. Status values and rules

Status: **Blocked** (a stated trigger has not occurred), **Ready** (every trigger holds and a
maintainer has admitted the item), **Done**, **Dropped** (with reason).

- An item moves to Ready only when its listed triggers are verified in live GitHub and the
  repository, not from this file.
- When an item completes or is dropped, search this file for items it blocked and surface them
  (`Unblocks` column) in the same change or PR comment.
- Every line citation in the inventory and the delta is stale against a later `main` once the
  pinned files change. Item W0 exists to refresh them before any other item starts.
- Behavior-preserving means no intended change in accepted inputs, refusals, exit codes, lock
  semantics or serialized bytes. If a step cannot meet that, it stops and returns to the
  maintainer as a decision.

## 3. Work items

| ID | Inventory step | Work | Status | Blocked by | Unblock trigger | Unblocks |
| --- | --- | --- | --- | --- | --- | --- |
| W0 | 0 | Decide D1 to D10 as needed; accept the inventory; re-pin and refresh every affected consumer, citation, assumption and test against the then-current implementation base (a second delta after `5b137ba`, since `#174` and `#175` landed and `#178` is open); check other open work for a seam; read the unread documents (U1, U8) | Blocked | Review of GSA-TTS/agentic-coding-maintainers#169 and GSA-TTS/agentic-coding-maintainers#179 by wz-gsa; D1 and D8 answers | wz-gsa has re-reviewed `#169` at its final head, a maintainer has made the merge decision for `#169` and `#179`, and D1 and D8 are answered in writing | W1, and every item below |
| W1 | 1 | Add one sibling module (provisionally `task-store.py`, loaded by path like `runtime-observation.py`) exposing `inspect`, `list`, `apply` that delegate to existing core functions; add it to the execution-plan `MODULES` list in the same change; update `CANONICAL-SHA256SUMS` and tests; the core keeps its function names | Blocked | W0; D2 (shape), D6 (manifest effect), D3 if S1/S2/G4 are in scope | W0 is Done, and a maintainer has recorded D2 and D6 (the inventory defaults are three operations and defer extraction, so the default is not to start) | W2 |
| W2 | 2 | Migrate the simplest single-section controllers: S10 (`review-accept.py`), S11 (`review-collect.py`), S9 (`repair-proposal.py`). Each is lock, `read_task`, `verify_reservations`, apply, `write_task` with a catch-all exit 3 handler; the seam must raise the same exception types | Blocked | W1 | W1 is Done | W3 |
| W3 | 3 | Migrate S12 (`review-evidence.py`), S3 (`execution-plan.py`) and S8 (`repair-apply.py`). S8 is multi-persist (`persist` callback); S12's status path and S3's assessment are unlocked reads and S3's two reads must stay two independent reads; S12 keeps `validate_collected_retention` after the read | Blocked | W2 | W2 is Done | W4 |
| W4 | 4 | Migrate the multi-section controllers S1 (`candidate-binding.py`) and S2 (`execution-observe.py`), and decide whether G4 (`standing-grant-dispatch.py`) joins them. Migrate S4 (`foreground-delivery.py`) only after W6 | Blocked | W3; D3 (repeated `apply` versus a held lock); W6 for S4 | W3 is Done, D3 is decided with a tester's reading of the three control flows, and for S4 the strict read mode of W6 exists | none |
| W5 | 5 | Decide the read-only layout contract for the core-independent readers R1, R2, R3, R11 and S15, and decide separately whether the core-loading readers R6, R8, R10 move to `inspect`/`list`. R11 has already drifted (it refuses kind `intake` and schema 3 while core and R1 accept them), so the contract must say which copy is authoritative | Blocked | D5, D10; W6 and W7 for any reader migration | A maintainer records D5 and D10; the refusal tests of W7 exist for any reader that would move | none |
| W6 | 4 (prerequisite) | Add a seam strict read mode that refuses at least what S4's reader refuses (duplicate keys, non-finite constants, symlinked ancestors, caller-bounded size), with refusal tests for each on the task path. The core `strict=True` refuses duplicate keys only, so it is not equivalent. S4 stays on its own reader until this exists | Blocked | W1; D9 | W1 is Done and D9 answers "add strict mode" | W4 (S4 part) |
| W7 | 5 (prerequisite) | Add refusal tests for the root-reader guards before any reader migrates: duplicate keys, floats and non-finite constants, non-UTF-8 input, oversize and empty files, symlinked or non-private components, hard-linked or wrongly owned or moded files, and file change between reads (R10 and R8 have the fewest, U10, U11). Tests only; no production code change | Blocked | D10 | A maintainer decides that readers may move (D10 answers "add equal-guard mode") | W5 |

Notes on the table.
- W6 and W7 split out prerequisites that the inventory embeds in steps 4 and 5, so each has its
  own blocking dependency. Step numbers in the second column are the inventory's.
- The inventory's step 6 (a second backend) is out of scope here and has no item.
- W0 may be split by a maintainer (decisions, re-pin, refresh). Splitting does not change the
  triggers above.

## 4. Manifest and retained-plan effects (for planning, not a decision)

Each step that edits a manifest-hashed controller changes that module's digest, so retained
execution plans recorded before it stop matching. This is a retained-plan effect, not a
behavior change (inventory D6). Per the inventory and the delta:

| Item | Controllers edited | In `MODULES` | Effect |
| --- | --- | --- | --- |
| W1 | new module added | the new module is added to `MODULES` | manifest key set changes |
| W2 | S10, S11, S9 | S10 and S11 yes, S9 no | S10 and S11 digests change |
| W3 | S12, S3, S8 | S12 and S3 yes, S8 no | S12 and S3 digests change |
| W4 | S1, S2, S4 and possibly G4 | S2 yes; S1, S4 and G4 no | S2 digest changes |

`orchestrator-state.py` is in `MODULES`, and its digest already changed at `36e98f7` (delta
section 6, D6). Plans recorded at the pin are already stale before W1, independent of any seam.

## 5. Related identified work, not part of steps 1 to 5

These were named while preparing the inventory and the delta. They are recorded so they are not
only in conversation. None is admitted or prioritized.

| ID | Work | Status | Blocked by | Unblock trigger |
| --- | --- | --- | --- | --- |
| A1 | Make `tests/task-store-inventory-test.py` run its historical citation check in hosted CI. The hosted checkout is shallow, so the pin is unreachable there and the test reports its explicit skip; fetching the pin in the CI job is one way. Changes a CI configuration | Blocked | Maintainer decision to want the check in CI; CI changes need explicit approval | A maintainer asks for it |
| A2 | Investigate the intermittent first-run failures of foreground fixture tests (seen as `test_adopt_parseable_wronghash_root_and_descendant_trees` and `test_fresh_persistence_failure_existing_packet_fsync_and_retry`; they passed on rerun). Not root-caused | Blocked | A maintainer decision to investigate; a reproduction in an isolated environment | A maintainer asks for it, or the failures recur on a PR head |
| A3 | Inventory the consumers not covered by the delta: changes after `5b137ba`, including `#174` and `#175` (`9315596`, which unified the assignment guard and settlement sequence in `scripts/assignment-dispatch.py` and `scripts/standing-grant-dispatch.py`) and open `#178`. Folded into W0's re-pin when W0 runs | Blocked | W0 | Same as W0 |

## 6. Review focus for the reader

1. Is each blocking dependency and trigger correct and checkable? In particular W0's trigger
   and the D-to-item mapping in the `Blocked by` column.
2. Is W6 and W7 as separate items the right split of the inventory's steps 4 and 5?
3. Should any item in section 5 be dropped or moved to a GitHub issue?
4. This file treats itself as the tracking record. If the maintainers prefer GitHub issues for
   some items, they can be copied from the table; the dependency text is meant to be portable.

AI assistance: drafted by Claude Sonnet 5.5 in OpenCode from the inventory and the delta; no
code was executed. Requires human review before acceptance.
