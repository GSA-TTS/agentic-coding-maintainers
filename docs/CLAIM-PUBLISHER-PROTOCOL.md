# Proposed operator-controlled GitHub claim publisher

**Proposal only; no activation or remote-write authorization.** Issue #117 covers
user/operator native claims. Issue #69's GitHub App automatic actions remain
parked. Issue #116 ownership and #117 intent/observer work are separate dependencies;
their retained evidence does not implement this publisher. First delivery is one
human-approved assignment runner end to end; claim-comment delivery follows review.

## Publisher and approval

Choose the exact current authenticated human user as first publisher. Fresh
`GET /user` must return `type: User` and numeric ID, node ID and expected login
matching request v2's identity observation. The same operator's existing issue
permissions constrain the proposal; do not elevate privileges to make it work.
An optional App is deferred and would need explicit operator/session/App/installation
binding and separate review. This proposal requires no new service.

`public_text_declaration.reviewer` is a declared reviewer, not authenticated
approval. Require a genuine per-action interactive approval in the trusted host
runner: display exact action, target and payload, then require operator affirmation.
Privately bind it to payload SHA-256 (exact comment UTF-8 including final newline),
immutable repository/issue IDs and issue number, action, operation/attempt IDs,
publisher ID, retained task incarnation/full digest/revision, worker, session and
generation, and reviewed implementation head. Changed inputs invalidate approval.
Assignment and comment each require their own approval; approving text alone is
insufficient. Do not accept a fabricated approval file or a readiness boolean.
Collect every human interaction outside global coordinator and SQLite locks. Before
attempt creation, revalidate exact approval metadata under coordinator and record
monotonic elapsed age against a reviewed implementation constant (proposed: 120
seconds maximum). Reject unmeasurable age; policy and age validation stay private.
Recheck age immediately before launch: expired approval means no POST and new
interaction outside locks. A committed attempt positively proven unlaunched settles
`NOT_SENT` through guarded durability, never expiry-based clearing; otherwise it
remains `UNKNOWN`. After dispatch, approval
expiry is irrelevant to settlement and never clears pending dispatch/reservations.

This is cooperative binding, not cryptographic human authentication. Shared-account
identity cannot constrain an uncooperative process with the same credentials.
The runner must actually collect the interaction; journal digests preserve its
recorded binding, not independent proof that a human approved or sent a request.

## Typed dispatch prerequisite

Existing request v2/journal v5 records intent only. Add a reviewed typed assignment
phase **before** any comment phase, with distinct assignment/comment operation IDs
and unrelated attempt IDs. Reuse the private journal, preserving old immutable rows.
Do not prescribe another version ladder: review one phase-one schema migration and
all shared readers together before enabling effects. Unknown types remain refused.

The current core rejects bound-task domain extensions/default domain entry points.
A narrowly qualified adapter plus core guard is a significant reviewed dependency,
not an authority-denial bypass or permission to copy validators into the runner.
Under coordinator, validate the full current task, revision/session/generation,
worker, all slot/lane/scope leases, physical storage, intent and approval bindings.
Refuse pending recovery, drift, inactive ownership or competing local dispatch.

Atomically establish a durable typed `DISPATCHING` attempt and task-scoped ownership
reservation under that same coordinator, with coordinator-before-SQLite lock order.
Core mutation/release/cancellation/handoff/recovery paths must honor the reservation:
no task-binding change or release while dispatch is unresolved. Commit and
complete durability barriers before launching transport; ambiguous local commit
blocks launch. If stores cannot commit together, use reviewed recoverable ordering
whose intermediate state blocks dispatch and handoff, never an unfenced gap.

Release global coordinator and SQLite locks for bounded network calls. The durable
reservation closes the guard-to-POST handoff race for cooperating runners; a fresh
snapshot alone does not. Settlement reacquires coordinator, validates the same
reservation and fences, and durably records outcome before clearing it. Crash,
timeout or lease expiry cannot clear pending dispatch automatically. Unrelated
tasks may proceed. Unknown completion needs the explicit arbitration below.

## Fresh remote checks and assignment

Use a separately reviewed credential-isolated host transport, fixed GitHub.com
endpoints, controlled redirects, raw-body media and a pinned supported API version.
Check live actor/target identities immediately before each dispatch; never infer
permission from `/user`, login spelling or an owner label. Require live repository
permissions sufficient for assignment (including documented push requirement),
credential scopes/selected-repository Issues write access for the chosen auth mode,
and assignability `GET /repos/{owner}/{repo}/assignees/{login}` returning 204.
Missing permission evidence blocks. Reject PR targets, closed/locked issues,
repository drift, incomplete responses and changed approved bindings.
Neither additive assignment nor marker creation has an HTTP compare-and-swap here.
Rereads are not a distributed lock; another publisher can race either POST.

Capture **all prior assignees by immutable ID** in the approved assignment request.
Bound the prior/result sets to ten; require capacity for the actor if absent.
POST only `{"assignees":["<verified-current-login>"]}` to the issue's
`/assignees` endpoint. This is additive, not a replacement PATCH. GitHub documents
preservation of existing users but can silently ignore assignees [1]. If the actor
is already present, settle `SATISFIED_NO_POST`, completion `NOT_SENT`, satisfaction
true, after a fresh complete GET preserves prior IDs; this proves no write.

Validate assignment POST 201 and returned issue identity, then GET the issue again.
Require actor ID present and result IDs a superset of all prior IDs; concurrent
additions are allowed within bounds. A removed prior assignee is `DRIFT`; an ignored
actor absent after a complete GET is `FAILED_ACTUAL_RESULT`, even with HTTP 201.
Successful 201 plus complete validating GET settles `ASSIGNMENT_CONFIRMED_OBSERVED`,
completion `CONFIRMED`, satisfaction true. Persist observations separately from
transport completion: additive/idempotent semantics cannot establish write provenance.
Lost response plus actor presence is correlated satisfaction, completion `UNKNOWN`.
With confirmed POST, complete `DRIFT`/`FAILED_ACTUAL_RESULT` evidence is terminal
failure, satisfaction false. These four terminal outcomes release the reservation
only after no producer remains in flight and evidence/settlement are durable.
Incomplete GET stays blocked pending; fresh bounded GET may finish observation
after revalidating identities, current task and original dispatch fences, never POST.

## Claim comment after settled assignment

Only `ASSIGNMENT_CONFIRMED_OBSERVED` or `SATISFIED_NO_POST`, durably settled with
satisfaction true and fresh assignment preservation, permit comment consideration.
Drift, failure, pending, correlation and `ABANDONED_UNKNOWN` never qualify. Collect
fresh per-comment approval and reread competing claims and assignment. Introduce a
reviewed qualified bounded read for this gate; existing observers keep
`absence_authorizing: false`. A clean complete visible traversal is one operator-
approved prerequisite, not proof of exclusivity. Block conflicting/different-target
or different-operation claims, multiple/malformed markers and incomplete refetches.
Recheck local fences and reserve the comment attempt under coordinator as above.

POST `{"body":"<exact-approved-body>"}` to the bound issue comments endpoint [2].
Require 201, returned positive comment ID, exact raw body/digest, correct issue
identity and immutable author ID plus expected login matching the fresh publisher.
GET that comment by ID and reread the bounded issue claims/assignment to verify the
authoritative **currently observed** receipt. Persist `POST_CONFIRMED_OBSERVED` only
when those checks pass; this is not proof the comment will remain unchanged.
An exact operation claim found after a lost response is `VISIBLE_CORRELATED`, not
write-provenance proof; remote-operation completion remains `UNKNOWN`. Arbitration
may retain correlation but must not relabel it confirmed dispatch.
Edits, duplicates, foreign targets, missing known IDs or conflicting refetches block.
Never automatically delete comments, undo assignments or repair remote drift.

## Attempt and recovery rules

Durable pending precedes every launch. A possibly issued POST cannot be proved
not-sent by observed absence. Never automatically retry either POST, including
additive assignment; persist evidence before settlement, with ambiguous durability
blocked. Normal manual new attempts require proven not-sent or positively settled
prior outcome, fresh guards and approval. Unknown old operations block automatic
resubmission forever; never replay that operation, even after abandonment.

### Operator arbitration of unknown dispatch

Record durable `ABANDONED_UNKNOWN` to resolve the local reservation only; completion
remains `UNKNOWN` forever. Require verified termination/reaping of the original
worker and dispatch-capable descendants, plus evidence no producer remains in flight.
Unknown stop status or inability to prove termination refuses release; an operator
declaration is not termination proof. This cannot cancel an already issued remote POST.

Require a new arbitration operation ID, explicit reason and private evidence IDs,
and interactive approval bound to the exact pending operation/attempt and original
dispatch incarnation. Under coordinator then SQLite, match the current task to
explicit expected revision/generation, full task digest/incarnation and retained
session/worker/reservation binding. Active-worker eligibility is **not** required:
this is stopped-worker arbitration. Changed task or dispatch identity refuses.
Commit arbitration and complete durability barriers before clearing the reservation;
lost acknowledgment leaves release blocked until exact local durability recovery.

Abandonment grants no POST, retry or comment-consideration authority. A new operation/
attempt after abandonment requires a **separate explicit operator decision**, fresh
scope/current-task/remote checks and per-action approval acknowledging unresolved
prior effects; never reinterpret absence as not-sent or reuse the unknown operation.
Correlated satisfied assignment remains ineligible for this runner's comment phase
after abandonment. A human may separately approve a manual comment for another
purpose outside this automation; that is not this runner's continuation authority.

| Boundary/scenario | Outcome, reservation and downstream comment eligibility |
| --- | --- |
| Before attempt commit: stale fence, denial or declined approval | No launch; reconcile and collect fresh approval if appropriate. |
| Attempt commit/durability acknowledgment lost | No launch; inspect retained phase/reservation, repair local durability only. |
| Committed attempt, positively proven transport never launched | Durably settle `NOT_SENT` and release with no in-flight producer; comment ineligible; a new approved attempt may be admitted. |
| Assignment 201 and complete GET confirms actor/preserved prior IDs | `ASSIGNMENT_CONFIRMED_OBSERVED`, completion `CONFIRMED`, satisfaction true; durable release, comment consideration eligible. |
| Actor already present; complete GET preserves prior IDs; no POST | `SATISFIED_NO_POST`, completion `NOT_SENT`, satisfaction true; durable release, comment consideration eligible. |
| Crash after commit, launch status unprovable | `UNKNOWN`; retain reservation, no POST replay. |
| POST may have issued; timeout, lost response or rate-limit/error ambiguity | `UNKNOWN`; bounded GET/operator reconciliation only. |
| Assignment 201 then complete GET omits actor or removes prior ID | Terminal `FAILED_ACTUAL_RESULT` or `DRIFT`, completion `CONFIRMED`, satisfaction false; durable release with no in-flight producer, comment ineligible. |
| Assignment response lost; GET shows actor and preserved prior IDs | Correlated satisfaction, completion `UNKNOWN`; retain reservation pending arbitration, comment ineligible. |
| Comment 201/ID/body/author valid; GET confirms complete current evidence | Durably settle `POST_CONFIRMED_OBSERVED`, release with no in-flight producer; retain immutable receipt. |
| Comment response lost; exact operation/body/author found by GET | `VISIBLE_CORRELATED`, completion `UNKNOWN`; retain reservation pending arbitration, no completion claim or repost. |
| POST confirmed but GET incomplete, or receipt commit lost | Preserve transport evidence; reservation blocked; fresh guarded GET/local durability recovery only, comment ineligible pending finalization. |
| Comment GET edited/conflicting after confirmed POST | Preserve evidence, block continuation; no repair or repost, explicit settlement required. |
| Handoff/release requested during dispatch, restart or expired lease | Core refuses until durable explicit settlement; no timeout takeover. |
| Unknown worker termination/in-flight producer cannot be excluded | Refuse arbitration release, retain reservation; comment ineligible. |
| Verified stopped producer, exact fences, approved arbitration durably committed | `ABANDONED_UNKNOWN`, completion `UNKNOWN` forever; reservation releasable, old operation never replayable, comment ineligible. |

Honor `Retry-After`, reset headers and secondary limits [3]; bounded reads may resume
after backoff, but rate-limit guidance never authorizes a POST retry here.

## Delivery and qualification

1. Review the narrow core adapter, pending guard and single typed migration; build
   one assignment runner with actual interactive approval, journal and transport.
   Exercise the table offline using an effect-disabled runner and fake network.
   A scripted fixture collector must exercise the actual interaction path and
   refusal/expiry gates; it proves neither human identity nor approval authority.
   No production approval override, caller boolean or fake receipt substitutes.
2. Bind review/qualification to the exact implementation head. In an owned
   disposable target, separately obtain explicit user approval for issue creation,
   assignment and each other mutation. Verify preserved assignees and actual GET
   results. Use independently justified isolation for executing candidate code;
   credentials and host-control approval stay outside guests, never guest tokens.
3. Review assignment evidence before enabling the comment vertical with the same
   crash/ambiguity fixtures and individually approved disposable comment actions.
   No automatic native claiming or App actions activate through this document.

Keep approval, task/session/lease/store metadata and diagnostics private. Publish
only reviewed codec fields and sanitized qualification outcomes, never local
secrets, private identifiers, paths or raw journal/credential material.

### Assignment implementation boundary

`scripts/github-assignment-transport.py` contains the candidate direct HTTPS
transport, with fixed GitHub.com endpoints, no redirects, a 30-second total
deadline per transport instance, and no POST retry. A credential-free isolated
Python DNS resolver is killed and reaped on timeout; numeric-address connection
and hostname-verified TLS occur in the runner. No dispatch-capable child is
created. It intentionally supports only
recognizable classic PAT/OAuth token formats with fresh `X-OAuth-Scopes` evidence;
fine-grained PAT, App, installation, Actions, and unprefixed legacy tokens fail
closed. Repository push permission and actor assignability are separate checks.
It is a private library, not a dispatch authorization interface.

`scripts/publish-github-assignment.py` contains the candidate controlling-terminal
collector. It displays JSON-escaped exact private bindings, flushes queued input,
requires an exact digest challenge from a foreground canonical `/dev/tty`, and
revalidates monotonic age and binding in memory. It has no file, boolean, stdin,
or environment approval override. The 120-second ceiling includes interaction
time. Offline PTY fixtures exercise this actual path, not human authentication.

The candidate command now composes `assignment-dispatch.py`, the schema-3 core
reservation adapter, and journal v6 in an assignment-only path. It requires a
clean committed implementation matching the explicit implementation SHA, existing
identity-bound intent with exact original task equality, fresh permissions and
prior assignees, and the real controlling-terminal challenge. The immutable
original task and prospective reserved full task are both retained. The approval
binds the reserved revision/digest, avoiding a self-referential request hash.

The task marker is durably written **before** journal migration/`DISPATCHING`.
Before the marker, a rolled-back insertion rehearsal exercises the same typed
validation, identifier exclusions, retention limits and actual SQLite page
allocation as the real reservation. Predictable full-store/collision refusals
therefore leave the task untouched. Reservation repeats those checks after the
marker; interruption or new storage failures still remain fenced.
Marker-only failure blocks all task lifecycle/release/recovery paths. After FULL
SQLite commit and filesystem barriers, locks are released before the sole POST
site. Evidence and settlement have preallocated bounded storage. Terminal
settlement is committed and synced before the marker becomes permanently
`settled`; old schema-3 readers refuse that extension even after release.
Unrelated task work can proceed while the selected assignment is pending.

`assign` supports confirmed observed assignment, already-satisfied no-POST,
confirmed drift/ignored-assignee failures, and positively unlaunched expired
approval. `settle` repairs exact durable terminal acknowledgment or completes
GET-only observation after retained confirmed transport; it never posts. All
operations refuse replay, including additive assignment. Old intent rows retain
their exact bytes and original v2 binding equality. Existing journal consumers
accept v6 and preserve its version and identifier reservations.

**Operator-approved assignment-only scope:** on 2026-11-09 the operator chose
to keep UNKNOWN permanently blocked and defer abandonment release. Issue #117
remains open for that later work. `arbitrate`
returns `PRODUCER_TERMINATION_PROOF_UNSUPPORTED` without effects. UNKNOWN, absent
transport evidence, and marker-only crash remain blocked. PID disappearance,
operator declarations and changed boot IDs are not termination proof: descendants,
cloned machines and restored snapshots defeat those assumptions. There is no
`ABANDONED_UNKNOWN` release path or comment continuation in this candidate.

The fixtures exercise real terminal interaction, core state, SQLite migration,
dispatch-boundary interruptions and injectable HTTP. They require independent
isolated execution; edits alone are not passing validation. This implementation
and its fixtures grant no live-target write authorization or automatic activation.

[1]: https://docs.github.com/en/rest/issues/assignees#add-assignees-to-an-issue
[2]: https://docs.github.com/en/rest/issues/comments#create-an-issue-comment
[3]: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
