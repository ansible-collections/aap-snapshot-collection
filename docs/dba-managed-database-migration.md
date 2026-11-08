# DBA-managed database migration

This workflow separates database restoration from collection-managed configuration,
application keys, Hub media, and reconciliation. Its initial scope is **RPM AAP 2.6
to OCP AAP 2.6**, with Controller, Gateway, Hub and EDA. It is an implementation
PoC; complete live RPM/OCP acceptance remains outstanding.

Ordinary exports and imports retain their automatic database migration behavior.
Set `postgres_skip_data: true` explicitly on both sides for this workflow.
Skipping dump/restore still permits database reads. Finalization resumes operators,
runs application schema migrations and reconciliation, and can write to databases.
Do not use this workflow as an unvalidated shared-database cutover procedure.

## Responsibilities and backups

The platform administrator owns source shutdown, inventory, configuration/keys,
consistent Hub media capture, target holds, and application acceptance. The DBA owns
all included database backups/restores, target provisioning, ownership, extensions,
ACLs, restore error review, and data completeness checks. Agree on exact component
builds and PostgreSQL compatibility before scheduling downtime. Matching the AAP
minor version alone does not establish application schema compatibility.

Back up both deployments, target databases, target application Secrets, and Hub
media. Keep the non-database artifact paired with the DBA backup set from the same
quiesced source. The artifact contains credentials and application keys; restrict
access and retain it securely. A checksum detects corruption; it is not a signature
or proof of provenance. Use a trusted artifact and trusted checksum sidecar.

Deploy the target using disposable/empty target databases first and let installation
finish. Configure its intended application database Secrets, connectivity and TLS
before preparation. Do not let an active target connect to the source databases.
The migration checks do not provision databases, roles, extensions, network access,
or certificates. The application user must own its application tables (or inherit
the owning role), have the required DML/sequence privileges, database CREATE and
schema USAGE/CREATE. Hub requires `hstore`; source extension schemas must match.

## Quiesce RPM and export without dumps

1. Drain Controller jobs and EDA activations, schedules, external integrations and
   callbacks. Complete or cancel Hub sync/import/upload tasks and container pushes.
2. Use the shutdown procedure appropriate to the actual RPM installation to stop
   every application writer on every node, including workers, schedulers, receptor
   and any custom integration writers. Keep the source stopped through the final
   database and media captures. Stop HTTP entry points as appropriate.
3. Confirm no source writers or database-writing sessions remain. Known service
   checks below supplement this administrator check; they cannot discover every
   external writer. The collection's `playbooks/common/stop_services.yaml` helpers
   target containerized deployments and are **not an RPM shutdown procedure**.
4. Have the DBA capture the final databases and identify the matching media point.

Example `rpm-export.yml` (use the normal RPM installer inventory with the actual
source component groups and access settings):

```yaml
---
aap_platform: rpm
postgres_skip_data: true
artifact_source_quiesced: true
artifact_dest_dir: /srv/migrations
artifact_build_dir: /srv/migrations/artifact
export_hub_content: true
...
```

```bash
ansible-playbook -i source.ini playbooks/artifact_export.yaml -e @rpm-export.yml
```

The maintenance preflight permits intentionally stopped services, checks known RPM
writers are stopped, and omits HTTP health checks. Package/version, key/configuration
and database metadata discovery still run. No `pg_dump`, `pg_restore` or Controller
partition preparation is run. Keep the PostgreSQL server available for bounded
metadata reads and install the normal RPM export Python/PostgreSQL dependencies.

These exports use artifact schema **1.2**, with an explicit
`has_database_dump: false` on every component and source database metadata where
available. All payload files, including the manifest, secrets, configuration and
optional Hub content, have SHA-256 entries. An artifact without dumps or Hub media
is valid. Do not remove dumps from a legacy artifact or edit its manifest to create
an omission: missing legacy dumps/checksums remain errors. Automatic import rejects
an omitted-dump artifact before downtime. Normal exports retain schema 1.1.

## Prepare the OCP target and hand off

Use a shared `manual-import.yml` for every phase. `artifact_file` must continue to
refer to the same archive bytes. Place it in a dedicated migration directory with
no stale extracted payloads from other artifacts. Set the selected AAP instance explicitly when the
namespace contains multiple deployments. Database credentials remain in the target's
operator-managed/configured application Secrets, independently for each component.
They are never read from source connection values for target validation.

```yaml
---
aap_platform: operator
postgres_skip_data: true
artifact_file: /srv/migrations/aap-snapshot-2.6-example.tar
kubeconfig: /home/admin/.kube/config
ocp_namespace: aap
aap_instance_name: production
operator_namespace: aap
ocp_utils_operator_namespace: aap
# Optional; use an image supported by the target PostgreSQL server.
postgresql_temp_container_image: registry.redhat.io/rhel9/postgresql-15:latest
# Honor sslmode from each configured application Secret; these are explicit
# per-component overrides. CA Secrets are namespace-local and mounted read-only.
postgresql_ocp_ssl_options:
  controller: {sslmode: verify-full}
  gateway: {sslmode: verify-full}
  hub: {sslmode: verify-full}
  eda: {sslmode: verify-full}
postgresql_ocp_ssl_rootcert_secrets:
  controller: {name: controller-database-ca, key: ca.crt}
  gateway: {name: gateway-database-ca, key: ca.crt}
  hub: {name: hub-database-ca, key: ca.crt}
  eda: {name: eda-database-ca, key: ca.crt}
...
```

If operators are installed in another namespace, set `operator_namespace` for
operator-version discovery and `ocp_utils_operator_namespace` for auxiliary
operator holds to that namespace.

Omit the CA/SSL mappings where they are not required by the target's configuration;
do not copy the example host or certificate assumptions to an unrelated deployment.
For client certificate authentication, supply paths through
`postgresql_ocp_ssl_options` and appropriate read-only mounts through
`postgresql_ocp_ssl_extra_volumes` and `postgresql_ocp_ssl_extra_mounts` only if they
are configured consistently with the temporary pod. The current automatic CA
mounting interface provides root CA Secrets, not client certificate provisioning.

```bash
ansible-playbook -i target.ini playbooks/artifact_import.yaml \
  -e @manual-import.yml -e artifact_import_phase=prepare
```

Preparation validates the artifact, discovers target versions/configuration while
application pods are available, stages the archive and captures original idle and
replica settings. It writes a namespace-local ConfigMap named
`<AAP-name-up-to-40-characters>-snapshot-migration`, bound to the target CR UID,
archive SHA-256 and included components. It retains resource UIDs/names, target
versions, progress and sanitized validation results, with **no credentials or
application keys**. Temporary PVC/deployment names include the target UID and
archive digest. Retain the record and temporary PVC during the DBA window.

Parent and child idle controls keep core operators running. Application deployment holds and target CronJob suspension settings are also
captured. CronJob-created Jobs and pods must drain before the handoff. Scheduled
writers are restored only after successful reconciliation. For the existing Lightspeed/MCP idle limitation, their
auxiliary operator replica settings are captured and held as well. Those auxiliary
operator deployments can be shared; include their owners in the maintenance plan.
The workflow verifies holds and waits a bounded period for application pods to
terminate. Unfinished migration jobs block preparation; resolve them deliberately,
then repeat `prepare`. Preparation never deletes migration jobs. Finalization invalidates only completed
Controller initialization migration Jobs, with recorded UID preconditions and a
durable checkpoint, so the operator migrates the restored schema.

A successful preparation exits immediately. It does not wait for the DBA, schedule
an expiry, or automatically restart AAP. Disconnect for hours or days if necessary;
the persisted Kubernetes settings continue to hold the target. Repeating `prepare`
reuses the original recovery settings and does not overwrite them with zero replicas.
Run phases serially; do not launch concurrent migration commands for one target.

Have the DBA restore **every included component database** into its intended target
logical database with the agreed target ownership/privileges, extensions and TLS.
The collection never initiates database restoration in this workflow.

## Repeatable validation after a long restore

```bash
ansible-playbook -i target.ini playbooks/artifact_import.yaml \
  -e @manual-import.yml -e artifact_import_phase=validate
```

This is a one-shot check and works with application pods stopped. It requires a
matching prepared record and verifies that the recorded target resources are still
held. It resolves current application Secrets and TLS settings each time, then
uses a temporary client pod with a 10-second connection timeout and bounded,
read-only SQL transactions (10-second statement and 3-second lock timeout).

Per-component checks cover connectivity, PostgreSQL version, recovery/default
read-only settings, application ownership and privileges, required extensions and
schemas, application tables, and Django migration records. Available source
metadata is compared with the target. Legacy artifacts may still be used with
explicit DBA mode, but report reduced verification when source metadata is absent.
Raw credential-bearing client output is protected; sanitized failures identify the
component and prerequisite to correct.

Failed validation leaves the target held and clears the previous readiness flag.
Correct the database, connection, TLS or ownership issue and rerun validation.
Passing means **ready for finalization checks**. It cannot prove that the DBA restore
finished or that all business data, rows or media are complete. DBA restore-log and
data verification and explicit confirmation remain mandatory.

## Explicit finalization and application acceptance

```bash
ansible-playbook -i target.ini playbooks/artifact_import.yaml \
  -e @manual-import.yml -e artifact_import_phase=finalize \
  -e artifact_db_restore_confirmed=true
```

Finalization reruns database readiness checks, installs source application keys,
restores matching Hub content onto the existing file-storage PVC, and resumes the
captured workload settings. It never invokes a database restore or deletes the Hub
PVC. It reconciles AAP and runs the normal component-specific schema/topology and
credential reconciliation. Failures reapply holds; successful finalization alone
prints `Migration Complete` and cleans up temporary migration resources. The
completed recovery record remains available for audit and harmless completion
retries. Archive the record before starting a different migration; do not delete
an active record to bypass its identity checks.

Before reopening traffic or enabling schedules, verify source-key decryption of an
existing credential, a Controller job, Gateway login/routing, EDA activation and
Controller integration, target endpoints/credentials/TLS, expected object counts,
and component readiness. For Hub, download existing locally uploaded and synced
collections, and pull existing custom EEs by digest from an **uncached** client.
Check final media/database consistency before relying on content repair. Then test
a new upload/push and confirm new media lands on the target storage.

## Interrupted phases and recovery

- Before any target database writes: retain the backups and record, rerun `prepare`
  if preparation was interrupted, and repeat `validate` after correction. Original
  recovery values are captured once. A changed archive, component set or target CR
  UID is rejected. Replaced recovery resources are also rejected by UID.
- During finalization: completed key/media checkpoints persist. Rerun `finalize`
  with DBA confirmation; it revalidates while held and continues safely. Interrupted
  media extraction may replay the same archive files. No destructive PVC operation
  is repeated. If the process is killed after workloads start, rerun finalization
  promptly: it reholds the target before further checks. An abrupt process kill
  cannot execute Ansible rescue; the persisted phase identifies this condition.
- After any DBA restore, target initialization, reconciliation or user write:
  treat recovery as a database-and-media operation. Do not simply restart RPM or
  patch the target idle flag manually. Stop writers and use the rehearsed backup,
  data reconciliation and recovery procedure with the DBA. The collection does not
  automatically roll back databases, keys or media, or erase a failed migration.

The workflow deliberately has no automatic restart or expiry. Administrator changes
to workload/CR settings, admission policies or operator behavior can defeat a hold;
monitor the cluster and database sessions during the handoff. Live acceptance must
prove the exact operator release's hold behavior, all four components, encryption,
Hub media, interruption recovery and post-migration operations before production use.
