# Human-approved delivery batches

Run `python3 -I -B scripts/delivery-batch.py /private/batch.json` for a bounded,
read-only GitHub snapshot of an explicit batch. No model, mutation, branch change,
approval or merge is performed. Use an installed trusted copy; candidate script
tests run in isolation. The caller's gh authentication is used for reads only.

```json
{
  "schema_version": 1,
  "repo": "owner/repository",
  "default_branch": "main",
  "prs": [
    {"number": 10, "head": "<40-hex inspected head>", "depends_on": [], "review_evidence": ["private QA/security report reference"]},
    {"number": 11, "head": "<40-hex inspected head>", "depends_on": [10], "review_evidence": []}
  ]
}
```

Every dependency must be explicitly listed. The tool rejects cycles and returns
a stable topological order, but does not infer semantic independence from file
paths. Unchanged heads and observed all-success check rollups yield
GREEN_OBSERVED, not READY_TO_MERGE. Missing/skipped checks, changed heads and
unavailable observations remain UNVERIFIED or an explicit attention state.
Each PR is read twice; a differing snapshot is refused. This is still a sequential
as-of observation, not an atomic GitHub-wide snapshot or ongoing monitor.

Operator-supplied review references are reported as UNVERIFIED_REFERENCES_ONLY;
the tool does not authenticate them, judge fixes, interpret native branch rules,
or substitute check summaries for QA/security review. Human approval and live
required-check/CODEOWNER/dependency acceptance remain separate requirements.

The report preserves the fetched `reviewDecision` and validates the PR URL
against its owning repository and number. Observed CHANGES_REQUESTED yields
review attention even when all checks pass; the next action is owner fixes and
fresh re-review. Other primary blockers (changed head, draft, dependency or
non-default base) retain priority but do not hide that review attention. A
GitHub APPROVED summary still supplies no merge authority or proof that all
required independent reviews apply to the current head. Missing/malformed
review fields or mismatched URLs are unavailable evidence, not clean reviews.

## Branch deletion and dependency safety

Independent PRs should target the repository default branch and can merge in
either order after their own gates pass. The report flags any non-default PR
base. This avoids relying on an upstream feature branch that auto-pruning may
delete. It does not retarget, rebase or force-push anything.

For dependent work, wait for the predecessor to merge, refresh main, then prepare
the successor from that integration point. Its PR must include only its intended
change. Record explicit merge order in the batch. The report checks predecessor
merge state and merge-commit evidence; that alone cannot prove the successor
contains or tested the predecessor's changes. Such a successor remains
INTEGRATION_REVIEW_REQUIRED even if its observed checks are green. Re-run integration checks and
independent review for material rebases/new heads. Closed-unmerged or unobserved
predecessors never satisfy a dependency.

Limits: one explicit repository, at most20 PRs, two reads per PR, a120-second
shared fetch budget and2MB per response. The manifest is bounded to100KB.
Exit0 means all listed PRs are merged-observed or green-observed; exit3 means
attention/unavailable evidence. It is never a merge-authorization exit code.
Use the report to reduce operator search effort, not to bypass native policy.
