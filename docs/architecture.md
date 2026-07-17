# Architecture

## Migration Pipeline Overview

```
 SOURCE (RPM / Containerized / OCP)          TARGET (Containerized / OCP)
 ┌──────────────────────────────────┐        ┌──────────────────────────────┐
 │  1. Preflight                    │        │  1. Preflight                │
 │  2. Initialize artifact          │        │  2. Extract artifact         │
 │  3. Export components            │        │  3. Quiesce target           │
 │     - version, secrets, DB dump  │        │  4. Import DB + secrets      │
 │     - custom configs (RPM)       │        │  5. Resume target            │
 │     - hub content (optional)     │        │  6. Reconcile components     │
 │  4. Package + checksum           │        │                              │
 │  5. Validate artifact            │        │                              │
 └──────────────┬───────────────────┘        └──────────────┬───────────────┘
                │                                           │
                └──────── artifact.tar ─────────────────────┘
```

The collection implements a three-phase migration model:

1. **Export** - extract data from a running AAP deployment into a portable artifact
2. **Import** - restore the artifact into a target AAP deployment
3. **Reconcile** - fix post-import state inconsistencies

## Playbook Structure

### Entry Points

| Playbook | Description |
|----------|-------------|
| `artifact_export.yaml` | Multi-play export workflow (all platforms) |
| `artifact_import.yaml` | Multi-play import workflow (containerized + OCP) |
| `artifact_verify.yaml` | Standalone artifact verification |

### Platform Sub-Playbooks

```
playbooks/
├── artifact_export.yaml              # Main export entry point
├── artifact_import.yaml              # Main import entry point
├── artifact_verify.yaml              # Standalone verification
└── common/
    ├── start_services.yaml           # Ordered service startup
    ├── stop_services.yaml            # Ordered service shutdown
    └── validate_artifact.yaml        # Imported by export for validation
```

The main entry point playbooks (`artifact_export.yaml`, `artifact_import.yaml`)
use the `aap_platform` variable to conditionally execute platform-specific logic
inline. Common service start/stop playbooks are in the `common/` subdirectory.

## Role Reference

### Core Roles

| Role | Purpose | Called By |
|------|---------|----------|
| `artifact` | Artifact lifecycle: init directories, build from exports, package tarball, extract, verify checksums | Entry point playbooks |
| `common` | Normalize inventory groups to universal names (`controller_groups`, etc.) | Entry point playbooks |
| `preflight` | Validate environment and platform before migration | Entry point playbooks |
| `validate_artifact` | Validate artifact structure, schema, required files, checksums | `artifact` role, verify playbook |

### Component Info Roles

These roles provide task entry points for each AAP component. Each contains
sub-tasks for version discovery, secret extraction, database export, preflight
checks, and service management.

| Role | Component | Sub-Tasks |
|------|-----------|-----------|
| `automationcontroller` | Controller | `get_version`, `get_secret`, `db_export`, `preflight`, `stop_service`, `custom_configs` |
| `automationhub` | Hub | `get_version`, `get_secret`, `db_export`, `preflight`, `stop_service` |
| `automationgateway` | Gateway | `get_version`, `get_secret`, `db_export`, `preflight`, `stop_service` |
| `automationeda` | EDA | `get_version`, `get_secret`, `db_export`, `preflight`, `stop_service` |

### Export Roles

| Role | Purpose | Called By |
|------|---------|----------|
| `export_component` | Generic component export orchestrator: version + secrets + DB dump + custom configs | `export_controller`, `export_hub`, `export_gateway`, `export_eda` |
| `export_controller` | Export controller (delegates to `export_component`) | `artifact_export.yaml` |
| `export_hub` | Export hub (delegates to `export_component`) | `artifact_export.yaml` |
| `export_gateway` | Export gateway (delegates to `export_component`) | `artifact_export.yaml` |
| `export_eda` | Export EDA (delegates to `export_component`) | `artifact_export.yaml` |
| `export_hub_content` | Export Pulp content data as tarball | `export_component` (hub only) |

### Import Roles

| Role | Purpose | Called By |
|------|---------|----------|
| `import_component` | Generic component import: DB restore + secret update (OCP and containerized) | `import_controller`, `import_hub`, `import_gateway`, `import_eda` |
| `import_controller` | Import controller (delegates to `import_component`) | `artifact_import.yaml` |
| `import_hub` | Import hub (delegates to `import_component`) | `artifact_import.yaml` |
| `import_gateway` | Import gateway (delegates to `import_component`) | `artifact_import.yaml` |
| `import_eda` | Import EDA (delegates to `import_component`) | `artifact_import.yaml` |

### Reconcile Roles

| Role | Purpose | Called By |
|------|---------|----------|
| `reconcile_gateway` | Run migrations, reset admin password (OCP), delete vestigial objects, remove resource server secret | `artifact_import.yaml` |
| `reconcile_controller` | Find and deprovision orphaned instances (stale heartbeat > 600s), reset admin password (OCP) | `artifact_import.yaml` |
| `reconcile_hub` | Trigger Pulp content repair, reset admin password (OCP) | `artifact_import.yaml` |
| `reconcile_eda` | Run resource sync, reset admin password (OCP) | `artifact_import.yaml` |

### Utility Roles

| Role | Purpose | Called By |
|------|---------|----------|
| `postgresql` | Shared database operations: `db_auth`, `db_export`, `db_import` | Component info roles, `import_component` |
| `ocp_utils` | OCP operations: idle/resume AAP, scale operators, find pods, manage commands, temp resources, artifact transfer | `artifact_import.yaml`, `artifact_export.yaml` (OCP) |
| `receptor` | Stop receptor service | `common/stop_services.yaml` |
| `pcp` | Stop PCP monitoring service | `common/stop_services.yaml` |
| `redis` | Stop Redis service | `common/stop_services.yaml` |

## Shared Role Pattern

Export and import use a delegator pattern to avoid code duplication. The shared
roles (`export_component`, `import_component`) contain all logic and are
parameterized by component name. The per-component roles are thin wrappers:

```yaml
# roles/export_controller/tasks/main.yml
- name: Export controller
  ansible.builtin.include_role:
    name: ansible.aap_snapshot.export_component
  vars:
    export_component_name: "controller"
```

Configuration for each component is centralized in the shared role's defaults:

- `export_component/defaults/main.yml` - `_export_component_config` dict
- `import_component/defaults/main.yml` - `_component_config` dict

This pattern means adding a new component requires only a new entry in the
config dict and a thin wrapper role.

## Plugins

### Modules

| Module | Purpose | Platform |
|--------|---------|----------|
| `aap_component_info` | Discover component version, DB credentials, and secrets by importing Python settings | RPM only |
| `validate_migration_artifact` | Validate artifact structure, manifest schema, required files, and checksums | All |

Module documentation is available via `ansible-doc ansible.aap_snapshot.<module_name>`.

### Filter Plugins

| Filter | Purpose | Example |
|--------|---------|---------|
| `parse_aap_version` | Parse AAP version strings into structured components | `"2.6.3" | ansible.aap_snapshot.parse_aap_version` returns `{major: "2", minor: "6", patch: "3", major_minor: "2.6"}` |

## Inventory Requirements

The collection expects inventory groups matching the AAP component names. The
`common` role normalizes platform-specific group names to universal groups:

| Inventory Group | Universal Group | Component |
|-----------------|-----------------|-----------|
| `automationcontroller` | `controller_groups` | Controller |
| `automationedacontroller` or `automationeda` | `eda_groups` | EDA |
| `automationgateway` | `gateway_groups` | Gateway |
| `automationhub` | `hub_groups` | Hub |

For OCP deployments, inventory targets `localhost` with `connection: local`
since all operations use the Kubernetes API.

Components are optional - the collection only processes components present
in the inventory. An AAP deployment with only controller and gateway will
only export/import those two components.
