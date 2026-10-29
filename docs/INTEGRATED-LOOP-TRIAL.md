# Integrated live loop trial — 2026-10-29

AI-assisted qualification checkpoint. This is not full automated-maintainer
completion or an activated unattended service.

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
