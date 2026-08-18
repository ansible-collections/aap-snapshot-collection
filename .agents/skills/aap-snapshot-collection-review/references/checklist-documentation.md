# Documentation Checklist

## Changelog Fragments

- [ ] Every user-facing change (bugfix, feature, breaking change,
      deprecation, security fix) includes a fragment in
      `changelogs/fragments/` — see the
      [aap-snapshot-collection-authoring](../../aap-snapshot-collection-authoring/SKILL.md)
      skill for the exact format and section keys.
- [ ] The fragment's section key matches the actual change type
      (`bugfixes` vs `minor_changes` vs `breaking_changes`, etc.) — don't
      accept a bugfix filed under `minor_changes` or vice versa.

## `docs/` Accuracy

- [ ] If the PR changes the actual role/task architecture (adds a role,
      renames a task file, changes what `operations`/`ocp_utils` are
      responsible for), check whether `docs/architecture.md`,
      `docs/workflows.md`, or `docs/migration-fsm.md` need a corresponding
      update. `docs/architecture.md` already contains stale role names
      (`export_component`, `reconcile_gateway`, etc. that don't exist — see
      the [structure skill](../../aap-snapshot-collection-structure/SKILL.md))
      — a PR shouldn't add new drift on top of the existing gap, and fixing
      a piece of this doc while touching the surrounding area is a good
      opportunistic improvement (flag as a suggestion, not a blocker).
- [ ] `docs/variables.md` is updated if the PR adds or renames a
      user-facing default variable.
- [ ] `docs/artifact-format.md` is updated if the tarball layout or
      manifest schema changes.

## Module/Filter/Plugin Documentation

- [ ] New or changed `plugins/modules/*.py` / `plugins/filter/*.py` follow
      the existing `DOCUMENTATION`/`EXAMPLES`/`RETURN` block convention
      (see the conventions skill) — including `version_added`, `author`,
      and `notes:` for platform constraints.
- [ ] If a module returns a password/secret field, the `RETURN` doc
      explicitly states the caller must apply `no_log` (as
      `aap_component_info.py` already does) — this is the module's only
      enforcement mechanism, since the module itself can't force the
      caller's task to set `no_log`.

## Role READMEs

Every role README in this collection today is a one-line stub. Don't block
a PR for not expanding a README to a full parameter reference — that's not
the established convention here — but do flag it as a suggestion if a PR
introduces a genuinely non-obvious new role and a one-liner would leave
future maintainers with no orientation at all.
