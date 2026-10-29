# Integrated live review and owner-proposal qualification

This increment connects existing review collection, finding retention and owner
application. It does not add remote GitHub effects or whole-candidate readiness.

## Bound reviewer context

`review-collect` admission may include a bounded `context` object (canonical
JSON, maximum50KB). Its bytes go to `review-run --context FILE`; the runner hashes
them before/after invocation and collection verifies the expected digest.
Context contains acceptance criteria, prior findings and controller-observed
evidence. It remains data, not candidate authority. Re-review requests explicit
`fixed`, `refuted` or `persists` dispositions for retained finding IDs.

Legacy admissions without context remain valid. Owner-proposal output cannot
count as an independent review. Context is separate from packet source selection
because task/finding metadata is not a captured source blob.

## Read-only owner proposals

After `repair-apply prepare` and original-owner rework claim, invoke
`run.sh repair-proposal TASK --request REQUEST` with action `admit`. Its payload
contains correction_id, session, model, agent, binary_sha256, profile_sha256,
cwd and `sources` mapping guest absolute names to admitted repository-relative
files. The command returns a retained context and admission_id.

Run the bounded worker with `--role owner-proposal --context FILE`, a fresh
assigned session, the exact source files and installed profile. The worker has
read access only. It returns either:

```json
{"schema_version":1,"status":"proposed","replacements":[{"path":"calc.py","content":"complete UTF-8 file contents"}],"limitations":[]}
```

or an explicit `unable` status with empty replacements and a limitation. At most
two admitted source files and50KB total proposed UTF-8 contents are supported.
The controller never asks the model to compute hashes/base64, never interprets
commands in the response, and never rewrites the proposed content.

Collect using action `collect`, with admission_id and the five runtime artifact
digests, plus `--bundle DIR`. Session/source/profile/model/context and completion
must match. The controller retains original output and deterministically renders
the existing replacement bundle, supplying before hashes and base64 encoding.
The ordinary `repair-apply` path then governs actual mutation. An unable response
is retained but produces no bundle or repair credit. Historical retry grants no
new authority. Owner sessions remain distinct from reviewer assignments.

Prepared correction generations cannot advance until application or explicit
settlement, preventing accidental invalidation between prepare and apply. After
application, commit and update-head precede a fresh packet, generation and review.

## Repeatable qualification driver

`tests/qualify-review-repair.py` is an explicit live fixture driver, not part of
default tests and not a production scheduler. Run it only in a disposable
controller environment using `--isolated-guest --root ROOT --profile PROFILE
--binary-sha256 SHA --owner-pid PID`. Its phases are:

1. `init`: create defective committed ordinary source, run independently fixed
   behavioral assertions, admit first reviewer; emit source/context/session.
2. `review --bundle DIR`: ingest actual reviewer output; stop on a missed defect;
   prepare correction and owner admission; emit owner context.
3. `proposal --bundle DIR`: ingest exact model proposal; apply through the
   guarded transport; verify assertions; commit fixture and admit re-review.
4. `rereview --bundle DIR`: accept fresh actual review and require full assigned
   coverage and explicit resolution of original findings. Retain final outcome.

The operator provides a separate qualified read-only model guest and copies
source/context and returned artifacts between phases. There is no fake-response
fallback. A role-specific failed stage stops with retained evidence. The driver
does not itself provision guests, grant network access or install models. Owner
PID is session accounting, not independent worker-process attestation.

Use a Linux controller filesystem that meets `repair-apply`'s same-device and
metadata contract. In the measured setup, Docker supported it while MSB's guest
filesystem reported differing file/directory devices. MSB remains qualified for
the read-only model workers. Multipass was only the local host for a Docker
controller in the trial: no Multipass API is imported or required by this skill.
No filesystem guard should be weakened to make an unsupported backend pass.

The driver demonstrates ordinary-code qualification; protected self-maintenance
and unattended service recovery remain separate. Runtime artifact consistency,
real model behavior, independent behavioral assertions and repository readiness
are different kinds of evidence and must be reported separately.
