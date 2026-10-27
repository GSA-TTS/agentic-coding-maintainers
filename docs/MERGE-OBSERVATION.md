# Bound, read-only GitHub merge observation

`scripts/observe-merge.py` takes a **caller-supplied, private mapping**
from an opaque case ID to `owner/repo`, PR number and full expected head SHA.
The tool also requires a private, validated cohort ledger. It checks for one
recorded implementation/documentation intake whose **effective eligibility**
is eligible at observation time (either initially or through a validated
correction), and
exactly one matching `pr_association` event with `provenance: agent_recorded`;
it rejects a contradictory recorded outcome head. These checks do **not**
authenticate who confirmed the case-to-PR association. A signature can be an
**optional** stronger provenance layer later, not a prerequisite for
automating implementation and reviews. The association remains unverified as
a maintainer decision and never grants cohort delivery credit.
It performs at most two public `api.github.com` **GET** calls: one for that PR, and a
commit lookup when GitHub says it merged. It checks that GitHub's PR identity,
`gh --jq` projects only the allowlisted identity/merge fields before returning
to this tool; the projected stdout and diagnostics are each bounded to 8 KiB.
Presence flags distinguish an explicitly null merge field on an open PR from a
field omitted by a degraded GitHub response; omitted fields are UNVERIFIED.
Large PR bodies are discarded by the projection and never entered into the
report. A host-side `gh` process still receives GitHub's full API response;
its resource use is limited by the subprocess deadline, not the projected
output cap. It checks that GitHub's PR identity,
base repository and head agree with the mapping; merged PRs require a valid
closed state, merge time and corroborated merge commit. A response claiming
`merged: true` while still `state: open` is contradictory and UNVERIFIED.
Squash and rebase commits may differ
from the PR head. Missing/contradictory evidence is `UNVERIFIED` (exit 3).

```json
{"schema_version":1,"case_id":"opaque-case-id","repository":"owner/repo","number":7,"head_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
```

Keep that file in a current-user-owned `0700` directory, mode `0600`, outside
the repository. Run:

```bash
python3 -I -B scripts/observe-merge.py \
  --mapping /absolute/private/mapping.json \
  --ledger /absolute/private/cases.jsonl \
  --key-file /absolute/private/report.key --case-id opaque-case-id
```

The key is the same private 32–128-byte cohort report key used by
`cohort-reflection.py`; no key is created or printed by this command. The
result includes a **keyed HMAC of the exact ledger bytes** and the UTC
observation time, so a later changed ledger cannot masquerade as the same
snapshot. Neither is a signature on the agent's association or proof a human
approved it. The output has no raw case ID, repository, title, branch or PR body. A positive
`MERGE_OBSERVED_IN_GITHUB` is a **fresh read-only observation**, not an
as-of-merge record, historical policy-compliance verdict, authorization to
merge, or completed case in the cohort report. `cohort_delivery_credit` is
always false; `policy_compliance` is always UNMEASURED. This tool does not
modify the event ledger or `verified_completion_ids`. The association between
the recorded case and PR is still caller-supplied. Future work must establish
an authenticated, timestamped mapping and private case pseudonym and
policy revision before affecting a throughput numerator.
