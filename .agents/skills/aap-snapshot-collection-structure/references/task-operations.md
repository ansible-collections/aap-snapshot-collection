# Operations Engine (`roles/operations`)

This is the role `docs/architecture.md` refers to (inaccurately) as
`export_component`/`import_component`. It's the actual generic engine that
every per-component delegator role (`automationcontroller`, `automationeda`,
`automationgateway`, `automationhub`) calls into.

## `_operations_component_config`

Defined in `roles/operations/vars/main.yml`, a dict keyed by component name
(`controller`/`eda`/`gateway`/`hub`). Every task file's first task is:

```yaml
- name: Resolve the current component's config
  ansible.builtin.set_fact:
    _operations_current_component: "{{ _operations_component_config[component_name] }}"
```

Known fields (add new ones here when a new component needs behavior none of
the existing four have — don't special-case `component_name` inline in a
task file):

| Field | Purpose |
|---|---|
| `manage_cmd` | The Django `manage.py`-equivalent command name |
| `django_user` | OS user to `become` as for RPM manage/secret access |
| `container_name` | Podman container name (containerized platform) |
| `python_package` | Python package name for RPM-side introspection |
| `secret_keys` | Which secret fields to extract/restore |
| `k8s_secret_name` / `k8s_secret_field` | OCP secret location for this component |
| `postgres_secret` | Name of the K8s secret holding DB credentials |
| `podman_secret_name` / `podman_secrets` | Containerized secret names |
| `admin_password_secret` / `admin_password_cmd` | How to reset the admin password |
| `services` | Fixed list of systemd services (used by simple start/stop) |
| `has_worker_discovery` | Use the worker-discovery start/stop pattern instead of a fixed `services` list (EDA, Hub) |
| `has_custom_configs` | Component has extra config files to export (controller) |
| `has_db_partitions` | Component's DB needs partitions pre-created before restore (controller) |
| `has_hub_content` | Component has non-DB content storage to export/import (hub) |
| `has_aap_version` | Whether version discovery applies to this component |
| `django_environment` | Env vars needed to run manage commands |
| `django_manage_get_cmd` | How to invoke a read-only manage command |
| `ocp_extra_secrets` | Additional K8s secrets to fetch beyond the primary one |
| `multi_resource_keys` | Component has more than one K8s resource to look up |
| `static_services` | Non-worker services always started/stopped alongside worker discovery |
| `worker_service_pattern` | Glob/prefix pattern used to discover worker systemd units |

## Task Files and Platform Branching

Every task file branches on `aap_platform` (`rpm` | `containerized` |
`operator`) after resolving `_operations_current_component`:

- **`get_version.yml`** — discovers the component's AAP version (RPM: via
  `aap_component_info`; containerized: podman exec; OCP: pod exec), gated by
  `has_aap_version`.
- **`get_secret.yml`** — RPM: `become_user: "{{ ...django_user }}"` +
  `aap_component_info` module; containerized: podman secret inspect; OCP:
  `ocp_utils/get_db_credentials.yml`-style K8s secret read.
- **`db_export.yml`** — for controller, pre-creates DB partitions
  (`has_db_partitions`) via a manage command, then delegates to
  `postgresql/db_export.yml`.
- **`db_import.yml`** — delegates to `postgresql/db_import.yml`.
- **`get_db_credentials.yml`** — resolves DB host/port/name/user/password
  per platform.
- **`update_secret.yml`** — writes a secret back during import (containerized
  podman secret, or OCP K8s secret).
- **`set_config.yml`** — writes component config (used with
  `has_custom_configs`).
- **`preflight.yml`** — asserts the source and target AAP versions match via
  `ansible.builtin.assert ... is version(...)`.
- **`reset_admin_password.yml`** — called from every component's
  `reconcile.yml` after import.
- **`detect_django_version_ocp.yml`** — Django ≥ 5 needs a `--no-imports`
  flag on `manage shell`; this task detects which flag to use.
- **`start_service.yml`/`stop_service.yml`** — two patterns: a fixed
  `services` list, or (when `has_worker_discovery` is true, for EDA/Hub) a
  discovery pattern using `ansible.builtin.find` on
  `~/.config/systemd/user` to enumerate worker units matching
  `worker_service_pattern`.

## Secrets and Logging

Every task in this role that touches a password, token, or secret key uses
`no_log: "{{ __operations_no_log }}"`, where `__operations_no_log` is
defined once in `roles/operations/defaults/main.yml` as
`{{ not (disable_no_log | default(false) | bool) }}`. See the
aap-ansible-conventions skill for the full rule and the custom lint check
that enforces it.
