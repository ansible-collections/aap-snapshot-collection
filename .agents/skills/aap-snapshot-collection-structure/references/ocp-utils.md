# OCP Utils Role (`roles/ocp_utils`)

Unlike the per-component delegator roles, `ocp_utils` is a **flat toolbox**
— 16 independent task files, each invoked à la carte with `tasks_from:`
from many other roles and from `roles/artifact/tasks/consume.yml`. There is
no `main.yml` and no implied ordering between the files; each is a
self-contained unit of OCP/Kubernetes interaction.

## Task Files

| File | Purpose |
|---|---|
| `check_aap_cr.yml` | Validate the target AAP Custom Resource exists/is ready |
| `cleanup_temp_resources.yml` | Remove temp PVCs/pods created during import |
| `create_aap_cr.yml` | Create a fresh AAP CR (fresh-namespace import path) |
| `create_temp_resources.yml` | Create temp PVC/pod used to transfer the artifact into the cluster |
| `delete_controller_migration_jobs.yml` | Clean up leftover controller migration Jobs |
| `delete_hub_file_storage_pvc.yml` | Remove hub's file-storage PVC (content re-import path) |
| `discover_components.yml` | Find which components exist in the target cluster |
| `discover_pod.yml` / `find_pod.yml` | Locate a component's running pod by label selector |
| `get_db_credentials.yml` | Read DB credentials from a K8s Secret |
| `idle_aap.yml` | Idle the AAP CR (scale down) before import |
| `run_manage_command.yml` | Exec a Django `manage.py`-style command in a pod |
| `scale_operators.yml` | Scale operator deployments up/down |
| `set_secret_mapping.yml` | Apply the secret-mapping table below |
| `transfer_artifact.yml` | Copy the artifact tarball into the temp pod/PVC |
| `wait_aap_ready.yml` | Poll until the AAP CR reports ready |

## Secret Mapping Table

`__ocp_utils_artifact_secret_mapping` (defined in this role) is the master
table of component → K8s Secret name → field → artifact key, and
`__ocp_utils_component_postgres_secrets` maps components to their DB
credential secrets. Both are consumed across `postgresql`, `operations`,
and `artifact/consume.yml`. **If you add a new secret a component needs
during import, add it here** rather than hardcoding a secret name/field in
the calling role — this table is what keeps secret restoration consistent
across components.

## Where It's Called From

- `roles/postgresql/tasks/db_auth.yml` and `db_export.yml`/`db_import.yml`
  (OCP branches) call `get_db_credentials.yml`, pod discovery, and
  transfer/cleanup tasks.
- `roles/operations/tasks/*` call `run_manage_command.yml`,
  `discover_pod.yml`, and secret tasks for OCP-platform component
  operations.
- `roles/artifact/tasks/consume.yml` orchestrates the OCP import's
  scale-down/create-temp/transfer/scale-up/cleanup sequence by calling
  several of these task files in order inside its `block/rescue/always`
  (see [Artifact Role](task-artifact.md)).
- `roles/automationhub/tasks/import_hub_content.yml` calls PVC discovery
  and temp-resource tasks to mount both the migration PVC and the hub
  file-storage PVC together.

Because there's no enforced calling order, when adding a new OCP-path
feature, trace forward from `artifact/consume.yml` to see the actual
sequence in effect for the flow you're touching, rather than assuming a
canonical order from this file list alone.
