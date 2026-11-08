# DBA migration verification

Run from the collection root with Python 3.12+, pytest, PyYAML, psycopg 3,
Ansible and the collection's usual dependencies:

```bash
pytest tests/unit/ -q
pytest tests/integration/dba_migration/ -q
```

`test_postgresql.py` starts a disposable Podman PostgreSQL 15 container, creates
four independently owned application databases and removes the container afterward.
It checks actual read-only metadata SQL, migration records, extensions, privileges
(including revoked INSERT) and read-only server defaults. It never connects to an
existing database. The image must already be available or accessible to Podman.

`test_phases.py` runs the real playbooks/roles in separate Ansible processes.
`kubernetes_boundary.py` is installed only in a temporary test collection and
models the Kubernetes module boundary using a temporary JSON resource store.
It does not contact an API server or use a real kubeconfig. The tests cover
explicit phase guards, archive/CR identity, long handoffs represented by independent
processes without retained facts, retries, failed validation, recovery settings,
CronJob writers, completed initialization jobs, new workloads, TLS/credential
isolation, source metadata, and interrupted key/Hub content checkpoints.

The local boundary fixture uses ZIP input so Ansible's unarchive module works
on macOS without GNU tar. Production artifact packaging remains tar. Hub media
inside the fixture remains a tar archive. These tests establish task sequencing
and resource mutations, not actual operator reconciliation or application behavior.

Live RPM 2.6 to OCP 2.6 acceptance remains outstanding: prove the specific operator
release holds all writers, execute DBA restore for all four components, verify
source-key decryption, Controller jobs, Gateway/EDA integration, existing collection
downloads, uncached custom EE pulls, and complete database/media recovery scenarios.
