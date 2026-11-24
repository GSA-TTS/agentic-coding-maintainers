# Linux capacity text parser (candidate v1)

This is the bounded offline parser slice of [#192](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/192),
following [Capacity contract v1](CAPACITY-CONTRACT.md), particularly sections 4–6
and 11. It is **not** a collector, activated observation interface, qualified
Linux adapter, entitlement calculator, or admission controller. Its tests are
registered once in `make test-rest` and the explicit CI-partition inventory.

## API and trust boundary

`scripts/capacity-linux-parser.py` exports `parse_sample(metric, source, context)`
and `ParseError`. There is no CLI, import, runtime dependency, schema engine,
dynamic loading, file access, environment access, clock, network, persistent
state, or launch behavior in the parser. The test harness loads this local module;
the parser itself loads nothing. Every call returns fresh dictionaries, including
nested context and result dictionaries, without modifying or retaining inputs.

Inputs must use **exact built-in** `dict`, `str`, `int`, and `bool` types where
specified. Subclasses, alternate mappings, coercion, floats, and booleans in
integer fields refuse. All record keys must be exact strings. Records are closed:
extra keys refuse, including injected health, admission, or entitlement fields.
Already-decoded dictionaries cannot preserve duplicate input keys: any future
wire decoder must reject duplicate keys *before* constructing these dictionaries.
PSI text duplicates are detected here.

The metric is exactly one of `cpu.max`, `memory.max`, `memory.current`,
`cpu.pressure`, `memory.pressure`, or `io.pressure`.

Source is exactly one of:

```python
{"kind": "text", "text": "max 100000\n", "complete": True}
{"kind": "unavailable", "reason": "not_collected"}
```

Unavailable reasons are `not_collected`, `not_visible`, `permission_denied`,
`unsupported`, `inapplicable`, and `read_failed`. These are caller assertions,
not proof of applicability or an exception caught by this parser. No raw error
message or path is accepted in place of an allowlisted reason.

Context has exactly these fields (synthetic example):

```python
{
    "producer_id": "example-parser-input",
    "producer_version": "1",
    "collector_instance_id": "collector-1",
    "domain_id": "cgroup:example",
    "boot_id": "boot-1",
    "clock_domain_id": "clock-1",
    "backing": {"kind": "declared", "domain_id": "vm:example"},
    "start_ns": 10,
    "end_ns": 20,
    "sequence": 0,
    "policy_digest": "a" * 64,
    "config_digest": "b" * 64,
}
```

* All six identity/version fields and a declared backing domain are opaque
  1–256-character ASCII strings: first character alphanumeric, remaining
  characters alphanumeric or `._:/@+-`. They are not resolved as paths or names.
* Backing is either exactly `{"kind": "declared", "domain_id": ...}` or exactly
  `{"kind": "unavailable"}`. No topology, ancestry, uniqueness, or relationship
  to `domain_id` is inferred.
* `start_ns`, `end_ns`, and `sequence` are integers in `0..18446744073709551615`
  (U64), with `start_ns <= end_ns`. Zero duration is accepted.
* Digests are exactly 64 lowercase ASCII hexadecimal characters, preserved
  without normalization. No policy/configuration document is loaded or hashed.

Metadata is **asserted, not verified**. The parser cannot establish boot or clock
identity, monotonicity across calls, freshness, sample age, completeness of a
collector read, sequence continuity, producer authenticity, or digest authority.
It does not compare samples, interpret resets, or subtract different clock domains.

## Supported text profile

Raw text is bounded **before** tokenization or numeric conversion: at most 128
ASCII bytes for scalar metrics and 1024 for PSI, including terminal LF. Oversized
strings refuse by character length before scanning/encoding; accepted ASCII has
equal character and byte lengths. Only printable ASCII plus space, tab, and LF
are allowed. CR, NUL, other controls, non-ASCII, and byte strings refuse. Only
spaces/tabs may separate tokens; leading/trailing spaces/tabs are accepted.
Exactly one terminal LF is required, with no blank extra lines. Scalar input
has one nonempty line; PSI has two nonempty rows. `complete=False` cannot produce
an observation, even when the supplied text otherwise looks valid.

Unsigned integers are canonical decimal (`0` or a nonzero first digit followed
by digits), at most 20 digits and at most U64. No signs, padding zeros, exponents,
decimal points, or alternate bases are accepted.

| Metric | Supported grammar and result |
| --- | --- |
| `cpu.max` | `QUOTA PERIOD`; quota is literal `max` or integer `1000..U64`; period is integer `1000..1000000`. Both numeric values are microseconds. Result keeps quota and period separately, preserving the exact fraction without rounding or converting to millicores. |
| `memory.max` | Literal `max` or integer `0..U64`, in bytes. |
| `memory.current` | Integer `0..U64`, in bytes; `max` is not accepted. |
| All three PSI metrics | Exactly one `some` and one `full` row, in either order. Each row has exactly one `avg10`, `avg60`, `avg300`, and `total` as `key=value`, in any order. Averages are canonical `0.00..100.00`, with **exactly two fractional digits**, returned as integer percent hundredths. `total` is U64 microseconds. |

This is an explicit **supported canonical two-fraction-digit profile**, not a
claim that every Linux release, scope, controller, or producer supports this
grammar. Missing `full` refuses as incomplete; it is not silently synthesized.
System-level CPU `full` pressure is undefined (and may be reported as zero for
compatibility); accepting its syntax does not make that value meaningful.
Scope/applicability and kernel/controller qualification belong to a future adapter.

`cpu.max` and `memory.max` describe local limits, **not** effective ancestor limits
or entitlement. CPU fit also needs cpusets, online CPUs, ancestry, and authority.
`memory.current` includes descendants and can temporarily exceed a limit. This
parser compares neither independently collected limits/usage nor PSI totals with
elapsed time. A zero, an unlimited limit, and an unavailable sample stay distinct;
none establishes health or headroom.

## Output and refusals

Every successful observation has exactly:

```python
{
    "format": "capacity-linux-observation",
    "version": 1,
    "metric": metric,
    "context": copied_context,
    "duration_ns": context["end_ns"] - context["start_ns"],
    "result": typed_result,
}
```

Result shapes:

```python
{"kind": "cpu_quota", "unit": "microseconds",
 "quota": {"kind": "finite", "value": 1500}, "period": 100000}
# Unlimited CPU replaces quota only with {"kind": "unlimited"}.
{"kind": "finite", "unit": "bytes", "value": 0}
{"kind": "unlimited", "unit": "bytes"}
{"kind": "pressure", "average_unit": "percent_hundredths",
 "total_unit": "microseconds",
 "rows": {"some": {"avg10": 0, "avg60": 1, "avg300": 10000, "total": 0},
          "full": {"avg10": 0, "avg60": 0, "avg300": 0, "total": 0}}}
{"kind": "unavailable", "reason": "unsupported"}
```

No raw text, healthy/fresh/verified/admitted claim, or authority decision is
returned. `ParseError` is a `ValueError` whose `code` and message are the same
fixed token, never interpolated input:

| Code | Meaning |
| --- | --- |
| `INCOMPLETE` | `complete=False`, missing terminal LF, empty sample, missing scalar token, PSI key, or PSI row. |
| `DECIMAL` | Noncanonical integer/average syntax. |
| `ENCODING` | Non-ASCII or disallowed control character. |
| `RANGE` | Numeric bound or context timestamp ordering violation. |
| `LIMIT` | Oversized text/identity or decimal token longer than 20 characters. |
| `SHAPE` | Wrong type/tag/record shape, missing context/source field, extra/blank line, token count, or malformed assignment. |
| `DUPLICATE_FIELD` | Repeated PSI row or key. |
| `UNKNOWN_FIELD` | Extra record field or unknown PSI row/key. |

Validation is deterministic, not an aggregation of every defect: metric/context
and source shape are checked first; text length and encoding precede completeness;
then grammar is checked. PSI missing keys/rows are reported after checking present
tokens, so a malformed present token can take precedence over a missing key.
Refusal codes are parser errors, not coordinator exit 3/4 or lifecycle outcomes.

## Offline validation and deferred work

`tests/capacity-linux-parser-test.py` uses only the Python standard library and
synthetic inputs. It covers boundaries, canonical decimals, truncation, ordering,
duplicates, closed metadata, type/subclass rejection, independent copies, fixed
errors, and absence of effectful parser dependencies. Run it in the independently
justified workspace sandbox; registration does not establish execution or platform
qualification. Required full checks and fixed-head review remain delivery gates.

Collection, wire decoding, cross-sample reset/freshness checks, topology and
ancestor calculation, effective-limit math, runtime integration, actual-platform
qualification, and admission remain outside this slice. Offline fixtures alone
do not satisfy all of #192, qualify a supported platform tuple, or activate any
capacity increase.
