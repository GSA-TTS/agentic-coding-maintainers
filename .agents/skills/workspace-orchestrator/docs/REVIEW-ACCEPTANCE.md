# Accepting collected structured reviews

`run.sh review-accept TASK --request REQUEST` bridges retained observations into
the existing claim/finding/correction protocol. Use the trusted installed
controller; test candidate copies only in isolation. There is no model-supplied
task mutation or identity authority.

```json
{
  "schema_version": 1,
  "operation_id": "accept-attempt-1",
  "expected_revision": 8,
  "action": "accept-collected",
  "payload": {"admission_id": "<64-character retained admission digest>"}
}
```

The controller revalidates all retained packet, assignment, collection and
operation bindings, then reads `final_text` from the retained receipt. The exact
final response must be one bounded JSON object with these fields:

```json
{
  "schema_version": 1,
  "coverage": {"correctness": "reviewed", "acceptance": "unverified"},
  "findings": [],
  "dispositions": [],
  "limitations": ["No tests executed by reviewer"]
}
```

Coverage must name **every and only** the assigned obligations. The abbreviated
example is not sufficient for a normal five-obligation assignment. Findings and
dispositions follow REVIEW-PROTOCOL.md. Zero findings and unverified coverage
are legitimate. Markdown fences, duplicate/unknown fields, missing coverage,
invented identity fields and malformed JSON are refused without changing state.
Rejected output remains collected for diagnosis. No prose-to-JSON model retry
or silent normalization changes the evidence being accepted.

Invoke `review-run` with one `--obligation ID` per assignment obligation to
request this strict response format. The controller inserts generation, run,
packet, policy, profile and session identity from its admission. The runner
prompt is a request, not a guarantee that a model returns conforming JSON.

Claim, protocol operation receipt and collection-to-claim link are persisted in
one atomic task write under the coordinator lock. Exact retries return the
original claim receipt without duplicate findings. Changed operation reuse,
unlinked existing claims, lost artifacts, substituted final responses, stale
generations, changed owners and cancelled tasks cannot create a new acceptance.
Accepted links are revalidated against collection chronology and report content
on retry. The artifact-aware `review-evidence` CLI also validates retained links
before assessment or owner-correction projection; pure in-memory assessment
does not access artifact storage and is not sufficient to establish retention.

Existing legacy manual claims remain legacy claims. They are not retroactively
linked to observations. A first acceptance adds `collected_review_acceptances`
without migrating unrelated task records. Every acceptance consumes the existing
protocol operation/report budgets and task byte bound.

`CLAIM_ACCEPTED` is deliberately unchanged: the evidence remains internally
consistent worker-supplied observations. Neither structured coverage nor a clean
review confers execution authenticity, test execution, candidate readiness,
approval or delivery. The existing readiness refusal remains in force. Findings
can now flow directly into the bounded original-owner correction projection,
with retained history and normal rework admission required before any edits.
