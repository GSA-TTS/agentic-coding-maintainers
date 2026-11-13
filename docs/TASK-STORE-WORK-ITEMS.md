---
title: "Task-store seam: tracked work items for inventory steps 1 to 5"
description: "Tracking record, without GitHub issues, for the conditional migration steps in docs/TASK-STORE-INVENTORY.md, with each item's blocking dependency and unblock trigger"
status: proposed
tier: 2
date: "2026-11-13"
inventory_head: a64e483e4db70701a48234410271c2fd630a5045
delta_head: 55c1721250f0c8c1b20c057e1791f21f99bc4244
---

# Task-store seam: tracked work items

## 1. Purpose and status

The tracking rule (the repository playbook's "Track All Identified Work" section, which the inventory also invokes) is that identified work, including deferred work, must be
captured in a durable record and not only in a PR bullet, a code comment or a conversation.
`docs/TASK-STORE-INVENTORY.md` names migration steps 1 to 5 as conditional possibilities and
its decision D7 ("create tracked issues for steps 1 to 5 now") defaults to "not done". The
operator chose to record those steps in one reviewed document instead of GitHub issues. This
file is that record. It is a record only once a maintainer has merged it; until then it is a
proposal like the two documents it summarizes.

**Relation to D7.** This file is not an answer to D7 as the inventory words it (GitHub issues).
It does not file, draft or authorize any issue. If maintainers later want issues, they write
them from the table; that is a separate authorization.

**What this file is not.** It does not approve the proposed seam, admit or prioritize any
item, assign an owner, choose answers for decisions D1 to D10, or change code, tests, schemas
or runtime behavior. Every item is **Blocked** until its trigger holds. The rows are tracking
records, not issue bodies.

**Stacking.** The documents it cites are not on `main`. `docs/TASK-STORE-INVENTORY.md` is on
the branch of GSA-TTS/agentic-coding-maintainers#169, and `docs/TASK-STORE-REPIN-DELTA.md` is
on the branch of GSA-TTS/agentic-coding-maintainers#179, which is based on #169. This file is
based on the #179 branch; merge order is #169, then #179, then this PR; because the PRs stack, the later ones will need retargeting to `main` or rebasing after each earlier merge.

## 2. Sources and what is not sourced

Content is restated from the inventory at `a64e483e4db70701a48234410271c2fd630a5045` (pin
`159bc1fc7593fc420d0d6d580199ddc7edea08dc`) and the re-pin delta at
`55c1721250f0c8c1b20c057e1791f21f99bc4244` (source `5b137bade94121e63ba6a80284e6ee03d11ced4f`).
Consumer, decision and unknown IDs (S, R, G, F, D, U, X) refer to those two documents. The
drafting of this file executed nothing and re-derived nothing from source, except where the
list below says otherwise.

Not taken from those two documents (carried over from the PR descriptions and the orchestrator's
own session record; unverified here):
- The PR numbers #169, #179, #174, #175 and #178, and the descriptions of #174, #175 and #178
  (diff stat and a skim of each diff; not inventoried). The names of the reviewer and the
  status of the reviews of #169 and #179 used in W0's trigger come from live GitHub state at the
  time of writing, not from either document.
- Items A1 and A2 in section 6, and the content of A3. A2 reflects the foreground tests failing on some first runs
  and passing on rerun during the orchestrator's own isolated validation runs of these PRs. A1
  reflects that the hosted workflow uses the default shallow checkout, so the pin is not
  reachable there and the inventory test reports its skip; neither was re-checked here.

## 3. Status values and rules

Status: **Blocked** (a `Blocked by` condition or the unblock trigger has not been met), **Ready**
(every condition in `Blocked by` and the unblock trigger hold, and the item has been admitted
through the repository's task admission process), **Done**, **Dropped** (with reason).

- An item moves to Ready only when every item and decision in its `Blocked by` column is
  resolved and its unblock trigger holds, each verified in live GitHub and the repository, not
  from this file. The trigger text may restate only part of the `Blocked by` column; the
  `Blocked by` column governs.
- When an item completes or is dropped, search this file for items it blocked and surface them
  in the same change or PR comment.
- Line citations in the inventory and the delta can be stale against a later `main` (the delta's
  section 5.4 lists the shifts it found, as a sample). W0 refreshes them before any other item.
- The inventory's migration table gives steps 2 to 4 "no behavior change intended", step 1
  "none intended" and step 5 "none until decided". Proposed here, not stated by the inventory:
  if a step turns out to need a behavior change, it stops and returns to the maintainer as a
  decision. The retained-plan effect of editing a manifest-hashed module is a separate matter
  that the inventory does not count as a behavior change (its D6 and its "Compatibility and
  rollback risks" table; section 5 below).

## 4. Work items

| ID | Inventory step | Work | Status | Blocked by | Unblock trigger | Unblocks |
| --- | --- | --- | --- | --- | --- | --- |
| W0 | 0 | Decide D1 to D10 as needed; accept the inventory; re-pin and refresh every affected consumer, citation, assumption and test against the then-current implementation base (a second delta after `5b137ba`: A3); check other open work for a seam; decide whether `standing-grant.py` and `assignment-journal.py` join the controller manifest (delta section 7.2 item 10); read the unread documents (U1, U8, and per the delta `docs/STANDING-GRANT-EXECUTOR.md` and `docs/CLAIM-PUBLISHER-PROTOCOL.md` in full, X3); extend the consumer table with G1 to G4 | Blocked | Review of #169 and #179 (different PRs from this one) by the maintainer reviewer (wz-gsa at the time of writing); D1 and D8 answers | The reviewer has re-reviewed #169 at its final head, a maintainer has made the merge decision for #169 and #179, and D1 and D8 are answered in writing | W1, W5, W7 |
| W1 | 1 | Add one sibling module (provisionally `task-store.py`, loaded by path like `runtime-observation.py`) exposing `inspect`, `list`, `apply` that delegate to existing core functions; add it to the execution-plan `MODULES` list in the same change; update `CANONICAL-SHA256SUMS` and tests; the core keeps its function names. Per the delta, F9 and the patchable-core-attribute invariant must include `acquire_dir`/`release_dir`, which G4 calls and G2 reaches through G4's `acquire_gate` (G2 calls `release_dir` directly) | Blocked | W0; D6 accepted (the inventory's step 1 prerequisite); D2 recorded | W0 is Done, a maintainer has recorded D6 as "accept manifest change" (not "defer extraction", which is the inventory default and means this item does not start) and has recorded D2 | W2, W6 |
| W2 | 2 | Migrate the simplest single-section controllers: S10 (`review-accept.py`), S11 (`review-collect.py`), S9 (`repair-proposal.py`). Each is lock, `read_task`, `verify_reservations`, apply, `write_task` with a catch-all exit 3 handler; the seam must raise the same exception types | Blocked | W1 | W1 is Done | W3 |
| W3 | 3 | Migrate S12 (`review-evidence.py`), S3 (`execution-plan.py`) and S8 (`repair-apply.py`). S8 is multi-persist (`persist` callback); S12's status path and S3's assessment are unlocked reads and S3's two reads must stay two independent reads; S12 keeps `validate_collected_retention` after the read | Blocked | W2 | W2 is Done | W4 |
| W4 | 4 | Migrate the multi-section controllers S1 (`candidate-binding.py`) and S2 (`execution-observe.py`), and decide whether G4 (`standing-grant-dispatch.py`) joins them. Migrate S4 (`foreground-delivery.py`) only after W6. Per the inventory's step 4: S2 also has an unlocked early read gate, a cross-task glob scan and a launch-window lock section inside `authorize()`, which cannot complete migration without a D2 or D3 decision; S1 has a receipt-dependent verify and a post-write re-read; S4 is multi-persist on repair actions | Blocked | W3; D3 (repeated `apply` versus a held lock, with a tester's reading of the control flows) and D2; W6 for S4 | W3 is Done, D3 and D2 are decided, and for S4 the strict read mode of W6 exists | none |
| W5 | 5 | Decide the read-only layout contract for the core-independent readers R1, R2, R3, R11 and for S15 (no direct core load; transitive path per F6), and decide separately whether the core-loading readers R6, R8, R10 move to `inspect`/`list`. Per the delta, the contract must cover `intake` records, marker v2 and `intake_completion` and say which copy is authoritative; R11 appears to have drifted (by reading, inferred: it accepts kinds implementation, review and monitor only and schemas 1 and 2 only, while core and R1 accept `intake`) | Blocked | W0; D5, D10; U11; W7 for any reader migration | W0 is Done, a maintainer records D5 and D10 (U11 is already located; its findings feed W7); for any reader that would move, the refusal tests of W7 exist. Moving the readers themselves is not a separate item here | none |
| W6 | 4 (prerequisite) | Add a seam strict read mode that refuses at least what S4's reader refuses (duplicate keys, non-finite constants, symlinked ancestors, caller-bounded size), with refusal tests for each on the task path. The core `strict=True` refuses duplicate keys only, so it is not equivalent. S4 stays on its own reader until this exists. Per the delta (section 6, strictness), the D9/D10 choice must also be made explicit for the fence enumerations `scripts/standing-grant-dispatch.py:98` and `scripts/assignment-dispatch.py:286`, which read through non-strict `command_list` at 5b137ba (delta X7 is the related test) | Blocked | W1; D9 | W1 is Done and D9 answers "add strict mode" | W4 (S4 part) |
| W7 | 5 (prerequisite) | Before any root reader migrates, add the refusal tests the inventory lists (extending the cases U11 located): duplicate keys (a discriminating case for R11), floats and non-finite constants, non-UTF-8 input, oversize and empty files, symlinked or non-private components, hard-linked or wrongly owned or moded files, and file change between reads. The inventory says R10 and R8 have fewer such tests than the other root readers. Proposed constraint: tests only, no production code change | Blocked | W0; D10 | W0 is Done and a maintainer decides that readers may move (D10 answers "add equal-guard mode") | W5 |

Notes on the table.
- W6 and W7 split out prerequisites that the inventory embeds in steps 4 and 5, so each has its
  own blocking dependency. Step numbers in the second column are the inventory's. The inventory
  does not make W6 a prerequisite of step 5; W5 therefore does not list it.
- The inventory's step 6 (a second backend) is out of scope here and has no item.
- W0 may be split by a maintainer (decisions, re-pin, refresh). Splitting does not change the
  triggers above.

## 5. Manifest and retained-plan effects (for planning, not a decision)

Each step that edits a manifest-hashed controller changes that module's digest, so retained
execution plans recorded before it stop matching. The inventory (D6) treats this as a
retained-plan effect, not a behavior change. Per the inventory and the delta:

| Item | Modules edited | In `MODULES` | Effect |
| --- | --- | --- | --- |
| W1 | the new seam module, and `execution-plan.py` (the `MODULES` list lives in it, `.agents/skills/workspace-orchestrator/bin/execution-plan.py:21-22`, and it is itself a member) | the seam module is added by W1; `execution-plan.py` is already a member | manifest key set changes, and the `execution-plan.py` digest changes |
| W2 | S10, S11, S9 | S10 and S11 yes, S9 no | S10 and S11 digests change |
| W3 | S12, S3, S8 | S12 and S3 yes, S8 no | S12 and S3 digests change |
| W4 | S1, S2, S4 and possibly G4 | S2 yes; S1, S4 and G4 no | S2 digest changes |
| W6 | the seam module (adds a strict mode) | yes, once W1 has added it | the seam module's digest changes |

Whether W2 to W4 also edit the seam module (which would change its digest again) is not
determined by the inventory. `orchestrator-state.py` is in `MODULES`, and its digest already
changed at `36e98f7` (delta section 6, D6), so plans recorded at the pin are already stale before
W1, independent of any seam.

## 6. Related identified work, not part of steps 1 to 5

A1 and A2 were named while preparing the inventory and the delta; A3 was named while preparing this file. They are recorded so they are not
only in conversation. None is admitted or prioritized. Items A1 and A2 are unsourced in the
two documents (section 2).

| ID | Work | Status | Blocked by | Unblock trigger |
| --- | --- | --- | --- | --- |
| A1 | Make `tests/task-store-inventory-test.py` run its historical citation check in hosted CI. The hosted checkout is shallow, so the pin is not reachable there and the test reports its explicit skip; fetching the pin in the CI job is one way. Changes a CI configuration | Blocked | A maintainer decision that the check should run in CI; CI changes need explicit approval | A maintainer asks for it |
| A2 | Investigate the intermittent first-run failures of foreground fixture tests (seen as `test_adopt_parseable_wronghash_root_and_descendant_trees` and `test_fresh_persistence_failure_existing_packet_fsync_and_retry`; they passed on rerun). Not root-caused | Blocked | Both: a maintainer decision to investigate, and a reproduction in an isolated environment | Both hold; a recurrence on a PR head is a reason to ask for the decision, not a trigger by itself |
| A3 | Inventory the consumer changes after `5b137ba`: `#175` (`9315596`) unified the assignment guard and settlement sequence in `scripts/assignment-dispatch.py` and `scripts/standing-grant-dispatch.py`; `#174` (`eaa3ea5`) changed the Makefile check ordering (it also added `tests/syntax-first-test.py`); `#178` is open and touches `scripts/prepare-task-claim.py` and `scripts/record-claim-observation.py` (and other claim scripts). A component of W0's re-pin, listed separately so it is visible; it is part of W0 and not a downstream item. W0 is not Done until A3 is | Blocked | none beyond W0 (A3 is part of W0) | Same as W0 |

## 7. Review focus for the reader

1. Is each blocking dependency and trigger correct and checkable? In particular W0's trigger and
   the decision-to-item mapping in the `Blocked by` column.
2. Is W6 and W7 as separate items the right split of the inventory's steps 4 and 5?
3. Should any item in section 6 be dropped?
4. Is a merged Markdown record an acceptable substitute for issues, given decision D7?

AI assistance: drafted by Claude Sonnet 5.5 in OpenCode from the inventory and the delta; no
code was executed. Requires human review before acceptance.
