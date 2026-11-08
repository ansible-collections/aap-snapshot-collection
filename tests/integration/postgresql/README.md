# PostgreSQL integration fixtures

Run from the collection root with pytest and a running Podman machine:

```bash
AAP_SNAPSHOT_PG_INTEGRATION=1 python -m pytest tests/integration/postgresql/ -q
```

The tests create and remove an isolated PostgreSQL 15 container without
publishing a host port. The default image is
`quay.io/sclorg/postgresql-15-c9s:latest`; override
`AAP_SNAPSHOT_PG_TEST_IMAGE` with a compatible SCL image. The extension fixture
expects `/usr/share/pgsql/extension` in the disposable image.

Fixtures exercise actual pg_dump/pg_restore archives, administrator-owned
hstore, extension configuration data, differing source/target identities,
source-only grant roles, permission/authentication/data-load failures, and
Controller-style inherited partition constraint cleanup. They run the same
connection builder, TOC filter, target preflight SQL, and result classifier as
the OCP workflow. They do not emulate the Kubernetes API or constitute live
RPM/OCP or AWS acceptance. See the live acceptance checklist in
[external PostgreSQL migration](../../../docs/external-postgresql.md).
