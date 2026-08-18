# Migration Safety Checklist

This checklist is specific to this collection's core risk: a failed or
partial export/import should never leave the source or target AAP
deployment in a broken, half-migrated state.

## `consume.yml` `block/rescue/always`

- [ ] A new failure path added inside the OCP import `block:` (scale down,
      create temp resources, transfer, DB import, restore secrets, scale
      up, reconcile) is covered by the existing `rescue:` — i.e., if the
      new step can fail, does `rescue:` still correctly scale operators
      back up and un-idle the AAP CR afterward, or does the new step need
      its own rescue-equivalent handling?
- [ ] The `always:` cleanup (`ocp_utils/cleanup_temp_resources.yml`) still
      runs regardless of where in the block a new step fails, and its
      `_artifact_import_succeeded` / `keep_temp_on_failure` gating logic
      isn't bypassed by the new step.
- [ ] A new step doesn't introduce a state where the target cluster is left
      idled/scaled-down if the step after it fails — trace the actual
      execution order, don't assume block/rescue makes this automatic for
      steps added at the wrong point.

## Version and Schema Compatibility

- [ ] `operations/tasks/preflight.yml`'s version-match assertion still
      covers any new version-sensitive behavior added by the PR (e.g. a
      Django-version-dependent manage command flag, similar to
      `detect_django_version_ocp.yml`).
- [ ] Changes to the manifest/artifact structure (`manifest.yaml.j2`,
      `secrets.yml` layout) are reflected in
      `plugins/modules/validate_migration_artifact.py`'s schema check —
      including whether `validate_artifact_supported_schema_versions`
      needs a bump. An artifact the validator doesn't understand should
      fail validation clearly, not silently pass with missing checks.

## Containerized vs. OCP Path Symmetry

- [ ] A fix or feature added to the containerized import path in
      `consume.yml` is evaluated for whether the OCP path needs the same
      fix, and vice versa — these are separate branches of the same file
      implementing the same conceptual operation, and historically fixes
      have landed on only one side (see the DB-name/username fix, which
      initially only needed the version-check query but is a pattern to
      watch for elsewhere).

## Reconcile Correctness

- [ ] Changes to a component's `reconcile.yml` don't skip the
      admin-password reset or other post-import fixups that all four
      components currently perform — reconcile changes are easy to
      under-scope to just the new feature and accidentally drop existing
      steps if the file is rewritten rather than extended.
- [ ] Reconcile logic that depends on AAP CR readiness (EDA's wait-for-
      `Successful` condition) uses bounded retries with a sane
      retry/delay, not an unbounded wait that could hang a migration
      indefinitely on a stuck cluster.

## Rollback / Idempotency

- [ ] Re-running export or import after a partial failure doesn't corrupt
      state — e.g., does `init.yml` clean up a partial build directory from
      a previous failed run, does `consume.yml`'s temp-resource creation
      handle temp resources left over from a previous failed attempt?
