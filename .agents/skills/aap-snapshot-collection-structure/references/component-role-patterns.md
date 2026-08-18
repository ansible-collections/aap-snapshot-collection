# Component Role Patterns

`roles/automationcontroller`, `roles/automationeda`, `roles/automationgateway`,
`roles/automationhub` all follow the identical delegator shape:

```
roles/automationX/
├── defaults/main.yml
├── meta/main.yml
├── vars/main.yml          # sets automationX_component_name: <controller|eda|gateway|hub>
├── tasks/
│   ├── export.yml
│   ├── import.yml
│   ├── reconcile.yml      # the one file with real per-component logic (see below)
│   ├── preflight.yml
│   ├── get_secret.yml
│   ├── db_export.yml
│   ├── start_service.yml
│   └── stop_service.yml
```

No `handlers/` or `templates/` — these roles hold no state and render
nothing themselves. Hub adds `export_hub_content.yml`/`import_hub_content.yml`;
controller adds `export_custom_configs.yml`.

## The Delegator Body

Nearly every task file's entire body is 1-3 tasks:

```yaml
- name: Export controller data
  ansible.builtin.include_role:
    name: ansible.aap_snapshot.operations
    tasks_from: export.yml   # or the equivalent operations/ocp_utils task
  vars:
    component_name: "{{ automationcontroller_component_name }}"
```

`vars/main.yml` sets exactly one fact per role: `automationcontroller_component_name: controller`,
`automationeda_component_name: eda`, `automationgateway_component_name: gateway`,
`automationhub_component_name: hub`. This is the only thing that
distinguishes one delegator role's behavior from another — everything else
comes from `operations`/`ocp_utils` looking up `component_name` in
`_operations_component_config`.

**When you're tempted to add real logic to one of these roles**, ask
whether it actually belongs in `operations` (if it should apply to how any
component gets exported/imported) instead — only genuinely
component-specific behavior belongs here, and even that should usually be
expressed as extra fields in `_operations_component_config` rather than
inline tasks, to keep the four delegator roles symmetric.

## Per-Component `reconcile.yml` Logic

`reconcile.yml` is called after import to fix up state that doesn't survive
a raw DB restore. This is genuinely different per component:

- **`automationcontroller/tasks/reconcile.yml`**: finds orphaned `Instance`
  objects (a Django ORM script checking heartbeat age > 600s) via
  `ocp_utils/run_manage_command.yml`, deprovisions them with
  `awx-manage deprovision_instance --hostname={{ item }}`, resets the admin
  password, and rewrites Execution Environment image URLs from the source
  hub to the destination hub via the gateway API
  (`/api/v2/execution_environments/`).
- **`automationeda/tasks/reconcile.yml`**: waits for the AAP CR's
  `Successful` condition (OCP only, 60 retries / 15s delay), re-discovers
  the `eda-api` pod, runs `aap-eda-manage resource_sync`, resets the admin
  password.
- **`automationgateway/tasks/reconcile.yml`**: runs
  `aap-gateway-manage migrate`, resets the admin password, deletes vestigial
  `HTTPPort`/`ServiceNode`/`ServiceCluster` (+`Route` on OCP) Django objects
  via inline Python scripts stored in `vars/main.yml`
  (`_automationgateway_cleanup_ocp_script`,
  `_automationgateway_cleanup_containerized_script`), calls
  `MigrateServiceDataHasRan.mark_migration_not_completed()`, then deletes
  the `aap-resource-server` K8s Secret (OCP) or the matching podman secrets
  (containerized).
- **`automationhub/tasks/reconcile.yml`**: triggers Pulp content repair via
  `POST /api/galaxy/pulp/api/v3/repair/` (`verify_checksums: true`), with a
  `rescue:` fallback that curls the repair endpoint from inside the hub pod
  if the localhost `uri` call fails, then resets the admin password.

## Adding a Fifth Component

1. Create `roles/automationX/` following the skeleton above.
2. Add its config block to `_operations_component_config` in
   `roles/operations/vars/main.yml` (see
   [Operations Engine](task-operations.md) for the field schema).
3. Add its inventory group to `roles/common/tasks/set_groups.yml`.
4. Add its host-group to the `hosts:` lines in
   `playbooks/artifact_export.yaml` / `artifact_import.yaml` and to
   `playbooks/common/start_services.yaml` / `stop_services.yaml` (both the
   ordering and, separately, the inline stop/start block in
   `roles/artifact/tasks/consume.yml` — see
   [Playbook Orchestration](playbook-orchestration.md)).
5. If the component needs DB partitioning, custom config files, or content
   storage handling like hub's, extend `operations`/`postgresql` rather than
   reimplementing it in the new delegator role.
