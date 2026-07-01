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
| `export_hub_content` | `true` | Include Pulp content data (`/var/lib/pulp/`) in artifact |
| `postgresql_db_type` | `managed` | Database topology: `managed` (co-located) or `external` |

### Hub Content Export

| Variable | Default | Description |
|----------|---------|-------------|
| `hub_pulp_data_dir` | `/var/lib/pulp/` | Pulp content directory on hub host |
| `hub_content_tar_name` | `hub-content.tar.gz` | Filename for the content tarball |

### Database Export

| Variable | Default | Description |
|----------|---------|-------------|
| `postgresql_export_dir` | `/tmp/backups/automation-platform` | Temp directory on source host for database dumps |
| `postgresql_export_dest` | `$PWD/db_export` | Local directory to fetch database dumps to |
| `postgresql_export_extension` | `pgc` | Database dump file extension (PostgreSQL custom format) |

## Import Variables

Control artifact restoration to the target platform.

| Variable | Default | Description |
|----------|---------|-------------|
| `artifact_file` | (required) | Path to the artifact archive to import. Validated at preflight before any destructive operations |
| `target_aap_version` | (optional) | Target AAP version for compatibility validation |
| `keep_temp_on_failure` | `true` | Keep temporary OCP migration resources (PVC, pod) on failure for debugging. Set `false` to auto-cleanup |
| `postgresql_restore_admin_user` | `postgres` | PostgreSQL superuser for database restore operations |
| `postgresql_restore_timeout` | `3600` | Async timeout in seconds for `pg_restore` |

## OCP (Operator) Variables

Apply when `aap_platform: operator`. Control interaction with the OpenShift
cluster and AAP operator.

### Namespace and Instance

| Variable | Default | Description |
|----------|---------|-------------|
| `ocp_namespace` | `aap` | OpenShift namespace where AAP is deployed |
| `operator_namespace` | `{{ ocp_namespace }}` | Namespace where operator deployments live. Override to `openshift-operators` for cluster-scoped installations |
| `aap_instance_name` | `aap` | Name of the AnsibleAutomationPlatform CR |
| `aap_cr_kind` | `AnsibleAutomationPlatform` | Kubernetes kind for the AAP CR |
| `aap_cr_api_version` | `aap.ansible.com/v1alpha1` | API version for the AAP CR |

### Temporary Migration Resources

During OCP import, a temporary PVC and PostgreSQL pod are created to perform
database restores. These are cleaned up after import completes.

| Variable | Default | Description |
|----------|---------|-------------|
| `temp_pvc_name` | `aap-snapshot-temp` | Name for the temporary PVC |
| `temp_pvc_size` | `200Gi` | Size of the temporary PVC (see sizing guidance below) |
| `temp_pvc_access_mode` | `ReadWriteOnce` | PVC access mode |
| `temp_deployment_name` | `aap-snapshot-temp-postgres` | Name for the temporary PostgreSQL deployment |
| `temp_postgres_image` | `registry.redhat.io/rhel9/postgresql-15:latest` | Container image for the temporary PostgreSQL pod |

**Sizing `temp_pvc_size`:** The PVC must hold the artifact tarball and its extracted contents
simultaneously, so set it to at least **2× your artifact file size**. The 200Gi default is
appropriate for large production deployments; on storage-constrained clusters (CRC, single-node
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

### EDA Reconciliation

| Variable | Default | Description |
|----------|---------|-------------|
| `eda_container_name` | `automation-eda-api` | EDA container name for manage commands |
| `eda_manage_cmd` | `aap-eda-manage` | Django manage command for EDA |

## Artifact Validation

| Variable | Default | Description |
|----------|---------|-------------|
| `validate_artifact_dir` | `""` | Directory containing the extracted artifact to validate |
| `validate_supported_schema_versions` | `["1.0"]` | List of accepted artifact schema versions |
