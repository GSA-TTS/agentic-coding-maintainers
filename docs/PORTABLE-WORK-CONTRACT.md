# Portable work contract v1 — inert document validation

This is the bounded #199 / #191 seam described in the
[portable roadmap](PORTABLE-WORK-ROADMAP.md) and
[capacity proposal](CAPACITY-CONTRACT.md). It introduces a new, closed
`portable-work-bundle` document with integer `version: 1`; it does **not** change
any existing task format, coordinator, skill, manifest, or runtime consumer.

**A valid bundle establishes internal consistency only.** It establishes no
truth, freshness, source authority, reviewer independence, accepted evidence,
accepted completion, permission, capacity admission, or actual effect. All IDs,
revisions, provenance and support dependencies are caller declarations. Even an
`exact` tag cannot prove that a caller supplied an immutable revision rather than
a mutable label. No external reference is resolved or trusted by this validator.

## API and bounds

[`scripts/portable-work-contract.py`](../scripts/portable-work-contract.py) exposes:

* `decode_bundle(data: bytes)` returns the decoded, validated bundle.
* `validate_bundle(value)` returns `None` on internal consistency and leaves the
  caller's value unchanged.
* Both refuse with `ContractError`, a `ValueError` subclass whose message is a
  fixed code, not untrusted document text. Codes are `TYPE`, `JSON`, `LIMIT`,
  `INTEGER`, `SHAPE`, `IDENTITY`, `VERSION`, `DUPLICATE_KEY`, `DUPLICATE_ID`,
  `REFERENCE`, `REVISION`, `DEPENDENCY`, `APPLICABILITY`, `CROSS_RUN`, `BINDING`,
  `UNIT`, and `OPERATION_CONFLICT`. They are not coordinator exit codes or a
  classification of authority. The first refusal is reported, not an error list.

The module has no CLI, filesystem/state/network/environment discovery, subprocess,
dynamic loading, import-time application I/O, or non-standard-library dependency.
It imports only `json` and `re`. Loading Python code still requires the caller's
normal trusted import mechanism; the module does not load schema or fixture files.
Text resembling commands remains inert data. No test or executable payload is
embedded in the workflow description.

Limits: 262,144 UTF-8 bytes (raw decode input and compact direct-value encoding),
16 levels from root depth zero, 16,384 visited values including object keys,
128 entries per collection, 4,096 Unicode characters per string, and integers
0–9,007,199,254,740,991. IDs are 1–256 ASCII characters starting with an
alphanumeric and otherwise using alphanumerics or `._:/@+-`. They are opaque,
case-sensitive, uninterpreted namespace-local identities, not titles, paths to
open, URLs to fetch, or commands. Revisions use `{ "kind": "exact", "value": ID }`;
references use `{ "id": ID, "revision": REVISION }`. No normalization occurs.

Decode rejects malformed UTF-8, a BOM, duplicate object keys (including escaped
equivalents), floats/exponents, non-finite numbers, negative integer spellings
(including `-0`), booleans, nulls, lone surrogates, excessive nesting and trailing
data. Direct validation accepts only exact built-in dict/list/str/int values,
not subclasses or coercible objects; cyclic containers fail bounded traversal.
Depth is checked before recursive JSON parsing. Whitespace counts toward raw
input size; direct values have no original spelling or duplicate-key history.

The [JSON Schema](portable-work-contract-v1.schema.json) is a closed **shape**
contract. Python additionally enforces encoding/global limits, exact Python
integer types, unique IDs, references and applicability. JSON Schema's abstract
integer semantics alone cannot reject a `1.0` token or recover duplicate keys;
schema-only validation is not equivalent to this API. No schema engine is needed
at runtime.

## Objects and ownership

The root requires `work`, `workflow`, `runs`, `attempts`, `artifacts`, `evidence`,
and `target`, with optional `effects`. Every nested object is closed. Collections
with IDs reject duplicates within their own namespace; distinct namespaces may
use the same opaque token. One bundle describes one work and one workflow.
An artifact ID names one immutable artifact instance in this slice; a newly
produced revision uses a new artifact instance ID so the old record remains
addressable. A multi-revision artifact registry is not introduced here.

| Object | Meaning and checks |
| --- | --- |
| `work` | Stable ID, exact definition revision, outcome, source `authority` reference, exact input references, prose constraints, acceptance IDs/descriptions and profile. At least one input and acceptance criterion are required. |
| `workflow` | Stable ID, exact definition revision and a bounded list of step IDs/descriptions. This is not a graph, interpreter, dispatch plan or general workflow language. |
| `runs` | Work ID and historical work/workflow revisions, exact input/configuration references and numeric duration/model-call/currency-micros budget. At least one run. Historical inputs need not still be in the current work's input set. |
| `attempts` | Run, logical operation and step IDs, optional parent attempt, optional coordinator lineage and capacity request. At least one attempt; parents must exist, share the operation and be acyclic. |
| `artifacts` | Opaque ID/revision, `patch`, `report` or `verification` kind, producing attempt and nonempty input provenance. Provenance must match the producer run's exact inputs. Artifact bytes are not stored, opened or hashed. |
| `evidence` | Producer attempt, exact verification artifact and subject artifact references, acceptance ID, depended-on inputs/configurations and workflow revision. Its producer must produce the verification artifact; both artifacts must belong to the same run. Inputs/configurations/workflow must match that run. Dependencies must include the declared provenance of both artifacts. Empty evidence is allowed. |
| `target` | Explicit subject revision, current declared input/configuration dependencies, workflow revision and a list of evidence IDs claiming support. Inputs equal the work's current input references; workflow equals the declared definition revision. Empty support is valid and claims nothing. |
| `effects` | Optional typed `export-artifact` or `publish-artifact` descriptions: operation ID, attempt, exact same-run artifact, target ID, authority reference, exact target precondition and `unobserved`, `unknown` or `reported` observation. No general payload, shell command, permission or success flag. |

The `coding` profile alone requires an opaque repository identity and exact source
reference matching a work input. It adds no branch/title identity or forge access.
The `documents` profile requires only its kind and rejects coding fields. Neither
profile selects tools, models, credentials or an execution environment.

Source authority is **separate** from optional coordinator lineage. No portable
field writes or overrides native task facts. Existing coordinator/#66 ownership,
W0–W7 migration gates and consumer qualification remain controlling.

## Historical evidence and selective support

Evidence records describe their original producer run, not the external world.
Historical revisions can differ from the work/target's currently declared
revisions without invalidating retained history. A record used in `target.support`
must additionally satisfy:

1. Its exact subject reference equals `target.subject`.
2. Its workflow revision equals the target workflow revision.
3. Every input and configuration dependency it names exists at the same exact
   revision in the corresponding target dependency set.

Changing a depended-on input, configuration, workflow or target subject therefore
refuses the **support claim**. Removing that claim from `target.support` preserves
the historical evidence unchanged and allows internal validation. Changing an
unrelated input/configuration does not invalidate support. There is no implicit
"latest", wall-clock freshness, source lookup or blanket invalidation by run ID.

This checks declared dependency coverage, not whether the author omitted a real
dependency or lied about provenance. It does not require every acceptance ID to
have support, decide acceptance, or certify the referenced verification's content.
An input removed from the target still survives in a historical run; a support
claim depending on it refuses. Historical workflow **definitions** are not a
second registry here: attempt step IDs must remain in the one declared workflow.
Arbitrary removed-step/acceptance histories need a future explicit versioned
consumer design, not relaxed references or silent legacy downgrade.

## Logical operations and optional coordinator mapping

Logical operation IDs are bundle-wide, across runs, attempts and typed effects.
Repeating the same operation with the same declared content is inert retained
description, not a retry authorization. Changing a run/attempt ID does not reset
the operation. Attempt identity includes work/workflow revisions, input and config
maps (reference order is immaterial), budget, step, request and coordinator mapping;
capacity's run/attempt labels are excluded. Changed content under an existing
operation ID refuses, including collision between an attempt and effect operation.
Effects exclude observation and attempt labels from logical content, so historical
observations may coexist without being interpreted as permission to retry.
Parent linkage names retry history, not another operation or capacity release.

There is no durable ledger, canonical request digest, retained-result service,
cross-bundle replay guarantee, exactly-once effect guarantee or settlement logic.
Future consumers must retain the coordinator's operation history and guards.

Optional `coordinator` mapping is asserted on a run and repeated **exactly** on
every attempt in it (absence must also agree):

* Ordinary schema **2**: `schema`, `task_id`, tagged `task_revision`, opaque retained
  `task_digest`. Session/generation fields are forbidden, not fabricated.
* Cooperative schema **3**: the same fields plus exact `session_id` and positive
  integer `generation`. Missing or disagreeing fields refuse.

These are lineage descriptions, not task parsers, migrations or live occupant
checks. Retained digest/revision strings are not recomputed. Native task schemas
**4/5 are unsupported** by this initial inert consumer. They are neither parsed nor
activated nor downgraded to 2/3; portable format numbering remains independent.

## Capacity requests only

Optional attempt `capacity` has `kind: request` and exactly matching
work/run/operation/attempt IDs, opaque domain ID, class, policy/config revisions,
resource vector, maximum fanout, duration and retry count. Classes are
`remote_static`, `implementation`, `heavy_validation`, `vm_start_provision`.
The initial resource subset is CPU millicores, memory/storage bytes, workers and
provider-concurrent counts. Unknown resources/units, negative quantities, floats,
booleans and entitlement/admitted/release fields refuse. Zero is a numeric request,
not an unsupported-value marker. Other resource types in #191 are deliberately
unsupported in this small portable slice; no generic unit DSL is introduced.

Budget and request numbers are declarations, not enforced ceilings. No topology,
resource availability, backing hierarchy, effective limit, fanout qualification,
authorization, reservation, launch, cancellation or release is calculated.
The existing coordinator's **6 workers / 2 implementation lanes**, review reserve,
serial heavy-check policy and uncertain charges remain outside this validator.
Labels, new runs and import cannot create entitlement or clear reservations.

## Examples, tests and next consumer gate

* [`coding-link-v1.json`](../tests/fixtures/portable-work/coding-link-v1.json):
  synthetic exact-source link repair, patch plus verification, ordinary mapping,
  request-only capacity and an unobserved export description.
* [`staged-documents-v1.json`](../tests/fixtures/portable-work/staged-documents-v1.json):
  repository-free synthetic brief plus verification. The background document has
  changed, but support depends only on the unchanged primary source. No coordinator
  identity is manufactured.

These are metadata input/output examples, **not executed workflows or review
receipts**. Their symbolic revisions and budgets are synthetic. They do not prove
actual content hashes, citation quality, isolated execution or independent review.

`tests/portable-work-contract-test.py` covers positive fixtures, bounded decoding,
closed nested fields, missing/cross-run references, stale/selective support,
operation conflicts across runs, mapping disagreement, capacity injection, typed
effects and instrumented import/validation side effects. The recipe appears once
in `make test-rest`, with exact CI-partition coverage. Execute checks only inside
an independently justified workspace sandbox (`python3 -I -B`), then run the
repository's full and strict gates before review. This document itself asserts
no check result or runtime qualification.

Next work is separate admission for local binding/workflow consumers, with exact
source pin, W0–W7 applicability review, durable identity/replay and equal-guard
authority enforcement. This slice requires no Nexus runtime and cannot stand in
for a qualified engineering-review path, activation approval or human merge decision.
