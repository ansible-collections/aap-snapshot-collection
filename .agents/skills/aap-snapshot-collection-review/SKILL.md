---
name: aap-snapshot-collection-review
description: >-
  Code review guide for aap-snapshot-collection pull requests. Use this
  skill whenever reviewing a PR, doing a code review, checking a diff, or
  preparing review comments for this repository. Covers the standard review
  format, severity classification, and area-specific checklists for role
  structure, security/secrets, database (PostgreSQL) patterns, playbook
  integration, documentation, and migration safety (export/import
  correctness). Also use when asked to "review this", "check this PR",
  "what's wrong with this diff", or when preparing feedback on someone's
  changes to roles/, playbooks/, or plugins/ in this collection.
---

# Review Approach

Reviews should be **concise and problem-focused**. The goal is to catch
real issues — not to demonstrate thoroughness by listing every convention
that was followed correctly. If something looks correct, don't mention it.

## Verify Before Flagging

Before flagging any finding — at **any** severity level, including
suggestions — **actively search the codebase to verify the concern is
valid**. The diff shows only changes, not full context.

- Use Grep/Glob to find related definitions, patterns, or usage elsewhere
  in the collection (especially the other 3 component roles, if the diff
  touches one of `automationcontroller`/`automationeda`/
  `automationgateway`/`automationhub`)
- Use Read to examine full file contents and surrounding tasks
- Check `_operations_component_config` in `roles/operations/vars/main.yml`
  if the diff adds a new field or behavior flag
- For suggestions: verify the change would produce a concrete benefit. If
  you can't demonstrate the benefit after investigation, drop it.

**Only flag verified issues.** If you cannot find evidence after searching,
don't flag it. When in doubt, ask a question instead of asserting it's
wrong.

### Invalid Deductions (do not flag these)

- Micro-optimizations with no practical impact
- Structural changes necessary for the PR's stated goal — verify before
  calling something "scope creep"
- Cosmetic formatting preferences (indentation style, blank lines) beyond
  what `.yamllint.yml`/`ansible-lint` actually enforce
- Architectural decisions — score the implementation, not the design choice
- Pre-existing patterns not changed in this diff — use Incidental Findings
  instead
- "Add tests" without identifying a specific untested code path and what
  the test should assert

## Output Guidelines

**Include:** clear problem descriptions with file:line references, quoted
evidence from the diff for every finding, a concrete fix, references to the
relevant checklist section, and questions where clarification is needed.
Flag any changes unrelated to the PR's stated purpose.

**Exclude:** praise sections, full checklists of everything that passed,
verbose examples of correct patterns.

**Verdict language:** never say "ready to merge" — the reviewer role here
is advisory. Use "ready for maintainer review" when no blocking issues
remain.

## Severity Levels

- **Critical (blocking):** will cause failures, data loss, a leaked
  secret, or a broken migration in production. Must fix before merge.
- **Important:** won't break things immediately but creates tech debt,
  inconsistency across the 4 component roles, or maintenance risk.
- **Suggestion:** optional improvement with a verified, concrete benefit.
  Omit this section entirely if nothing survives verification.

## Confidence Levels

- **DIRECT** — self-evident from the quoted diff alone (e.g. `no_log:
  true` hardcoded, missing `| bool`, a `login_password:` parameter with no
  `no_log`).
- **TRACED** — required reading another file or tracing a variable across
  tasks (e.g. comparing this component's `reconcile.yml` against the other
  three, or checking whether `_operations_component_config` already has
  the field being added).
- **INFERRED** — depends on runtime state or deployment topology that
  can't be verified from the repo alone (e.g. behavior of a specific K8s
  cluster version). Convert to a Question if you can't be more precise.

## Self-Validation (run before presenting)

1. **Evidence** — can you quote the specific diff line? If no, remove.
2. **Invalid** — is it in the Invalid Deductions list? If yes, remove.
3. **Scope** — pre-existing or outside the diff? Move to Incidental Findings.
4. **Materiality** — can this actually manifest in practice? If no, remove.
5. **Confidence** — does the label match what you actually did?
6. **Severity** — proportionate to actual impact?

## Review Structure

```markdown
# PR #{NUMBER} Review: {Title}

**Reviewer:** {reviewer}
**Date:** YYYY-MM-DD
**PR Author:** {author}
---

## Summary of Required Actions

### Must Fix (Critical - Blocking)
1. [Issue with file:line reference]

### Should Fix (Important)
1. [Issue with file:line reference]

### Questions for Author
1. [Question about unclear implementation]
---

## Critical Issues

- **[file:line]** [description] (Confidence: DIRECT|TRACED|INFERRED)
  - **Evidence**: `[quoted code from the diff]`
  - **Fix**: [code change]

## Important Issues

[Same format as Critical]

## Suggestions (if any — omit section if none survived verification)

## Incidental Findings (out of scope — not scored)

[Pre-existing issues noticed during review, not introduced by this PR,
noted so maintainers are aware.]

<!-- END OF REVIEW -->
```

---

# What to Check

Quick-reference of the highest-signal items. For deep-dive reviews, read
the relevant `references/checklist-*.md` file.

## Ansible Conventions (quick check)

See the [aap-ansible-conventions](../aap-ansible-conventions/SKILL.md)
skill for the full rules. In short: `no_log` must be the canonical computed
expression (never hardcoded), `| bool` on every boolean `when:`, FQCN on
every module, `become` only when a specific file/command ownership
requires it, YAML files end with `...`, loops that might carry secret
values need `loop_control.label`.

## Role Structure (quick check)

- **New component?** Does it follow the delegator pattern (thin
  `export.yml`/`import.yml`/`reconcile.yml`/`preflight.yml` calling into
  `operations`), or does it duplicate logic that belongs in `operations`/
  `postgresql`? See
  [Role Structure](references/checklist-role-structure.md).
- **Reference role comparison:** for a change to one of `automationcontroller`/
  `automationeda`/`automationgateway`/`automationhub`, read the
  corresponding file in the other three and check whether the same fix/
  feature should apply there too (e.g. a `_operations_component_config`
  field added for one component that the others could also use).
- **`_operations_component_config` changes:** adding a field here affects
  every component that references it (or defaults silently to undefined
  for the ones that don't set it) — check all four config blocks, not just
  the one being edited.

## Security & Secrets (quick check)

- Every task passing a password/token/secret parameter has computed
  `no_log`.
- Every `loop:` over potentially-secret data has `loop_control.label`.
- New secrets go through the existing `secrets.yml`/`__ocp_utils_artifact_secret_mapping`
  path, not a new standalone file.
- File permissions on anything written to the artifact (`secrets.yml`
  0600, manifest/checksum 0640) are preserved if packaging logic changes.
- See [Security](references/checklist-security.md).

## Database / PostgreSQL (quick check)

- `login_db` explicitly passed wherever a DB name might differ from the DB
  username (see PR #96).
- Dump and restore paths (RPM/containerized vs. OCP) both updated
  symmetrically — check for `no_log` and `login_db` on both branches, not
  just the one being touched.
- Restore operations that grant temporary privileges (CREATEDB) revoke
  them in a `block/always`, not just on the happy path.
- See [Database](references/checklist-database.md).

## Playbooks (quick check)

- New plays set `gather_facts: false` and `any_errors_fatal: true`
  (`custom-play-boilerplate`).
- No `tags:` introduced where `when:` on `aap_platform`/group membership
  is the existing pattern — flag inconsistent flow-control mechanisms.
- If component start/stop ordering changes, check both
  `playbooks/common/start_services.yaml`/`stop_services.yaml` **and** the
  inline sequence in `roles/artifact/tasks/consume.yml` — they are
  currently duplicated, not shared.
- See [Playbooks](references/checklist-playbooks.md).

## Migration Safety (quick check)

- Changes to `consume.yml`'s OCP import `block:` preserve the `rescue:`
  (scale back up / un-idle) and `always:` (temp resource cleanup) behavior
  — a new failure path added inside `block:` without rescue coverage can
  leave a cluster stuck mid-migration.
- Changes to the artifact format (`manifest.yaml.j2`, `secrets.yml`
  structure) are reflected in `validate_migration_artifact` (the module
  backing the verify path) — a new field the module doesn't know about
  won't be validated, and a schema version bump may be needed.
- See [Migration Safety](references/checklist-migration-safety.md).

## Documentation (quick check)

- Changelog fragment present for user-facing changes (see the
  [aap-snapshot-collection-authoring](../aap-snapshot-collection-authoring/SKILL.md)
  skill).
- If the change affects the actual role/task architecture, check whether
  `docs/architecture.md` needs correcting too — that file already contains
  stale role names (see the
  [aap-snapshot-collection-structure](../aap-snapshot-collection-structure/SKILL.md)
  skill) and PRs can make this worse if they add to the drift.
- See [Documentation](references/checklist-documentation.md).

## Detailed Checklists

- [Role Structure](references/checklist-role-structure.md)
- [Security](references/checklist-security.md)
- [Database](references/checklist-database.md)
- [Playbooks](references/checklist-playbooks.md)
- [Migration Safety](references/checklist-migration-safety.md)
- [Documentation](references/checklist-documentation.md)
