# Manual rule-impact protocol

This is a required review protocol, not an implemented comparison engine or
source-fetching pipeline. Do not report that this skill ran Vale, classified a
corpus, reduced false positives, preserved true positives, or certified a rule.

## Fixed inputs and reproducibility

Before proposing a rule change, identify baseline and candidate revisions. Freeze
the exact engine executable/version and bytes (including the real Vale binary),
configuration bytes, style dependencies, rule bytes, and a corpus manifest with
each fixture's stable identity, content digest, document type, applicability
population, and classification provenance. Record both configs when intentionally
different. Preserve the same corpus bytes before and after. Record sandbox/image
identity, command arguments, environment and relevant locale/encoding settings,
exit codes, complete machine-readable outputs, output digests and parsing contract.
Freeze the complete authority-bundle bytes and SHA-256, its schema version,
selected claim IDs and explicit as-of cutoff alongside both runs. Bind each
fixture's document period and applicability decision to its source/claim IDs,
including the operative-period boundary interpretation and reviewer rationale.
Distinguish source period, document period and metadata review cutoff. Historical
assessment must use an explicitly selected historical view/cutoff, not an implicit
mode or automatically followed supersession link; do not forge earlier retrieval
or review times to make a modern artifact pass a historical cutoff.
An inaccessible input, missing dependency, partial/truncated output, unexpected
exit or invalid engine output means invalid/unverified evidence, never pass.

Run both sides in an independently justified isolated environment. For Vale,
document the supported CLI's output and exit semantics: a finding exit must not
be confused with invocation failure. Require full reproducible **real Vale**
assertions for the affected rules: expected matches, nonmatches, scope, severity,
and relevant exceptions. Parser mocks and invented synthetic outputs are useful
tests of plumbing, not substitutes for actual engine execution.

## Finding identities and dispositions

Declare a stable finding identity, for example corpus fixture ID, rule/check ID,
span coordinates, and matched text. Keep severity as an explicit compared
attribute so changing severity cannot conceal a finding. Compare **multisets**,
not sets or raw totals: preserve duplicate occurrence counts. Explain coordinate
normalization and matching rules up front; do not hide unmatched findings with
fuzzy matching. Record unchanged, added, removed and severity-changed occurrences
with identities and before/after values, including multiplicity.

Classify each changed occurrence with a disposition, reason, and supporting
bundle claim/source IDs. Require scoped true-positive preservation: known
applicable obligations still match at the intended severity, except where the
owner and authority evidence explicitly approve a changed disposition. Inspect
added findings for new false positives, removed findings for lost true positives,
and severity changes for changed enforcement. Report out-of-scope effects too;
do not bury them in aggregate improvement numbers.

## Corpus evidence and acceptance

Use an appropriately scoped, **classified corpus** with independent/manual
classification provenance and explicit authority applicability/exceptions. Avoid
private material in source control. Label synthetic fixtures separately; they
demonstrate declared cases only and support no real-world false-positive rate or
coverage inference. Unclassified documents cannot establish true/false positives.
Report denominators, sampling limitations, ambiguous cases and unreviewed scope.

An acceptance packet must include fixed bytes/manifests, both full real runs,
reproduction commands, classified finding multisets, every changed disposition
and its source claims, scoped true-positive preservation assertions, and owner
review. Missing or inaccessible evidence is unverified; failed assertions block
acceptance. Bundle exit 0 and model approval cannot replace any of these gates.
Any rule edit requires separately admitted implementation scope and review.
