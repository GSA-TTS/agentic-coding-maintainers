---
title: "Minimal local operation and the Paseo experience under one contract"
description: "Source-pinned comparison of a minimal Markdown/Git/CLI team runtime and Paseo's richer bindings, with observed guarantees and open human choices."
status: draft
tier: 2
last_updated: "2026-11-06"
---

# Minimal local operation and the Paseo experience under one contract

AI-authored research evidence for
[Compare minimal local operation with the Paseo experience](../issues/02-minimal-and-paseo-bindings.md),
a child of [Portable team-as-code](../map.md).

Historical worker-placement note: this file was written at its preapproved path
`.scratch/portable-team-as-code/research/minimal-and-paseo-bindings.md` inside
the researcher's own workspace, where tracker links were unavailable. This
publication copy is integrated beside the map and tickets; those links now resolve.

Research only. Nothing here was executed as a candidate runtime: no OpenRig
daemon, rig, cron entry, schedule, or demonstration agent was started. All
findings below are **source inspection** of pinned revisions plus **bounded
read-only probes of the already-running host** this researcher happens to
occupy. No claim here rests on having run a candidate runtime; where a
behavior could only be settled by execution, §9 says so rather than asserting
it, and §6 grades every guarantee as observed, proposed, absent, or
uninspected.

Primary integration note: the researcher original is preserved in its workspace.
This copy corrects inference overreach about CLI server dependencies, storage
guarantees, and already-settled user direction. Source inspection is not live
qualification. The reported independent review is researcher-reported evidence;
the primary has not inspected that review transcript.

## Source pins

| Source | Pin | How read |
| --- | --- | --- |
| OpenRig | `bd39da9872afc39cbe0c8e839a322b4cb8955cbe` (2026-11-05, repo version `0.7.1`) | Full clone checked out read-only in a temp dir; every citation also confirmed fetchable at that SHA on raw.githubusercontent.com (HTTP 200) |
| Paseo server/CLI (installed, live) | `@getpaseo/cli` and `@getpaseo/server` **0.12.0** (`paseo --version` → `0.12.0`) | Compiled JS in `~/.npm-global/lib/node_modules/@getpaseo/cli/node_modules/@getpaseo/server/dist` |
| Paseo server (kit-pinned) | `@getpaseo/server` **0.15.0**, npm tarball sha256 `4c405938f1e1602e2fa6e0a20c786df4c36c661d794ace15bedeaea6e2593ad4`, registry integrity `sha512-aWGakQhvwEE16OCXW+dg2kq4mBV5iEB0wVxC2VOInY49yruvxpypWA5K3miZ72uV4Vo3HfE+L8eOitpJnfvsfQ==` | Downloaded and extracted read-only; diffed against 0.12.0 |
| Patterns (Paseo acq kit) | `941a286f912b99475429c3c00db49a99af5b241e` (main, 2026-11-04); kit pin bump in `0c4e1a82231e0f03bbb42039d51f210c0776ee42` | Local sibling checkout (behind) plus `git show origin/main` and raw.githubusercontent.com |
| Kits (sibling) | `mogul/agentic-coding-kits` @ `1097829e3655f003080ea5222d9ce980c90b3c23` | Local read-only checkout |
| OpenCode (host) | `opencode v2.0.30` | `--help` surfaces and `opencode api get /api/info` |

### Pin corrections to the handoff

- **Paseo kit pin is 0.15.0, confirmed.** `integrations/isolation/acq-kits/paseo/spec.yaml`
  at Patterns `main` exports `PASEO_CLI_VERSION="0.15.0"`
  ([spec.yaml:192](https://github.com/GSA-TTS/agentic-coding-patterns/blob/941a286f912b99475429c3c00db49a99af5b241e/integrations/isolation/acq-kits/paseo/spec.yaml#L192)).
  The **local sibling checkout is 33 commits behind** and still shows `0.12.0`;
  reading it alone would have reported a stale pin.
- **The running host is 0.12.0, not the kit pin.** `PASEO_CLI_VERSION=0.12.0`
  in this process's environment, `paseo --version` → `0.12.0`, and every
  `@getpaseo/*` package under the CLI's `node_modules` is `0.12.0`. So the
  *configured* kit pin and the *observed* runtime differ by three minor
  versions. Both were read.
- **`GSA-TTS/agentic-coding-kits` 404 is explained.** The sibling checkout's
  remote is `https://github.com/mogul/agentic-coding-kits.git`, not GSA-TTS.
  That repository contains no Paseo acq kit; its only Paseo asset is a
  personal skill, `personal/files/home/.agents/skills/paseo-first-mate`.
- **OpenCode V2 API docs remain unreachable.** `https://opencode.ai/v2/docs/api`
  and `https://opencode.ai/docs/` both failed with transport errors from this
  workspace. Local CLI help output and the live `/api/info` response are used
  instead, and labeled as such. No API surface is invented.

## 1. What OpenRig treats as the stable seat, and what is replaceable

OpenRig's own vocabulary already separates the three things the map asks to
separate. These are the primary-source definitions, not a paraphrase.

**The seat is the stable thing.** "A stable role and address in a rig, such as
`dev-build@starter`. The conversation occupying it can change while its
identity and authored context remain"
([README.md:397](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/README.md#L397)).
The logical seat ID is `pod.member`; its session address is `pod-member@rig`
([topology-naming.md:17-18](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/topology-naming.md#L17-L18)).

**Runtime, model and account are configuration, not identity.** "Runtime,
model and account belong in configuration. Changing a provider does not change
the role's name"
([topology-naming.md:22-23](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/topology-naming.md#L22-L23)).
A label change is not a migration: "Changing a label does not rename a seat or
move its conversation, queue or work"
([topology-naming.md:70-72](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/topology-naming.md#L70-L72)).
This is direct support for the map's "authority migration ≠ live execution
rebinding" position.

**Occupant generations are ledgered separately from registrations.** Migration
`060_occupant_tenures` is an append-only ledger with one row per occupant
generation on a node. Its comment states the distinction precisely: "A
`sessions` row is a REGISTRATION, not a tenure — treating a row as a
generation mints PHANTOM generations"; `generation_uuid` "PERSISTS within a
tenure (a same-native relaunch is a continuation, not a new generation) but
CHANGES for a new occupant"; and "node_id is the identity that IS stable
across handover/swap/repair"
([060_occupant_tenures.ts:5-13](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/daemon/src/db/migrations/060_occupant_tenures.ts#L5-L13)).
It also states its own honest boundary: "node_id does NOT survive a `rig`
teardown-recreate of the node"
([same:15-17](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/daemon/src/db/migrations/060_occupant_tenures.ts#L15-L17)).

**Occupant replacement is a first-class, two-phase operation with named
sources.** `rig seat handover <seat>` takes `--source fresh | discovered:<id> |
fork:<seat> | rebuild`, supports `--dry-run`, and records reason and operator
([seat.ts:597-612](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/cli/src/commands/seat.ts#L597-L612)).
Its result reporting is unusually candid about partial success, and is worth
copying as a contract shape:

- A successor that started without a required startup file is reported as
  "complete, degraded", not success
  ([seat.ts:358-364](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/cli/src/commands/seat.ts#L358-L364)).
- If the lineage (tenure) record failed to write, the output says the seat is
  *already bound to the successor* and instructs the operator **not** to re-run
  ([seat.ts:376-378](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/cli/src/commands/seat.ts#L376-L378)).
- Context delivery outcome is distinguished three ways: delivered, *unconfirmed*
  ("may already be working on it" — do not resend), or not attempted
  ([seat.ts:397-415](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/cli/src/commands/seat.ts#L397-L415)).
- Handover observability has its own schema columns: `occupant_lifecycle`,
  `continuity_outcome`, `handover_result`, `previous_occupant`, `handover_at`
  ([021_seat_handover_observability.ts:6-10](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/daemon/src/db/migrations/021_seat_handover_observability.ts#L6-L10)).

**Execution observation is a third, separate axis.** The agent state taxonomy
declares three orthogonal axes (session / activity / resumability), says only
the activity axis is served today, and insists "`unknown` is a first-class
honest value — the oracle saying it cannot tell. Unknown beats a confident
wrong answer"
([agent-state-taxonomy.md:20-33](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/agent-state-taxonomy.md#L20-L33)).
It also refuses to collapse blocked-on-input into a status value: needs-input
rides as `{count, reason}`, never a state
([same:35-48](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/agent-state-taxonomy.md#L35-L48)).
And it is explicit that a clean flag is not proof: "A false attention flag
means no known trigger, not proof that an unobserved input box is clear"
([same:58-63](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/agent-state-taxonomy.md#L58-L63)).

### Correction to a prior finding

The handoff says prior findings described OpenRig as "Markdown recaps/learned/
proof **plus** SQLite queue (do not describe pure Markdown)". Confirmed, and
the division is explicit in source: "Live runtime state is SQLite-canonical;
markdown queue mirrors are read-only debug/export only"
([024_queue_items.ts:7-8](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/daemon/src/db/migrations/024_queue_items.ts#L7-L8)).
So OpenRig's **knowledge** layer is authored Markdown on a filesystem tree,
while its **work/task** layer is a database. A minimal configuration that
makes Markdown+Git authoritative for *tasks* is therefore deliberately
**not** an OpenRig reimplementation; it is a different authority choice, and
the consequences are listed in §4.

## 2. Minimum runtime to launch or resume an agent without Paseo

### What OpenRig itself requires (not the floor we need, but the comparison point)

Node.js 22 or 24, tmux, and macOS or Linux (WSL2 on Windows)
([README.md:486-492](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/README.md#L486-L492)),
plus one signed-in harness
([README.md:38-39](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/README.md#L38-L39)).
Architecturally it is "a local daemon + CLI + terminal UI + MCP server, built
on tmux" over "SQLite + tmux + runtime adapters"
([README.md:358-367](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/README.md#L358-L367),
[ARCHITECTURE.md:44-58](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/ARCHITECTURE.md#L44-L58)),
with `better-sqlite3` as a native dependency
([packages/daemon/package.json:106](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/daemon/package.json#L106)).
So OpenRig's floor is: a long-lived daemon, a database, a terminal
multiplexer, and a native module. That is the thing the scale-down default is
trying to avoid, and it is *why* the question is worth asking.

### CLI surfaces and portable dependency considerations

Observed on the host (read-only probes, no services started):

- `opencode` can run a single bounded task non-interactively:
  `opencode run [--session <id>] [--continue] [--fork] [--model provider/model]
  [--agent <name>] [--format json] <message>` (`opencode run --help`).
  **`--session <id>` creates the session if it does not exist**, which makes a
  stable, externally-chosen conversation address possible from the shell.
- Resume is exposed through CLI flags: `--session`/`--continue`. Primary's
  `opencode run --help` also shows a background service by default and
  `--standalone` for a private server. CLI access does not establish server-free
  execution or absence of an internal database dependency.
- Session transcripts have CLI enumeration/export/import surfaces:
  `opencode session list --format json`, `opencode session export [<id>]
  [--sanitize]`, `opencode session import <file> [--directory <dir>]`.
  `--sanitize` "redacts sensitive transcript and file data".
- There is **no scheduler, cron, timer, or watch verb anywhere in the
  OpenCode CLI surface** (`opencode --help` has no such subcommand; grep for
  cron/schedul/timer/watch over the top-level help returns nothing). Recurrence
  must come from outside the agent CLI.
A portable design cannot assume cron is installed. A *cron-compatible*
command — a single idempotent command,
safe to invoke repeatedly, that exits — runs under cron where cron exists and
under a foreground `while sleep` loop where it does not. Which of those
constraints the project accepts was research choice O8. The sibling kits repo already
contains a worked example of exactly that shape: a `flock(2)`-owned foreground
loop whose ownership key is `PASEO_AGENT_ID`, with documented exit codes for
"change found" (0), "nothing changed in the window" (3), "a loop is already
running and you own it" (4), and "another owner holds it" (5)
(`agentic-coding-kits@1097829e/personal/files/home/.agents/skills/paseo-first-mate/assets/first-mate-wait.sh`,
lines 1-24). It notes `flock` is from util-linux on Linux and needs
`brew install flock` on macOS — a real portability caveat for the minimal
configuration.

### Minimal runtime dependency set (candidate, for human decision)

| Need | Minimal binding | Notes |
| --- | --- | --- |
| Task + knowledge authority | Markdown files in Git | No database, no forge account, no network |
| Seat → occupant binding | A file mapping seat address → provider/model + current session id | Mirrors OpenRig's "runtime belongs in configuration" |
| Launch / resume an occupant | `opencode run --session <id>` (or the harness's equivalent) | CLI accepts a supplied ID; provider-qualified identity and valid-ID rules need qualification |
| Recurrence | One idempotent command; cron entry *where available*, else a foreground `sleep` loop | Must assume cron may be absent |
| Single-writer safety | Candidate lock/conditional-publication protocol | `flock` needs install on macOS; neither an index lock nor a plain file edit alone enforces task ownership |
| Transcript retention / export | `opencode session export --sanitize` | Separate from authored knowledge; see §5 |

The CLI and filesystem primitives exist here; the team binding does not.
No separate team database, tmux, or cron installation is inherently required
by this candidate. The model harness still has its own server and persistence
requirements, which must be counted separately.

## 3. Timer executing vs. agent reassessing

This distinction is the single most important one in the comparison, and both
products make it explicitly — in different places.

**OpenRig states it as doctrine.** A watch is "a queue task the operator owns,
set aside with a one-shot timer": the timer fires and wakes the operator; "the
operator does the judgment: what to check, and whether it's worth telling the
person"
([keeping-a-watch.md:14-24](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/keeping-a-watch.md#L14-L24)).
And it draws the line against reframing: "A refocus corrects drift; it is not a
wake (which restores liveness and must not reframe work) and not a checkpoint"
([refocus-channel.md:192-198](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/refocus-channel.md#L192-L198)).
The timer restores liveness; the agent decides meaning.

**Paseo implements the two as two different targets of one scheduler.** Both
`create_schedule` and `create_heartbeat` write the same `StoredSchedule`
record through `ScheduleService.createOrReplace`; they differ only in the
`target` field:

- `create_schedule` → `target: {type: "new-agent", config}` — the tick
  **executes**: it provisions a workspace, creates a fresh agent, runs the
  prompt, then (by default) archives the workspace
  (`schedule/service.js:750-834`, `archiveOnFinish ?? true` at
  `service.js:124-126`).
- `create_heartbeat` → `target: {type: "agent", agentId: callerAgentId}` — the
  tick **reassesses**: it sends the prompt into the *existing* conversation,
  wrapped so the receiving agent sees it as system-injected context
  (`formatSystemNotificationPrompt`, `<paseo-system>…</paseo-system>`), with
  `replaceRunning: true, activeTurnBehavior: "steer"`
  (`schedule/service.js:711-731`;
  `agent/agent-messages/index.js:157-164`).

Observed consequence worth stating plainly: a heartbeat is **agent-ID
targeted**, and the MCP tool refuses to create one outside an agent-scoped
session (`create_heartbeat requires an agent-scoped session`,
`agent/tools/paseo-tools.js:2033-2035`); the CLI equivalent reads
`PASEO_AGENT_ID` from the environment and refuses without it
(`cli/dist/commands/heartbeat/index.js:14-20`). Deleting one requires caller
ownership (`requireCallerHeartbeat`, `paseo-tools.js:604-613`). Confirms the
prior finding "heartbeats agent-ID-targeted".

A second asymmetry, for anyone building a team panel: `list_schedules`
**filters to `new-agent` targets only** (`paseo-tools.js:2082`), and so does
`paseo schedule ls` (`cli/dist/commands/schedule/ls.js:13`). Heartbeats are
therefore invisible to the schedule listing on both surfaces; only the owning
agent knows its own. A panel that enumerated schedules would silently omit
every reassessment timer in the system.

A surface asymmetry worth recording because it contradicts the shipped
guidance: the bundled `paseo` skill says "MCP intentionally exposes no
heartbeat update tool; delete and recreate when its task or cadence changes".
The MCP half is confirmed — there is no `update_heartbeat` tool anywhere in
`paseo-tools.js` — but the **CLI does expose one**: `paseo heartbeat update
<id> --cron <expr> [--timezone <iana>]`
(`cli/dist/commands/heartbeat/index.js:131-135`). Cadence can be changed
without delete-and-recreate from the CLI, just not from MCP. A portable
capability's absence on one surface does not establish its absence in the product.

A **minimal** configuration could expose both launch shapes through one command;
equivalent lifecycle, delivery and cleanup guarantees have not been established:

- executing tick → `opencode run --session <fresh-id> "<task>"`
- reassessing tick → `opencode run --session <seat's current occupant session id> "<nudge>"`

The nudge/reassess variant is the one that needs a contract, because it enters
a conversation that may be mid-turn. Paseo's answer is `steer`; a minimal
CLI help inspected here exposes no explicit steer flag. That does not establish
the runtime's complete delivery behavior; the binding must specify and qualify
its busy-recipient policy (see §8, open choice O3).

## 4. Observed outcomes for the named failure modes

All Paseo line numbers in this section are the **installed 0.12.0** compiled
files under
`~/.npm-global/lib/node_modules/@getpaseo/cli/node_modules/@getpaseo/server/dist/server/server/`.
`schedule/service.js`, `schedule/cron.js`, `schedule/store.js` and the
heartbeat/schedule MCP tool bodies are **byte-identical in 0.15.0** (verified
by md5 and by diffing the extracted tarball), so these schedule findings hold
at the kit pin as well. Where 0.15.0 differs, it is called out.

### 4.1 Overlapping ticks

| | Observed |
| --- | --- |
| Paseo | Tick cadence is 1000 ms (`service.js:12,200`), and the interval timer is `unref`'d (`service.js:201`). Two guards prevent overlap: an in-memory `runningScheduleIds` set skipped at tick time (`service.js:420`) and claimed before any store I/O (`service.js:536-537`), and `claimDueRun` atomically claims the due slot *and* advances the cursor inside one serialized store update (`service.js:592-630`). The comment names the race it closes: "A tick can hold a stale list while another tick finishes this schedule" (`service.js:606-607`). `ScheduleStore` serializes per-schedule-id and per-name+target-identity mutations through promise chains (`store.js:179-197`). `runOnce` refuses when already running (`service.js:407-409`). |
| Minimal | Nothing is given. A cron entry firing while the previous run is alive produces two writers unless the command itself refuses. The `flock`-based pattern in the kits repo is the worked precedent, including a distinct exit code for "you already hold the loop" vs. "someone else holds it" (`first-mate-wait.sh:12-17`). |

**The honest difference:** Paseo's guard is *in-memory* (`runningScheduleIds` is
a `Set` on the service instance). It protects against overlapping ticks of one
daemon, not against two daemons over one `$PASEO_HOME`. A minimal runtime using
`flock` on a filesystem lock is, on that one axis, protecting a *wider* scope.

### 4.2 Daemon / loop exit, and restart

| | Observed |
| --- | --- |
| Paseo | On `start()`, `recoverInterruptedRuns()` runs before the tick timer is armed (`service.js:190-203`). Any run still marked `running` is rewritten as **failed** with the literal reason "Daemon restarted before the scheduled run completed" (`service.js:470-475`), and if the target was a `new-agent` run with an archivable workspace, that workspace is archived (`service.js:456-469, 497-512`). `sweepOrphanedSchedules()` then **completes** any agent-target schedule whose agent is missing or archived, "so they stop ticking and surface as ended in the UI" (`service.js:514-533`). |
| Minimal | Nothing is given. A loop killed mid-run leaves no record that a run was in flight. `flock` releases on process death including SIGKILL, "so there is no pidfile to go stale" (`first-mate-wait.sh:21-23`) — that solves the lock but not the in-flight-work record. |
| OpenRig | Two different mechanisms, worth separating. Interrupted *runs*: next-due is recomputed from `last_evaluation_at` + cadence at startup, so the database alone determines the next fire (§4.3). Undelivered *wakes*: the retry ladder stores no counter — "the transitions ARE the ladder state. Attempts, rungs, suspension and exhaustion are all markers on the row's transition log, and every tick DERIVES its position from them — a daemon restart can neither forget a ladder (silent park returns) nor restart its counts (cap violated by repetition)" ([queue-wake-ladder.ts:28-31](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/daemon/src/domain/queue-wake-ladder.ts#L28-L31)), with configurable bounds defaulting to 300 s and a cap of 3 ([same:76-79](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/daemon/src/domain/queue-wake-ladder.ts#L76-L79)). |

### 4.3 Missed wakes

Scheduler bookkeeping in §4.2 is distinct from execution/effect reconciliation.
A failed schedule record, archive invocation or recomputed due time does not prove
prior work stopped or external effects settled. Those claims need separate
attempt-bound evidence; without it G6b is UNVERIFIED and dependent work must not
infer safe resumption.

| | Observed |
| --- | --- |
| Paseo | **Missed ticks are skipped, never replayed.** On restart, an overdue `nextRunAt` is advanced by an inline `while` loop until it is in the future (`service.js:482-491`); the same rule is factored as `advanceNextRunAtPast` for the non-restart paths (`service.js:34-40`). The same suppression applies after a long run: "Move an overdue cursor past a long run without advancing a future one twice" (`service.js:686-690`). At most one catch-up fire happens, because `claimDueRun` claims the single due slot and advances past `now` (`service.js:601-605`). |
| OpenRig (for contrast) | Also non-replaying, and says so for its reminder path: "recovery does not replay every elapsed cycle" ([keeping-a-watch.md:113-117](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/keeping-a-watch.md#L113-L117)). Its scheduler's next-due is derived from `last_evaluation_at` + cadence, so SQLite state alone determines next due after restart ([watchdog-scheduler.ts:17-19](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/daemon/src/domain/watchdog-scheduler.ts#L17-L19), [watchdog-due.ts:21-42](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/daemon/src/domain/watchdog-due.ts#L21-L42)). A periodic reminder with no evaluation yet measures its first interval from registration rather than firing on the first scan ([watchdog-due.ts:25-36](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/daemon/src/domain/watchdog-due.ts#L25-L36)). |
| Minimal | Whatever the chosen command does. Cron under a sleeping laptop simply does not fire; a foreground loop measures from its own last iteration, i.e. drift accumulates but nothing is replayed. |

Cadence expressiveness, since it bounds what a shared contract can promise:
Paseo's cron parser accepts **exactly five fields** — "Cron expressions must
have 5 fields"
(`@getpaseo/protocol/dist/schedule/cron-expression.js:77-78`) — with `*`,
lists, ranges and `/step`, and **no** seconds field, `@daily` macro, `L`, `W`
or `#`. Next-run search starts at the start of the next minute and scans
minute-by-minute up to 366 days (`cron.js:68-81`). Timezones go through
`Intl.DateTimeFormat` and are validated (`cron.js:5-11, 23`). The alternative
`every`/`everyMs` cadence is explicitly legacy: "COMPAT(scheduleEveryMs):
execute legacy persisted rolling intervals until the compatibility floor
reaches v0.2.0. Added in v0.2.0; remove after 2027-01-17" (`cron.js:61-64`).
A cron cadence does **not** fire on create; an `every` cadence does
(`runOnCreate ?? cadence.type === "every"`, `service.js:224-225`).

### 4.4 Busy recipients

| | Observed |
| --- | --- |
| Paseo heartbeat (reassess) | **Skipped, and the skip is recorded as a failed run.** The agent-target path throws `Agent ${agent.id} already has an active run` when `hasInFlightRun` is true (`service.js:725-727`); the throw is caught by `runSchedule` and written as a `failed` run (`service.js:575-586`). `hasInFlightRun` is true when lifecycle is `running`, or an active foreground turn exists, or a run is registered (`agent/agent-manager.js:458-466`). Confirms the prior finding "busy skipped", with the added detail that **it burns a `maxRuns` slot**: `countCompletedRuns` counts every run whose status is not `running` (`service.js:121-123`), and completion is evaluated against that count (`service.js:127-135`). |
| Paseo interactive send | Different policy from the scheduler: `send_agent_prompt` defaults to `steer` for agent callers and `interrupt` for top-level callers (`agent/tools/paseo-tools.js:1454`), and steering falls back to interruption when unavailable (`agent/agent-prompt.js:5-19`). So "send steers or interrupts" is confirmed — and the *scheduler's* heartbeat path uses `replaceRunning: true, activeTurnBehavior: "steer"` (`service.js:729-730`) but only after the `hasInFlightRun` refusal above, so in practice the steer applies to a non-busy agent. |
| Paseo 0.15.0 only | Adds a 2-second coalescing window for agent-to-agent delivery: messages to one recipient are batched and dispatched together, splitting only when send options conflict (`agent-messages/delivery.js:88-111, 65-87`). **This does not affect heartbeat wakes.** Its only callers are finish subscriptions, the `send_agent_prompt` tool, and the WebSocket session path (`finish-subscriptions/index.js:121`, `agent/tools/paseo-tools.js:1458`, `session.js:6335`); the scheduler's heartbeat path calls `startAgentRun` directly (`schedule/service.js:728-731`), and `schedule/service.js` is md5-identical across the two versions. So scheduler busy-recipient behavior is **unchanged** between 0.12.0 and 0.15.0; only interactive and notification sends coalesce. |
| OpenRig (for contrast) | "A message sent to a busy Codex seat joins its running turn and may redirect it" ([seat-delivery.md:30](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/seat-delivery.md#L30)); the opt-in `--wait-for-idle <seconds>` sends nothing if still busy at the deadline, exits 1, and "OpenRig keeps nothing to send later" ([seat-delivery.md:37-39](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/seat-delivery.md#L37-L39)). A six-mode typing guard governs which automatic messages may type at all ([seat-delivery.md:8-15](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/seat-delivery.md#L8-L15)). |
| Minimal | Nothing is given; the chosen binding must define and qualify skip, queue, refusal, or supported in-turn delivery. Inspected CLI help has no explicit steer flag. |

### 4.5 Occupant replacement

| | Observed |
| --- | --- |
| Paseo | There is **no seat abstraction**. The durable unit is an agent record keyed by UUID, persisted one JSON file per agent under `$PASEO_HOME/agents/<path-slug>/<agent-uuid>.json`, carrying `provider`, `cwd`, `workspaceId`, `labels`, `config`, `persistence` (`{provider, sessionId, nativeHandle, metadata}`, its own `PERSISTENCE_HANDLE_SCHEMA` at `agent-storage.js:27-35`) and `archivedAt` (`STORED_AGENT_SCHEMA`, `agent/agent-storage.js:36-69`). Resume means reopening *that* conversation from its persistence handle, or, absent a handle, starting its first session (`agent/agent-loading.js:48-83`). Replacing the occupant while keeping the role is not an operation Paseo offers; a new agent is a new identity. |
| Paseo 0.15.0 only | Adds opt-in startup resume: `prepareStartup` marks agents that were `running` as resume candidates, rewrites their status to `closed`, and `resumePending` later dispatches a configured prompt (default "Resume working.") to each — gated on `resumeOnStartup` (`agent/restart-recovery/index.js:1-54`, `bootstrap.js:712-722`). This is closer to "revive the same occupant" than to "replace the occupant". |
| OpenRig | Full replacement machinery: see §1 (`rig seat handover`, four sources, tenure ledger, degraded reporting). |
| Minimal | Replacement is a config edit plus a new session id, if the seat→occupant mapping is a file. That is the cheapest possible implementation of the stable-seat idea; it says nothing about in-flight work owned by the departing occupant, which files alone do not track. |

### 4.6 Uncertain notification delivery

| | Observed |
| --- | --- |
| Paseo 0.12.0 (installed) | Finish notifications are **in-process and non-durable**: arming state lives in a module-level `WeakMap` keyed by the `AgentManager` instance (`agent/agent-prompt.js:258-280`). A daemon restart loses every armed notification; nothing re-arms it. Notification suppression is checked at fire time: if the caller is archived, or (with `requireParentOwnership`) the child's parent label no longer points at the caller, the notification is dropped silently (`agent/agent-prompt.js:317-331`). Delivery errors are logged, not retried (`agent/agent-prompt.js:357-367`). |
| Paseo 0.15.0 (kit pin) | Behavior differs from 0.12.0 here: finish subscriptions are **durable**, stored as records in `$PASEO_HOME/finish-subscriptions.json` with atomic writes (`agent/finish-subscriptions/internal/json-store.js:12-47`), recovered on boot via `start()` (`finish-subscriptions/index.js:260-269`, wired at `bootstrap.js:1397`), with bounded retry/backoff (`index.js:51-55`) and a supersession/acknowledgement protocol. It also adds an explicitly *honest-uncertainty* terminal state: after three failed remote observations the subscription ends with reason `host unreachable`, and the message says "Status of child agent … is unknown … This finish subscription has ended. Reassess the delegated work; reconnecting will not resume notifications" (`finish-subscriptions/internal/notification.js:14-18`, `index.js:184-192`). |
| Event stream, both versions | `AgentManager.dispatch` fans out to in-memory subscribers with no cursor and no replay; `subscribe({replayState})` replays only *current* `agent_state` snapshots, never missed events (`agent/agent-manager.js:467-497`, and the `dispatch` filter body). Confirms the prior finding "events best effort / no replay". **But** the timeline is different and recoverable: it is cursor-addressed by `{epoch, seq}` and returns explicit `reset`, `staleCursor` and `gap` flags when a cursor cannot be honored (`agent/agent-timeline-store.js:54-87`), surfaced to clients in `fetch_agent_timeline_response` (`session.js:5900-5912`). So *state deltas* are lossy while *conversation history* is paginated and gap-flagged. |
| OpenRig | Says the same thing in doctrine for the human channel: "`posted` means the connector posted it, not that they read it. Don't say they saw it", and "If delivery fails or is indeterminate, inspect that task before anything else. Never resend blindly" ([keeping-a-watch.md:107-109](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/keeping-a-watch.md#L107-L109)). An occurrence that may have been received "ends unconfirmed and is not automatically sent again" ([keeping-a-watch.md:118-121](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/keeping-a-watch.md#L118-L121)). Also: a watch cannot be set at all if no human channel is registered — "a watch that can't reach them is a watch they'll never hear from" ([keeping-a-watch.md:26-30](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/keeping-a-watch.md#L26-L30)). |
| Minimal | Nothing is given. A file write is the only delivery, and "the recipient read it" is unknowable. The absence is at least visible, unlike a notification that fails silently. |

### 4.7 Correction: archive cascade is conditional

The prior finding "archive parent cascades" is true but incomplete. Archiving a
parent scans for children carrying the `paseo.parent-agent-id` label and
archives them — "so subagent fleets don't outlive their orchestrator" — but a
child is **detached instead of archived** when it is cross-workspace or has an
open agent tab (`agent/agent-manager.js:1136-1190`, predicate at
`agent-manager.js:269-274`). "Detached handoff agents omit this label, so they
stand outside the cascade" (`agent-manager.js:1138-1139`). Internal children
always archive with the parent because they never reach storage
(`agent-manager.js:1178-1190`). Archiving a workspace archives its agents and
terminals, and removes a Paseo-owned worktree only after the last active
reference goes (`workspace-archive-service.js:23-25, 26-68`). Archiving an
agent also **completes** any schedule targeting it (`service.js:366-387`).

### 4.8 Confirmed: profiles carry no system prompt

`AgentProfileSchema` is `{id, name, icon?, color?, provider, model?, modeId?,
thinkingOptionId?, featureValues?, notes?}` and the source states the reason:
"There is deliberately no system prompt here. `AgentSessionConfig.systemPrompt`
is creation-only, so a profile carrying one would apply when starting a new
agent and silently do nothing when applied to a running one"
(`@getpaseo/protocol/dist/agent-profile.js:2-27`). Profiles are read from
daemon config `agentProfiles` and surfaced read-only by `list_profiles`
(`agent/tools/paseo-tools.js:2301-2318`; config key
`daemon.agentProfiles`, `daemon-config-store.js:90,112`). **Design
consequence:** a profile is launch configuration only; the team's *role
instructions* cannot live in a Paseo profile and must live in the portable team
definition. Files are the portable candidate here; the absence of a profile
system-prompt field does not exclude creation prompts or other runtime channels.

A separate, non-portable channel exists in source: a
daemon-level append-to-system-prompt setting, stored as `daemon.appendSystemPrompt`
in `$PASEO_HOME/config.json`, is carried into the
agent manager at construction (`bootstrap.js:652`, with live updates at
`bootstrap.js:1230`) and merged into each agent's config as
`daemonAppendSystemPrompt` (`agent/agent-manager.js:3795-3802`; the setter is
`:411-413`). Anything that depends on it is a host setting, not part of the team
definition.

## 5. Ongoing memory: authored knowledge vs transcript retention

These are facts for the separate memory decision. No recommendation is made
about which model the team should adopt.

### 5.1 OpenRig: authored knowledge is addressed, scoped, and graded

**One filename at every altitude.** "One filename, identical at every altitude
of a tree. A reader orients by walking from where they stand toward the root,
reading the same-named file at each level"
([chain-file-convention.md:8-13](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/chain-file-convention.md#L8-L13)).
Two trees answer two questions: the **topology** tree (instance → rig → pod →
seat) carries "how work is done here" and ships defaults; the **project** tree
(project → mission → slice) carries "what is being built" and cannot ship
([same:19-24](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/chain-file-convention.md#L19-L24)).
Established names on the topology tree: `LEARNED.md` ("what a POSITION has
learned; never shared or shipped as-is" — identified by its *path*, so the same
seat name in two rigs is two different files), `CRAFT.md`, `CULTURE.md`
([same:48-57](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/chain-file-convention.md#L48-L57)).
Project tree names: `SPEC.md`, `PROOF.md`, `PROGRESS.md`, with `NOTES.md` and a
`README.md` fallback
([same:59-65](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/chain-file-convention.md#L59-L65)).
The scopes the map asks about (team / seat / task / occupant) map onto this as
rig / seat / mission-slice / — with the last one deliberately *absent*, because
position knowledge belongs to the seat, not the occupant.

**Trust is carried two ways, by surface.** Corpus files carry maturity **by
address** — "The filename law is the ladder: `NOTES.md` is field notes because
that is what the name says… Promotion or demotion is a **move**, and a move that
breaks references loudly is a feature"
([knowledge-maturity.md:81-89](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/knowledge-maturity.md#L81-L89)).
Packs, lore and scope items carry maturity as a **stage field from birth**, from
a closed vocabulary: `wip | provisional | established | canonical | superseded |
retired`, where "`superseded` must name its successor; `retired` means
do-not-use"
([same:91-104](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/knowledge-maturity.md#L91-L104)).

**Freshness, correction, supersession.** Rungs are defined by *expected rate of
change*: canon in years, insights in months, field notes in days-to-weeks, data
continuous
([knowledge-maturity.md:23-31](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/knowledge-maturity.md#L23-L31)).
"A canon diff should read as addition. Frequent edits to existing canon lines
are a smell"
([same:40-43](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/knowledge-maturity.md#L40-L43)).
Demotion is "legal but LOUD"
([same:50-53](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/knowledge-maturity.md#L50-L53)).
"A promoted claim carries its compressed warrant… Canon without warrants is
cargo cult with good formatting"
([same:55-61](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/knowledge-maturity.md#L55-L61)).
Staleness is a **cue, not a verdict**: a notes or `LEARNED.md` file older than
`OPENRIG_REFOCUS_NOTES_MAX_AGE_DAYS` (default 14) is named with its age and the
age's source (`updated:` frontmatter, else mtime) — "a cue for judgment, not a
staleness verdict"
([refocus-channel.md:165-168](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/refocus-channel.md#L165-L168)).

**Editing is not delivery.** The single most transferable rule for a demo:
"editing a file is not delivery to a running seat"
([chain-file-convention.md:119-124](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/chain-file-convention.md#L119-L124)),
and the delivery schedule is a separate mechanism: "The chain files are the
durable, altitude-addressed home of orientation content; the refocus channel is
its delivery schedule"
([refocus-channel.md:179-190](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/refocus-channel.md#L179-L190)).
The same doc warns that the default light trace shows only ~800 characters of
each `LEARNED.md`, so a practice appended to a long file may never reach seats
without `OPENRIG_REFOCUS_DEPTH=full`
([same:184-190](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/refocus-channel.md#L184-L190)).
Independently, in the state taxonomy: "Repairing the file in place doesn't clear
it either, because no route delivers guidance into a running conversation"
([agent-state-taxonomy.md:69-74](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/agent-state-taxonomy.md#L69-L74)).

**Retrieval is a walk, not a recollection.** `rig context trace --rig <rig>
[--pod <pod>] [--seat <seat>] --name <NAME>.md` prints each altitude root-first,
marks canonical vs legacy vs absent, and "needs no running daemon — orientation
is exactly when the daemon may be down"; "Your reads ARE the walk: a trace
assembled from memory is a recitation that reproduces the drift it was meant to
catch. Run it; do not recall it"
([chain-file-convention.md:90-101](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/chain-file-convention.md#L90-L101)).
This matters enormously for the minimal configuration: **the retrieval primitive
is a filesystem walk with no service dependency.**

**Selective preservation has a concrete implementation.** `rig context
recap-write --rig --seat --file` writes the outgoing occupant's authored recap
([context.ts:784-818](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/cli/src/commands/context.ts#L784-L818)).
The store is seat-homed "beside LEARNED… the recap is POSITION knowledge,
unshareable by construction — a library-homed recap would be position knowledge
on the portable shelf", with "superseded-chain versioning — the newest recap is
RECAP.md, predecessors stay byte-preserved under recap-superseded/"
([seat-recap-store.ts:1-13](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/daemon/src/domain/context-packs/seat-recap-store.ts#L1-L13)).
It has exactly **one hard gate and one advisory tier**:
*addressability* is hard-gated, because "an unaddressable recap
… would fail every handover profile downstream, silently late", while the
authoring contract validates **advisory only** on its checkable subset and the
unmechanizable halves "are NOT pretended at"
([same:14-22](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/daemon/src/domain/context-packs/seat-recap-store.ts#L14-L22)).
The two advisories it does emit: no decisions section ("conclusions alone are
the lossy handoff shape") and a nonstandard `UNVERIFIED:` marker
([context.ts:793-796](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/cli/src/commands/context.ts#L793-L796),
[seat-recap-store.ts:208-221](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/daemon/src/domain/context-packs/seat-recap-store.ts#L208-L221)).
And resolution refuses to guess: an unresolved seat ref fails with a labeled
reason, because "fuzzy-matching another seat's directory would hand a successor
a DIFFERENT occupant's decisions, which is strictly worse than honest absence"
([same:223-243](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/daemon/src/domain/context-packs/seat-recap-store.ts#L223-L243)).

**Position knowledge has its own address convention.** Lore items live at
`<topology-root>/rigs/<rig>/seats/<seat>/lore/<stable-slug>.md`; the filename
"never contains a stage, date, occupant generation, or version", so the address
is stable and "a stage change edits frontmatter and `date`; it never renames the
file"
([lore-routing.md:13-33](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/lore-routing.md#L13-L33)).
Required fields from birth: `taxonomy: lore` (the machine-readable privacy
class), `stage`, `method` ("how the owning position could know the claim"),
`date`, `position` ("It names the position, never an occupant")
([same:35-48](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/lore-routing.md#L35-L48)).
It writes "as the durable position, not as a particular occupant or
predecessor"
([same:21-23](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/lore-routing.md#L21-L23)).

**The inheritance ritual the demonstration needs already exists as a
convention.** The mission install's five layers are PIECES, ARRANGEMENT,
POSITION, CONTRACT, DERIVE-YOUR-OWN-DELTA
([mission-install.md:36-62](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/mission-install.md#L36-L62)),
and three of its rules bear directly on "verify consequential inherited
claims":

- ARRANGEMENT is "the one layer whose content is not on disk anywhere else: an
  authored recap by someone who held the work, stating what joins the pieces,
  what to trust, and what supersedes what", and it "is never skipped (it is
  what tells the reader whom to trust)"
  ([mission-install.md:43-47, 72-74](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/mission-install.md#L43-L47)).
- CONTRACT is the fastest-moving layer, so "every contract piece must carry its
  own `updated-at`, and any fact not re-derived at compose time carries an
  explicit `UNVERIFIED` marker. A stale plan misleads more than a missing one"
  ([same:52-56](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/mission-install.md#L52-L56)).
- DERIVE-YOUR-OWN-DELTA assigns volatile facts to be re-derived by the
  installee, "each stated as the command that derives it (never as a remembered
  value)", producing a dated delta as the successor's first artifact — "This is
  the layer that turns a briefing into an instrument check"
  ([same:57-62](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/mission-install.md#L57-L62)).
- Delivery is **paced and reactive**: "One piece per message, paced… a
  concatenated dump of the same bytes is a failed delivery regardless of
  content", and "A silent walk is unverified delivery"
  ([same:76-90](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/mission-install.md#L76-L90)).
- The reader who cannot ask is the design premise: "A freshly started or freshly
  cleared agent cannot pull context — it does not know what exists, so it cannot
  ask… the install is composed on the agent's behalf and pushed"
  ([same:21-25](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/mission-install.md#L21-L25)).

### 5.2 Paseo: transcript retention, not authored knowledge

| Dimension | Observed in Paseo |
| --- | --- |
| Durable agent record | One JSON file per agent under `$PASEO_HOME/agents/<slug>/<uuid>.json`; fields listed in §4.5. Carries title, labels, cwd, provider, persistence handle, attention flags. No knowledge content. |
| Conversation history | **Owned by the provider, not Paseo.** On load, Paseo hydrates the timeline *from* the provider: `hydrateTimelineFromProvider` streams `session.streamHistory()` and rebuilds (`agent/agent-manager.js:2240-2243, 2903-2958`), and "The replay is the timeline, so drop the rows a previous hydration committed" (`agent-manager.js:2987-2989`). Live timeline state is an **in-memory** store (`InMemoryAgentTimelineStore`, `agent/agent-timeline-store.js:7-9`; constructed unconditionally at `agent-manager.js:298`). A durable timeline store is an *optional injected* dependency (`durableTimelineStore`, `agent-manager.js:319`) and **nothing in either 0.12.0 or 0.15.0 passes one in** — `new AgentManager({...})` in `bootstrap.js` supplies no such option (0.12.0 `bootstrap.js:647-659`; 0.15.0 `bootstrap.js:689-702`). So Paseo's retained history is, in practice, the provider's own store. |
| Retention controls | None observed: no TTL, no compaction policy, no per-scope retention setting in the schedule/agent/timeline modules read here. Timeline content is bounded per item (`limitAgentStreamEventContent`) and paged at a 200-row default (`agent-timeline-store.js:3`), but that is display bounding, not retention. |
| Retrieval | Within one agent: cursor-paged timeline fetch with `reset`/`gap` flags (§4.6), and a Markdown-aware in-timeline text search that is deliberately approximate and says so: "Discovery is deliberately approximate. Only the client can verify displayed text… a match the client cannot highlight… still inflates the total" (`agent/chat-search/index.js:6-11`). Across agents: search matches **names only, never transcript bodies** — "Search the names people recall, never an incomplete subset of transcripts", over workspace name, agent title, branch and project name (`agent-history-search.js:1-10`). |
| Skills | Paseo ships and reconciles its own skill set into `~/.agents/skills`, `~/.claude/skills`, `~/.codex/skills` (`orchestration-skills/internal/paths.js:13-20`), selected by a config `skills.selection` of `{mode:"all"}` or `{mode:"custom", skills:[…]}` (`@getpaseo/protocol/dist/agent-profile.js:28-31`). Skills are *installed files*, i.e. the knowledge channel is already a filesystem one — which is why the same team skills can serve both configurations. |
| Agent-to-agent messages | Wrapped in a versioned, escaped envelope `<paseo-system version="1" kind="agent-message"` or `kind="agent-notification"`, plus `source-agent-id`, `message-id` and (for notifications) `event`) and projected into the receiving timeline as a tool-call-shaped item rather than a user turn (`agent/agent-messages/index.js:52-60, 127-156`). Schedule fires use the older unversioned `<paseo-system>` form (`same:157-168`). This is the mechanism by which "a timer woke me" is distinguishable from "a human asked me" — directly relevant to §3. |

### 5.3 Facts that bear on the memory decision (no recommendation)

1. **Authored knowledge and transcript retention are different artifacts with
   different owners.** OpenRig's authored layer is addressed, graded, and
   human-curated; Paseo's retained layer is provider-owned conversation history
   that Paseo re-derives on load. A team definition that treats "memory" as one
   thing will bind to one of these and silently lose the other.
2. **The authored layer is directly portable; transcript compatibility is
   provider-specific and must be qualified.** Provider history lives in the
   provider's store (for OpenCode on this host, `~/.local/share/opencode/`),
   is reachable through `opencode session export [--sanitize]`, and is
   per-provider. Authored Markdown is reachable by any configuration with a
   filesystem.
3. **Both products refuse to equate "written" with "received".** §5.1 ("editing
   a file is not delivery"), §4.6 ("`posted` means the connector posted it").
   Any shared contract has to carry a delivery state distinct from a storage
   state.
4. **"Unverified" is a vocabulary item in OpenRig, not a mood.** It is a
   canonical marker (`UNVERIFIED:`) whose nonstandard spellings are flagged
   (§5.1). A shared memory format could adopt it as-is.
5. **Address stability is what makes supersession cheap.** Lore filenames
   exclude stage/date/version precisely so citations survive a stage change
   (§5.1). The same property is what lets Git history carry correction without
   a database.
6. **Scope is not maturity and not audience.** "Audience decides where
   knowledge lives… maturity grades the line inside it. A pod-level item can be
   raw observation, a seat-level one can be canon"
   ([knowledge-maturity.md:106-113](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/knowledge-maturity.md#L106-L113)).
   Three axes, independently chosen.
7. **OpenRig's own maturity doc is honest that none of this is enforced.**
   "Nothing in this document is mechanized: no enforcement tooling, no mass
   relabeling, and no new tier scheme"
   ([knowledge-maturity.md:120-125](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/knowledge-maturity.md#L120-L125)).
   The convention is carried by agent discipline plus a `trace` command, not by
   a validator. Adopting it costs almost no machinery; relying on it to be
   enforced would be a mistake.

## 6. Observed vs proposed guarantees

"Observed" means read in pinned source or probed read-only on this host, and
in the **Minimal** column it can only mean a property of the primitives
probed here (filesystem, `git`, `opencode run`) — **never** a property of the
§7 sketch, which does not exist and was not run. "Proposed" means a guarantee
a shared contract *could* make, which no inspected implementation currently
makes. Proposed rows are design input, not findings. Source-read rows and
host-probed rows are distinguished in §9 rather than in the cell.

| # | Guarantee | Minimal (Markdown+Git+CLI) | Paseo 0.12.0 observed | Paseo 0.15.0 observed | OpenRig observed |
| --- | --- | --- | --- | --- | --- |
| G1 | A seat address outlives its occupant | **Proposed** (a config file could do it; nothing enforces it) | **Not offered** — agent UUID *is* the identity | Not offered | **Observed** — seat ref + tenure ledger + `handover` |
| G2 | Occupant replacement is a recorded, reviewable event | **Proposed** | Not offered (archive + create are separate) | Not offered | **Observed** — `handover_result`, `previous_occupant`, `handover_at`, tenure rows |
| G3 | One tick never overlaps itself | **Proposed** (`flock` precedent exists in kits) | **Observed**, per-daemon in-memory + serialized store claim | Same | **Observed**, single in-flight tick, sequential jobs |
| G4 | Missed wakes are skipped, not replayed | **Proposed** (follows from a stateless command) | **Observed**, cursor advanced past `now` | Same | **Observed**, "recovery does not replay every elapsed cycle" |
| G5 | A wake into a busy occupant has a defined outcome | **Proposed** — must be chosen | **Observed**: refused + recorded `failed`; consumes a `maxRuns` slot | Unchanged for scheduler wakes (same `schedule/service.js`); 2s coalescing applies only to interactive/notification sends | **Observed**: joins the turn by default; `--wait-for-idle` discards |
| G6a | Scheduler bookkeeping recovers on restart | **Proposed** — pending-purpose recovery needs qualification | **Observed in source**: run marked `failed` and workspace archive invoked | Same; opt-in agent resume is separate | **Observed in source**: next-due recomputed from `last_evaluation_at` + cadence; interrupted-run bookkeeping not inspected |
| G6b | Prior execution stopped and external effects reconciled before dependent work resumes | **UNVERIFIED** — no live qualification | **UNVERIFIED** — failed scheduler record/archive invocation does not prove stop or effect settlement | **UNVERIFIED** — resume capability does not establish stop or effect settlement | **UNVERIFIED** — due-time recomputation/wake history does not establish execution/effect reconciliation |
| G7 | Notification delivery survives a restart | **Not offered** | **Not offered** — in-process `WeakMap`; lost on restart | **Observed** — durable JSON store, recovered at boot, bounded retry | **Observed** for the queue wake ladder (retry interval 300 s and cap 3 by default, ladder position derived from the row's transition log; see §4.2) |
| G8 | Undeliverable/uncertain notification is reported as unknown, not as success | **Proposed** | Partially: errors logged, not surfaced to the caller | **Observed** — terminal `host unreachable` with "status … is unknown" | **Observed** — "ends unconfirmed and is not automatically sent again" |
| G9 | Event stream can be replayed after a gap | **Not applicable** (files are the state) | **Not offered** — no cursor, no replay | Same | Not inspected for the SSE stream |
| G10 | Conversation history is addressable and gaps are flagged | Partially — `opencode session export` exists and is whole-session, not cursored (probed via `--help`) | **Observed** — `{epoch, seq}` cursor with `reset`/`staleCursor`/`gap` | Same | Not inspected |
| G11 | Authored knowledge has a stable address independent of its trust level | **Proposed**, and cheap (filenames + frontmatter) | **Not offered** — no authored-knowledge layer | Same | **Observed** — chain files by address; lore filenames exclude stage/date |
| G12 | Trust/maturity is explicit and machine-readable | **Proposed** | Not offered | Same | **Observed** for stage-bearing items; address-carried for corpus files; **unenforced by tooling** |
| G13 | Writing knowledge ≠ delivering it to a running occupant | **Proposed** — must be stated | Implicit: nothing delivers files into a live turn | Same | **Observed and stated** — "editing a file is not delivery" |
| G14 | Retrieval works with no service running | **Observed of the primitives** — reading files needs nothing running | **Not offered** — needs the daemon | Same | **Observed** for `rig context trace` specifically |
| G15 | Occupant's decisions survive its replacement, with supersession | **Proposed** | Not offered | Not offered | **Observed** — `RECAP.md` + byte-preserved `recap-superseded/` |
| G16 | Role instructions are part of the portable team definition | **Proposed** — trivially satisfiable, since instructions would be files, but nothing was built | **Observed by exclusion** — profiles deliberately carry no system prompt | Same | **Observed** — AgentSpec/guidance files |
| G17 | A richer UI consumes authoritative state rather than owning it | **Not applicable** | Mixed — the web UI reads daemon projections, but the daemon *is* the authority for agents | Same | **Observed as doctrine** — "One oracle computes it; surfaces render it", with two named exceptions still deriving their own |
| G18 | Cadence vocabulary is portable across bindings | **Proposed** | **Observed** — 5-field cron, no seconds/macros/`L`/`W`/`#`; `every` is legacy-until-2027-01-17 | Same | Interval-seconds + scan-interval, not cron |
| G19 | Recurrence works where no cron daemon exists | **Proposed** — a foreground loop avoids requiring cron | **Observed** — daemon-internal timer, no cron needed | Same | **Observed** — daemon-internal scheduler |
| G20 | Single-writer guarantee spans multiple processes on one state dir | **Proposed** (`flock` would) | **Not offered** — in-memory set is per-daemon | Same | Not inspected |

Two rows run opposite to the direction the rest of the table runs, which is
worth noticing before weighing them:

- **G14 needs only filesystem reads; G19 still needs a running loop or external
  scheduler.** Neither implies a completed team runtime. OpenRig independently
  arrived at G14 for its own trace command, with
  the reason stated: "orientation is exactly when the daemon may be down".
  What that is worth against everything in the Paseo columns is the map's
  judgment, not a finding.
- **G7 is version-sensitive.** Finish notifications survive a restart in
  0.15.0 and not in the 0.12.0 running here. See open choice O9.

## 7. Minimal configuration candidate

Offered as a candidate for human decision, not a recommendation. It is shaped
to satisfy the guarantees marked Observed-or-cheap above and to refuse the
rest explicitly.

```
team/
  TEAM.md              # team purpose + coordination norms (OpenRig's CULTURE.md role)
  seats/
    <seat>/
      ROLE.md          # what this seat does; portable, read by any runtime
      OCCUPANT.md      # provider/model + current session id + tenure log (append-only)
      LEARNED.md       # position knowledge, graded by address (OpenRig convention)
      RECAP.md         # outgoing occupant's authored decisions-with-rationale
      recap-superseded/# byte-preserved predecessors
  tasks/
    <id>.md            # one task per file; frontmatter state + assignee + blockers
  NOTES.md             # team-level field notes
  bin/
    tick               # ONE idempotent command; exits; safe to re-invoke
```

Properties, each tied to a finding above:

1. **Task authority is Markdown+Git.** No database, no forge account, no
   network. This deliberately diverges from OpenRig, whose live work state is
   SQLite-canonical with Markdown as read-only mirror (§1 correction). The
   divergence is the point of the scale-down, and §8/O1 names its cost.
2. **Seat is the stable address; occupant is a file field.** `OCCUPANT.md`
   holds provider/model plus the harness session id, and appends a tenure line
   per replacement. This is the cheapest implementation of G1/G2, and it mirrors
   OpenRig's stated rule that runtime and model are configuration.
3. **Launch and resume are one CLI call.** `opencode run --session <id>` with
   the id read from `OCCUPANT.md`. Replacement = write a new id and append a
   tenure line, subject to a replacement protocol. OpenCode still uses a shared
   or private server; no separate team daemon is established as necessary.
4. **`bin/tick` is the only recurrence surface.** It is cron-compatible *and*
   loop-compatible, because it exits. Overlap protection and the busy-occupant
   outcome are the two things this shape does not get for free (G3/G20, G5);
   this sketch assumes `flock`, which is itself the subject of open choice O8.
5. **Timer vs reassessment is encoded in the tick's own branches**, not in two
   mechanisms: an *executing* branch starts a fresh session for a due task; a
   *reassessing* branch nudges a seat's existing session. Both are `tick`
   invocations.
6. **Memory is authored files only.** Transcript retention stays with the
   provider and is exported deliberately (`opencode session export --sanitize`)
   when a specific transcript must be preserved. Nothing attempts to make
   transcripts authoritative.
7. **Retrieval is a walk.** `grep`/`cat` over the tree, same-filename-at-every-
   altitude. No index to rebuild, no daemon to reach (G14).

Known gaps the candidate does **not** close, stated so nobody assumes they are
handled: durable notification (G7/G8 — there is no notification channel at all),
event replay (G9), cross-host coordination, and any guarantee that a written
file reached a running occupant (G13, which no inspected configuration offers either).

### The same team under Paseo

What source inspection says about running the same team under Paseo, and one
shape constraint it imposes:

- **Role content stays in the files.** Paseo profiles carry no system prompt by
  design (§4.8), and Paseo's skill channel is already filesystem-based
  (`~/.agents/skills`, §5.2). So `ROLE.md` and the team skills are read the same
  way in both configurations.
- **Paseo supplies the richer bindings, not a different authority**: workspaces
  (local or worktree, incl. `checkout-pr`), profiles as launch bundles,
  agent-to-agent messaging with a versioned envelope, cron scheduling with
  `new-agent` and `agent` targets, finish notifications, and plugin UI surfaces.
- **The plugin surface is sufficient for a read-mostly team panel.** A plugin
  can contribute a workspace- or agent-scoped panel (`addWorkspacePanel`,
  `PluginWorkspacePanelProps`/`PluginAgentPanelProps`), screens, sidebar items,
  Command Center items, slash commands, composer pills, timeline
  transformers/renderers, and themes
  (`@getpaseo/plugin/dist/client/contracts.d.ts:65-130`). Server-side it can
  observe lifecycle events (`agent.turn_started`, `agent.turn_ended`,
  `agent.permission_requested/resolved`, `agent.created/closed/archived`,
  `workspace.created/archived`) and *transform* three requests before they run
  (`agent.create`, `agent.session_open`, `workspace.create`)
  (`@getpaseo/plugin/dist/server/lifecycle.d.ts:44-94`). It reaches Paseo
  through the same `PaseoApi` the rest of the product uses — `terminals`,
  `workspaces`, `projects`, `agents`, `providers`, `config`
  (`@getpaseo/client/dist/index.d.ts:392-401`).
- **Capability declaration is where the two configurations diverge.** The
  skills cannot assume steering, durable notification, or cron, because at
  least one inspected configuration lacks each. If the contract takes the
  declared-capability route, these are the names the inspected gaps would
  require: `steer_running_turn`, `durable_finish_notification`,
  `cron_schedule`, `worktree_isolation`, `agent_to_agent_message`,
  `ui_panel`, `seat_handover`, `event_replay`. Whether to declare capabilities
  at all, and at what granularity, is not settled here.

## 8. Key unresolved human choices

**Historical questions, superseded by accepted decisions:** see the
[binding contract](../issues/03-team-and-binding-contract.md),
[memory contract](../issues/06-team-memory.md), and
[demonstration definition](../issues/05-demonstration-design.md).
The questions below explain the research; they do not reopen those decisions.

These are decisions, not findings. Each carries the evidence that makes it a
real fork. None is resolved here.

**O1 — Settled direction: Markdown+Git owns default task state.**
OpenRig's answer is explicit and the opposite of the scale-down default: "Live
runtime state is SQLite-canonical; markdown queue mirrors are read-only
debug/export only"
([024_queue_items.ts:7-8](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/packages/daemon/src/db/migrations/024_queue_items.ts#L7-L8)).
The user already chose Markdown/Git authority for the default binding. It needs
a publication/recovery protocol; atomic multi-field transitions and retained
transition history are possible with one committed tree and conditional ref
publication, as the coordination report explains. Indexed-query convenience
differs. This evidence does not reopen the authority choice or imply that Paseo
should maintain a competing writable task store.

**O2 — What is the cadence vocabulary of the shared contract?**
Paseo accepts 5-field cron only (no seconds, no `@daily`, no `L`/`W`/`#`) and
treats `every`/`everyMs` as legacy with a removal date of 2027-01-17
(`cron.js:61-64`, `cron-expression.js:77-78`). OpenRig uses interval-seconds
plus a separate scan interval. A portable team definition must pick one and
accept lossy translation, or declare cadence a binding-local concern.

**O3 — What happens when a wake lands on a busy occupant?**
Three inspected answers already disagree: Paseo's scheduler refuses and records
a failed run that consumes a `maxRuns` slot (§4.4); Paseo's interactive send
steers or interrupts (§4.4); OpenRig joins the running turn by default and
discards with `--wait-for-idle` (§4.4). The minimal CLI's in-turn delivery is
unqualified. The inspected implementations disagree, so a shared contract cannot
inherit one silently; what to do about that — declare it as a capability with a
fallback, standardize one behavior, or leave it binding-local — is the open
choice.

**O4 — Does a failed/skipped tick count against a run budget?**
Observed in Paseo: yes. `countCompletedRuns` counts every non-`running` run
(`service.js:121-123`) and completion is evaluated against it
(`service.js:127-135`), so a schedule with `maxRuns: 5` that is busy five times
ends having accomplished nothing. Whether the portable contract inherits that
is a human call.

**O5 — Is the occupant's conversation part of the team's memory, or outside
it?** Paseo re-derives timelines from the provider and ships no durable
timeline store (§5.2). OpenRig keeps authored artifacts and treats transcripts
as the `data` rung, the fastest-changing and least trusted
([knowledge-maturity.md:23-31](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/knowledge-maturity.md#L23-L31)).
If transcripts are inside team memory, the contract needs retention,
redaction (`--sanitize`) and export policy; if outside, the contract needs a
rule for what must be authored *before* an occupant is replaced.

**O6 — Who may promote knowledge, and is promotion mechanized?**
OpenRig's ladder is deliberately unmechanized (§5.3 item 7). Adopting it as a
convention is nearly free; adding a validator is a new maintenance surface.
Also unresolved: whether `stage: superseded` must name its successor
(OpenRig requires it for stage-bearing items) in this project's format.

**O7 — Settled direction: the panel consumes authoritative team operations.**
The map's position ("UI consumes authoritative state/operations, not own
lifecycle authority") is matched by OpenRig doctrine — "One oracle computes it;
surfaces render it", with two named exceptions that still derive their own
([agent-state-taxonomy.md:3-9](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/agent-state-taxonomy.md#L3-L9)).
Paseo can remain authoritative for its agents and execution observations while
the selected team binding owns task assignment and seat-to-occupant mapping.
Those are different facts, not duplicate task authorities. The missing interface
must define how team intent is bound to observed runtime results, including
uncertainty. The user already requires the panel to consume those operations.

**O8 — Minimum acceptable dependency set.** `flock` is absent from stock macOS
(the kits script says `brew install flock`), and cron cannot be assumed in a
minimal environment. Which of {cron, flock, tmux, sqlite3} may the minimal configuration
require? The answer changes what G3/G19/G20 can promise.

**O9 — Which Paseo version is the floor?** Durable finish subscriptions, startup
resume, and message coalescing exist in 0.15.0 and not in the 0.12.0 running
here (§4.6, §4.5, §4.4). The kit pins 0.15.0; the live host is 0.12.0.
Which of the two a demonstration binds to is therefore a choice, not a detail
to inherit from whatever happens to be installed.

**O10 — What does "verify consequential inherited claims" mean operationally?**
OpenRig already provides a shape: a derive list stating each volatile fact *as
the command that derives it*, producing a dated delta as the successor's first
artifact
([mission-install.md:57-62](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/mission-install.md#L57-L62)).
Whether this project adopts that form, and what counts as "consequential", are
human decisions.

## 9. Verification status and limitations

**What was verified.** Every OpenRig citation was read in a checkout at
`bd39da9872afc39cbe0c8e839a322b4cb8955cbe`, and each cited path was
additionally confirmed to return HTTP 200 at that exact SHA on
raw.githubusercontent.com (22 distinct paths checked, all 200). Every Paseo behavioral
claim was read in compiled JS: the live 0.12.0 install, and the 0.15.0 npm
tarball (hash recorded in §Source pins). Schedule, cron, store and the
heartbeat/schedule MCP tool bodies were confirmed **byte-identical** between
0.12.0 and 0.15.0 by md5 and by diff, so those findings are pin-independent;
every 0.12-vs-0.15 difference reported here came from an actual diff, not an
assumption. Patterns' kit pin was read from `origin/main` after fetching, not
from the stale local checkout. Every line range cited in this file was
mechanically re-checked twice: first by a script that re-read each cited span
and asserted a distinctive phrase from the claim appears inside it, then by an
researcher-reported adversarial review that re-opened a sample across every section.
Primary did not inspect that transcript; this is unverified review history,
not established independent approval.
Five ranges were wrong across those passes and were corrected, not quietly
dropped (`agent-state-taxonomy.md`, `chain-file-convention.md`,
`keeping-a-watch.md`'s evidence note, one `schedule/service.js` span where the
restart path uses an inline loop rather than the factored helper, and
`agent-storage.js`, whose persistence sub-schema sits outside the record
schema's span). The reported review also found one substantive error, now
fixed: an earlier draft claimed 0.15.0's message coalescing would merge
heartbeat wakes. It does not — the scheduler bypasses that queue entirely, so
scheduler busy-recipient behavior is identical across the two versions.

**Publication-safe probe summary.** CLI help and bounded runtime inspection
informed the research. Installation-specific inventory and runtime relationships
are retained privately, not published as design evidence. No
service was started, stopped, or reconfigured; no agent, schedule, heartbeat,
workspace, or demonstration was created; no candidate code was executed.

**Source-based process identity.** Paseo's v2 runtime keeps **one shared helper server** and
leases it to sessions, spawning a dedicated one only when a session needs
distinct env (`agent/providers/opencode/v2/runtime.js:21-33, 100-130`, leases at
`:67-89`). So a helper PID identifies a *generation of a shared server*, not a
worker. Conversation and process identifiers are distinct facts; a binding
must not substitute one for the other.

**Known limitations.**

1. **Almost no live behavior was confirmed.** Nearly every "observed" row in
   §6 is observed *in source*; the exceptions are host probes (binary
   availability, CLI flag surfaces, `/api/info`, `session list`, config and
   file shapes), which are observations of the running host but still not of
   the behavior being graded. Overlap guards, restart reconciliation,
   missed-wake suppression and busy-skip were read, not run. A future bounded
   demonstration should re-derive them live rather than cite this file.
2. **0.15.0 was read as a tarball, not run.** The durable finish-subscription
   behavior (G7/G8) is a code reading of an uninstalled version.
3. **OpenCode V2 API documentation is inaccessible** from this workspace
   (transport error on `https://opencode.ai/v2/docs/api` and
   `https://opencode.ai/docs/`). CLI help text and `/api/info` were used
   instead. Any claim about the V2 HTTP API beyond `/api/info` would be
   invention and none is made.
4. **No OpenRig database was inspected**;
   all OpenRig storage claims come from migration source and docs.
5. **The OpenRig docs read here carry their own staleness markers.** `rig-spec.md`
   says "Last validated against code: 2026-10-07, at the 0.6.6 cut"
   ([rig-spec.md:4](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/rig-spec.md#L4)),
   `ARCHITECTURE.md` says "This map is not the territory… it may be stale.
   Where it disagrees with the code, the code is right"
   ([ARCHITECTURE.md:3-7](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/ARCHITECTURE.md#L3-L7)),
   and `keeping-a-watch.md` states its own evidence level: the flow "was
   exercised with the CLI on an isolated private daemon", but "A native run
   with a real operator, install and channel has **not** been run yet"
   ([keeping-a-watch.md:8-12](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/keeping-a-watch.md#L8-L12)).
   Doc-sourced rows in §6 inherit that caveat; source-file rows do not.
6. **RigSpec `continuity_policy` is validated but inert.** "These fields are
   validated, stored on the pod and written back on export. In this version
   nothing acts on `sync_triggers`, `artifacts` or `restore_protocol`"
   ([rig-spec.md:1259-1261](https://github.com/mvschwarz/openrig/blob/bd39da9872afc39cbe0c8e839a322b4cb8955cbe/docs/reference/rig-spec.md#L1259-L1261)).
   Any design borrowing that vocabulary is borrowing a declaration, not a
   behavior.
7. **Historical worker handoff:** the researcher did not resolve human decisions
   or edit the primary tracker. The publication copy has since been integrated;
   current decisions and ownership are recorded in the linked map/tickets.
