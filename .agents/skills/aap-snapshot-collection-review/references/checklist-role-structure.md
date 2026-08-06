# Role Structure Checklist

## Per-Component Delegator Roles (`automationcontroller`/`automationeda`/`automationgateway`/`automationhub`)

- [ ] New task files follow the existing naming: `export.yml`, `import.yml`,
      `reconcile.yml`, `preflight.yml`, `get_secret.yml`, `db_export.yml`,
      `start_service.yml`, `stop_service.yml` — don't invent a new name for
      something that fits an existing phase.
- [ ] The task body actually delegates to `operations`/`ocp_utils` via
      `include_role` + `vars: component_name: "{{ <role>_component_name }}"`,
      rather than reimplementing logic inline. Real per-component logic only
      belongs in `reconcile.yml` (see the structure skill's
      [Component Role Patterns](../../aap-snapshot-collection-structure/references/component-role-patterns.md)
      for what's already there).
- [ ] If the change adds behavior that should apply to more than one
      component, it's implemented as a new field in
      `_operations_component_config` (`roles/operations/vars/main.yml`),
      not copy-pasted into one delegator role's task file.
- [ ] No `handlers/` or `templates/` added to a delegator role — these
      roles hold no state and render nothing; that logic belongs in
      `operations`/`postgresql`/`artifact`.

## `operations` Engine Changes

- [ ] New/changed task files start by resolving
      `_operations_current_component` from `_operations_component_config`.
- [ ] Platform branching (`aap_platform in ['rpm', 'containerized',
      'operator']`) covers all three platforms the collection supports, or
      explicitly documents why one is out of scope.
- [ ] A new `_operations_component_config` field is set (or explicitly
      defaulted) for all four existing components — an omitted field
      silently evaluates to `undefined` for components that don't set it,
      which can produce a confusing failure deep in a task rather than a
      clear error at config-resolution time.

## `postgresql` / `ocp_utils` Engine Changes

- [ ] Changes are platform-agnostic to component identity — if a fix is
      component-specific, it likely belongs in `operations` or a delegator
      role instead, not `postgresql`/`ocp_utils`.
- [ ] New OCP-path task files added to `ocp_utils` are documented in the
      structure skill's [OCP Utils](../../aap-snapshot-collection-structure/references/ocp-utils.md)
      reference if they introduce a new file others might reuse.

## `artifact` Role Changes

- [ ] Changes to `package.yml`'s manifest/secrets structure have a
      corresponding update in `plugins/modules/validate_migration_artifact.py`
      so the new field/structure is actually validated.
- [ ] Changes to `consume.yml`'s `block:` preserve `rescue:`/`always:`
      coverage — see [Migration Safety](checklist-migration-safety.md).
- [ ] If component stop/start ordering changes, both
      `playbooks/common/start_services.yaml`/`stop_services.yaml` and the
      inline sequence in `consume.yml` are updated together.

## Adding a New Component

If the PR adds a 5th AAP component to the collection, check all five steps
in the structure skill's
["Adding a Fifth Component"](../../aap-snapshot-collection-structure/references/component-role-patterns.md#adding-a-fifth-component)
section were actually done — a partial addition (e.g. delegator role
created but not wired into `set_groups.yml` or the playbook host lists)
will silently skip the new component rather than error.

## Value Fidelity Spot-Checks

When a PR touches secret names, K8s secret field names, or config file
paths, grep for the same literal string elsewhere in the repo (especially
`_operations_component_config`, `__ocp_utils_artifact_secret_mapping`, and
the corresponding entry for the other three components) to confirm nothing
was renamed inconsistently.
