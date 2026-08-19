# Artifact Format (SDP v1.0)

The migration artifact is a portable tar archive containing database dumps,
secrets, and metadata from an AAP deployment. It is produced by the export
workflow and consumed by the import workflow.

## Directory Structure

```
aap-snapshot-<version>-<date>.tar
  artifact/
  ├── controller/
  │   ├── controller.pgc             # PostgreSQL custom-format dump
  │   └── custom_configs/            # RPM-only: configuration files
  ├── hub/
  │   ├── hub.pgc                    # PostgreSQL custom-format dump
  │   └── hub-content.tar.gz         # Optional: Pulp content data
  ├── gateway/
  │   └── gateway.pgc               # PostgreSQL custom-format dump
  ├── eda/
  │   └── eda.pgc                   # PostgreSQL custom-format dump
  ├── manifest.yml                   # Artifact metadata and component list
  ├── secrets.yml                    # Base64-encoded secrets
  └── sha256sum.txt                  # File integrity checksums
```

Component directories are only present if the source deployment includes that
component. The artifact is self-describing - the manifest lists which
components were exported.

## manifest.yml

The manifest describes the artifact contents and source environment.

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | string | Always `"1.0"` for this format |
| `aap_version` | string | Major.minor version (e.g. `"2.6"`) |
| `aap_version_patch` | string | Patch version (e.g. `"3"`) |
| `source_topology` | string | Source platform: `rpm`, `containerized`, or `operator` |
| `export_timestamp` | string | ISO 8601 timestamp of export |
| `exported_by` | string | Collection name and version (e.g. `"ansible.aap_snapshot/1.0.0"`) |

### components

Array of exported components. Each entry:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Component identifier: `controller`, `hub`, `gateway`, `eda` |
| `version` | string | Component version string |
| `database_name` | string | PostgreSQL database name (e.g. `awx`, `automationhub`) |
| `has_custom_configs` | boolean | Whether custom configuration files are included |
| `has_content_data` | boolean | Hub only: whether Pulp content tarball is included |

### database

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | `managed` (co-located) or `external` (remote database) |
| `postgresql_version` | string | PostgreSQL major version (e.g. `"15"`) |

### checksums

| Field | Type | Description |
|-------|------|-------------|
| `algorithm` | string | Hash algorithm used (default: `sha256`) |
| `file` | string | Checksum file name (default: `sha256sum.txt`) |

### Example

```yaml
schema_version: "1.0"
aap_version: "2.6"
aap_version_patch: "3"
source_topology: "rpm"
export_timestamp: "2026-05-20T10:30:00Z"
exported_by: "ansible.aap_snapshot/1.0.0"

components:
  - name: controller
    version: "4.6.3"
    database_name: "awx"
    has_custom_configs: true
  - name: hub
    version: "4.10.3"
    database_name: "automationhub"
    has_custom_configs: false
    has_content_data: true
  - name: gateway
    version: "1.1.3"
    database_name: "gateway"
    has_custom_configs: false
  - name: eda
    version: "1.1.3"
    database_name: "automationedacontroller"
    has_custom_configs: false

database:
  type: "managed"
  postgresql_version: "15"

checksums:
  algorithm: sha256
  file: sha256sum.txt
```

## secrets.yml

An Ansible vars file containing base64-encoded secrets extracted from the
source deployment. Secret keys vary by component:

| Key | Component | Description |
|-----|-----------|-------------|
| `controller_secret_key` | Controller | Django SECRET_KEY |
| `hub_secret` | Hub | Django SECRET_KEY |
| `hub_db_fields_encryption_key` | Hub | Database field encryption key |
| `gateway_secret_key` | Gateway | Django SECRET_KEY |
| `eda_secret_key` | EDA | Django SECRET_KEY |
| `controller_db_password` | Controller | Database password |
| `hub_db_password` | Hub | Database password |
| `gateway_db_password` | Gateway | Database password |
| `eda_db_password` | EDA | Database password |

During import, secrets are restored to the target platform's secret store
(Kubernetes Secrets for OCP, podman secrets for containerized).

## Component Data

### Database Dumps

Each component directory contains a PostgreSQL custom-format dump (`.pgc`)
created with `pg_dump --format=custom`. These are restored with `pg_restore`
during import using `--clean --if-exists` flags to handle existing schemas.

Default database names:

| Component | Database | Default Name |
|-----------|----------|-------------|
| Controller | `controller.pgc` | `awx` |
| Hub | `hub.pgc` | `automationhub` |
| Gateway | `gateway.pgc` | `gateway` |
| EDA | `eda.pgc` | `automationedacontroller` |

### Custom Configs (Controller, RPM only)

When exporting from an RPM deployment, the controller directory includes a
`custom_configs/` subdirectory with configuration files specific to that
installation.

### Hub Content Data (Optional)

When `export_hub_content: true` (the default), the hub directory includes
`hub-content.tar.gz` - a tarball of the Pulp content directory
(`/var/lib/pulp/`). This preserves collection and execution environment
artifacts stored on disk outside the database.

## Integrity

`sha256sum.txt` contains SHA-256 checksums for all files in the artifact,
generated during the package phase. Format follows the standard `sha256sum`
output:

```
<hash>  controller/controller.pgc
<hash>  hub/hub.pgc
<hash>  hub/hub-content.tar.gz
<hash>  gateway/gateway.pgc
<hash>  eda/eda.pgc
<hash>  manifest.yml
<hash>  secrets.yml
```

The `validate_migration_artifact` module verifies these checksums during the
validation phase of both export and import workflows.

## Versioning

The `schema_version` field identifies the artifact format version. The
`artifact` role maintains an internal list of supported schema versions.
Artifacts with unrecognized schema versions are rejected during validation.

The `aap_version` and `aap_version_patch` fields record the source platform
version. These can be used to enforce version compatibility policies during
import (e.g. preventing cross-major-version migrations).
