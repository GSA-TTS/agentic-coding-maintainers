# Bounded owner replacement transport

`run.sh repair-apply` handles replacement bytes as data, never candidate code.
Run only the independently installed controller with exclusive worktree ownership.
Candidate versions are tested against isolated fixture state. Neither the bundle
nor the correction request grants execution, commit, push or review authority.

## Workflow

1. Review retains an unresolved finding. Admit `Reviewing → Rework`, consuming
   one of the existing three repair cycles.
2. Before reclaiming, run `repair-apply TASK prepare --expected-revision N`.
   This retains the exact owner/scope/finding correction and its generation,
   epoch and cycle. A changed owner cannot claim this prepared correction.
3. The original owner claims and enters `Implementing`, acquiring the normal
   global slot and implementation lane. Stop other worktree writers before
   application; one task remains one writer.
4. Supply a bounded JSON request and replacement bundle:

```json
{"schema_version":1,"operation_id":"repair-1","expected_revision":12,"correction_id":"<digest>","bundle_sha256":"<digest>"}
```

```json
{"schema_version":1,"correction_id":"<digest>","replacements":[{"path":"src/example.py","before_sha256":"<digest>","after_base64":"<canonical base64>"}]}
```

5. Invoke `repair-apply TASK apply --request REQUEST --bundle BUNDLE`. The
   controller checks the prepared context, active owner/leases, clean recorded
   checkout, stopped executions, target identity and **all** before hashes.
   It retains the bundle and persists APPLYING plus review invalidation before
   writing any candidate file.
6. On success, APPLIED_UNREVIEWED records only observed replacement bytes. The
   owner creates the new commit through the usual authorized workflow and uses
   `update-head`. Fresh source capture/review and execution plans are required.
   Findings remain unresolved until independently reviewed dispositions arrive.

## Scope and metadata

Version1 replaces at most two existing regular files, each at most256KiB, with
an800KB raw bundle bound. It does not create/delete/rename files or alter modes.
Paths use conservative ASCII relative components and component-aware owned/
restricted matching. Restricted paths win. Git, orchestration, agent, CI,
environment and active instruction paths are denied irrespective of scope.
The running controller and task state must be outside the repaired checkout.
This first transport does not repair candidate policy/controller files; those
require a separately reviewed self-maintenance transport and promotion process.

Targets must be owned by the current user, have one hard link, reside on the
same filesystem, have ordinary0600/0644 modes, and lack flags or extended
attributes. Symlink components, special files and unsupported metadata are
refused. Descriptor-relative no-follow traversal and same-directory atomic
replacement avoid path-string-only writes. Each file is fsynced before rename,
then its parent is fsynced. The multi-file bundle is **not atomic**.

These checks do not isolate a hostile same-user process able to relocate
ancestors or modify the authority store. Exclusive owner access and the actual
execution sandbox remain deployment requirements. No candidate hooks, filters,
formatters or tests are run during application. File writes must not be coupled
to host auto-reloaders that execute candidate code.

## Replay and recovery

Exact operation replay never repeats file writes. Changed reuse is refused.
An interrupted operation retains its fence. `repair-apply TASK reconcile
--operation-id ID` acquires the coordinator lock and only inspects targets:

- all before bytes/modes: NOT_APPLIED_OBSERVED;
- all after bytes/modes: APPLIED_UNREVIEWED;
- known mixture: PARTIAL, still fenced;
- missing/unknown bytes, metadata or evidence: UNVERIFIED, still fenced.

No automatic rollback or partial resume occurs. Cooperating application holds
the lock throughout mutation; stale-lock recovery remains an explicit operator
action, not an assumed termination proof. Prepared correction and accepted
bundle bytes are retained outside the candidate. Missing evidence cannot be
reconstructed from the worker's assertion.

Lifecycle, head/evidence and execution changes refuse an unresolved repair.
Application advances the material epoch before writes, invalidating old review
and execution plans even while Git HEAD is unchanged. New review at the old
head is refused after application. The third permitted repair can be reviewed;
admitting a fourth cycle remains blocked by the coordinator.
