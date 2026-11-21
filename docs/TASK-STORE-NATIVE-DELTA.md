---
title: "Task-store native/manual delta (5b137ba to c731688)"
description: "Bounded current-source checkpoint for W0, not an exhaustive consumer re-pin or migration approval"
status: proposed
tier: 2
date: "2026-11-19"
base_pin: 5b137bade94121e63ba6a80284e6ee03d11ced4f
source_sha: c731688d2439e051ea08692901c613bf2a3f195a
---

# Task-store native/manual delta

## 1. Scope and evidence boundary

This continues the [first re-pin delta](TASK-STORE-REPIN-DELTA.md) from
`5b137bade94121e63ba6a80284e6ee03d11ced4f` to
`c731688d2439e051ea08692901c613bf2a3f195a`. It supports W0/A3 and D8 in
[the tracker](TASK-STORE-WORK-ITEMS.md); it does **not** complete W0 or admit W1.
The historical inventory, delta, test pin/counts and roadmap checkpoints remain
historical evidence, not assertions about this newer source.

Method: static file reads and targeted content searches in the assigned worktree.
The worktree HEAD/ref was read as the source SHA above. No commands, tests,
imports, builds, live GitHub checks or historical blob comparison were performed.
The old side comes from the first delta; the new side was corroborated in source.
This is not an exhaustive diff, call-site census or proof that other files did
not change. Citations below refer only to this source SHA; line numbers are not
portable to later heads. Findings are observed source unless labeled inference
or recommendation. Test presence is not a passing execution result.

Paths prefixed `bin/` and `skill-tests/` mean
`.agents/skills/workspace-orchestrator/bin/` and
`.agents/skills/workspace-orchestrator/tests/`; `core` means
`bin/orchestrator-state.py`. S/R/G/D/U/X identifiers retain their historical
document meanings. No imported implementation or provenance record is changed.

## 2. Two independent native gates, not general enablement

The old core had ordinary schema 2 and cooperative schema 3. Current native
ordinary/cooperative schemas are 4/5. `validate_record`, `read_task`, `write_task`,
`command_list` and admission validation expose **both** `allow_bound=False` and
`allow_native=False` (core:567–590, 887–891, 1017–1030, 1964–1975, 2289–2293).
Schema 5 needs both permissions; `allow_bound` alone does not enable native.
The schema-1-to-2 compatibility conversion remains in `validate_record`.

Selected core lifecycle/CLI paths opt in, including show/list and claim. This is
implemented support for retained records, not a native creation switch:
`command_create` still emits schema 2 (core:1204–1207), and `write_task` rejects
unsupported identity conversion (1017–1030). Native workers carry exactly
`process_identity`, not legacy `process_start`; cooperative workers additionally
carry session/generation (525–564). The core preserves its patchable legacy
`process_identity` wrapper; native observation is record-directed (1102–1128).

Native profiles admit only implementation/review, bounded core fields and, for
schema 5, cooperative binding, recovery and manual assignment marker version 1.
Monitor/intake and standing marker version 2 are not native profiles
(core:510–522). This excludes general review/execution extensions too; a native
task is not automatically supported by the other skill controllers.
Backend qualification and production native claim approval remain separate,
unmet gates; see [native qualification](NATIVE-PROCESS-QUALIFICATION.md).

## 3. Family decoding and physical reads are not equal-guard reads

`decode_record_json` examines decoded pairs before last-value projection
(core:290–320). Any `process_identity` key, or integer schema/task-schema 4 or 5
at any depth, selects native duplicate refusal. Escaped key spellings count.
Repeated `schema_version`/`task_schema_version` always refuse, even if the final
value looks legacy. Other duplicates retain last-value behavior only for
unambiguously legacy input with `strict=False`; `strict=True` rejects them all.

`read_json` first decodes a pathname read, then native input is selected
again through held no-follow ancestor descriptors and `read_physical_json`, with
parsed equality required (core:323–383, 478–492). Physical reads require bounded
regular, single-link, caller-owned private files; use nonblocking/no-follow opens;
compare selected file identity and size/mtime/ctime; and recheck ancestor identities.
This is not a single descriptor-only initial read or an atomic tree snapshot.

Do not replace another reader merely because this path is called strict:

| Reader | Distinguishing current contract |
| --- | --- |
| Core family decoder/physical task read | Fixed 1,000,000-byte bound; UTF-8 text; duplicate policy above; decoder has no general float/nonfinite rejection or depth/container/string budgets. `physical_directory` refuses symlinks/replacements but does not require every ancestor to be private. |
| R1 `scripts/check-native-ownership.py`, reused by R8 | `parse` rejects every float/nonfinite value and enforces depth/string/container bounds; `read_selected` requires private selected directories, private single-link regular files and retains fingerprints for caller rechecks (96–121, 441–481). R8 retains this reader, not core `read_task` (`scripts/assignment-dispatch.py:167–176`). |
| S4 `foreground-delivery.py` via `review-collect.py` | Separate byte reader: caller-selected bound, ancestor symlink refusal, duplicate and literal nonfinite rejection (`bin/review-collect.py:53–88`). Its byte-decoding behavior is not core UTF-8 text decoding. |

Inference: core native physical reads strengthen selected dimensions without
subsuming R1 or S4. Semantic record checks do not make the decoder's contracts
identical. A new seam must preserve each caller's refusal set, read sequencing,
lock placement and errors, or explicitly obtain a behavior-change decision.

## 4. Native reservation checks include reverse ownership

The historical per-record-only description of `verify_reservations` is no longer
complete for native records. Native selected owners are compared in full, with
exact worker validation; scope owners still use schema 2. Native verification
also scans capacity groups and scopes for reverse leases (core:1888–1961).
Release reselects held physical lease state before deletion (1048–1070).
Keep the existing ordered intent/reservation/task-write protocol outside a
storage-only abstraction; checking only task id/token would lose native checks.

Mixed stores need the owning task, not the apparent worker shape, to choose
duplicate policy. `native_lease(owning_family=True)` tentatively reads an owner,
loads its task with both gates, proves group/index/token association, and for a
native owner strictly re-reads the same file and verifies its full contents
(core:387–463). Scope schema 2 alone is not evidence of a legacy owner.
`mixed_reservation_owner` rechecks selection; it does not cache family authority.
Thus unambiguous legacy duplicate leases can remain compatible in these core
reverse scans, while native duplicates and repeated discriminators refuse.

R1's native inspection separately reverse-scans slots/implementation using its
always-strict `read_selected` (scripts/check-native-ownership.py:527–538).
That is not the core's mixed-family duplicate policy or its reverse-scope scan.
Do not infer interchangeable reservation APIs from two successful native reads.

## 5. Manual workflow: 5 / 4 / 3 / 3, not a SQLite version bump

The supported native manual dispatch chain binds task **5**, identity-declared
intent **4**, assignment request **3**, and terminal approval binding **3**.
Weak native claim intent 3 exists but does not authorize this dispatch chain.
Legacy manual remains 3 / 2 / 1 / 1; standing requests remain version 2.
Sources: `scripts/assignment-dispatch.py:264–286`,
`bin/assignment-journal.py:116–158`, `bin/monitor-journal.py:322–425`.

Native task bindings add `task_schema_version: 5` and include the full native
worker plus whole-task digest (`bin/assignment-journal.py:92–97`). Original and
reserved copies, intent, family and marker are cross-checked; relabeling a
legacy envelope does not qualify it. The terminal collector validates native
private binding through the journal/core, not merely its digest
(`scripts/publish-github-assignment.py:165–187`). This adds a transitive core load
to R9's native branch, without making R9 a task-file reader.

R1 now validates 2/3/4/5 independently (402–428); selected preparation, journaling
and observation paths accept cooperative 3/5. Examples:
`scripts/journal-claim-intent.py:84–112`,
`scripts/journal-approved-claim.py:74–81,134`,
`scripts/observe-claim-intent.py:76,135`. Their selected-file safeguards remain
distinct from core reads. This is bounded manual compatibility, not new authority.

SQLite remains `monitor/history.sqlite3` with the existing version families,
including metadata 5/6/7 for identity-bound/manual/standing history; native JSON
envelopes do not introduce metadata version 8 or a new table family
(`bin/monitor-journal.py:146–207`; `bin/assignment-journal.py:248–254,306–308`).
Manual evidence versions 1/2 and settlement 1 remain valid for native requests;
these are not the request/approval version numbers (assignment journal:187–225).

## 6. Monitor loads, settlement and manifest boundaries

S15's own task reader still accepts schemas 1/2, kind monitor, and checks legacy
`ps` start text (`bin/orchestrator-monitor.py:244–269`). Its durable path loads
the journal (404–426). Journal validation of native intent 3/4 calls
`validate_native_binding`, which loads core via assignment-journal even without
assignment rows (monitor journal:177–180, 382–386, 416–425). The v6/v7 assignment
and v7 standing validation paths also remain (204–207). No direct core import
in S15 does not mean independence from core or native validation dependencies.

Manual and standing dispatch now share `Store.guard` and `_settle`
(`scripts/assignment-dispatch.py:226–258,310–367`;
`scripts/standing-grant-dispatch.py:188–194`). Ordering is guard, evidence fill,
durability barrier, settlement fill, durability barrier, re-guard, core release.
Unknown outcome returns after durable evidence with reservation pending. Only
coordinator entry contention retries; guard/write/barrier/release failures do not.
Closed-producer continuation and recovery remain distinct, with compatibility
refusal vocabularies. A generic `apply` must not collapse those boundaries.
Both target-fence enumerations now explicitly pass both gates (assignment
dispatch:303; standing dispatch:98), but use core family-sensitive `command_list`,
not R8's always-strict selected read. Standing native admission remains fenced
(`scripts/standing-grant-dispatch.py:135–143`).

`bin/execution-plan.py:21–28,53–54` hashes **nine** modules, including
`native-process-observation.py`. Exact historical seven/eight-module manifests
remain readable but cannot equal the current installation. Neither
`assignment-journal.py` nor `standing-grant.py` is in this list. Decide their
coverage separately; shared settlement does not automatically hash its modules.
Any eventual seam addition must bind moved code and disclose retained-plan and
rollback effects, not rewrite retained plans or historical manifest findings.

## 7. Current recommendations for D1–D10 (not adopted decisions)

| ID | Recommendation at c731688 |
| --- | --- |
| D1 | Amend the planning basis with this bounded delta; retain the historical inventory. Do not call W0 complete. |
| D2 | Keep a minimal proposed API, but forward both opt-ins and preserve family-specific reads. Leave unexpressed lock windows in their owners. |
| D3 | Re-read multi-section/multi-persist paths with a tester, including shared settlement. Do not replace held launch windows or durability barriers with repeated single-shot calls. |
| D4 | Keep reservations outside the first seam; native reverse scans and physical release proofs remain core responsibilities. |
| D5 | Document a read-only layout/family contract first. Preserve independent readers and explicitly record transitive journal/core loads. |
| D6 | Require explicit acceptance of manifest/retained-plan effects before extraction; add any new delegated module to coverage. Resolve assignment/standing coverage separately. |
| D7 | Keep W0–W7 as the durable conditional tracker. This delta creates no issues and changes no row status. |
| D8 | Use c731688 for this bounded checkpoint, then finish exhaustive W0 re-pin against the actual implementation base and check competing work before W1. |
| D9 | Keep S4 separate pending a tested caller-equivalent strict mode. Native physical reads do not settle D9. Revisit both target-fence enumerations explicitly. |
| D10 | Keep root readers separate pending per-reader equal-guard fixtures, including mixed-family duplicates, reverse leases and replacement races; shared validation is not equal storage semantics. |

## 8. Coverage still required for W0

Source fixtures located include `skill-tests/dual-format-core-test.py` (raw and
escaped duplicates, mixed reverse scans, native release/recovery and observation
refusals), `tests/dual-format-integration-test.py` (both-reader raw duplicates,
manual lifecycle and old-reader refusals), and the native/manual cases in
`tests/assignment-dispatch-test.py` and `tests/check-native-ownership-test.py`.
The inspected core fixture deliberately injects schema 4 and mocks observation
(55–85); it is not native creation support or actual-backend qualification.

Unfinished: exhaustive S/R/G consumer/call-site and citation refresh; full F/U/X
reconciliation, including historical unread documents U1/U8/X3; complete A3
post-5b137ba changes (public claim codec/observer and check-order changes included);
live competing-work/dependency reconciliation; and the W6/W7 refusal matrix.
No old absence search, count, byte-unchanged assertion or test result is renewed.
The roadmap's pinned historical rows are not current-source defects to rewrite.
W0/A3 and dependent rows retain their recorded status until their own conditions
are verified and maintainer decisions are recorded. Run the applicable checks in
the reviewed workspace sandbox before requesting review of this candidate.

AI assistance: GPT 6 Astra in OpenCode, static source inspection and drafting;
no code executed. Human review required before acceptance.
