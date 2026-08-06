# Database (PostgreSQL) Checklist

Background: [PostgreSQL Role](../../aap-snapshot-collection-structure/references/task-postgresql.md).

## Connection Parameters

- [ ] `login_db` is passed explicitly wherever a query/dump/restore
      connects to a specific database — never assume DB name equals DB
      username. PR #96 fixed exactly this gap on a version-check query; any
      new `community.postgresql.*` task is a candidate for the same
      mistake if it omits `login_db`.
- [ ] Host/port/user/password are sourced from `postgresql_auth_settings`/
      `_postgresql_db_secrets` (the existing aggregation), not
      re-derived or hardcoded in a new task.

## Dump / Restore Symmetry

- [ ] A change to the RPM/containerized dump path
      (`community.postgresql.postgresql_db: state: dump`) that fixes a bug
      or adds a parameter is mirrored in the OCP `pg_dump` exec path if the
      same issue applies there (and vice versa) — these are two independent
      implementations of the same operation, not a shared code path.
- [ ] Same check for restore: `postgresql_db: state: restore` (RPM/
      containerized) vs. `pg_restore` exec (OCP).
- [ ] Restore operations that grant a temporary privilege (e.g. GRANT
      CREATEDB before restore) revoke it in a `block/always`, not only on
      the success path — a failed restore should not leave elevated
      privileges granted.
- [ ] Long-running restore operations keep the `async`/`poll` pattern
      (`postgresql_restore_timeout`, currently 3600s) rather than reverting
      to a synchronous call that could hit Ansible's default task timeout
      on a large database.

## Secrets

- [ ] `no_log` present on every task passing `login_password` or embedding
      `PGPASSWORD` in a shell string — see
      [Security](checklist-security.md).
- [ ] The version-check query and the dump/restore task in the same file
      are checked together — historically these have diverged (one had
      `no_log`, the sibling didn't).

## Temp Container Fallback

- [ ] If a new role/task needs throwaway postgres client tooling, it reuses
      `roles/postgresql/tasks/create_temp_container.yml`/
      `remove_temp_container.yml` (added in PR #98) rather than introducing
      a new ad hoc podman-exec pattern.

## DB Name/Username Divergence — Regression Class

This bug class (DB name ≠ DB username) has already caused one real fix
(PR #96). When reviewing any new or modified PostgreSQL task, explicitly
check whether it assumes the two are the same — this is the single most
likely regression to reintroduce in this area.
