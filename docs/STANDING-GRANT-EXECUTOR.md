# Standing-grant executor candidate

This implements the synthetic first vertical from [scoped autonomy](SCOPED-AUTONOMY.md),
tracked by issue #68. Source installation, endpoint qualification and an actual
human activation are separate decisions. This candidate has not activated a grant.

Activation and dispatch default to `ENDPOINT_QUALIFICATION_NOT_INSTALLED` until
the human controller installs an exact qualification record. Only
`OFFLINE_REVIEWED_ONE_USE_LIVE_PILOT` is supported: offline evidence plus an explicit
human assessment authorizes one synthetic create attempt and its additive assignment
under a separately activated grant. It does not certify production qualification.
No production mode, general metadata switch or runtime qualification-file selector
exists. Installed evidence proves byte identity and bindings; actual execution and
review quality remain the installing human's assessment in this cooperative model.

## Human qualification installation

`control-standing-grant.py install-qualification --proposal <private-manifest>`
uses the existing canonical store, supports bootstrap from v5/v6, and takes
`--expected-epoch` for the qualification selector (separate from the grant epoch).
It performs no network writes. The manifest has exactly:

- `version: 1`, unique 32-hex `qualification_id`, the supported `mode`, and
  explicit `human_identity`;
- `scope`: exact `implementation_head`, `policy_sha256`, repository name/immutable
  IDs, publisher identity, objective/work item, typed `workflow_effects`, the two
  `actions`, Linux `platform`, and fixed `pilot_limits` (1 create attempt, 1 assignment
  attempt, maximum 86400-second grant, daily 5/20 and cumulative risk 3);
- `report` and `transcript`: each contains a simple `name`, byte `size`, and `sha256`.

Artifacts must already reside in private, owner-only physical directories at
`.orchestrator/qualification-evidence/<qualification_id>/`. Each artifact must be
an owner-only regular single-link file. Descriptor-relative reads reject symlinks,
replacement, wrong size/hash and directory changes. Reports are canonical JSON
bounded to 32 KiB; transcripts are bounded to 1 MiB. Runtime retains no caller path.

The report contains exact `version`, `scope`, `cases`, `independent_reviews`, and
`assessment: OFFLINE_FIXTURES_ONLY_HUMAN_MUST_ASSESS_ARTIFACT_MEANING`. All fixed
required cases enumerated in `standing-grant.py:QUALIFICATION_CASES` must say
`PASS`; both distinct QA and security reviewer references must bind the same head,
PASS result and evidence digest. Hashes and PASS strings are not proof of execution:
the installing human must examine the actual transcript and referenced reviews.
The TTY challenge shows the complete bounded manifest/report, identities, limits
and evidence digests. The controller checks clean code, policy and artifact bytes
again after the decision, then durably stores an immutable receipt and selects it.

Activation and runtime resolve this installed selection and recheck the retained
artifact bytes and exact target/controller/policy/workflow bindings. Altered or
missing artifacts refuse effects. `revoke-qualification` requires its own real TTY
decision and exact qualification epoch. It first requires the grant already revoked
and all effect gates quiescent; thus qualification revocation cannot race an active
producer. Reinstallation needs a new human decision and ID; it does not erase logical
work deduplication, issue budgets, UNKNOWN history or a pending core marker.

## Supported scope

The controller binds one admitted `intake` task, its incarnation, worker, owner,
session/generation and revision to one finite objective/work item. Intake tasks
own no branch, worktree or paths and stay `Claimed` during publication. Use scope
`GSA-TTS/agentic-coding-maintainers:intake:<objective>:<work_item>` and initially
`tracker: none`. The controller does not admit or claim tasks for callers.

The runtime actions are `issue-create`, `assignees-add` (publisher self-assignment),
`settle`, and local-only `complete`. Text is a fixed synthetic template selected at activation; runtime
accepts no title, body, labels, milestone, target number, grant file or approval
flag. The current repository restriction is immutable ID `1422648445` at the fixed
GitHub API origin. Classic PAT/OAuth credentials and fresh push/assignability
permission are required; GitHub App and fine-grained credentials are unsupported.

Creation consumes both the five-issue and twenty-metadata UTC-day ceilings.
An actual assignment mutation consumes metadata. A durable synchronous `NOT_SENT`
receipt plus a matching `NOT_SENT` or `SATISFIED_NO_POST` terminal settlement
releases reserved remote quota, while retaining all request and dedup history.
An already-present publisher cannot POST and requires no remote quota; it still
records evidence, settlement and core acknowledgement. Evidence without terminal
settlement does not refund quota. Pending/UNKNOWN attempts remain charged across
restart and renewal. Daily and cumulative UNKNOWN/outstanding counters are shared
across all repository grants and objectives, conservatively stronger than the
per-grant minimum; changing objective cannot reset risk. Only one grant is active
at a time; concurrent active objective grants are unsupported.

## Controller and runtime entry points

Run installed, clean, reviewed code with `python3 -I -B`. Both entry points require
the canonical `--authority-root`, identical `--invoking-root`, and exact
`--implementation-head`. They also require the admitted `--task-id`,
`--expected-revision`, `--expected-worker-id`, `--expected-session-id`, and
`--expected-generation`. `--expected-epoch` is a mismatch guard, not a grant selector.

`scripts/control-standing-grant.py activate --proposal <private-file>` takes a
canonical JSON proposal with exactly these fields:

- `version: 1`, unique 32-hex `grant_id`, lowercase slug `objective` and `work_item`;
- `repository`, `repository_id`, `repository_node_id`;
- `publisher` containing immutable `id`, `node_id` and verified `login`;
- current `policy_sha256`, full `implementation_head`, `lifetime_seconds` (1–86400);
- `qualification` with `endpoint_evidence_sha256` (64 lowercase hex);
- `workflow_effects` with exact `events: ["issues.opened", "issues.assigned"]`,
  `decision: "AUTHORIZE_REVIEWED_SYNTHETIC_ISSUE_EVENT_WORKFLOWS_AND_COST"` and
  `evidence_sha256` (64 lowercase hex). These mandatory references require the
  human-installed qualification; syntactically valid hashes do not enable actions;
- `title`: `Synthetic standing-grant tracking fixture: <work_item>`;
- `body`: `Synthetic fixture for the <objective> objective. No production change requested.`

The controller snapshots the proposal and actual admission and displays the full
escaped binding on a foreground canonical controlling terminal. A digest challenge
and fresh remote identity/permission checks precede durable activation. Files,
environment variables and stdin cannot confirm the challenge. Its receipt is
`CONTROLLING_TTY_GRANT_CHALLENGE`, distinct from manual assignment approval.
The digest includes the complete effective action/field scope, allowlisted assignee,
5/20/3/24-hour and worker/target limits, repository-wide accounting, platform,
workflow events/cost decision and qualification references.

`scripts/control-standing-grant.py revoke` requests revocation durably before
waiting for the per-grant effect gate, without holding the global coordinator.
`GRANT_REVOKED_QUIESCENT` means the producer has left the gate. A retained gate with
an unknown owner leaves `REVOKE_REQUESTED_GATE_UNVERIFIED`; it is not auto-taken-over.
Repeat `revoke` with the same epoch to resume a durable `revoke-requested` record
after timeout or interruption. The controller validates and preserves the original
receipt, collects no replacement authorization, and acknowledges only after normal
gate acquisition. An existing unknown-owner gate continues to refuse completion.
The activation and revocation bindings/receipts are retained in the shared journal.

`scripts/execute-standing-grant.py issue-create` resolves active authority from
the canonical journal, performs a bounded complete all-state issue traversal,
and reserves a typed request and budgets. A public opaque SHA-256 work marker
derives from repository/objective/work item, never private task or session IDs.
Title/body correlation refuses creation; it cannot turn an unknown POST into a
confirmed write. Traversal is bounded to ten 100-item pages and the transport's
byte/deadline limits. Incomplete traversal refuses. GitHub snapshots are not a
distributed lock and cannot exclude a concurrent external create after the read.

Only a confirmed create response and matching immutable-ID GET permit durable
`ISSUE_CREATED_OBSERVED` settlement. The core then binds the intake tracker exactly
once. Both representations must identify the activated publisher as the author by
immutable user ID, node ID, login and User type, and must have no assignees;
unexpected assignment is drift, not implicit setup authority. `assignees-add` resolves the issue from this retained
create request/settlement, verifies identity and existing assignees, then uses the
additive endpoint. It accepts no caller issue identity. Complete the intake and
admit implementation separately against the returned tracker; there is no task-kind
morph and no intake branch/worktree reservation to conflict with implementation.

`execute-standing-grant.py complete` completes only a claimed intake with the exact
durable confirmed-create and successful additive-assignment (or satisfied-no-POST)
settlement chain. It compares the explicit task revision/session/worker fences,
requires the unchanged post-settlement task and exact leases, and writes a durable
`Done` transition intent before releasing global/scope reservations. No fabricated
head, reviewer or implementation acceptance is needed. On interruption, repeat
`complete` with the current explicit revision: only that exact settlement-backed
intent permits already-released leases; conflicting owners fail closed. Generic
cooperative recovery never silently completes it. Completion uses no network and
does not require an unexpired grant.

The completion receipt binds the physical device/inode of each owned lease.
Every invocation rechecks the exact task bytes and selected file identity and
fsyncs the task file and parent before any lease release. Whole lease directories
are renamed to task-private `intake-slot-release` / `intake-scope-release`
tombstones and both parents are fsynced. A durable per-lease cleanup phase precedes
owner unlink and directory removal. Resume authenticates an empty tombstone by
its retained physical identity and cleanup phase; an arbitrary empty original
lease or a foreign/reused slot is never treated as release evidence. Generic
`release_dir` semantics remain unchanged.

Compatibility fixtures include inert, byte-pinned production sources under
`tests/fixtures/standing-grant-legacy/`. Tests verify their source manifest before
materializing Python in sandbox temporary directories; shallow CI needs no history
fetch. Qualification cases now include actual executor changed-code/expiry/daily
budget refusals and interrupted intake completion, in addition to migration guards.

`settle --operation-id <retained-operation>` never posts. It can acknowledge an
already durable terminal result or repeat a GET for a confirmed create whose
observation failed. UNKNOWN remains fenced and cannot be retried with a new task,
operation or grant. A crash-owned effect gate still needs separately qualified
containment recovery; this delivery supplies no takeover operation.

## Durability, compatibility and clocks

Journal v7 adds definitions/selection to the existing SQLite store and uses the
existing request/attempt/evidence/settlement tables. Request v2 explicitly carries
`authorization.source: STANDING_GRANT`; it is not a legacy claim or TTY receipt.
Old request v1 and evidence v1/v2 retain their validators and bytes. Historical
validation resolves the retained definition, not the active selector.

Schema-3 task markers have a distinct version 2 carrying action, grant, target
and logical key. The marker is fsynced first, then journal reservation and budget
history, then synchronous network outside the coordinator, then evidence and
settlement, then core acknowledgement. All lifecycle release guards retain the
pending marker fence. Both legacy and standing dispatch consult opposing pending
targets, including marker-only failures. Existing #154 UNKNOWN and #158 history
are not rewritten, released or reinterpreted.

The initial supported clock platform is Linux with `/proc` boot identity and
`CLOCK_BOOTTIME`. Wall, elapsed and awake clocks must advance consistently within
two seconds. Rollback, suspension, reboot or uncertainty pauses new dispatch
durably. Unsupported platforms refuse activation/dispatch explicitly. Settlement
does not require active authority or clock continuity. A revoked grant cannot renew
across lost continuity; a future independently reviewed recovery procedure is
needed instead of resetting budgets after reboot.

This is cooperative same-account automation. The active store and effect gate do
not isolate authority from hostile same-UID code. Credential-bearing execution
and human terminal interaction belong to the installed trusted controller;
candidate fixtures must run in an independently justified sandbox.

## Validation status

The added fixtures exercise actual controller TTY interaction and actual core/
SQLite state with injected HTTP for create/bind/assignment, refusal, lost response,
marker-first failure and GET-only recovery. Additional fixtures exercise actual
TTY revocation before reservation and during an in-flight POST, durable no-POST
quota release, objective-hop risk refusal, qualification refusal and byte-for-byte
preservation of real legacy v6 UNKNOWN rows/core markers during migration.
`make check` includes them and the
existing manual-publisher/assignment compatibility suites. They have not been run
on the host. Full endpoint qualification requires the primary session's isolated
behavioral and strict checks, plus fixed-head independent review; source presence
or structural tests alone are not qualification evidence.
