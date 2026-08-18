# PostgreSQL Role (`roles/postgresql`)

The actual pg_dump/pg_restore engine. `operations/tasks/db_export.yml` and
`db_import.yml` both delegate here — this role has no per-component
awareness, only per-platform branching.

```
roles/postgresql/
├── defaults/main.yml   # postgresql_export_dir, postgresql_export_extension,
│                         # postgresql_restore_admin_user, postgresql_restore_timeout
├── handlers/
├── meta/
└── tasks/
    ├── db_auth.yml
    ├── db_export.yml
    ├── db_import.yml
    ├── create_temp_container.yml
    ├── discover_container_image.yml
    └── remove_temp_container.yml
```

## `db_auth.yml`

Resolves `postgresql_auth_settings.default.{HOST,PORT,NAME,USER,PASSWORD,OPTIONS}`
per platform:

- **RPM**: `aap_component_info` module (reads Django `DATABASES['default']`
  via `manage.py shell`). Caller must `no_log` — the module's `RETURN` doc
  says so explicitly.
- **Containerized**: `containers.podman.podman_container_exec` reading the
  component container's config.
- **OCP**: `ocp_utils/get_db_credentials.yml` (K8s Secret read).

Also aggregates `_postgresql_db_secrets` on `localhost`
(`<component>_pg_host`, `_pg_port`, `_pg_database`, `_pg_username`,
`_pg_password`) via `delegate_to: localhost, delegate_facts: true`, so the
packaging phase can assemble `secrets.yml` from every host's facts.

**DB name vs. DB username**: these can legitimately differ. Any task that
authenticates against the database must pass `login_db` explicitly (don't
assume it equals `login_user`) — this was a real bug (PR #96, see
`evals/diffs/pr-96-db-name-username-differ.patch`), and every `community.postgresql.*`
call added in this role should be checked for a `login_db` parameter.

## `db_export.yml`

- **RPM/containerized**: `community.postgresql.postgresql_db: state: dump,
  target_opts: "--clean --create"`, then `ansible.builtin.fetch`. Runs with
  `become: "{{ (aap_platform == 'rpm') | ternary(true, false) }}"` and
  `become_user` set to the Django-manage-owning OS user.
- **OCP**: execs `pg_dump --clean --create -Fc` inside the postgres
  StatefulSet pod (`ocp_utils_postgres_statefulset`) via
  `kubernetes.core.k8s_exec`, using a `sh -c 'PGPASSWORD="..." pg_dump ...'`
  string, then `kubernetes.core.k8s_cp`s the file out.
- Both branches compute `_postgresql_db_checksum`.

## `db_import.yml`

- **Containerized**: `block/always` — `community.postgresql.postgresql_user`
  (GRANT CREATEDB) → `postgresql_db` (`state: restore`,
  `--create --clean --if-exists`, `async: postgresql_restore_timeout`
  (3600s) / `poll: 30`) → `postgresql_user` (REVOKE CREATEDB), always run
  even on failure so the temporary CREATEDB grant doesn't leak.
- **OCP**: `block/always` — `kubernetes.core.k8s_exec` `pg_restore --clean
  --if-exists --no-owner` against the temp pod, then GRANT/REVOKE CREATEDB
  against the real postgres pod.

## Temp Container Fallback

`create_temp_container.yml`/`remove_temp_container.yml` spin up a
throwaway podman container (`command: sleep infinity`) to run pg_dump/
pg_restore client tooling when it isn't available on the host directly.
These are the reusable tasks added in PR #98 ("add reusable podman
temp-container tasks for postgres client ops") — reuse them rather than
writing a new ad hoc container-exec pattern if a future role needs
throwaway postgres client tooling.

## Secrets Handling

- No Ansible Vault is used anywhere in this role — secrets are plain YAML
  in the artifact, protected by `no_log` (in-flight) and file permissions
  (`secrets.yml` written `mode: '0600'` by `artifact/package.yml`).
- Every task that handles `login_password`/`PGPASSWORD` must carry
  `no_log: "{{ __postgresql_no_log }}"`. Double-check version-check queries
  and dump/restore tasks equally — a real gap existed where the OCP-path
  dump task had `no_log` but the equivalent RPM/containerized
  `postgresql_db` dump task (which also receives `login_password`) did not.
  See the review skill's [Database checklist](../../aap-snapshot-collection-review/references/checklist-database.md).
