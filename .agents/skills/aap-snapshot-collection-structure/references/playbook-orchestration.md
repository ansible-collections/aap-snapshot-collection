# Playbook Orchestration

## Boilerplate Enforced on Every Play

The custom ansible-lint rule `custom-play-boilerplate`
(`rules/play_boilerplate.py`) requires every play (that isn't an
`import_playbook`) to explicitly set:

```yaml
gather_facts: false
any_errors_fatal: true
```

Most plays also set `max_fail_percentage: 0`. None of the three entry-point
playbooks use `tags:` — every conditional inclusion is via `when:` on
`aap_platform`, `_snapshot_operation`, or inventory group membership
(`groups['controller_groups']`, `inventory_hostname in groups.get(...)`).

## `playbooks/artifact_export.yaml`

| # | Hosts | Role/tasks_from | Purpose |
|---|-------|------------------|---------|
| 1 | `all` | `common` → `set_groups.yml`, then `preflight` → `main.yml` | Build inventory groups, validate the source environment |
| 2 | `localhost` | `artifact` → `init.yml` | Create the build directory structure |
| 3 | `controller_groups:eda_groups:gateway_groups:hub_groups` | `artifact` → `build.yml` | Loop over the 4 components; each calls its own `export.yml` |
| 4 | `localhost` | `artifact` → `package.yml` | Template `manifest.yml`, write `secrets.yml`/`sha256sum.txt`, tar, checksum |
| 5 | — | `import_playbook: common/validate_artifact.yaml` | Validate the artifact that was just built |

## `playbooks/artifact_import.yaml`

Sets `vars: _snapshot_operation: import` on the first play.

| # | Hosts | Role/tasks_from | Condition |
|---|-------|------------------|-----------|
| 1 | `all` | `common/set_groups.yml`, then `preflight/main.yml` | `set_groups.yml` skipped `when: aap_platform | default('') != 'operator'` |
| 2 | `localhost, connection: local` | `artifact/extract.yml` | sets `_artifact_path`, `artifact_filename`, `artifact_dir` |
| 3 | `localhost` | `artifact/consume.yml` | `when: aap_platform == 'operator'` |
| 4 | `controller_groups:eda_groups:gateway_groups:hub_groups` | `artifact/consume.yml` | `when: aap_platform == 'containerized'` |
| 5 | `localhost, connection: local` | migration summary / advisory debug messages | `when: artifact_manifest is defined` or `aap_platform == 'containerized'` |

Note that `consume.yml` is the single task file that does both containerized
and operator import — it internally branches on `aap_platform`, rather than
having separate per-platform playbook plays.

## `playbooks/artifact_verify.yaml`

Single play, `hosts: localhost`, `connection: local`, `become: false`
(verification never needs privilege escalation):

1. `ansible.builtin.unarchive` the artifact to a temp dir
2. Call the `validate_migration_artifact` module
3. Print the report
4. Remove the temp dir

## `playbooks/common/validate_artifact.yaml`

Single play, `hosts: localhost`: unarchive
`{{ __artifact_dest_dir }}/{{ __artifact_filename }}`, then
`include_role: validate_artifact` with
`validate_artifact_dir: "{{ __artifact_dest_dir }}/{{ __artifact_build_dir | basename }}"`,
then clean up. This is `import_playbook`'d from the tail of
`artifact_export.yaml` — it validates the artifact you just exported, it is
not used at import time (import-time validation happens inside
`artifact/extract.yml` and the preflight checks).

## `playbooks/common/start_services.yaml` / `stop_services.yaml`

Standalone utility playbooks — **not included by `artifact_export.yaml` or
`artifact_import.yaml`**. Five ordered plays each, keyed on overridable
host-group variables (`_start_eda_hosts | default('eda_groups')`, etc.):

- **Stop order**: monitoring (`pcp`) → EDA → Hub → Controller → Gateway
- **Start order**: EDA → Hub → Controller → Gateway → monitoring (`pcp`)

Each play does `include_role: ansible.aap_snapshot.<automationX>,
tasks_from: stop_service.yml` (or `start_service.yml`).

**Important**: the containerized import path inside `roles/artifact/tasks/consume.yml`
re-implements this same stop/start sequence inline (per-host `when:
inventory_hostname in groups.get(...)` blocks) rather than calling these
playbooks. If you change component stop/start ordering or add a new
component to one, you must update the other to match — there is no single
source of truth for this sequence today.
