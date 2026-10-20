# Variable Reference

All user-configurable variables for the ansible.aap_snapshot collection, organized by
workflow phase. Variables prefixed with `_` are internal and should not be
overridden.

## Common Variables

These apply to both export and import workflows.

| Variable | Default | Description |
|----------|---------|-------------|
| `aap_platform` | (required) | Source/target platform: `rpm`, `containerized`, or `operator` |
| `artifact_dir` | `$PWD` | Directory where the artifact is created (export) or read from (import) |
| `artifact_file` | (required for import/verify) | Path to the artifact archive |
| `disable_no_log` | `false` | Set `true` to show sensitive values in output for debugging |

## Export Variables

Control artifact creation and packaging.

### Artifact Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `artifact_build_dir` | `$PWD/artifact` | Working directory for building the artifact |
| `artifact_dest_dir` | `$PWD` | Where the final tar archive is placed |
| `artifact_prefix` | `aap-snapshot` | Filename prefix for the tar archive |
| `artifact_extension` | `tar` | File extension for the tar archive |
| `artifact_checksum_algo` | `sha256` | Hash algorithm for integrity checksums |

### Export Control

| Variable | Default | Description |
|----------|---------|-------------|
| `artifact_export_hub_content` | `true` | Include Pulp content data in the artifact; OCP export supports file-storage PVCs. Set to `false` to omit it when Hub content is transferred separately. |
| `automationhub_export_hub_content` | `true` | Hub role alias for the export toggle. This controls export, not restoration during import. |
| `postgresql_db_type` | `managed` | Database topology: `managed` (co-located) or `external` |

### Hub Content Export

| Variable | Default | Description |
|----------|---------|-------------|
| `automationhub_pulp_data_dir` | `/var/lib/pulp/media` | Source content directory for RPM Hub export. Containerized export discovers the Pulp media directory from the Hub container's mounts instead. |
| `automationhub_content_tar_name` | `hub_content.tar` | Filename of the uncompressed Hub content tar archive used during export and restoration. |
| `automationhub_content_staging_dir` | `/tmp` | Directory on the source Hub host where the content archive is staged during export. Set to a larger filesystem if `/tmp` is too small for the Hub content. |

### Database Export

| Variable | Default | Description |
|----------|---------|-------------|
| `postgresql_export_dir` | `/tmp/backups/automation-platform` | Temp directory on source host for database dumps |
| `postgresql_export_dest` | `$PWD/db_export` | Local directory to fetch database dumps to |
| `postgresql_export_extension` | `pgc` | Database dump file extension (PostgreSQL custom format) |
| `postgresql_export_rsync_opts` | `[]` | Additional rsync options for database dump transfers; the role applies `--chmod=F600` after these options |

## Import Variables

Control artifact restoration to the target platform.

| Variable | Default | Description |
|----------|---------|-------------|
| `artifact_file` | (required) | Path to the artifact archive to import. Validated at preflight before any destructive operations |
| `target_aap_version` | (optional) | Target AAP version for compatibility validation |
| `keep_temp_on_failure` | `true` | Keep temporary OCP migration resources (PVC, pod) on failure for debugging. Set `false` to auto-cleanup |
| `postgresql_restore_admin_user` | `postgres` | PostgreSQL superuser for database restore operations |
| `postgresql_restore_timeout` | `3600` | Async timeout in seconds for `pg_restore` |
| `postgresql_temp_container_image` | `registry.redhat.io/rhel9/postgresql-15:latest` | Image used for the throwaway postgres client container that runs `pg_dump`/`pg_restore` on containerized targets. Override if your target's PostgreSQL server version differs |

### Hub Content Import

| Variable | Default | Description |
|----------|---------|-------------|
| `automationhub_import_hub_content` | `true` | Restore Hub (Pulp) content on containerized targets. Set to `false` to skip content restoration when content is transferred separately. This variable does not control operator content restoration or disable the storage-backend check. |

Hub content restoration supports only file-based target storage. For
S3-compatible or Azure Blob targets, transfer the content separately and
pre-populate the target storage before importing an artifact exported with
`automationhub_export_hub_content=false`. If the artifact includes Hub content,
both containerized and operator imports reject object-storage targets; setting
`automationhub_import_hub_content=false` does not prevent that rejection.
Operator content restoration is controlled by whether the artifact contains Hub
content, rather than by this import toggle. See
[Automation Hub Content Storage](../README.md#automation-hub-content-storage)
for the preparation steps.

## OCP (Operator) Variables

Apply when `aap_platform: operator`. Control interaction with the OpenShift
cluster and AAP operator.

For export, use a localhost inventory and provide kubeconfig access to inspect
the AAP/component CRs and secrets, execute commands in component pods, and copy
files from pods. OCP-source artifacts include a sanitized `aap_cr.yml`
reference. Hub content is supported only on file-storage PVCs; set
`artifact_export_hub_content: false` to omit it when Hub uses S3 or Azure Blob.

### Namespace and Instance

| Variable | Default | Description |
|----------|---------|-------------|
| `ocp_namespace` | `aap` | OpenShift namespace where AAP is deployed |
| `operator_namespace` | `{{ ocp_namespace }}` | Namespace where operator deployments live. Override to `openshift-operators` for cluster-scoped installations |
| `aap_instance_name` | `aap` | Name of the AnsibleAutomationPlatform CR |
| `aap_cr_kind` | `AnsibleAutomationPlatform` | Kubernetes kind for the AAP CR |
| `aap_cr_api_version` | `aap.ansible.com/v1alpha1` | API version for the AAP CR |
| `postgresql_ocp_postgres_statefulset` | `{{ aap_instance_name }}-postgres-15` | Managed PostgreSQL StatefulSet name used to find the source pod during OCP export; when no running pod matches, export creates a temporary PostgreSQL client pod |

### Temporary Migration Resources

During OCP import, a temporary PVC and PostgreSQL pod are created to perform
database restores. These are cleaned up after import completes.

| Variable | Default | Description |
|----------|---------|-------------|
| `temp_pvc_name` | `aap-snapshot-temp` | Name for the temporary PVC |
| `temp_pvc_size` | `60Gi` | Size of the temporary PVC (see sizing guidance below) |
| `temp_pvc_access_mode` | `ReadWriteOnce` | PVC access mode |
| `temp_deployment_name` | `aap-snapshot-temp-postgres` | Name for the temporary PostgreSQL deployment |
| `temp_postgres_image` | `registry.redhat.io/rhel9/postgresql-15:latest` | Container image for the temporary PostgreSQL client pod used during OCP import or when OCP export has no managed PostgreSQL pod |

**Sizing `temp_pvc_size`:** The PVC must hold the artifact tarball and its extracted contents
simultaneously, so set it to at least **2x your artifact file size**. The 60Gi default is
appropriate for most deployments; on storage-constrained clusters (CRC, single-node
MicroShift, or clusters with limited thin-pool capacity) provision too little and the temporary
pod stays `Pending` indefinitely. Override in your inventory:

```ini
# For a ~1Gi artifact on a lab cluster
temp_pvc_size=10Gi
```

### Operator Management

| Variable | Default | Description |
|----------|---------|-------------|
| `postgres_statefulset` | `aap-postgres-15` | StatefulSet name for PostgreSQL pod discovery |
| `gateway_operator_deployment` | `aap-gateway-operator-controller-manager` | Gateway operator Deployment name |
| `controller_operator_deployment` | `automation-controller-operator-controller-manager` | Controller operator Deployment name |

### Timing Controls

| Variable | Default | Description |
|----------|---------|-------------|
| `idle_wait_retries` | `60` | Retry count when waiting for AAP to idle |
| `idle_wait_delay` | `10` | Seconds between idle status checks |
| `scale_wait_retries` | `30` | Retry count when waiting for operator scale |
| `scale_wait_delay` | `10` | Seconds between scale status checks |

## Reconcile Variables

Post-import reconciliation settings.

### Gateway Reconciliation

| Variable | Default | Description |
|----------|---------|-------------|
| `gateway_container_name` | `automation-gateway` | Gateway container name for manage commands |
| `gateway_manage_cmd` | `aap-gateway-manage` | Django manage command for gateway |
| `resource_server_secret_name` | `aap-resource-server` | OCP Secret to delete for resource server cleanup |

### Controller Reconciliation

| Variable | Default | Description |
|----------|---------|-------------|
| `controller_container_name` | `automation-controller-task` | Controller container name for manage commands |
| `controller_manage_cmd` | `awx-manage` | Django manage command for controller |

### Hub Reconciliation

| Variable | Default | Description |
|----------|---------|-------------|
| `gateway_admin_user` | `admin` | Admin username for Pulp repair API call |
| `gateway_admin_password` | (required) | Admin password for Pulp repair API call |
| `gateway_hostname` | (required) | Gateway hostname for Pulp repair API endpoint |
| `validate_certs` | `false` | Whether to validate TLS certificates for API calls |
| `automationhub_pulp_repair_retries` | `120` | Number of polling attempts for the Pulp repair async task |
| `automationhub_pulp_repair_delay` | `30` | Seconds between polling attempts (total timeout = retries x delay) |

### EDA Reconciliation

| Variable | Default | Description |
|----------|---------|-------------|
| `eda_container_name` | `automation-eda-api` | EDA container name for manage commands |
| `eda_manage_cmd` | `aap-eda-manage` | Django manage command for EDA |
