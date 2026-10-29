# Maintainer implementation trial checkpoint

AI-assisted work; incomplete and not ready for publication or activation.

## Implemented code

Canonical `review-packet` captures bounded committed source, full changed-file
inventory, explicit comparison semantics and initial mandatory obligations.
Canonical `review-evidence` retains assigned review claims, finding dispositions
and idempotent operation receipts in authoritative task JSON. Prospective and
persisted records are revalidated; material head-change epochs prevent revival
of old generations. Protocol tasks cannot use legacy readiness claims.

These interfaces do not dispatch agents, authenticate source-access receipts,
apply repairs, authorize GitHub effects or implement the durable service.

## Measured validation

Executed through the workspace Docker harness, with digest-pinned Node 22,
read-only candidate mount and non-root tests in ephemeral guest scratch:

```text
make -C /work/candidate check
review-packet-test.py: Ran 10 tests ... OK
review-evidence-test.py: Ran 13 tests ... OK
import-sync tests: PASS
OpenCode runtime probes: SKIP (set OPENCODE_V1 and OPENCODE_V2)
operating surface: PASS (4 measured checks, 6 profiles)
python syntax: PASS (30 files)
json syntax: PASS (12 files)
shellcheck: PASS
repository checks: PASS
```

This full pass preceded the last receipt-chronology regression fix. After that
fix, MSB 0.7.11 ran the latest source with network off, restricted security,
UID 1000, read-only `/candidate`, two CPUs, 2 GiB RAM and nproc=128:

```text
python3 -I -B /candidate/.agents/skills/workspace-orchestrator/tests/review-packet-test.py
Ran 10 tests ... OK
python3 -I -B /candidate/.agents/skills/workspace-orchestrator/tests/review-evidence-test.py
Ran 14 tests ... OK
```

Latest static Ruff (E4/E7/E9/F/I), Pyright and Bandit checks passed. The Docker
test environment used Python 3.11 and Debian ShellCheck 0.9.0, not the complete
pinned hosted-CI toolchain. Full strict/core CI and signed contribution commit
remain UNVERIFIED. No tests were removed or weakened to obtain a pass.

Initial failed validation runs are retained as outcomes: missing rsync, missing
jq, and executable fixture failure under noexec `/tmp`. Disposable dependency
installation and `TMPDIR=/work/tmp` resolved those environment prerequisites.

## Independent review and repair

Native independent static review used separate clean, fixed Git snapshots:

| Snapshot | Findings and disposition |
|---|---|
| `225515772f074fe4c6bb2de92a5f4dd8a743f67b` | Persisted validation, head-return invalidation and relative diff defects; repaired with regression tests |
| `7f2d76fe927c5af923306b02afd8ef137ae36766` | Dangling receipt/evidence consistency and empty-base admission; repaired with regression tests |
| `d5a359b6734cda709aa81517de34c685b0fc2b97` | Prior concrete defects resolved statically; remaining acceptance/receipt chronology gap repaired locally |

The final chronology change has not received independent re-review. Three
substantive review cycles reached the bounded checkpoint; escalation and renewed
admission are required before further implementation/review cycles. These are
synthetic sandbox review commits, not signed contributions in upstream history.
Native subagent slot accounting does not establish separate OS-process identity.

## Actual OpenCode/MSB trial

Copied the existing Ubuntu VM OpenCode 2.0.32 binary; source and destination
SHA-256 matched:
`4199ae2d2c96ad2a140d32cabe6a1d9280b4cd1d9d8ed533a5431f54c422693c`.

Used a task-local configuration, read-only candidate source, no GitHub
credential, MSB-protected USAi binding, bounded read-only reviewer, 12 steps and
five-minute command timeout. Native v2 agent/provider fields loaded successfully
after an initial legacy-config `Agent not found` failure. The model route was
`usai/gpt-6-astra`.

Both the first provider attempt and the corrected gateway-DNS retry ended with:

```text
{"type":"provider.transport","message":"getaddrinfo ENOTFOUND api.gsa.usai.gov"}
```

No source-read event, completed review, model usage measurement or repair result
was produced. The first attempt omitted the explicit DNS grant; adding the
documented `allow@dns` rule did not resolve the failure. No alternate provider,
proxy probe or TLS bypass was attempted. This was a direct MSB qualification
trial, not a completed acq adapter invocation.

## Authority and outcomes

Activated only the operator-authorized tracker creation and disposable testing/
pilot actions. No service, App installation, ruleset change, eligibility check,
approval, merge or unattended delivery authority was activated. Existing native
CODEOWNER enforcement remains in place.

Protocol correctness has positive and adversarial test evidence. Semantic review
quality, accepted real-agent repair, live review publication, integration,
polyrepo delivery, cost improvement and follow-up maturity remain UNMEASURED.
The worktree is preserved for continuation; the initiative is not complete.
