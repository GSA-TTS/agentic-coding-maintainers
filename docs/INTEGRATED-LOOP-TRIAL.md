# Integrated live loop trial — 2026-10-29

AI-assisted qualification checkpoint. This is not full automated-maintainer
completion or an activated unattended service.

**Update:** the clean hardened repeat described below supersedes this document's
earlier open qualification gates. The earlier trial and its limitations remain
historical evidence, not erased failures.

## Clean hardened repeat and independent audit

The operator authorized renewed independent QA and three new bounded model
calls. Independent QA reviewed `a36b9addd1b91d4c7ee7328f3da2c38e7b5d8738`
and confirmed the final same-head replay correction resolved the outstanding
finding. The complete repeat ran that revision with the Docker controller from
the outset, using persistent task-local storage, and MSB read-only model workers.
There was no controller relocation or proposal rewriting.

The real reviewer identified `double-increments-instead-of-doubling`. The operator
explicitly confirmed that finding matched the seeded arithmetic invariant before
the driver continued. The original-owner model proposed only:

```python
def double(x):
    return 2 * x
```

The rendered bundle, applied bytes and fixture commit matched that proposal.
The original test file was unchanged. The independent fixed oracle observed
`[4, -1, 1, 12]` before and `[6, -4, 0, 22]` after, each with exit zero and empty
stderr. Repair commit `dc7075994980395d43e41a4303238b1a5cb8d5f7` directly followed
`92c4cdcd770ef8df0478aacba8ac39cb19ff4da7`. A fresh reviewer resolved the retained
finding against the new head with all five obligations covered and no new findings.

| Phase | Distinct session | Input tokens | Output tokens |
|---|---|---:|---:|
| Review | `ses_qualification_cbf7a3180e684304814fd98f39053986` | 2,574 | 501 |
| Owner proposal | `ses_qualification_2420fea3a2494130980ba7271cbad26d` | 3,837 | 114 |
| Re-review | `ses_qualification_7a21ffe16c754c80a5a2434b581c2e1b` | 3,117 | 297 |

Before teardown, the controller validated retained proposal/review artifacts,
compared model content with rendered/applied bytes and Git history, and repeated
the final phase with unchanged complete file inventory. It exported its entire
qualification root, including hidden task state/artifacts and `.git`, plus a
SHA-256 manifest. All 100 manifest entries matched after transfer. An independent
evidence reviewer repeated the hash verification and inspected the three model
bundles, finding adjudication, oracle results, repair commit and final state.
The audit found no blocking contradiction in this bounded live-loop evidence.

**Qualified limitations:** controller timestamps and model timestamps disagree
(controller October 26, models October 29). Cross-runtime wall-clock ordering is
unverified; revisions, hashes, session identities and Git parentage are consistent.
The export retains the final inventory and the controller's replay-audit result,
not paired pre/post inventories independently rerun by the evidence reviewer.
Runtime isolation and the pinned installation remain operator-established
provenance, not independent hardware/process attestation.

The result is **LIVE_LOOP_OBSERVED for a controlled ordinary-code fixture**.
Candidate readiness, execution credit and delivery credit remain false. The
driver still requires operator provisioning, transfers and semantic finding
adjudication; it is not an unattended maintainer service. Multipass hosted this
machine's Docker controller only and is not a dependency of the skill.

The final full Docker suite and hosted Repository checks passed at `a36b9ad`.
This report-only update requires normal CI and review, but changes no code used
in the repeat. The bounded integration gate is met; general runtime rollout,
broader acceptance cases, durable PR monitoring, remote effects and polyrepo
delivery remain subsequent work.

## Actual three-model sequence

Using OpenCode2.0.32 and the authorized USAi route, three distinct sessions ran:

1. Reviewer read `calc.py` and its tests, identified the arithmetic defect and
   supplied a supported finding `double-increments-instead`.
2. Original-owner proposal returned exactly:
   `def double(x):\n    return 2 * x\n` for `calc.py`.
3. Fresh reviewer read the repaired source, retained finding and oracle evidence,
   supplied a resolving disposition and complete assigned coverage.

No assistant editing of the model's replacement contents occurred. The controller
rendered exact UTF-8 contents to the bounded bundle, applied it, verified the
fixed oracle and committed the fixture at
`83b41ddd0932e97d0eb35f8a209e6d6ca9757075`. The original finding remains retained.
The independently fixed oracle over inputs `(3,-2,0,11)` observed
`[4,-1,1,12]` before and `[6,-4,0,22]` after. Final captured outcome was
LIVE_LOOP_OBSERVED, CLAIMS_COMPLETE and no unresolved findings. Candidate
readiness, execution credit and delivery credit remained false.

## Backend relocation qualification

The controller originally ran in a network-off MSB guest. Application refused
because MSB reported differing device IDs for a regular file and its parent.
The same behavior was measured in guest scratch. The guard was preserved.

The operator explicitly authorized moving this disposable fixture to a
network-off Docker controller hosted inside the existing Ubuntu Multipass VM.
Its checkpoint was restored at the same guest paths. Original source/proposal
bytes, correction identity and evidence bindings were preserved, and collection
replayed instead of fabricating a new owner response. The two matching devices
allowed application to proceed. The fresh reviewer remained in MSB.

This was an operator-directed **test backend relocation**, not production crash
recovery. Original session-owner metadata was preserved for fixture accounting;
it does not attest a migrated worker process. Multipass is a local test host,
not a skill dependency. The supported property is a controller filesystem meeting
the repair contract; other suitable isolated Linux environments can provide it.

Source, API credentials and authority were separated: provider-only read-only
model guests had no controller-state or GitHub credential. The controller had
no network. The reused pinned Node image was
`sha256:8a34c4ab3ea2c5cd194f07e317b2a8f09461d3c8b05c4e34c8ccd56d56024c4d`;
the Docker controller used the VM's existing digest-pinned development image.

## Review hardening and checkpoint

The live sequence preceded subsequent fixed-revision QA/security hardening.
Reviews at `9cad7a59434083e1f4b4297810e13c8291a4f697` found proposal retention,
session-separation, chronology, unbounded context reads and driver evidence/retry
gaps. Repairs were reviewed at `8d06d58626617d91d6d46774b4f0b925d47cdbb1` and
`2ad1a5204daabc164c1e54cbfefb082f6d693644`.

The final security re-review cleared its findings. QA's final residual was a
cached qualification surviving a new finding at the same head. The local final
fix recomputes current review coverage/findings and checks the completed
generation and eligible state, with a regression test. That final correction
has **not received independent re-review**. Three substantive review cycles were
reached; the candidate is checkpointed rather than declared ready.

The hardened driver now requires explicit operator finding adjudication; the
earlier live run predates that input. Its retained finding text concretely
matches the seeded invariant, but the run is not claimed to validate the final
adjudication/recovery interface. No fourth model call was made or authorized.

## Evidence scope

The final driver has five deterministic tests covering exact request retention,
unmeasured baseline refusal, explicit finding adjudication, commit-resume and
same-head changed-review refusal. Proposal tests include inherited repair cases;
reported suite totals are not all new tests. Full initial Docker checks passed;
final full checks must be recorded separately from the pre-hardening live trial.

The next gate is independent confirmation of the final QA correction and a clean
single-backend controller replay of the hardened qualification procedure when
authorized. Durable PR monitoring, remote effects, legitimate integration,
backlog planning and polyrepo delivery remain subsequent plan stages. No new
service, App, merge policy or controller promotion was activated.
