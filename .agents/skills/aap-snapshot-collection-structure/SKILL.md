---
name: aap-snapshot-collection-structure
description: >-
  Standard role/playbook layout, task-file patterns, plugin conventions, and
  the export/import/verify orchestration flow for the aap-snapshot-collection
  (ansible.aap_snapshot). Use this skill whenever creating a new component
  role, adding task files to an existing role, working with the `operations`
  or `ocp_utils` engine roles, modifying playbook orchestration
  (artifact_export.yaml/artifact_import.yaml/artifact_verify.yaml), or trying
  to understand how a component's export/import/reconcile flow is wired
  together. Also consult this when adding a new AAP component to the
  collection, debugging why one component's flow doesn't match the others,
  or working with the artifact tarball lifecycle (init/build/package/extract/
  consume/verify in roles/artifact). Even for small changes like adding a
  single task file, check that you're following these structural patterns —
  and note that docs/architecture.md describes role names that no longer
  exist in the codebase, so treat this skill (and the real roles/ tree) as
  the source of truth over that doc.
---

# aap-snapshot-collection Structure

## Why This Matters — and a Documentation Trap

This collection migrates AAP component data (Controller, EDA, Gateway, Hub)
between deployment platforms (RPM, containerized, operator/OCP) by exporting
each component to a single artifact tarball, then importing it into a target
platform. Four AAP components, three source/target platforms, and three
phases (export/import/reconcile) multiply out fast — structural consistency
is what keeps that matrix maintainable.

**`docs/architecture.md` is stale.** It describes roles named
`export_component`, `export_controller`, `import_component`,
`reconcile_gateway`, etc. None of these exist. The real architecture uses a
different (and more DRY) layering described below. If you're orienting from
that doc, stop and read this skill and the actual `roles/` tree instead —
the conceptual flow in `docs/workflows.md` and `docs/migration-fsm.md` is
still accurate, only the role *names* in `docs/architecture.md` are wrong.

## Repository Skeleton

```
aap-snapshot-collection/
├── galaxy.yml                  # Collection metadata (ansible.aap_snapshot)
├── requirements.yml            # Collection dependencies (kubernetes.core, community.postgresql, ...)
├── meta/runtime.yml            # Ansible content metadata
├── playbooks/
│   ├── artifact_export.yaml    # Entry point: export
│   ├── artifact_import.yaml    # Entry point: import
│   ├── artifact_verify.yaml    # Entry point: verify-only (no import)
│   └── common/
│       ├── start_services.yaml # Standalone: start all components in order
│       ├── stop_services.yaml  # Standalone: stop all components in order
│       └── validate_artifact.yaml  # Unarchive + validate (used by export tail)
├── roles/
│   ├── artifact/                # Tarball lifecycle: init/build/package/extract/consume/verify
│   ├── automationcontroller/    # Per-component delegator (controller)
│   ├── automationeda/           # Per-component delegator (eda)
│   ├── automationgateway/       # Per-component delegator (gateway)
│   ├── automationhub/           # Per-component delegator (hub) + content export
│   ├── operations/              # Generic component engine (config-dict driven)
│   ├── postgresql/              # DB dump/restore engine
│   ├── ocp_utils/               # Flat toolbox of OCP/K8s helper tasks
│   ├── preflight/               # Pre-migration validation, sequenced main.yml
│   ├── common/                  # Inventory group assembly (set_groups.yml)
│   ├── validate_artifact/       # Thin wrapper around validate_migration_artifact module
│   ├── pcp/                     # Monitoring service start/stop (containerized only)
│   └── receptor/                # Execution-node service stop (no start — out of scope)
├── plugins/
│   ├── modules/                 # aap_component_info, validate_migration_artifact
│   ├── filter/                  # aap_version.py → parse_aap_version filter
│   └── module_utils/
├── changelogs/fragments/        # antsibull-changelog fragments (see the authoring skill)
└── docs/                        # architecture.md (stale role names), flow-diagrams.md,
                                  # workflows.md, migration-fsm.md, variables.md (accurate)
```

## Playbook Orchestration

Every play across all three entry-point playbooks sets `gather_facts: false`
and `any_errors_fatal: true` — enforced by the custom `custom-play-boilerplate`
ansible-lint rule (see the conventions skill). None of these playbooks use
`tags:`; all flow control is via `when:` on `aap_platform`,
`_snapshot_operation`, and inventory-group membership.

**`playbooks/artifact_export.yaml`** (5 plays):
1. `hosts: all` → `common/set_groups.yml`, then `preflight/main.yml`
2. `hosts: localhost` → `artifact/init.yml` (create build dir structure)
3. `hosts: controller_groups:eda_groups:gateway_groups:hub_groups` → `artifact/build.yml` (loops over the 4 components, calling each one's `export.yml`)
4. `hosts: localhost` → `artifact/package.yml` (manifest, secrets.yml, tar, checksum)
5. `import_playbook: common/validate_artifact.yaml` (validates the artifact it just built)

**`playbooks/artifact_import.yaml`** (5 plays, `_snapshot_operation: import`):
1. `hosts: all` → `set_groups.yml` (skipped for `aap_platform == 'operator'`) → `preflight/main.yml`
2. `hosts: localhost, connection: local` → `artifact/extract.yml`
3. `hosts: localhost` → `artifact/consume.yml` `when: aap_platform == 'operator'`
4. `hosts: controller_groups:eda_groups:gateway_groups:hub_groups` → `artifact/consume.yml` `when: aap_platform == 'containerized'`
5. `hosts: localhost, connection: local` → migration summary / advisory output

**`playbooks/artifact_verify.yaml`** — single `localhost` play, `become: false`:
unarchive → `validate_migration_artifact` module → print report → clean up temp dir.

`playbooks/common/start_services.yaml` / `stop_services.yaml` are **standalone
utility playbooks**, not included by the export/import entry points — the
containerized stop/start sequence used during import is instead re-implemented
inline inside `roles/artifact/tasks/consume.yml`. If you change component
start/stop order in one place, check whether the other needs the same change.
See [Playbook Orchestration](references/playbook-orchestration.md) for the
full per-play detail and host-group variables.

## The Three Role Layers

Roles fall into three distinct patterns. Knowing which one you're extending
tells you where new logic belongs.

### 1. Per-component delegator roles

`automationcontroller`, `automationeda`, `automationgateway`, `automationhub`
are **thin wrappers**, not implementations. Each has task files `export.yml`,
`import.yml`, `reconcile.yml`, `preflight.yml`, `get_secret.yml`,
`db_export.yml`, `start_service.yml`, `stop_service.yml` (hub adds
`export_hub_content.yml`/`import_hub_content.yml`; controller adds
`export_custom_configs.yml`). Almost every task file's body is 1-3 tasks that
`include_role: ansible.aap_snapshot.operations` (or `ocp_utils`) with
`vars: component_name: "{{ <role>_component_name }}"`. `vars/main.yml` sets
that one fixed fact (`controller`, `eda`, `gateway`, or `hub`).

**`reconcile.yml` is the one file with real per-component logic** —
orphaned-instance cleanup and EE URL rewriting for controller, worker
resync for EDA, service-data cleanup for gateway, Pulp content repair for
hub. See [Component Role Patterns](references/component-role-patterns.md).

**Adding a 5th component follows this pattern**: create the delegator role,
add its config block to `_operations_component_config` in
`roles/operations/vars/main.yml`, add it to the group-assembly logic in
`roles/common/tasks/set_groups.yml`, and wire it into the host-group lists in
the playbooks and `start_services.yaml`/`stop_services.yaml`.

### 2. Engine roles

- **`operations`** — the real generic component engine (this is what
  `docs/architecture.md`'s `export_component`/`import_component` actually
  refers to). Config-dict driven via `_operations_component_config` in
  `roles/operations/vars/main.yml`, keyed by component name. Every task file
  starts with `_operations_current_component: "{{
  _operations_component_config[component_name] }}"`, then branches on
  `aap_platform`. See [Operations Engine](references/task-operations.md).
- **`postgresql`** — the actual pg_dump/pg_restore engine, branching on
  `aap_platform in ['rpm', 'containerized']` vs `'operator'`. See
  [PostgreSQL Role](references/task-postgresql.md).
- **`ocp_utils`** — a flat toolbox of 16 independent, à la carte task files
  (not component-parallel) covering CR/pod discovery, temp resource
  lifecycle, secret mapping, and manage-command execution. See
  [OCP Utils](references/ocp-utils.md).

### 3. Lifecycle / utility roles

- **`artifact`** — owns the tarball lifecycle: `init.yml` (build dir),
  `build.yml` (loop components' export), `package.yml` (manifest +
  secrets.yml + tar + checksum), `extract.yml` (unarchive on import),
  `consume.yml` (the big one — full stop/import/start/reconcile
  orchestration, `block/rescue/always`), `verify.yml`/`verify_local.yml`/
  `verify_content.yml` (checksum-only, no import). See
  [Artifact Role](references/task-artifact.md).
- **`preflight`** — the only role with a real `tasks/main.yml`, sequencing
  platform/version/storage/service/database checks before delegating to each
  component's own `preflight.yml`. See [Preflight Role](references/task-preflight.md).
- **`common`** — just `set_groups.yml`, builds `controller_groups`,
  `eda_groups`, `gateway_groups`, `hub_groups` via `add_host` from
  platform-specific inventory group names.
- **`validate_artifact`** — single `tasks/main.yml` wrapping the
  `validate_migration_artifact` module; used both by the export-tail
  validation and standalone artifact checks.
- **`pcp`**, **`receptor`** — minimal service start/stop roles for
  monitoring and execution nodes; not component-parallel.

## Shared Variable Conventions

- **`component_name`** — the universal parameter (`controller`/`eda`/
  `gateway`/`hub`) passed via `vars:` into `operations`/`ocp_utils` includes.
- **`aap_platform`** (`rpm` | `containerized` | `operator`) — the single
  dimension almost every task file branches on.
- **Component enablement is inventory-driven, not a boolean flag.** There is
  no `controller_enabled`-style variable — whether a component's tasks run
  at all is gated by `groups.get('controller_groups', []) | length > 0`.
- **Leading double-underscore vars** (`__artifact_build_dir`,
  `__operations_no_log`, `__postgresql_no_log`) are internal/resolved facts
  derived from a public-facing default, always defined once in the owning
  role's `defaults/main.yml`. Don't reference a role's internal `__` vars
  from another role — go through its public defaults or task interface.
- **`no_log` is computed, never hardcoded**: every occurrence must equal
  `{{ not (disable_no_log | default(false) | bool) }}` (directly or via a
  `__<role>_no_log` alias) — enforced by a custom ansible-lint rule. See the
  aap-ansible-conventions skill.
- **Facts cross hosts via `delegate_to: localhost, delegate_facts: true`.**
  Component-level facts computed on remote hosts (version, secrets, DB
  credentials) get pushed to `localhost` so the packaging phase can assemble
  `manifest.yml`/`secrets.yml` from every host's facts via `hostvars`.

## Deep-Dive References

- [Playbook Orchestration](references/playbook-orchestration.md) — full per-play breakdown, host-group variables, why start/stop order is duplicated
- [Component Role Patterns](references/component-role-patterns.md) — delegator role anatomy, per-component `reconcile.yml` logic, adding a new component
- [Operations Engine](references/task-operations.md) — `_operations_component_config` schema, task file responsibilities, platform branching
- [PostgreSQL Role](references/task-postgresql.md) — db_auth/db_export/db_import for RPM, containerized, and OCP paths; temp container fallback
- [OCP Utils](references/ocp-utils.md) — the 16 task files, secret-mapping table, when each is invoked
- [Artifact Role](references/task-artifact.md) — init/build/package/extract/consume/verify, artifact tar layout, the `consume.yml` block/rescue/always
- [Preflight Role](references/task-preflight.md) — check sequencing, per-component delegation
