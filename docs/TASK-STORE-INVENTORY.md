---
title: "Task-store inventory: direct readers and writers of coordinator task records"
description: "Source-linked, pattern-bounded inventory of consumers of coordinator task.json records and adjacent reservation state at a pinned main SHA, with a clearly separated PROPOSED task-store seam"
status: proposed
tier: 2
source_sha: "159bc1fc7593fc420d0d6d580199ddc7edea08dc"
date: "2026-11-11"
---

# Task-store inventory

## Status and scope

**Status: proposed, pending maintainer review.** AI-assisted draft (Claude
Sonnet 5.5 in OpenCode) for
[GSA-TTS/agentic-coding-maintainers#167](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/167).
Follows the merged portable-team proposal
[GSA-TTS/agentic-coding-maintainers#138](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/138), the
process-observation issue
[GSA-TTS/agentic-coding-maintainers#161](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/161) and its merged
change [GSA-TTS/agentic-coding-maintainers#165](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/165).
Nothing here is accepted until a human maintainer accepts it.

- **Pinned source:** `159bc1fc7593fc420d0d6d580199ddc7edea08dc` (main after GSA-TTS/agentic-coding-maintainers#165).
  Permalink form:
  `https://github.com/GSA-TTS/agentic-coding-maintainers/blob/159bc1fc7593fc420d0d6d580199ddc7edea08dc/<path>#L<start>-L<end>`.
- **Static only.** Every row is from reading source at the pinned SHA. No inventoried
  code, test or build was executed; no row asserts runtime behavior. "Derived" means
  it follows from cited lines combined; "inferred" means it needs interpretation.
- **Citations are to the pinned SHA.** Line numbers are those of the file at `159bc1f`.
  For files this change does not touch they equal the working tree. The `Makefile` is the
  exception: this change adds one test line, so a pin citation `Makefile:91` is line 92 at
  the candidate HEAD. `tests/task-store-inventory-test.py` checks ranges against the pinned
  blob when the pin is reachable in git, and against the working tree otherwise.
- **Citation convention.** A `path:N` or `path:N-M` citation is a full citation. A bare
  `:N-M` citation resolves against the row's own path (the first path in the Consumer or
  Test cell, or the path of the same ID in the access tables). `tests/task-store-inventory-test.py`
  checks only that cited files exist and ranges fit the file; it cannot check that a
  line still says what the row claims, so refresh rows when the pin is advanced.
- **Post-pin item, not inventoried.** GSA-TTS/agentic-coding-maintainers#168 merged into main as
  `aa37c5542256b21585fd8a924622de7b85ee954d` after the pin. By its diff stat it touches
  `scripts/assignment-dispatch.py` (R8) and `scripts/github-assignment-transport.py`, with tests and
  `docs/CLAIM-PUBLISHER-PROTOCOL.md`. It is not in the pinned source and was not inventoried, so R8's
  rows may be stale against current main; its changes to R8 settlement and lock handling were not
  read in detail. It does not introduce a task-store seam. See U4 and D8.
- **Authority.** The portable-team proposal states that GitHub issues are authoritative
  and locally cached issue metadata is an optimization (documented; see the Authority
  boundary table). This draft preserves that statement and does not extend it to the
  `tracker_*` task fields, whose semantics this inventory did not establish.

**Basis vocabulary** (used in the Basis and Kind columns): `observed` (cited line says
it), `derived` (follows from cited lines), `inferred` (interpretation, evidence cited),
`documented` (a repository document says it), `unknown`.

## Enumeration method

Pattern `PAT` (extended regex), applied with `git grep` at the pinned SHA:

```
task\.json|ORCHESTRATOR_STATE_DIR|\.orchestrator|orchestrator-state|CoordinatorLock|read_task|write_task|task_path|validate_record|verify_reservations|allow_bound|state_root|"tasks"|"slots"|"scopes"|global_slot|implementation_lane|scope_token|process_identity|controller_manifest
```

| Step | Command (at the pinned SHA) | Result |
| --- | --- | --- |
| E1 file universe | `git ls-tree -r --name-only 159bc1f` | 302 tracked files |
| E2 primary sweep | `git grep -lE "$PAT" 159bc1f -- . ':!*.md'` | 70 files: 35 under `tests/` or `*/tests/`, 35 other. All 35 non-test files were read at the matching lines. One false positive: `tests/fixtures/scoped-autonomy/grant-example.json:43` (`implementation_lanes` budget, not a store reader). |
| E3 secondary sweep | same with `owner\.json\|\.lock\b\|"locks"\|"implementation"\|review-artifacts\|review-packets\|review-handoffs` | 13 further files; hit lines inspected: enum values, cleanup lock, content-addressed artifact stores, `.lock` suffix checks. None reads task records. |
| E4 hash sweep | `git grep -nE "__file__...read_bytes\(\)"` on non-test `*.py` | 4 files: S2, S3, S8 and `review-packet.py:180` |
| E5 Markdown sweep | `git grep -lE "$PAT" 159bc1f -- '*.md'` | 22 files matched; only the ones cited here were read (rest in U1) |
| E6 count checks | `git grep -c 'CoordinatorLock('` and `git grep -c 'write_task('` on non-test `*.py` | used in F2 |

**Exclusions (so completeness is not claimed).** Pattern-bounded and tracked-files-only:
not found are path strings built dynamically, consumers that receive a `record` dict from
a caller without touching storage (the sweep pattern cannot find them; the ones listed here
were found by reading call chains and a `record[`/`record.get(` sweep of the skill `bin/`, and others may be missing from the tables), untracked
files, `.orchestrator/` runtime state, other repositories and installed copies, git
history, and `.scratch/` files other than those cited. This is not a proof of completeness.

| Absence claim | Command (narrow) | Result |
| --- | --- | --- |
| A1 | `git grep -nE "$PAT"` on `review-run.py`, `review-packet.py`, `review-materialize.py`, `review-source-map.py`, `review-handoff.py`, `foreground-admission.py`, `monitor-journal.py`, `reservation-history.py`, `orchestrator-monitor.sh` (all under the skill `bin/`) | no matches |
| A2 | `git grep -nE 'task\.json\|\.orchestrator\|orchestrator-state\|CoordinatorLock'` on `.agents/skills/cross-repo-epic`, `.agents/skills/federal-authority-research`, `bin/{epic-status,portfolio-status,review-packet,workspace-cleanup,orchestrator-monitor}.sh`, `scripts/{workspace-cleanup.py,sync-agentic-workspace.sh,delivery-batch.py,cohort-reflection.py}` | no matches |
| A3 | same pattern on `.github` and `.opencode` excluding `*.md` | no matches |
| A4 | `git ls-files \| grep -E 'task\.json$\|owner\.json$'` | no checked-in task or owner fixture files |
| A5 | `git grep -n allow_bound` on non-test `*.py` outside the core | only `assignment-journal.py:133` and `assignment-dispatch.py:117` (S14, R8) |

## Core store: orchestrator-state.py

Base path for bare citations: `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py`
(1,792 lines). Layout: `<root>/tasks/<task-id>/task.json`; `<root>` is
`$WORKSPACE_ORCHESTRATOR_ROOT/.orchestrator` (test mode may override, `orchestrator-state.py:177-184`).

| ID | Consumer | Evidence | Operations | Schemas | Lock | Basis |
| --- | --- | --- | --- | --- | --- | --- |
| C1 | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py` — `state_root`, `task_path`, `read_json`, `read_task` | `:176-205` `:208-218` `:277-294` `:618-622` | read; derive path | 1 (upgraded in memory), 2; 3 only with `allow_bound` | none taken; callers hold it | observed |
| C2 | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py` — `validate_record` schema gates | `:297-392` `:301-304` `:305-315` `:327-330` | read (validate) | 1, 2, 3 (`BOUND_SCHEMA`, `:26`); bound allows only listed extension keys (`:327-328`) | n/a | observed |
| C3 | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py` — `serialized_json`, `atomic_json`, `write_task` | `:245-274` `:723-734` | write | validates the record being written | not enforced inside `write_task` | observed |
| C4 | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py` — enumeration: `command_list`, admission preflight, reconcile, recovery preflight | `:1663-1667` `:1387` `:1622` `:1510` | enumerate (`glob("*/task.json")`) | per C2; reconcile refuses bound (`:1625-1627`) | create/claim/reconcile/recover under lock (`:857` `:970` `:1621` `:1568`); `list`/`show` none (`:1759-1762`) | observed |
| C5 | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py` — `CoordinatorLock` | `:594-615` | lock | n/a | `mkdir locks/coordinator.lock`, `owner.json` with token, fenced release | observed |
| C6 | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py` — reservations: `acquire_dir`, `release_dir`, `reserve_first`, `verify_reservations`, `validate_admission_reservations` | `:737-777` `:1337-1375` `:1378-1413` | write; read; enumerate | scope owner `schema_version` 2 (`:1369`); worker owner shape | under lock | observed |
| C7 | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py` — `allow_bound` semantics | `:297` `:303` `:618` `:723` `:1760-1762` | derive | default refuses 3; CLI `show`/`list`/lifecycle pass `True` | n/a | observed |
| C8 | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py` — transition intent and recovery receipts | `:467-528` `:1151-1166` `:1416-1466` `:1563-1614` | read; write | recovery requires 3 (`:1572-1573`); legacy `finish_intent` refuses 3 (`:1418-1419`) | under lock | observed |
| C9 | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py` — assignment reservation anchor | `:625-720` | read; write | 3 only (`:630`) | caller (dispatch adapter) holds (`:657`) | observed |
| C10 | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py` — process identity wrapper and `worker_metadata` | `:780-800` | derive | worker fields | n/a | observed |
| C11 | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py` — lifecycle writers (create, claim, transition, record, resolve-finding, update-head) | `:803-896` `:969-1024` `:1105-1167` `:1209-1240` `:1243-1293` `:1296-1334` | write; lock | 2 on create (`:878`); claim may move to 3 (`:985`) | each under lock | observed |
| C12 | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py` — extension-validator hooks loaded by path | `:378-391` `:916-966` | read | keys `candidate_binding`, review reservations, `repair_protocol`, `execution_observations` | within caller lock | observed |

## Consumers: skill controllers

All under `.agents/skills/workspace-orchestrator/bin/`. They load the core by path
(`importlib.util.spec_from_file_location`) and call it as a library. "Default" below
means `read_task`/`validate_record` called without `allow_bound`, so schema 3 is refused
(derived from `orchestrator-state.py:303`).

| ID | Consumer | Evidence | Operations | Schemas | Lock | Basis |
| --- | --- | --- | --- | --- | --- | --- |
| S1 | `.agents/skills/workspace-orchestrator/bin/candidate-binding.py` | `:71-72` `:210-221` `:228-255` `:278-279` `:309` | read; write; lock; derive (incarnation from `scope_token`); fsync task file | default (1, 2) | two sections (`:230` `:248`) around an external poll lock (`:238-245`) | derived |
| S2 | `.agents/skills/workspace-orchestrator/bin/execution-observe.py` | `:299-302` `:372-375` `:385-387` `:418-424` `:437` `:450-467` `:481-487` | read; write; enumerate (`glob`); lock; hash; derive | default | three separate sections (`:385` `:450` `:481`) with a subprocess between | derived |
| S3 | `.agents/skills/workspace-orchestrator/bin/execution-plan.py` | `:21-26` `:51-52` `:167-168` `:274` `:336-359` | hash (controller manifest); read; write; lock | default | write path locked (`:352`); assessment reads twice unlocked (`:341-343`) | derived |
| S4 | `.agents/skills/workspace-orchestrator/bin/foreground-delivery.py` | `:33-40` `:230` `:309-316` `:544-547` `:564-588` | read (raw bytes via `task_path`, then `validate_record`); write (one final write, or repair `persist` callbacks); lock; derive (process identity `:581`) | default | `:565` | derived |
| S5 | `.agents/skills/workspace-orchestrator/bin/foreground-repair.py` | `:5` `:202-208` `:260-274` | derive (replicates `write_task` size/revision fields); no storage I/O | n/a | caller holds (`:5`) | observed |
| S6 | `.agents/skills/workspace-orchestrator/bin/foreground-adopt.py` | `:270-272` `:280` `:292-297` | read (`verify_reservations`); in-memory mutation | default (record from caller) | caller holds | derived |
| S7 | `.agents/skills/workspace-orchestrator/bin/foreground-review.py` | `:185` `:191` `:99-100` `:121` | read (`verify_reservations`); own `review-packets/` store | default (record from caller) | caller holds | derived |
| S8 | `.agents/skills/workspace-orchestrator/bin/repair-apply.py` | `:26` `:245` `:284` `:301-302` `:322` `:326` `:333` `:365` `:381-397` | read; write (three persists); lock; hash | default | `:385` | observed |
| S9 | `.agents/skills/workspace-orchestrator/bin/repair-proposal.py` | `:35-44` `:272-281` | read; write; lock | default | `:276` | observed |
| S10 | `.agents/skills/workspace-orchestrator/bin/review-accept.py` | `:106` `:119` `:171-178` | read; write; lock | default | `:173` | observed |
| S11 | `.agents/skills/workspace-orchestrator/bin/review-collect.py` | `:240-254` `:389` `:469-476` | read; write; lock | default | `:471` | observed |
| S12 | `.agents/skills/workspace-orchestrator/bin/review-evidence.py` | `:311-312` `:603-604` `:638-645` `:689-707` | read (status path unlocked, `:692`); write; lock; derive (incarnation from `scope_token`) | default | `:701` (mutation only) | observed |
| S13 | `.agents/skills/workspace-orchestrator/bin/review-reservation.py` and `.agents/skills/workspace-orchestrator/bin/reservation-history.py:9-27` | `:149` `:173-189` `:206` `:235-253` | read; derive (structural key probe); own `review-handoffs/` store | default (record from caller) | caller holds | derived |
| S14 | `.agents/skills/workspace-orchestrator/bin/assignment-journal.py` | `:84-90` `:131-137` `:145` | read (`validate_record(allow_bound=True)`); derive (task digest binding) | 3 required (`:134`) | caller holds (`:333`) | observed |
| S15 | `.agents/skills/workspace-orchestrator/bin/orchestrator-monitor.py` | `:38` `:185-200` `:203-229` `:239-263` `:266-272` `:510` `:537` | read (direct `task.json` and `slots/N.lock/owner.json`); derive (own `ps` probe); write (own monitor files) | {1, 2} only (`:244`) | none (repeated reads) | observed |
| S16 | `.agents/skills/workspace-orchestrator/bin/runtime-observation.py` | `:15-28` | derive (process identity) | n/a | n/a | observed |
| S17 | `.agents/skills/workspace-orchestrator/bin/monitor-journal.py` | `:48-49` `:375-383` | derive (task digest and worker shape bound into claim intents); no storage I/O (A1) | 3 (worker has `session_id`, `generation`) | n/a | derived |
| S18 | `.agents/skills/workspace-orchestrator/bin/foreground-admission.py` | `:43` `:58` | derive; no storage I/O (A1); called from S4 (`foreground-delivery.py:512`) | default (record from S4) | caller holds | derived |
| S19 | `.agents/skills/workspace-orchestrator/bin/review-handoff.py` | `:195-215` `:240` | derive (reads `foreground_control` receipts and `runtime_collections` of a caller-supplied record); no storage I/O of its own | default (record from S4 `foreground-delivery.py:453` or S13 `review-reservation.py:202`) | caller holds (`:196`) | derived |

## Consumers: root scripts and wrappers

| ID | Consumer | Evidence | Operations | Schemas | Lock | Basis |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | `scripts/check-native-ownership.py` | `:14-41` `:336-350` `:383-402` `:405-447` `:473-504` | read (descriptor-based, no core import); derive (own schema copy) | {2, 3} (`:339`) | none; retained file fingerprints (`:447`) | observed |
| R2 | `scripts/prepare-task-claim.py` | `:37-55` `:71-79` | read (reuses R1 helpers); derive | via R1 | none | observed |
| R3 | `scripts/prepare-approved-claim.py` | `:55-85` | read task and three owner files; derive | via R1 | none | observed |
| R4 | `scripts/journal-claim-intent.py` | `:30-35` `:80-84` `:111-114` | lock; read; derive (task digest) | 3 required (`:84`) | `:80` | observed |
| R5 | `scripts/journal-approved-claim.py` | `:72-76` `:147` `:156` | lock; read; derive (task digest) | 3 | `:147` | observed |
| R6 | `scripts/observe-claim-intent.py` | `:62-67` `:75-76` `:89-93` `:150` | read; derive | 3 required (`:76`) | none, by design (`:66-67`) | observed |
| R7 | `scripts/record-claim-observation.py` | `:141` `:148-154` | lock; read | 3 | `:141` | observed |
| R8 | `scripts/assignment-dispatch.py` | `:39-47` `:50-72` `:80-81` `:96` `:110-119` `:121-153` `:241` `:289` `:351` | lock; read; write (`assignment_reserve`/`assignment_release`); derive; replaces core `git_probe` (`:71`) | 3 (`allow_bound=True`, `:117`) | `:96` | observed |
| R9 | `scripts/publish-github-assignment.py` | `:94-99` `:143-148` | derive (validates `task_binding` field set); no storage I/O | n/a | n/a | derived |
| R10 | `scripts/evaluate-workflow.py` | `:27-29` `:48-56` `:61-80` `:84-110` `:130` | enumerate (descriptor walk); read; derive (imports core validator) | 1, 2 (default; bound fails) | none | observed |
| R11 | `scripts/review-workspace-preflight.py` | `:3-5` `:38-48` `:185-198` `:257-261` `:316-336` `:383-384` | enumerate; read (snapshots whole `tasks/` and reservation trees); derive (own schema copy) | {1, 2} (`:260`); 3 reported unsupported | none | observed |
| R12 | `Makefile` (check target), `scripts/sync-agentic-workspace.sh`, `scripts/import-workspace-orchestrator.sh` | `Makefile:91` (at the pin) `scripts/sync-agentic-workspace.sh:39-43` `scripts/import-workspace-orchestrator.sh:11-13` `scripts/import-workspace-orchestrator.sh:46` | hash (skill package manifest); no task I/O | n/a | n/a | observed |
| W1 | `bin/orchestrator-state.sh` | `:3-7` `:27-45` | derive (authority root); exec; no storage I/O | n/a | n/a | observed |
| W2 | `.agents/skills/workspace-orchestrator/run.sh` and `.agents/skills/workspace-orchestrator/bin/orchestrator-state.sh:10` | `:13` | dispatch only | n/a | n/a | observed |

## Consumer assumptions

Keyed by ID from the three tables above. "Extension keys" lists quoted record keys found
by grep (`record["key"]`/`.get("key"`/`setdefault("key"` forms); other access forms may exist, so every list in this column is non-exhaustive.

| ID | Durability / atomicity | Extension keys | Failure mode | Coupling | Tests | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| C1 | read-only; 1 MB bound, symlink refusal, optional duplicate-key refusal | none | `UnknownError` | storage layout | T1 T17 T23 | `:277-294` |
| C2 | n/a | `cooperative_binding`, `legacy_finding_dispositions`, `transition_recovery`, `assignment_dispatch` allowed on 3 | `UnknownError` | schema gates; lifecycle rule | T1 T17 | `:327-328` |
| C3 | temp file, fsync, `os.replace`, directory fsync; directory-fsync failure raises `AmbiguousWriteError`; 1 MB cap | all (whole record) | ambiguous write surfaced; claim re-raises it (`:1019-1020`) | storage layout; durability | T1 T17 | `:245-274` `:1019-1020` |
| C4 | none | all | `UnknownError`; exits 3 | storage layout | T1 T23 | `:1663-1667` |
| C5 | no stale takeover; a held lock raises `BusyError` | none | exit 4 (`:1779-1781`) | process identity (pid recorded); lifecycle | T17 T24 | `:601-615` `:1779-1781` |
| C6 | each reservation is a directory plus atomic `owner.json`; failed owner write leaves an empty directory deliberately ambiguous (`:744-747`) | none | `UnknownError` on mismatch | storage layout; lifecycle rule | T1 T20 | `:744-747` `:1341-1375` |
| C7 | n/a | n/a | refuses with "unsupported by this controller" | schema gates | T17 | `:303` |
| C8 | intent written before effects, final write after (`:1151-1166`); receipt pending and settled | `transition_recovery`, `transition_intent` | `UnknownError` | lifecycle rule | T17 | `:1151-1166` |
| C9 | marker written first and never rolled back (`:657`) | `assignment_dispatch` | `UnknownError`/`BusyError` | lifecycle rule; durability | T24 | `:657` `:676-679` |
| C10 | n/a | `worker.pid`, `worker.process_start` | `unknown` status becomes `UnknownError` | process identity | T16 | `:786-800` |
| C11 | per C3 | all | exit 2/3/4 taxonomy (`:22-24`) | lifecycle rule | T1 T3 T4 | `:22-24` |
| C12 | n/a | `candidate_binding`, `execution_observations`, `repair_protocol`, `review_protocol`, review reservations | `UnknownError("retained repair evidence unavailable")` | schema gates | T9 T13 | `:378-391` `:959` |
| S1 | explicit task-file and directory fsync after write (`:210-221`) | `candidate_binding` | prints `REFUSED` (exit 4) or `UNVERIFIED` (exit 3) | storage layout (fsync of `task_path`); lifecycle rule | T7 | `:210-221` `:311-317` |
| S2 | each write through `write_task`; DISPATCHING made durable before spawn (`:443`) | `execution_observations` | JSON `UNVERIFIED`, exit 3 (`:490-493`) | storage layout (enumerates `tasks/`); process identity; hash binding | T8 | `:423-424` `:443` `:490-493` |
| S3 | via `write_task` | `execution_plans`, `execution_observations`, `review_protocol`, `runtime_collections` | JSON `UNVERIFIED`, exit 3 | hash binding (controller manifest); lifecycle rule | T9 | `:21-26` `:274` |
| S4 | persist callback runs twice for `apply-owner-proposal` and once for reconcile (`.agents/skills/workspace-orchestrator/bin/foreground-repair.py:299-311` `.agents/skills/workspace-orchestrator/bin/foreground-repair.py:324-338`); other actions use one final `write_task` (`.agents/skills/workspace-orchestrator/bin/foreground-delivery.py:588`). Single locked section | `foreground_control`, `foreground_initialized`, `repair_proposals`, `repair_protocol`, `review_protocol`, `runtime_collections`, `collected_review_acceptances` | JSON `UNVERIFIED`, exit 3 (`:590-594`) | storage layout (raw `task_path` read bypasses `read_task`); process identity | T5 T6 | `:567-568` `:581` `:590-594` |
| S5 | n/a; projects the write budget (900,000 canonical bytes, then `serialized_json`) | `foreground_repairs` and S4's keys | `Unverified` | durability (copies `write_task` limits) | T14 | `:202-208` |
| S6 | n/a | `foreground_control`, `foreground_repairs`, `repair_proposals`, `repair_protocol`, `review_protocol`, `legacy_finding_dispositions` | `Unverified` | lifecycle rule; reservation ownership | T14 | `:280` `:292-297` |
| S7 | n/a | `foreground_control`, `review_protocol` | `Unverified` | reservation ownership; lease shape | T14 | `:185` `:191` |
| S8 | three persists (`:326` `:333` `:365`); first is a fence before the first file write | `repair_protocol`, `review_protocol` | JSON `UNVERIFIED`, exit 3 | lifecycle rule; hash binding (`controller_sha256`) | T10 T12 | `:322` `:326` |
| S9 | via `write_task` | `repair_proposals`, `repair_protocol`, `review_protocol`, `runtime_collections` | JSON `UNVERIFIED`, exit 3 | lease shape (`global_slot`, `implementation_lane` must be int) | T27 T5 T12 | `:35-36` |
| S10 | via `write_task` | `collected_review_acceptances`, `review_protocol`, `runtime_collections` | JSON `UNVERIFIED`, exit 3 | lifecycle rule | T15 | `:171-178` |
| S11 | artifact store fsynced (`:251`); record via `write_task` | `review_protocol`, `review_reservations`, `runtime_collections` | JSON `UNVERIFIED`, exit 3 | lifecycle rule | T15 | `:240-254` |
| S12 | via `write_task` | `review_protocol`, `foreground_*`, `repair_*`, `runtime_collections`, `review_reservations` | JSON `UNVERIFIED`, exit 3 | lifecycle rule; incarnation identity | T15 | `:689-707` |
| S13 | n/a | non-exhaustive: `review_reservations`, `review_reservations_initialized`, `foreground_control`, `foreground_repairs`, `repair_protocol`, `runtime_collections` (also reads `owner`, `worker`, `task_id`, `revision`) | `Unverified` | lifecycle rule | T13 | `:173-189` |
| S14 | digest of the full task record is bound into the journal | `assignment_dispatch` | `require()` refusal | schema gates; durability (digest equality) | T24 | `:84-90` `:145` |
| S15 | own `atomic_json` replaces files without a directory fsync (`:185-200`) | none | `monitor: UNVERIFIED`, return 3 (`:497-503`) | storage layout; process identity (own `ps` probe, `:252-257`); capacity constant (`:259`) | T2 T11 | `:242` `:252-257` `:259` `:497-503` |
| S16 | n/a | none | `unknown` result | process identity | T16 | `:15-28` |
| S17 | n/a | none | `JournalError` | schema gates (binding field set) | T25 | `:375-383` |
| S18 | n/a | non-exhaustive: `foreground_control`, plus the `review_protocol` or `runtime_collections` table named by the request (`foreground-admission.py:37`) | `Unverified` | lifecycle rule | T14 | `foreground-delivery.py:512` |
| S19 | n/a | `foreground_control`, `runtime_collections` (`:199` `:207`) | `ValueError` from local `require` (`:21-23`); callers convert to `Unverified` | lifecycle rule | T29 | `:195-215` |
| R1 | read-only; compares file fingerprints before and after (`:447`) | optional bound keys only (`:41`) | fixed reason codes; exit 0, 3 or 4 (`:504`) | storage layout; schema gates; capacity constants (`:170-173`) | T20 | `:41` `:170-173` `:504` |
| R2 | read-only | via R1 | fixed codes | storage layout (via R1) | T21 | `:37-55` |
| R3 | read-only; fingerprints retained across reads | via R1 | fixed codes | storage layout; lease paths | T22 | `:69-82` |
| R4 | holds lock while writing the journal; fsync on journal file and directory (`:38-65`) | via R1 | `IntentRefusal` fixed codes | lifecycle rule; durability | T25 | `:38-65` |
| R5 | as R4 | via R1 | fixed codes | lifecycle rule | T25 | `:147` |
| R6 | no lock, repeated bounded reads (`:66-67`) | via R1 | fixed codes | storage layout | T25 | `:66-67` |
| R7 | as R4 | via R1 | fixed codes | lifecycle rule | T25 | `:141` |
| R8 | reserve, durable journal, release ordering (`:289` `:241` `:351`) | `assignment_dispatch` | `Refusal` fixed codes | lifecycle rule; durability; process identity (`:152`) | T24 | `:152` `:289` |
| R9 | n/a | none | `INVALID_APPROVAL_BINDING` | schema gates (binding field set) | T28 | `:94-99` |
| R10 | read-only; per-record 100,000 byte cap and 500-task cap (`:27-29`) | none | exits 3 with `UNVERIFIED` | storage layout; schema gates | T19 | `:27-29` |
| R11 | read-only; whole-tree snapshot bounded (4,096 entries) | none | `UNVERIFIED` codes; unknown top-level state entries fail (`:383-384`) | storage layout; capacity constants (`:297`) | T18 | `:383-384` |
| R12 | n/a | none | manifest diff fails the check | package layout | T26 | `Makefile:91` |
| W1 | n/a (exec only) | none | `refuse` prints UNVERIFIED and exits 3 | process identity; authority root (physical primary checkout) | T23 | `:3-7` `:27-45` |
| W2 | n/a (dispatch only) | none | not examined | none (dispatch only) | none located | `:13` |

## Tests and fixtures

Fixtures are not checked in (A4): tests build state in temporary directories and, in
several cases, patch core attributes (`write_task`, `atomic_json`, `release_dir`,
`CoordinatorLock`), so those names are a test-facing surface. "Runner not verified" means
the file was not shown to be listed in `make test`.

| ID | Test or fixture | Evidence | Couples to | Basis |
| --- | --- | --- | --- | --- |
| T1 | `.agents/skills/workspace-orchestrator/tests/orchestrator-state-test.sh` | `:8` `:33` `:422` `:458-460` | `ORCHESTRATOR_STATE_DIR`, `task.json` bytes, slot counts, orphan lock left in place | observed |
| T2 | `.agents/skills/workspace-orchestrator/tests/orchestrator-monitor-test.sh` | `:10` `:86-91` | state dir env, `monitor/poll.lock` | observed |
| T3 | `.agents/skills/workspace-orchestrator/tests/orchestrator-production-worktree-test.sh` | `:13` `:60` | production path `.orchestrator/tasks/<id>/task.json` | observed |
| T4 | `.agents/skills/workspace-orchestrator/tests/orchestrator-demo.sh` | `:8` `:25` | `task.json` layout | observed |
| T5 | `.agents/skills/workspace-orchestrator/tests/foreground-delivery-test.py` | `:56` `:344-350` `:514` `:521` `:556` `:674` `:1612-1617` | `task.json` path, `CoordinatorLock`, `write_task`, reservation `owner.json`; drives `repair-proposal` through the domain CLI; installs the `*-cases.py` suites (T14) | observed |
| T6 | `.agents/skills/workspace-orchestrator/tests/foreground-handoff-test.py` | `:18-20` `:31-41` | `task_path` bytes unchanged; installs the `*-cases.py` suites (T14) | observed |
| T7 | `.agents/skills/workspace-orchestrator/tests/candidate-binding-test.py` | `:37` `:160` `:176` | state dir env, `task.json`, `poll.lock` | observed |
| T8 | `.agents/skills/workspace-orchestrator/tests/execution-observe-test.py` | `:91` `:170-172` `:179-180` | `active_execution_owner` lease shape, CLI state script | observed |
| T9 | `.agents/skills/workspace-orchestrator/tests/execution-plan-test.py` | `:82` `:144-158` `:300` | `controller_manifest`, `MODULES` | observed |
| T10 | `.agents/skills/workspace-orchestrator/tests/repair-apply-test.py` | `:179` `:193` | state dir env, `task.json` | observed |
| T11 | `.agents/skills/workspace-orchestrator/tests/monitor-journal-test.py` | `:14-18` `:250-257` | loads the journal module; its CLI case runs the core state script and the monitor against a workspace. Does not exercise the claim-intent task binding (S17) | observed |
| T12 | `.agents/skills/workspace-orchestrator/tests/qualify-review-repair.py` | `:55-58` `:136` | `read_task` on `.orchestrator`; guest-only driver, loaded (not run live) by `qualification-driver-test.py:11`, which `Makefile:27` at the pin lists | observed |
| T13 | `.agents/skills/workspace-orchestrator/tests/review-reservation-test.py` | `:118` `:315` | `write_task` calls and patches | observed |
| T14 | `.agents/skills/workspace-orchestrator/tests/foreground-adopt-cases.py` | `:283` `:425-431` | patches `write_task` and `atomic_json`; sibling case files `foreground-admission-cases.py:268` and `foreground-review-cases.py:260`; all three are loaded by `foreground-delivery-test.py:1612-1617` and `foreground-handoff-test.py:18-20`, which `Makefile:18-19` at the pin list | observed |
| T15 | `.agents/skills/workspace-orchestrator/tests/review-collect-test.py` | `:288-300` | state dir env, `task.json`; same pattern in `review-accept-test.py:150-160` and `review-evidence-test.py:279-291` | observed |
| T16 | `.agents/skills/workspace-orchestrator/tests/runtime-observation-test.py` | `:30` `:51` `:187-213` | core `process_identity` wrapper, `worker_metadata`, copied-skill loading | observed |
| T17 | `tests/cooperative-session-binding-test.py` | `:24-37` `:62` `:127` `:133` `:138-153` | embeds an excerpt of a previous core validator; patches `write_task`, `release_dir`; asserts no leftover lock | observed |
| T18 | `tests/review-workspace-preflight-test.py` | `:96` `:112-113` `:205-209` `:253-256` | builds `.orchestrator` trees, schema variants, lock contents | observed |
| T19 | `tests/evaluate-workflow-test.sh` | `:116-119` `:135-140` `:156` | copies core, builds `tasks/` tree | observed |
| T20 | `tests/check-native-ownership-test.py` | `:103-106` `:343-345` | task, slot, lane, scope file paths | observed |
| T21 | `tests/prepare-task-claim-test.py` | `:36-56` `:180` | state dir env, task and owner paths | observed |
| T22 | `tests/prepare-approved-claim-test.py` | `:173-176` | `TASK_FILE` rewrite | observed |
| T23 | `tests/shared-authority-admission-test.py` | `:26` `:38` `:74` `:105-107` | wrapper plus `.orchestrator/tasks`, `scopes` | observed |
| T24 | `tests/assignment-dispatch-test.py` | `:57` `:138` `:530-539` | owner files, lock leftovers, direct calls to release/reserve primitives | observed |
| T25 | `tests/journal-claim-intent-test.py` | `:100-103` `:392-398` | asserts the journal `binding` equals `task_sha256`/`created_at`/`worker` of the task (S17 behavior); task path; siblings `tests/journal-approved-claim-test.py:566`, `tests/record-claim-observation-test.py:515`, `tests/observe-claim-intent-test.py:327` | observed |
| T26 | `tests/import-sync-test.sh` | `:19-22` | copies wrapper and core files; sibling `tests/operating-surface-test.sh:82` runs `reconcile` | observed |
| T27 | `.agents/skills/workspace-orchestrator/tests/repair-proposal-test.py` | `:9-19` `:24` | loads `repair-proposal.py` and subclasses the `repair-apply-test.py` fixture; calls `p.apply` on an in-memory record. Domain-level CLI use of repair-proposal (`self.domain("repair-proposal", ...)`) is in `foreground-delivery-test.py:514,521` (T5) | observed |
| T28 | `tests/publish-github-assignment-test.py` | `:39-52` `:226` | builds a fixture `task_binding` and calls `publisher.validate_binding`; no task file is read | observed |
| T29 | `.agents/skills/workspace-orchestrator/tests/foreground-handoff-test.py` | `:23-27` `:29` `:60` `:92` | `HandoffCLI` drives `export-admitted-review` through the public CLI; also `review-reservation-test.py:339` calls `export_admitted` directly | observed |

## Adjacent reservation and lock directories

Only five directories are created by `state_root` (`orchestrator-state.py:194`); the rest
are created lazily by the module named.

| Directory under `.orchestrator/` | Evidence | Writers | Readers | Basis |
| --- | --- | --- | --- | --- |
| `tasks/<id>/task.json` | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:214-218` | C3 C9 C11 | all of C1 to S15, R1 to R11 | observed |
| `locks/coordinator.lock/owner.json` | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:594-615` | C5 | R11 (generic reservation-entry checks for every group including `locks`, `scripts/review-workspace-preflight.py:341-357`; `locks` owner `pid`, `hostname`, `created_at` checks, `scripts/review-workspace-preflight.py:364-369`) | observed |
| `scopes/<sha256-of-scope>.lock/owner.json` | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:856` `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:894` `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:1160-1163` | C11 | C6, R1, R3, R6, R7, R8, R11 | observed |
| `slots/<0-5>.lock/owner.json` | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:29` `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:1007` | C11 | C6, S15 (`orchestrator-monitor.py:261`), R1, R3, R6, R7, R8 | observed |
| `implementation/<0-1>.lock/owner.json` | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:30` `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:1149` | C11 | C6, R1 (bound `Implementing` only, `scripts/check-native-ownership.py:444-446`), R8 | observed |
| `monitor/` (`poll.lock`, `history.sqlite3`, `checkpoint.json`, `last-failure.json`) | `.agents/skills/workspace-orchestrator/bin/orchestrator-monitor.py:219-228` `.agents/skills/workspace-orchestrator/bin/candidate-binding.py:238` `.agents/skills/workspace-orchestrator/bin/monitor-journal.py:58` | S15 (`.agents/skills/workspace-orchestrator/bin/orchestrator-monitor.py:426`, writable open; own JSON files `.agents/skills/workspace-orchestrator/bin/orchestrator-monitor.py:390` `.agents/skills/workspace-orchestrator/bin/orchestrator-monitor.py:398`); S1 (`.agents/skills/workspace-orchestrator/bin/candidate-binding.py:259` `.agents/skills/workspace-orchestrator/bin/candidate-binding.py:286`, writable open); R4 (`scripts/journal-claim-intent.py:102-104`); R5 (`scripts/journal-approved-claim.py:156` `scripts/journal-approved-claim.py:164`); R7 (`scripts/record-claim-observation.py:161`); R8 (`scripts/assignment-dispatch.py:98`) | R11 (`scripts/review-workspace-preflight.py:47-48`); S15 status (`.agents/skills/workspace-orchestrator/bin/orchestrator-monitor.py:482`); R6 (`scripts/observe-claim-intent.py:114`, read-only open); R7 (`scripts/record-claim-observation.py:81`); R5 (`scripts/journal-approved-claim.py:51`); C9 (`.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:685-686`, read-only open in `assignment_release`) | observed |
| `review-artifacts/` | `.agents/skills/workspace-orchestrator/bin/review-collect.py:240-254` | S11 (`.agents/skills/workspace-orchestrator/bin/review-collect.py:391` `.agents/skills/workspace-orchestrator/bin/review-collect.py:415` `.agents/skills/workspace-orchestrator/bin/review-collect.py:436`); S2 (`.agents/skills/workspace-orchestrator/bin/execution-observe.py:428-429` `.agents/skills/workspace-orchestrator/bin/execution-observe.py:471-472`); S3 (`.agents/skills/workspace-orchestrator/bin/execution-plan.py:227` `.agents/skills/workspace-orchestrator/bin/execution-plan.py:240` `.agents/skills/workspace-orchestrator/bin/execution-plan.py:243`); S8 (`.agents/skills/workspace-orchestrator/bin/repair-apply.py:312-313`); S9 (`.agents/skills/workspace-orchestrator/bin/repair-proposal.py:245-248`) | S2 S3 S8 S9 S10 S5 (`.agents/skills/workspace-orchestrator/bin/foreground-repair.py:294`) | observed |
| `review-packets/` | `.agents/skills/workspace-orchestrator/bin/foreground-review.py:99-100` | S7 | S7 | observed |
| `review-handoffs/` | `.agents/skills/workspace-orchestrator/bin/review-reservation.py:149` `.agents/skills/workspace-orchestrator/bin/review-reservation.py:206` | S13 | S13 | observed |
| `execution-docker-config/` | `.agents/skills/workspace-orchestrator/bin/execution-observe.py:387` | S2 | S2 | observed |
| unrecognized entries (preflight) | `scripts/review-workspace-preflight.py:383-384` `.agents/skills/workspace-orchestrator/bin/review-collect.py:240-254` | none | R11 | inferred |
| `tmp/cleanup/.lock` (separate store, excluded) | `scripts/workspace-cleanup.py:153` | workspace cleanup | workspace cleanup | observed |

The inferred row: preflight accepts only the five state groups plus `monitor`
(`scripts/review-workspace-preflight.py:38` and `scripts/review-workspace-preflight.py:383-384`), while other modules create
`review-artifacts/` and similar siblings. By reading, a state root holding them would be
reported `UNVERIFIED` by preflight. This was not executed.

## Authority boundary

| Fact | Where it lives | Evidence | Basis |
| --- | --- | --- | --- |
| Task-record tracker fields are validated for shape only | `tracker_type` must be `none`, `issue` or `pr` and `tracker_number` a non-negative int; creation also requires number 0 for `none` and positive for `issue`/`pr` | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:349-350` `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:852-855` | observed |
| GitHub issues are authoritative; locally cached issue metadata is an optimization | stated by the proposal for cached issue metadata; it says nothing about `tracker_*` field semantics, and no cited source line states that these fields are references only | `.scratch/portable-team-as-code/proposal.md:22-25` | documented |
| Claims, execution attempts and operation receipts are distinct from cached issue metadata | proposal statement; the existing store keeps them in the task record | `.scratch/portable-team-as-code/proposal.md:23-25` `docs/NATIVE-OWNERSHIP.md:7-8` | documented |
| A candidate binding is not remote authority | `candidate_binding.result.remote_authority` is `False` | `.agents/skills/workspace-orchestrator/bin/candidate-binding.py:113` `.agents/skills/workspace-orchestrator/bin/candidate-binding.py:168` | observed |
| Ownership preflight never authorizes mutation | `mutation_authorized` is `False` | `scripts/check-native-ownership.py:57-59` | observed |

## Findings

| ID | Finding | Evidence | Basis |
| --- | --- | --- | --- |
| F1 | Task schema is validated by four separate code paths: core, `check-native-ownership.py`, preflight and the monitor. They accept different schema sets ({1,2,3}, {2,3}, {1,2}, {1,2}). | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:297-330` `scripts/check-native-ownership.py:339` `scripts/review-workspace-preflight.py:260` `.agents/skills/workspace-orchestrator/bin/orchestrator-monitor.py:244` | observed |
| F2 | The sequence lock, `read_task`, `verify_reservations`, mutate, `write_task` is repeated in nine skill controllers (S1 to S4, S8 to S12), plus four root scripts take the lock. | `.agents/skills/workspace-orchestrator/bin/repair-apply.py:385-391` `.agents/skills/workspace-orchestrator/bin/review-collect.py:471-476` `.agents/skills/workspace-orchestrator/bin/review-accept.py:173-178` `.agents/skills/workspace-orchestrator/bin/repair-proposal.py:276-281` | derived |
| F3 | Capacity constants (6 slots, 2 lanes) appear in four places: core, R1 (as maxima 5 and 1), R11 and the monitor. | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:29-30` `scripts/check-native-ownership.py:170-173` `scripts/review-workspace-preflight.py:297` `.agents/skills/workspace-orchestrator/bin/orchestrator-monitor.py:259` | observed |
| F4 | `orchestrator-state.py` and `execution-observe.py` are in the execution-plan controller manifest; changing either changes the manifest, and a plan whose manifest differs is refused. | `.agents/skills/workspace-orchestrator/bin/execution-plan.py:21-22` `.agents/skills/workspace-orchestrator/bin/execution-plan.py:274` `.agents/skills/workspace-orchestrator/bin/execution-plan.py:306` | derived |
| F5 | Many readers reach `task.json` without calling `read_task`, in two groups. **(a) Direct file readers of one or more records:** S4 (`task_path` bytes, then `validate_record`); S15 (builds the path itself); R1 (`read_selected`, shared with R2, R3, R4, R5, R6, R7 through `prepare.selected`); R8 (`read_selected`, then core `validate_record`); R10 (descriptor walk, then `validate_record`); R11 (whole-tree snapshot); and the core's own `read_json` paths in admission preflight, recovery, reconcile and `command_list`. **(b) Enumeration-only bypass:** S2 globs `tasks/*/task.json` but then calls `coordinator.read_task` per record (`execution-observe.py:424`). S1, S3, S8 to S12 call `read_task` and are not in either group. | `.agents/skills/workspace-orchestrator/bin/foreground-delivery.py:567-568` `.agents/skills/workspace-orchestrator/bin/orchestrator-monitor.py:242-243` `scripts/check-native-ownership.py:414` `scripts/prepare-task-claim.py:45` `scripts/assignment-dispatch.py:116` `scripts/evaluate-workflow.py:85` `scripts/review-workspace-preflight.py:330` `.agents/skills/workspace-orchestrator/bin/execution-observe.py:423-424` `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:1387-1388` `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:1510-1511` `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:1570` `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:1665-1666` | observed |
| F6 | Core-import status of the direct readers. **Core-independent (no direct load, and none loads `monitor-journal` or `assignment-journal`; both checked by `git grep` at the pin):** R1 (comment says no state-module import), R11 (docstring says no controller imports), R2 and R3 (load only `check-native-ownership.py`, `native-claim.py`, `prepare-task-claim.py`, `observe-github-claims.py`). **No direct core load, but a transitive path exists:** S15 loads only `monitor-journal.py` (`orchestrator-monitor.py:405-409`); `journal.open_store` calls `validate_store` (`monitor-journal.py:130`), which for a version-6 store calls `assignment_journal().validate(db)` (`.agents/skills/workspace-orchestrator/bin/monitor-journal.py:199-200`, loader `.agents/skills/workspace-orchestrator/bin/monitor-journal.py:597-605`); `assignment-journal.py` `validate` calls `validate_request` for each `assignment_requests` row (`.agents/skills/workspace-orchestrator/bin/assignment-journal.py:261`), and that loads `orchestrator-state` (`.agents/skills/workspace-orchestrator/bin/assignment-journal.py:131`). By reading, S15 can therefore reach the core lazily, only when a v6 journal holds assignment request rows; not executed. **Do load the core:** R10 (`evaluate-workflow.py:48-56`), R4 (`journal-claim-intent.py:34`), R5 and R6 and R7 (through `intent.modules()`), R8 (`assignment-dispatch.py:43`). | `scripts/check-native-ownership.py:337` `scripts/review-workspace-preflight.py:3-5` `scripts/prepare-task-claim.py:28-29` `scripts/prepare-approved-claim.py:168-172` `.agents/skills/workspace-orchestrator/bin/orchestrator-monitor.py:405-409` `.agents/skills/workspace-orchestrator/bin/monitor-journal.py:130` `.agents/skills/workspace-orchestrator/bin/monitor-journal.py:199-200` `.agents/skills/workspace-orchestrator/bin/monitor-journal.py:597-605` `.agents/skills/workspace-orchestrator/bin/assignment-journal.py:107` `.agents/skills/workspace-orchestrator/bin/assignment-journal.py:131` `.agents/skills/workspace-orchestrator/bin/assignment-journal.py:261` `scripts/evaluate-workflow.py:48-56` `scripts/journal-claim-intent.py:30-35` `scripts/observe-claim-intent.py:33` `scripts/record-claim-observation.py:22` `scripts/journal-approved-claim.py:23-24` `scripts/assignment-dispatch.py:43` | observed |
| F7 | Only `assignment-journal.py` and `assignment-dispatch.py` outside the core pass `allow_bound=True`. All other controllers refuse schema 3 by default. | `.agents/skills/workspace-orchestrator/bin/assignment-journal.py:133` `scripts/assignment-dispatch.py:117` `docs/NATIVE-OWNERSHIP.md:56-60` | derived |
| F8 | The monitor runs its own `ps -p <pid> -o lstart=` probe instead of the extracted process-observation module, so GSA-TTS/agentic-coding-maintainers#165's extraction does not cover it. | `.agents/skills/workspace-orchestrator/bin/orchestrator-monitor.py:252-257` `.agents/skills/workspace-orchestrator/bin/runtime-observation.py:15-28` `docs/decisions/0001-extract-process-observation.md:68-80` | observed |
| F9 | Tests treat `task.json` bytes and core function names as API (patched attributes, byte equality). | `tests/cooperative-session-binding-test.py:138-153` `.agents/skills/workspace-orchestrator/tests/foreground-adopt-cases.py:425-431` `.agents/skills/workspace-orchestrator/tests/foreground-handoff-test.py:31-41` | observed |

## Unknowns and not inspected

| ID | Item | Why unknown | Next action |
| --- | --- | --- | --- |
| U1 | 22 Markdown files matched the pattern; only those cited were read. Unread: skill `SKILL.md`, `PROVENANCE.md`, `docs/{CANDIDATE-BINDING,DURABLE-PR-MONITOR,OPERATOR-GUIDE,REVIEW-COLLECTION,REVIEW-HANDOFF}.md`, both `implementation-worker.md` profiles, `README.md`, `docs/{NATIVE-GITHUB-CLAIMS,REPOSITORY-SETUP,WORKSPACE-CLEANUP}.md` (partially), and `.scratch` research files | Grep listing only | Read before ADR; may add documented lock or recovery procedures |
| U2 | All runtime behavior (lock contention, crash recovery, fsync outcomes) | Nothing was executed, by constraint | Primary runs the verification commands in an isolated environment |
| U3 | Consumers outside this repository: installed skill copies, downstream `agentic/` copies, host-local scripts | Out of tree | Maintainer lists known installs before any seam rollout |
| U4 | What GSA-TTS/agentic-coding-maintainers#168 (merged as `aa37c5542256b21585fd8a924622de7b85ee954d` after the pin) changed in R8 (`scripts/assignment-dispatch.py`) and whether any other open work proposes a task-store seam | Diff stat and a skim of the diff only; R8 rows are at the pin | Refresh R8 against current main when the pin is advanced (D8); `.scratch/portable-team-as-code/proposal.md:238-240` asks to adopt existing seams |
| U5 | Whether persisted records of schema 1 or other extension combinations exist on any host | Host state not inspected | Maintainer survey; affects migration risk |
| U6 | Whether `make test` at HEAD still lists the suites that load the `*-cases.py` and `qualify-review-repair.py` files | Resolved at the pin: `Makefile:18-19` and `Makefile:27` list `foreground-handoff-test.py`, `foreground-delivery-test.py` and `qualification-driver-test.py`, which load them (T12, T14). Not re-checked at HEAD | `git show 159bc1f:Makefile \| grep -n 'foreground-\|qualification-driver'` |
| U7 | Dynamically built paths and non-literal names | Pattern search cannot prove absence | Review by hand during any migration PR |
| U8 | Operator procedure for a leftover `locks/coordinator.lock` after a crash | Code has no takeover; docs unread | Read `OPERATOR-GUIDE.md` |
| U9 | Whether `.opencode` copies match skill profiles byte for byte | Not compared | `diff` in the isolated check |

## PROPOSED: task-store seam (not implemented)

Rows above this heading carry a Basis value: most are `observed` or `derived` from the
cited source, but some are `inferred`, `documented` or `unknown`, and the Unknowns table
lists what was not inspected. Rows below are **recommendation** unless a row says
otherwise. The proposal is not approved,
changes no code, moves no code, changes no schema or runtime behavior, and adds no
Markdown or Git adapter. Kind values: `observed` (cited above), `documented` (a
repository document states it), `recommendation` (this draft's proposal), `unknown`.

### Evidence that shapes the seam

| Claim | Kind | Evidence |
| --- | --- | --- |
| Nine skill controllers repeat state root, lock, read, reservation check, mutate, write | observed | F2; `.agents/skills/workspace-orchestrator/bin/review-collect.py:470-476` |
| Two distinct shapes defeat a single-shot "apply". **Multi-section** (several separate lock acquisitions in one CLI run, with external work between): S2 (three lock sections, each writing once; the middle one is entered per case) and S1 (a replay read section, then a read and conditional write section around an external poll lock). **Multi-persist within one locked section:** S8 (`apply_repair` persists twice) and S4's repair actions (the `persist` callback is called twice for `apply-owner-proposal`). S2 is multi-section only; each of its sections writes once | observed | `.agents/skills/workspace-orchestrator/bin/execution-observe.py:385` `.agents/skills/workspace-orchestrator/bin/execution-observe.py:450` `.agents/skills/workspace-orchestrator/bin/execution-observe.py:481` `.agents/skills/workspace-orchestrator/bin/candidate-binding.py:230` `.agents/skills/workspace-orchestrator/bin/candidate-binding.py:248` `.agents/skills/workspace-orchestrator/bin/repair-apply.py:326` `.agents/skills/workspace-orchestrator/bin/repair-apply.py:333` `.agents/skills/workspace-orchestrator/bin/foreground-repair.py:299-311` `.agents/skills/workspace-orchestrator/bin/foreground-delivery.py:586-588` |
| Reservation directories and task writes are ordered together (reserve, then write, release on failure; intent, release, final write) | observed | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:1007-1023` `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:1151-1166` |
| Four direct readers are core-independent (R1, R2, R3, R11). S15 has no direct core load but may reach it transitively through the journal (F6). R6, R10 and the lock-holding scripts R4, R5, R7, R8 load it directly | observed | F6 |
| The controller manifest hashes core modules, so a new module must be added to it or its code leaves the hash | observed | F4; `docs/decisions/0001-extract-process-observation.md:99-119` |
| Tests patch core attributes by name | observed | F9 |
| An existing precedent: sibling module loaded by path, wrapper retained in the core | documented | `docs/decisions/0001-extract-process-observation.md:68-80` |

### Smallest seam (recommendation)

One new sibling module, tentatively `task-store.py`, loaded by path like
`runtime-observation.py`, exposing only what the evidence above requires. Each function
delegates to the code that exists today; no behavior is meant to move or change.

| Operation | Shape | Replaces | Justification |
| --- | --- | --- | --- |
| `inspect(root, task_id, *, allow_bound=False)` | validated record | direct `read_task` calls (S1, S2, S3, S8 to S12) and raw reads (S4) | Same default refusal of schema 3 as `allow_bound` today (F7) |
| `list(root, *, allow_bound=False)` | sorted validated records | `command_list`, S2's `glob`, admission and recovery loops | Enumeration is the layout leak in C4 and S2 |
| `apply(root, task_id, change, *, allow_bound=False)` | runs `change(record, persist)` under the coordinator lock after `verify_reservations`; `persist(record)` is `write_task`; returns `change`'s result | the repeated block of F2; multi-persist callers (S4 repair actions, S8) via `persist` | Multi-persist sections need `persist`; multi-section callers (S1, S2) are a separate question (D3) |
| lock | not exposed separately at first; callers needing separate sections (S1, S2) call `apply` several times | `CoordinatorLock` in controllers | Exposing a bare lock would keep every caller coupled to lock semantics. Revisit only if S1 or S2 cannot be expressed (D3) |

`apply` keeps the lock, the read, `verify_reservations` and `write_task` exactly as in
the core; the core's own `command_*` functions keep calling its internal functions and
are not migrated. Naming is provisional and defers to any seam already proposed in
other open work (U4, D8).

### Invariants the seam must preserve (each cited to source)

| Invariant | Evidence |
| --- | --- |
| Mutation only under the coordinator lock; a held lock refuses with exit 4 and changes nothing | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:594-615` |
| Each write bumps `revision`, sets `updated_at`, validates, then atomically replaces; 1 MB cap | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:723-734` `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:245-250` |
| Directory-fsync failure stays an ambiguous write and is never retried silently | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:264-271` |
| Pending assignment anchor refuses writes; the settled anchor can never be changed | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:650-653` `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:723-730` |
| Default refuses schema 3; only explicit `allow_bound` accepts it | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:303` |
| Unknown or malformed state stays UNVERIFIED (exit 3), never "healthy" | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:1775-1788` |
| Reservation ownership is checked in both directions before admission or mutation | `.agents/skills/workspace-orchestrator/bin/orchestrator-state.py:1341-1413` |
| `write_task`, `atomic_json`, `release_dir` and similar remain patchable core attributes | F9 |
| The seam must not change what the record means as authority: `remote_authority` stays false in `candidate_binding`, and the proposal keeps GitHub issues authoritative over cached issue metadata | `.agents/skills/workspace-orchestrator/bin/candidate-binding.py:168` `.scratch/portable-team-as-code/proposal.md:22-25` |

### What must remain outside the seam

| Item | Reason | Basis |
| --- | --- | --- |
| Lifecycle rules, transitions, recovery receipts, validators and extension-key semantics (C2, C8, C9, C11, C12) | Not storage; moving them is a behavior change | recommendation |
| Reservation directories `scopes/`, `slots/`, `implementation/` and `locks/` | Ordered together with task writes (see evidence); separate decision (D4) | recommendation |
| Process identity (C10, S16, S15's own probe, F8) | Runtime-observation concern already extracted in GSA-TTS/agentic-coding-maintainers#165 | documented |
| Core-independent direct readers R1, R2, R3, R11 (F6), and the monitor S15, which has no direct core load but may reach it transitively via `monitor-journal` and `assignment-journal` for v6 journals with assignment rows. R6, R8 and R10 read task files directly but do load the core, so they are a separate case | Independence of R1, R2, R3, R11 is stated in their own comments or shown by their loaders; S15's is partial (F6). A store seam would have to offer a read-only layout contract first (D5). R6, R8 and R10 can route through the seam without losing independence | recommendation |
| Other `.orchestrator/` stores: `monitor/`, `review-artifacts/`, `review-packets/`, `review-handoffs/` | Not task records (S7, S11, S13, S15) | observed |
| Journal digest bindings (S14, S17, R4, R5, R9) | They hash whole task records and so depend on exact serialization | recommendation |
| Any alternate backend (Markdown, Git or other) | Out of scope for GSA-TTS/agentic-coding-maintainers#167; needs its own design after the seam exists | recommendation |

### Compatibility and rollback risks

| Risk | Kind | Evidence | Mitigation (recommendation) |
| --- | --- | --- | --- |
| A new controller module changes the execution-plan manifest key set; retained plans then differ and are refused, as in GSA-TTS/agentic-coding-maintainers#165 | documented | `docs/decisions/0001-extract-process-observation.md:99-119` `.agents/skills/workspace-orchestrator/bin/execution-plan.py:21-26` `.agents/skills/workspace-orchestrator/bin/execution-plan.py:167-168` | Add the module to `MODULES` in the same change; state the effect on retained plans and rollback in the PR |
| Rollback after plans carrying the new key exist is not a no-op | documented | `docs/decisions/0001-extract-process-observation.md:99-119` | Keep the newer controller or quarantine and re-plan; do not edit retained plans |
| Import-time dependency: a partial copy lacking the new file fails at import, not as a structured UNVERIFIED | documented | `docs/decisions/0001-extract-process-observation.md:127-133` | Copy the whole `bin/`; update `CANONICAL-SHA256SUMS` |
| Sync and import lists name files individually | observed | `scripts/import-workspace-orchestrator.sh:11-19` `scripts/import-workspace-orchestrator.sh:46` `tests/import-sync-test.sh:19-22` | Check each list when adding a file |
| Serialization drift would break digest bindings and byte-equality tests | observed | S14, S17, R4, R5; F9 | Keep `serialized_json` unchanged; add no key |
| Module-attribute patching by tests could silently stop affecting a moved call | observed | F9 | Keep calls resolving through the core module attribute, as GSA-TTS/agentic-coding-maintainers#165 did |
| Behavior differences between locked and unlocked readers (S12 status path, S3 assessment, `list`/`show`) | observed | S12, S3, C4 | Provide `inspect` without lock first; do not add a lock to read paths |
| Cooperative schema-3 extension rules are enforced by separate copies (R1, C2) | observed | F1 | The seam must not widen accepted keys |

### Migration order (recommendation; each step its own reviewed change)

| Step | Change | Behavior change | Prerequisite |
| --- | --- | --- | --- |
| 0 | Maintainer decisions D1 to D8; refresh R8 and check other open work for a seam (U4); read unread docs (U1, U8) | none | this inventory accepted |
| 1 | Add the module with `inspect`, `list`, `apply` delegating to core functions; add to `MODULES`; update checksums and tests; core keeps its names | none intended; manifest key set changes | step 0 |
| 2 | Migrate the simplest single-section controllers: S10, S11, S9 | none intended | step 1 |
| 3 | Migrate S12, S3, S8 (S8 is multi-persist via `persist`) | none intended | step 2 |
| 4 | Migrate S1, S2 (multi-section; D3), then S4 (multi-persist on repair actions, raw read) | none intended | step 3; D3 |
| 5 | Decide the read-only layout contract for the core-independent readers R1, R2, R3, R11 and for S15 (no direct core load; transitive path per F6); decide separately whether core-loading direct readers R6, R8, R10 move to `inspect`/`list` | none until decided | D5 |
| 6 | Only then discuss a second backend | out of scope here | all of the above |

Per the repository's tracking rule, steps 1 to 5 are blocked work that should each have a
tracked issue naming its blocking step. This document does not file them; the primary or a
maintainer decides (D7).

### Decisions for the maintainer

| ID | Decision | Options | Default if silent |
| --- | --- | --- | --- |
| D1 | Adopt the inventory as the basis for the seam | accept / amend / reject | pending |
| D2 | Seam shape: `inspect`, `list`, `apply` only, or also a bare lock | three operations / add lock | three operations |
| D3 | Can multi-section controllers (S1, S2) use repeated `apply`, or do they need a held lock across external work? Needs reading their control flow with a tester | repeated apply / expose lock | unknown |
| D4 | Reservation directories inside or outside the first seam | outside / inside | outside |
| D5 | Core-independent direct readers (R1, R2, R3, R11) and S15 (no direct core load; may reach it transitively for v6 journals with assignment rows): leave as is, give them a documented layout contract, or route through the seam. Core-loading direct readers (R6, R8, R10): route through `inspect`/`list` or leave | leave / contract / route | leave |
| D6 | New module in the controller manifest (accept the retained-plan effect) or leave the seam unhashed | hash / not hash | hash |
| D7 | Create tracked issues for steps 1 to 5 now | yes / no | not done |
| D8 | Before step 1, re-pin the inventory to current main (post GSA-TTS/agentic-coding-maintainers#168) and adopt any seam already proposed in other open work | re-pin then adopt / keep these names | refresh R8 and check other open work first (U4) |

## Links

- Proposal: [GSA-TTS/agentic-coding-maintainers#138](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/138)
- Process-observation issue: [GSA-TTS/agentic-coding-maintainers#161](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/161)
- Process-observation change: [GSA-TTS/agentic-coding-maintainers#165](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/165)
- This inventory: [GSA-TTS/agentic-coding-maintainers#167](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/167)
- Post-pin, not inventoried: GSA-TTS/agentic-coding-maintainers#168, merged as `aa37c5542256b21585fd8a924622de7b85ee954d`
- Precedent decision record: `docs/decisions/0001-extract-process-observation.md`

AI assistance: drafted by Claude Sonnet 5.5 in OpenCode from static reading of the
pinned source; no code was executed. Requires human review before acceptance.
