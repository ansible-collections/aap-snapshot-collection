===================================
ansible.aap\_snapshot Release Notes
===================================

.. contents:: Topics

v1.1.0
======

Minor Changes
-------------

- Add artifact delivery to containerized targets during import, verifying checksum and content integrity from orchestrator to the target environment.
- Add pre-import validation for containerized targets - detects stale containers and staged files from previous failed imports.
- Bump the kubernetes Python requirement from >=28.0.0 to >=36.0.3.
- Increase retries for listing execution environments in controller reconciliation to handle slower environments.
- Introduce artifact/consume.yml to consolidate the full OCP import orchestration flow, mirroring artifact/build.yml. Decompose operations/import.yml into atomic get_db_credentials.yml, db_import.yml, and update_secret.yml task files, consistent with the export-side structure.
- Move validate_artifact role content into the artifact role as artifact/validate.yml.
- Remove explicit postgresql_no_log parameter from operations role; the postgresql role now manages its own no_log toggle internally.
- Standardize no_log across all roles to use role-level toggle variables with a single disable_no_log input.
- Use operator OAuth2 token instead of gateway admin password for the Pulp content repair API call on OCP operator deployments.
- artifact - stage the hub content tarball from the extracted artifact to every hub node on containerized import (previously only each component's database dump was staged; hub content was never transferred at all).
- artifact - warn when a component present in the artifact has no matching inventory group on a containerized import target, or when a target inventory group has no matching component in the artifact, mirroring the existing OCP behavior.
- automationhub - Poll the Pulp repair async task to completion during import reconcile instead of fire-and-forget. Reports corrupted and repaired artifact counts and fails the play if the repair task does not complete successfully. Adds configurable polling timeout via ``automationhub_pulp_repair_retries`` and ``automationhub_pulp_repair_delay`` (default 60 minutes).
- automationhub - fail fast with a clear error during containerized import if Hub is configured with a non-FileSystem Pulp storage backend (Azure Blob or AWS S3). Containerized hub content import only restores files onto local FileSystem storage today; importing onto an object-storage-backed hub would previously restore the database silently and leave every migrated collection undownloadable with no warning.
- postgresql - Add reusable tasks (discover_container_image.yml, create_temp_container.yml, remove_temp_container.yml) to run postgres client commands inside a throwaway podman container instead of requiring pg_dump/pg_restore/psql on the target host. Not yet wired into db_import.yml or db_export.yml.

Security Fixes
--------------

- automationhub - add no_log to the containerized storage-backend check tasks. On a hub configured with Azure Blob or AWS S3 storage, the dumped and parsed settings.STORAGES value can contain the storage account key, secret access key, or SAS token, which was previously printed unmasked to Ansible output, CI artifacts, and log aggregators.

Bugfixes
--------

- Add loop_control with label to all loops to prevent sensitive data in output.
- Add missing any_errors_fatal to artifact_verify playbook.
- Add support for db name different than db username.
- Default ``_operations_manage_shell_args`` to ``--no-imports`` so containerized DB auth works for components where the Django version detection is skipped.
- Explicitly apply the resolved ``kubeconfig`` variable across every OCP-facing task in the collection, which previously relied on inherited environment and could silently fall back to ``~/.kube/config``.
- Fix "'delegate_to' is not a valid attribute for a TaskInclude" error on preflight - ansible-core rejects delegate_to/run_once directly on an include_tasks task, so move them onto the tasks inside check_import_vars.yml instead.
- Fix containerized import continuing into secret rotation and container removal when the database restore fails - re-raise the failure from the postgresql db_import block so the outer consume.yml rescue restarts services and aborts instead of leaving nodes in a split state.
- Fix disable_no_log toggle having no effect on the operations role due to a variable name typo.
- Fix hardcoded OCP PostgreSQL config secret name to support custom configurations.
- Fix hardcoded service account name in hub content import to support custom instance names.
- Fix import variable preflight check skipped on containerized targets - delegate to localhost with run_once so artifact_file is validated even when localhost is not in the inventory.
- Fix secret payload dict keys not evaluating in ``set_fact`` by using Jinja template blocks.
- Gather minimal facts for containerized preflight service check to resolve undefined ``ansible_user_dir``.
- Gather user directory facts before containerized service checks to prevent undefined ``ansible_user_dir`` errors during preflight.
- Prevent hub resource server register from overwriting the standard component register variable.
- Remove security context from hub content import that fails on OCP deployments.
- Remove unnecessary root privilege escalation when gathering service facts during RPM preflight checks - systemd unit state is readable without elevation.
- Replace ``omit`` sentinel with explicit default for ``django_manage_get_cmd`` in containerized DB export.
- Restore hub content files to the file-storage PVC during OCP import. Previously only the hub database was restored, leaving the storage backend empty and causing broken collection downloads.
- Rewrite Execution Environment image URLs in Controller to point to the destination Hub after import.
- Skip EE image URL rewrite during containerized import reconcile - the gateway API is not available at this point and the installer re-run owns service startup.
- Skip gateway schema migrations, vestigial object cleanup, and resource server podman secret removal during containerized import reconcile - these require running containers and are handled by the subsequent installer re-run.
- Update ``partner-certification-checker`` to v4.0.0 to fix ``ansible-lint`` import error caused by incompatibility between ``ansible-lint==24.12.2`` and ``ansible-core>=2.21`` (https://github.com/ansible-collections/partner-certification-checker/issues/93).
- artifact - add a rescue block to the containerized import path so a mid-import failure restarts every component's services back to their pre-import running state instead of leaving them stopped. The OCP import path already had equivalent block/rescue coverage; the containerized path had none.
- artifact - broadcast the resolved build directory to component hosts during export instead of relying on each host independently re-deriving the artifact role's default through several levels of nested role includes. Fixes "'__artifact_build_dir' is undefined" failures on containerized export of multi-host deployments.
- artifact - discover each component's DB credentials before stopping services during containerized import, not after. Credential discovery uses podman_container_exec into the component's own app container, which requires it to be running - consume.yml previously stopped all services first, causing "can only create exec sessions on running containers" once import reached the credential lookup step. get_db_credentials.yml now caches its result so the later, post-stop call from each component's import.yml is a no-op.
- artifact - fix artifact transfer selecting the wrong branch on remote (multi-node) containerized targets. The local-vs-remote transfer tasks are delegated to localhost, so checking ansible_connection directly in their when clause always evaluated against the delegate's own connection rather than the target host's, forcing every host onto the local-copy path and failing with a missing destination directory on genuinely remote hosts. Capture the target host's real connection in a non-delegated fact before delegating, and branch on that fact instead.
- artifact - fix artifact transfer task to support local connections (ansible_connection=local). When the control node is the same as the managed node, the synchronize module attempts SSH to localhost and prompts for a password. Split the transfer task into two paths using copy module for local connections and synchronize for remote connections.
- artifact - fix hub content staging failing on every hub host with an undefined-variable error. transfer_hub_content.yml referenced automationhub_content_tar_name, a role default that belongs to automationhub, but this task runs via include_tasks from the artifact role, which never loads automationhub's defaults. Resolve the tarball name once with the same default instead of referencing the role default directly.
- artifact role - add preflight stat checks at the start of init.yml to validate that artifact_dest_dir exists and is a directory, and that the parent of artifact_build_dir exists, before any build directory is cleared; previously a bad path would produce a raw Python traceback deep in package.yml after all export work had completed (https://github.com/ansible-collections/aap-snapshot-collection/issues/105).
- automationcontroller - Enable orphaned instance detection and deprovisioning on containerized deployments. Previously this reconciliation step only ran on OCP targets, leaving stale source instance records in the controller database after containerized imports.
- automationcontroller - Use the ``/api/controller/`` prefix when rewriting execution environment image URLs through the OCP gateway route, which previously 404'd against the bare ``/api/v2/`` path.
- automationcontroller reconcile - skip orphaned instance deprovisioning on containerized targets; the containerized installer's own init tasks handle this via throwaway containers with proper secret mounting, and the collection's exec-into-running-container approach fails when the controller_resource_server podman secret is updated during import (https://github.com/ansible-collections/aap-snapshot-collection/issues/119).
- automationgateway reconcile - stop deleting ServiceCluster during gateway cleanup; ServiceCluster has an on_delete=CASCADE FK to ServiceKey, so deleting it silently wiped all service keys from the restored gateway DB. On cross-cluster import the restored gateway and component DBs share consistent service key secrets - removing ServiceCluster broke that consistency and caused periodic_resource_sync to receive 401 errors. ServiceCluster carries no environment-specific addressing data (hostnames live in ServiceNode and Route, which are still purged); preserving it keeps the service key chain intact across the import.
- automationhub - Delete the hub file-storage PVC after database restore and before un-idling so the operator provisions a fresh empty volume; content can then be re-synced from configured remotes instead of running pulp repair on stale source artifacts.
- automationhub - check available disk space on the destination filesystem before extracting hub content on a containerized import, failing with a clear error rather than potentially exhausting disk mid-extraction.
- automationhub - fix the containerized hub storage-backend guard crashing on every hub, even a valid FileSystem-backed one. Django's settings.STORAGES is a dynaconf Box object whose repr ("<Box: {...}>") is not valid YAML, so parsing it with from_yaml always failed and aborted the import. Convert the Box to a plain dict and emit real JSON instead, parsed with from_json.
- automationhub - move the Hub Pulp storage backend check for OCP hub content import earlier, before the artifact is staged and AAP is idled, instead of failing deep into the import after the controller and hub databases were already restored. A non-FileSystem backend (Azure Blob or AWS S3) is now caught immediately, matching the fail-fast behavior already in place for containerized imports.
- automationhub - restore hub collection content (Pulp artifact blobs) on containerized import, not just the Pulp database. Migrated collections previously appeared in the published index with correct checksums but returned HTTP 500 on download, since the underlying blob files were never staged or restored. Extraction runs on every hub node (set automationhub_import_hub_content to false to opt out for very large hubs synced out-of-band instead).
- automationhub reconcile - skip Pulp content repair on containerized targets; Pulp repair requires a functioning gateway URL which may not be available at import time on containerized deployments.
- fix: containerized DB import now uses credentials discovered by get_db_credentials.yml (postgresql_auth_settings) directly, matching the export path, instead of passing them through postgresql_restore_* intermediaries. Also fixes an AIO regression where all components after the first shared the same host fact and ended up restoring with the controller's DB credentials.
- fix: remove unnecessary Grant/Revoke CREATEDB tasks from the containerized import path - the in-place restore strategy (pg_restore --clean --no-owner) does not require CREATEDB privilege.
- ocp_utils - Preserve ServiceCluster resource keys from backup artifact during operator platform import. The resource-server K8s secret now gets updated with controller_resource_key, hub_resource_key, and eda_resource_key values from the source system, fixing authentication failures between components after restore. Previously, components used the target cluster's original keys instead of the restored ServiceCluster keys, causing gateway database ServiceCluster records to mismatch component RESOURCE_SERVER secrets.
- operations - Recreate each component's containers, on every node, after its encryption secret is rotated during containerized import. Podman secrets aren't refreshed by a plain restart, so containers kept serving a stale key against the freshly restored database, causing gateway `migrate` to fail with `cryptography.fernet.InvalidToken` and hub Pulp repair to fail.
- operations - discover a component's static service units (e.g. EDA's ``automation-eda-scheduler``/``daphne``/``web``/``api``) via ``ansible.builtin.find`` alongside its dynamically-discovered worker units, instead of looping the hardcoded ``static_services`` list directly against ``ansible.builtin.systemd``. A static service name that doesn't exist as a real systemd unit on a given AAP version/topology (e.g. ``automation-eda-scheduler`` on this collection's tested environment) previously hard-failed both the stop and the rescue/recovery start paths, aborting the entire import before any component's data was touched. Missing units are now silently absent from the discovered list instead of causing a fatal "Could not find the requested service" error.
- operations - fix default() usage for django_manage_get_cmd in get_db_credentials.yml so an explicit null (controller/eda/gateway) falls through to a real default manage-shell command instead of rendering as an empty string. default(omit) only substitutes for undefined variables, not explicit null, and omit itself doesn't work here since the value is interpolated inside a larger command string in db_auth.yml rather than passed as a standalone module parameter - needs the same literal string default db_export.yml already uses. The empty value produced an empty -c '' argument to the Django manage shell, causing the DB settings introspection to return nothing during containerized import's credential discovery.
- operations - restore each component's resource server podman secret (controller_resource_server, eda_resource_server, hub_resource_server) during containerized import. Export already captures these (get_secret.yml reads them into the artifact as {component}_resource_key), but nothing restored them on import - the podman secret was left missing or stale, causing any awx-manage, aap-eda-manage, or pulpcore-manager shell command against that component's container to fail with a "no such secret" podman error.
- pcp - skip monitoring service start/stop operations when the pcp service is not installed. The rescue block in artifact import now tolerates containerized targets without pcp by checking LoadState before attempting systemd operations.
- playbooks - warn in the post-import advisory when hub content exists in the artifact but was not restored on a containerized target. The existing advisory logic only ever populated on OCP imports (it keyed off a fact the containerized import path never sets), so a containerized import that carried hub content but did not restore it previously gave no warning at all.
- postgresql - Use discovered credentials from ``postgresql_auth_settings`` for the OCP database restore instead of undefined ``postgresql_restore_*`` variables, and drop the unneeded CREATEDB grant/revoke around the restore (already removed from the containerized path since the restore uses ``--no-owner``).
- postgresql - parse the DB settings dumped from a component's Django shell (or, for hub, dynaconf's CLI) into a real dict on containerized targets instead of assigning the raw command stdout directly to ``postgresql_auth_settings``. The dumped value is a Python ``repr()`` string (single-quoted, bare ``True``/``False``), not JSON, and was never parsed - every downstream ``.default.NAME/.HOST/.USER/...`` reference then failed with "object of type 'str' has no attribute 'default'", blocking DB export and import on every containerized target. Confirmed fixed for both the shared Django ``print(settings.DATABASES)`` command (controller/eda/gateway) and hub's separate dynaconf-based command via a full containerized export/import round trip.
- postgresql - restore into the existing database on containerized targets (pg_restore --clean --if-exists --no-owner -d <db>) instead of dropping and recreating it (--create), matching the OCP import path. DROP DATABASE requires exclusive whole-database access and has no force option, so restore could fail outright with "database is being accessed by other users" if a stopped component's worker subprocess hadn't fully disconnected yet. Also fixes containerized DB name discovery (get_db_credentials.yml never set _operations_db_name, silently falling back to the component name instead of the real database name) so the existing database can be targeted directly.
- postgresql - run pg_dump/pg_restore inside a throwaway postgres client container on containerized targets instead of assuming psql/pg_restore exist as real host binaries. Containerized hosts only ship the containerized installer's own podman-wrapped CLI aliases, which are re-rendered with a volume mount for one specific file only immediately before the installer's own native restore runs - our staged artifact was never mounted into them, so database restore always failed with "No such file or directory" even though the file existed on the host. The client container's image defaults to the same image the OCP import path's temporary migration pod uses (postgresql_temp_container_image), and is user-overridable.
- postgresql - tolerate pg_restore's own non-fatal errors on containerized targets, matching the OCP import path. pg_restore --clean always raises (and itself only warns on) "cannot drop inherited constraint" errors when restoring partitioned tables (e.g. controller's time-partitioned job/event tables) - a well-known pg_dump/pg_restore limitation with declarative partitioning, not an actual restore failure. Only treat FATAL errors (connection/auth failures) as fatal, not per-statement restore errors.
- preflight - further scope the gateway status health gate (``check_gateway_status.yml``) to only the in-scope backends (controller, hub, eda) that are actually deployed on the target, instead of the static ``preflight_in_scope_gateway_services`` list. Hub and eda can be disabled on a given AAP instance; previously the health gate still demanded a 'good' status for them even when they were intentionally absent, which could hard-fail preflight on an otherwise healthy target. On RPM/containerized targets the in-scope list is now derived directly from non-empty inventory groups, so it self-updates as components are added or disabled with no changes needed to ``preflight_in_scope_gateway_services``; on operator (OCP) targets it is computed from discovered component CRs and intersected with that var, since OCP component discovery isn't backed by a uniform group structure.
- preflight - persist preflight_containerized_staging_dir as a fact instead of relying on the preflight role's default surviving into the later "Consume artifact (containerized)" play, where the preflight role is never re-included. Fixes "'preflight_containerized_staging_dir' is undefined" on containerized import's artifact transfer step.
- preflight - scope the containerized "check component services" fact-gather and the "check for stale staged artifact files" stat to hosts in the controller/eda/gateway/hub inventory groups. The Preflight play runs against all inventory hosts with any_errors_fatal enabled, so on a multi-node inventory these previously-unguarded remote tasks fanned out to hosts this collection never operates on (hop_nodes, execution_nodes, the local installer entry, external_database) and aborted the entire export/import run if any of them was unreachable or lacked the expected interpreter.
- preflight - scope the gateway status health gate (``check_gateway_status.yml``) to only the backends this collection actually exports/imports (controller, hub, eda) instead of hard-failing export/import whenever the gateway's own ``/api/gateway/v1/status/`` reports *any* backend as unhealthy - including redis, lightspeed, and metrics, none of which this collection touches. A transient or environment-specific issue in one of those out-of-scope services (e.g. a broken redis sidecar) previously blocked the entire preflight with no way to proceed, even though every in-scope component was healthy. The overall gateway status is now surfaced as a warning instead of a hard failure when only out-of-scope services are affected.
- preflight - scope the stale temp restore container check to component hosts (controller/eda/gateway/hub groups) instead of running it on every inventory host. It requires podman, which non-component hosts (an external database host, the node running the playbook, etc.) may not have, causing containerized import preflight to fail outright with ``Failed to find required executable "podman"``.

v1.0.5
======

Minor Changes
-------------

- Add preflight check that fails early when the artifact file is too large for the configured temp PVC size.
- Reduce default temp_pvc_size from 200Gi to 60Gi to avoid over-provisioning on smaller clusters.
- automationcontroller - Add ``automationcontroller_export_dir`` variable to configure the remote staging directory for database exports. Defaults to ``postgresql_export_dir``. Users with limited ``/tmp`` space can now point this to a larger filesystem without affecting other components.

Breaking Changes / Porting Guide
--------------------------------

- Remove legacy platform-specific playbook subdirectories (``ocp/``, ``rpm/``, ``containerized/``) and standalone dispatcher playbooks (``db_export``, ``start_aap``, ``stop_aap``, ``secrets_dump``). All functionality is covered by the main ``artifact_export`` and ``artifact_import`` playbooks using the unified role-based approach.

Bugfixes
--------

- Delete controller migration jobs before scaling operators back up during OCP import to prevent the controller operator from waiting on stale jobs from the restored database.
- Fix manage command result being lost when the skipped platform task overwrites the registered variable.
- Fix orphan instance detection to use OR instead of AND so that imported instances with stale heartbeats are cleaned up even when they still carry their original capacity from the source.
- Fix the URL for Pulp repair API call to call the route instead of the service.
- Restrict OCP preflight checks to localhost to prevent failures when using a containerized inventory with ``aap_platform=operator``.
- Skip import for components not present on the target cluster or missing from the artifact.
- automationhub - Wait for the AutomationHub CR API-Ready condition and verify the hub is routable through the gateway envoy proxy before triggering Pulp content repair, preventing 503 errors on slower environments.

v1.0.4
======

Bugfixes
--------

- Added top-level ``requirements.txt`` to the collection so that ``ansible-builder`` can resolve Python dependencies (``pyyaml``, ``kubernetes``) when constructing execution environments. Also added missing ``kubernetes`` dependency to ``meta/ee-requirements.txt`` (https://github.com/ansible-collections/aap-snapshot-collection/issues/48).
- automationhub - Fixed incorrect gateway service name in Pulp repair URL for OCP deployments (https://github.com/ansible-collections/aap-snapshot-collection/pull/49).
- import - Include the original error details in the import failure report instead of a generic message (https://github.com/ansible-collections/aap-snapshot-collection/pull/XX).

v1.0.3
======

Minor Changes
-------------

- Add debugging guide covering OCP import failure recovery, leftover temporary resource cleanup, idle state recovery, and common export issues (https://github.com/ansible-collections/aap-snapshot-collection/pull/26).
- Merge wait_for_pods and discover_components into a single pass to reduce redundant pod lookups during import.
- Move scale and un-idle recovery from always to rescue block so they only run on import failure.
- Remove duplicate gateway pod wait from import playbook.
- Standardize gateway pod label selectors to hardcoded values matching operator deployment_type defaults.

Bugfixes
--------

- Fix hub reconcile failing with ``automationgateway_admin_user is undefined`` by defining the admin username in the hub role's own defaults instead of depending on the gateway role's defaults (https://github.com/ansible-collections/aap-snapshot-collection/issues/46).
- Fix meta/execution-environment.yml python and system dependency paths for ansible-builder.
- Fix orphan instance detection to include nodes with null health check or null capacity after database restore.
- Fix post-export artifact validation failing when ``artifact_dest_dir`` differs from the default. The validate play now correctly resolves the extracted artifact path relative to ``artifact_dest_dir`` instead of using ``artifact_build_dir``, which is deleted by the package handler before validation runs (https://github.com/ansible-collections/aap-snapshot-collection/issues/23).
- Remove variable interpolation from task names to prevent exposing internal data in logs and CI output.
- Replace non-existent pulpcore-manager repair-artifacts command with Pulp REST API call for hub content repair.
- Reset gateway migrate_service_data flag during vestigial cleanup so the operator re-runs service registration after database restore.

v1.0.2
======

Minor Changes
-------------

- Skip artifact transfer to temporary pod when the file already exists with a matching checksum.

Breaking Changes / Porting Guide
--------------------------------

- The ``artifact_file`` variable is now required for import and verify playbooks. It no longer defaults to ``aap-snapshot-latest.tar``.

Bugfixes
--------

- Cascade idle_deployment false directly to child CRs when un-idling to work around AAP-77947 where the gateway operator fails to propagate it.
- Reconcile gateway before waiting for other components to clear stale service_nodes that block the gateway operator reconciliation loop.
- Remove aap-snapshot-latest.tar symlink from export packaging - k8s_cp copies the symlink instead of the file content, breaking imports.
- Remove statefulset idle wait that caused timeout failures during import - the operator does not scale statefulsets during idle.
- Resolve symlinks and relative paths to absolute real paths before artifact transfer to prevent dangling links inside the temporary pod.
- Set database.idle_disabled on the AAP CR before idling to keep postgres running during database import.

v1.0.1
======

v1.0.0
======

Breaking Changes / Porting Guide
--------------------------------

- Role namespace and instance name variables are now decoupled from ``ocp_utils`` defaults. Use ``-e ocp_namespace=<ns>`` and ``-e aap_instance_name=<name>`` instead of ``-e ocp_utils_ocp_namespace=<ns>`` and ``-e ocp_utils_aap_instance_name=<name>``. The ``ocp_utils_*`` variables still work for the ``ocp_utils`` role itself but no longer propagate to other roles.

Bugfixes
--------

- Idle wait now checks Deployment and StatefulSet replica counts instead of pod label selectors that matched no pods. The previous ``app.kubernetes.io/managed-by`` value-match selector did not match actual pod labels, causing the wait to pass immediately and database restores to run against live pods with active connections.
- Idle wait scoped to AAP-managed resources using the ``app.kubernetes.io/part-of`` label selector, preventing false matches against non-AAP workloads in shared namespaces.
- User-provided extra vars ``ocp_namespace`` and ``aap_instance_name`` are now respected by all roles. Previously, roles hardcoded the namespace to ``aap`` or chained through ``ocp_utils`` defaults that only resolved when ``ocp_utils`` was explicitly included first, silently ignoring ``-e ocp_namespace=custom-ns``.

New Plugins
-----------

Filter
~~~~~~

- parse_aap_version - Parse an AAP version string into structured components

New Modules
-----------

- aap_component_info - Discover AAP component information from RPM installations
- validate_migration_artifact - Validate an AAP migration artifact

v0.0.1
======

Major Changes
-------------

- Add Python modules ``aap_component_info`` for RPM component discovery and ``validate_migration_artifact`` for artifact validation, and ``parse_aap_version`` filter plugin for version string parsing.
- Add full export workflow for RPM deployments with SDP v1.0 artifact format, component export roles for controller, hub (with Pulp content), gateway, and EDA, and standalone artifact verification playbook.
- Add import workflow for OCP targets with database restore, secret synchronization, operator lifecycle management, temporary migration resources, and post-import reconciliation for all four AAP components.

Breaking Changes / Porting Guide
--------------------------------

- aap_component_info - The ``gather`` parameter now enforces ``choices`` validation. Unrecognized values that were previously accepted silently will now produce a validation error.
