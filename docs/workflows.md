# Workflows

Detailed step-by-step descriptions of each migration workflow. For variable
definitions, see [variables.md](variables.md). For artifact format details,
see [artifact-format.md](artifact-format.md).

## Export Workflow

**Playbook:** `artifact_export.yaml`
**Supported platforms:** RPM, containerized, OCP

### Phase 1: Preflight

- Normalizes inventory groups to universal names (`controller_groups`,
  `eda_groups`, `gateway_groups`, `hub_groups`)
- Validates `aap_platform` is set
- Runs per-component preflight checks (verifies component is reachable)

### Phase 2: Initialize Artifact

- Runs on `localhost`
- Creates artifact build directory structure
- Sets timestamp and version variables
- Initializes empty secrets dictionary

### Phase 3: Export Components

- Runs on each component's host group
- For each component present in inventory:
  1. **Get version** - discovers the installed component version
  2. **Get secrets** - extracts Django SECRET_KEY and related credentials
  3. **Database export** - runs `pg_dump --format=custom` to create `.pgc` file
  4. **Custom configs** - controller on RPM only: copies configuration files
  5. **Hub content** - hub only (when `export_hub_content: true`): creates
     tarball of Pulp content directory

**Platform differences:**
- **RPM:** Uses `aap_component_info` module to discover settings by importing
  Python modules. Runs as the component service user (awx, pulp, etc.)
- **Containerized:** Uses `podman exec` to run commands inside component
  containers
- **OCP:** Uses `kubernetes.core` to exec into pods and extract data

### Phase 4: Package

- Runs on `localhost`
- Generates `manifest.yml` from collected metadata
- Writes `secrets.yml` with base64-encoded secrets
- Generates `sha256sum.txt` checksums for all artifact files
- Creates tar archive with timestamp-based filename

### Phase 5: Validate

- Runs `validate_migration_artifact` module against the packaged artifact
- Checks manifest schema version, required files, component data, checksums
- Fails the export if validation errors are found

## Import Workflow

**Playbook:** `artifact_import.yaml`
**Supported platforms:** containerized, OCP

### Phase 1: Preflight

- Normalizes inventory groups
- Asserts `aap_platform` is `containerized` or `operator` (import to RPM is
  not supported)
- Validates `artifact_file` exists on the control node before any destructive
  operations
- OCP: asserts the AAP CR is not already idled from a previous failed run
  (provides `oc patch` recovery command on failure)

### Phase 2: Extract and Validate Artifact

- Runs on `localhost`
- Unpacks the tar archive
- Validates artifact structure and checksums
- Loads `manifest.yml` and `secrets.yml` into variables

### Phase 3: Quiesce Target (OCP)

When `aap_platform: operator`:

1. **Idle AAP** - sets `spec.idle: true` on the AnsibleAutomationPlatform CR
   to pause operator reconciliation
2. **Scale operators to zero** - scales gateway and controller operator
   deployments to 0 replicas

### Phase 3: Quiesce Target (Containerized)

When `aap_platform: containerized`:

- Stops services in order: PCP monitoring, EDA, Hub, Controller, Gateway

### Phase 4: Prepare Migration Resources (OCP only)

- Creates a temporary PVC (`aap-snapshot-temp`, 200Gi default)
- Creates a temporary PostgreSQL deployment with the PVC mounted
- Transfers the artifact to the temporary pod

### Phase 5: Import Databases and Secrets

For each component listed in the artifact manifest:

1. **Extract DB credentials** from the target platform (OCP Secret or
   containerized config)
2. **Restore database** using `pg_restore --clean --if-exists` with the
   admin user. Uses `block/always` to guarantee `CREATEDB` privilege is
   revoked after restore regardless of success/failure
3. **Update secrets** on the target:
   - OCP: patches Kubernetes Secrets with artifact values
   - Containerized: creates/updates podman secrets

**Platform routing:**
- OCP: all imports run on `localhost` using `kubernetes.core.k8s_exec`
  against the temporary PostgreSQL pod
- Containerized: imports run on each component host using
  `community.postgresql` modules

### Phase 6: Cleanup and Resume

**OCP:**
1. Remove temporary migration resources (deployment + PVC)
2. Scale operators back to 1 replica
3. Un-idle AAP (set `spec.idle: false`)

**Containerized:**
- Start services via systemd (monitoring, EDA, Hub, Controller, Gateway,
  execution nodes)

### Phase 7: Reconcile

Post-import state corrections run after services are back up. Each reconcile
role runs conditionally based on whether the component exists in the artifact
manifest.

See [Reconcile Details](#reconcile-details) below.

## Reconcile Details

After database restore, several components need state corrections because
the imported data references infrastructure from the source environment.

### Gateway Reconciliation

1. **Run schema migrations** - executes `aap-gateway-manage migrate` to
   apply any schema differences between source and target
2. **Reset admin password** (OCP) - reads the `admin-password` K8s Secret
   and runs `aap-gateway-manage update_password` to sync the database
   password with the operator-managed secret
3. **Delete vestigial objects** - removes Django model instances that
   reference the source topology:
   - `HTTPPort` objects
   - `ServiceNode` objects
   - `ServiceCluster` objects
   - OCP only: `Route` objects from the OpenShift API
4. **Remove resource server secret** - deletes the `aap-resource-server`
   Kubernetes Secret (OCP only) to force regeneration

These objects are recreated by the operator/installer when AAP reconciles
against the new environment.

### Controller Reconciliation

1. **Find orphaned instances** - queries the Django ORM for Instance objects
   with heartbeats older than 600 seconds (instances from the source cluster
   that will never heartbeat again)
2. **Deprovision orphaned instances** - runs `awx-manage deprovision_instance`
   for each orphaned instance to prevent web UI errors from stale entries
3. **Reset admin password** (OCP) - reads the `controller-admin-password` K8s
   Secret and runs `awx-manage update_password` to sync the database password

### Hub Reconciliation

1. **Trigger Pulp content repair** - sends a POST to
   `/api/galaxy/pulp/api/v3/repair/` via the gateway API to verify content
   checksums and restore integrity after database restore
2. **Reset admin password** (OCP) - reads the `hub-admin-password` K8s Secret
   and runs `pulpcore-manager reset-admin-password` to sync the database
   password

### EDA Reconciliation

1. **Run resource sync** - executes `aap-eda-manage resource_sync` to
   reconcile EDA's internal state with the restored database
2. **Reset admin password** (OCP) - reads the `eda-admin-password` K8s Secret
   and runs `aap-eda-manage update_password` to sync the database password

## Verify Workflow

**Playbook:** `artifact_verify.yaml`
**Supported platforms:** all (runs on localhost)

Standalone artifact verification for validating an artifact without importing
it.

1. **Verify package checksum** - if a checksum file exists alongside the
   artifact, validate integrity before extraction
2. **Extract artifact** - unpack to a temporary location
3. **Run validation** - execute `validate_migration_artifact` module to check
   manifest schema, required files, and internal checksums
4. **Report results** - display validation report
5. **Cleanup** - remove temporary extraction directory
