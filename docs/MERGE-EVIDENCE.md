# Supplied PR merge evidence probe — not an attestor

`scripts/merge-evidence.py` is an **offline, read-only** classifier for a
bounded PR snapshot supplied on stdin. It exists to make the delivery-vs-
compliance distinction from `VERIFIED-OUTCOMES.md` executable against synthetic
counterexamples before building a GitHub reader or changing the cohort
numerator. Run only with an operator-provided sanitized snapshot:

```bash
python3 -I -B scripts/merge-evidence.py \
  --repository owner/repo --number 7 --head <full-40-hex> < private-snapshot.json
```

The input schema (`schema_version: 1`) has exactly `repository` (`owner/name`),
`number`, `state` (`OPEN`/`CLOSED`), `head_sha`, `merged_at` (UTC timestamp or
null), and `merge_commit_sha` (full SHA or null). A reported
`MERGE_CLAIM_IN_SUPPLIED_SNAPSHOT` means only that this *unproven input* is
internally shaped like a merged PR at the expected head. Squash/rebase merge
commit SHA may differ from the PR head. Missing/conflicting identity, a
head mismatch, or contradictory merge
evidence, including an open PR with a non-null merge commit SHA or a future
merge timestamp, returns `UNVERIFIED` (exit 3); a consistently shaped open/closed PR is
reported as `NOT_MERGED_IN_SUPPLIED_SNAPSHOT` or
`CLOSED_NOT_MERGED_IN_SUPPLIED_SNAPSHOT`. The probe does not read GitHub, bind a
ledger case, inspect checks/reviews/rulesets, or claim delivery credit. It
prints no repository name, case ID, PR text, or raw input.

**No completion metric may consume this output as a verified outcome.** The
next separately reviewed step must establish trusted repository/PR identity,
time and merge commit from read-only source calls, case-to-PR binding,
versioned evidence, and a private receipt path for security assessments.
Historical compliance proxies, branch protection at event time, and complete
30-day follow-up remain separate axes. The existing cohort reader retains
`verified_completion_ids: []` until those evidence paths are implemented.
