# Preflight Role (`roles/preflight`)

The only role in the collection with a real `tasks/main.yml` entry point —
every other role is invoked via specific `tasks_from:`. `main.yml` runs on
`hosts: all` from both `artifact_export.yaml` and `artifact_import.yaml`,
right after `common/set_groups.yml`.

```
roles/preflight/
├── defaults/main.yml    # __preflight_no_log, etc.
├── meta/
└── tasks/
    ├── main.yml
    ├── check_platform.yml
    ├── check_import_vars.yml
    ├── check_temp_pvc_size.yml
    ├── check_ocp_target.yml
    ├── check_aap_cr.yml
    ├── check_services.yml
    ├── check_databases.yml
    ├── check_gateway_status.yml
    ├── check_storage_class.yml
    └── check_version_match.yml
```

## Sequencing in `main.yml`

1. `check_platform.yml` — always runs, determines `aap_platform`.
2. `check_import_vars.yml` — **import only**: asserts `artifact_file` is
   defined, resolves symlinks, asserts the file exists
   (`run_once: true, delegate_to: localhost`).
3. `check_temp_pvc_size.yml` — **OCP import only**.
4. `check_ocp_target.yml` — **OCP only**.
5. `check_aap_cr.yml`
6. `check_services.yml`
7. `check_databases.yml` — reads DB creds/version pre-checks on RPM hosts,
   `become: true`.
8. `check_gateway_status.yml`
9. Per-component delegation: `include_role:
   automationcontroller/automationeda/automationgateway/automationhub,
   tasks_from: preflight.yml`, gated on inventory group membership. This is
   what calls into `operations/tasks/preflight.yml`'s version-match assert
   for each component actually present.

**When adding a new preflight check**, decide whether it's platform-wide
(add a `check_*.yml` file and sequence it in `main.yml` at the right point
— before the component loop if it should gate all components) or
component-specific (add it to `operations/tasks/preflight.yml`'s logic
instead, so it runs once per component through the existing delegation).

Preflight validations use `ansible.builtin.assert` with `that:`/`fail_msg:`,
not `ansible.builtin.fail` with `when:` — this gives clearer failure output
and keeps validation logic in one place per check. See the
aap-ansible-conventions skill and the review checklist for the full rule.
