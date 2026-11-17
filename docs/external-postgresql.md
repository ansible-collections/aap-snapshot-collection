# RPM export to OCP with external PostgreSQL

AAP 2.6 RPM artifacts can be imported into an existing AAP 2.6 OCP deployment
whose components use separate external PostgreSQL databases. The collection
uses source credentials for export and each target component's configured
password credentials for import. Target database endpoints, names, users,
passwords, and TLS modes remain configured by the target deployment.

## Prepare the target

Before import:

- Deploy and reconcile AAP on OCP with its intended external databases.
- Provision dedicated component databases and password-authenticated users.
  Give each user CREATE on its database, USAGE and CREATE on application
  schemas, and ownership of existing application objects (directly or through
  an inherited role). Existing schemas that must be replaced also need to be
  owned by that user. The collection checks these prerequisites without
  granting privileges or creating databases.
- Provision the archive's PostgreSQL extensions in their source schemas. Hub
  requires `hstore`, normally in `public`. Administrator-owned extensions are
  supported. Grant the target user INSERT on any extension configuration
  tables whose data will be restored. Target extension versions must be
  compatible with the source application and extension data.
- Allow the temporary migration pod to resolve and reach each endpoint and
  port through network policies, firewalls, and AWS security groups. A working
  application connection alone does not prove migration-pod connectivity.
- Use a PostgreSQL client at least as new as the source server for export.
  At import the restore client must read the archive and be at least as new
  as its dump client and the target server. The target must be at least as new
  as both the source server and dump client; downgrades are rejected.

The default temporary client image is
`registry.redhat.io/rhel9/postgresql-15:latest`. Override
`postgresql_temp_container_image` for newer compatible versions. The RPM
source must have an appropriate `pg_dump` installed. PostgreSQL 15 is the
initial acceptance baseline; higher versions need separate validation.

Secret discovery prefers the selected AAP CR's resolved status references:
`databaseConfigurationSecret`, `controllerDatabaseSecret`, `hubDatabaseSecret`,
and `edaDatabaseSecret`. When unavailable, it uses the effective component
CR's configured reference, then the parent configuration and conventional
`<instance>-<component>-postgres-configuration` fallback. Required Secret keys
are `host`, `port`, `database`, `username`, and `password`; `sslmode` is optional
and follows libpq's default when absent. `postgres_admin_password` is unused.
All target connections are cached before AAP is idled.

## TLS and AWS CA certificates

RPM discovery propagates `sslmode`, root CA, and optional client certificate
and key independently into preflight, version queries, and export.

On OCP the database Secret's `sslmode` is passed into the temporary client.
For `verify-full`, use the database endpoint hostname that matches its
certificate and place the applicable AWS CA bundle in a Secret in the AAP
namespace. Reference existing Secrets in inventory, for example:

```yaml
postgresql_ocp_ssl_rootcert_secrets:
  gateway:
    name: aws-postgresql-ca
  controller:
    name: aws-postgresql-ca
    key: ca.crt
  hub:
    name: hub-postgresql-ca
    key: bundle.pem
  eda:
    name: aws-postgresql-ca
```

Each Secret reference is `{name, key}`, with `key` defaulting to `ca.crt`.
The collection mounts each certificate read-only at a component-specific path
and sets `PGSSLROOTCERT`. It does not change the configured `sslmode` or fetch
certificates. OCP client-certificate authentication and AWS IAM token generation
are outside this password-authentication workflow.

See [AWS PostgreSQL TLS guidance](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html),
[the AAP external database requirements](https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.6/install-configure_an_external_database_for_ansible_automation_platform),
and [Red Hat's database support policy](https://access.redhat.com/articles/4010491).
RDS PostgreSQL 15 appears in the
[AAP 2.6 tested operator topology](https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.6/plan-ref_ocp_b_env_a).
Aurora PostgreSQL uses the same logical migration approach; this collection
change does not establish Aurora-specific Red Hat validation or support.

## Import behavior and verification

The collection stages the archive and checks connectivity, writability,
versions, extension schemas, and ownership from the actual client pod before
downtime. It restores into existing databases with `--no-owner --no-acl`,
without `--create`. Source ownership and grants are not applied. Extension
creation, extension comments, and cleanup of extension schemas are omitted
from the restore list; application objects and extension configuration-table
data are retained. Provisioned target extensions are not dropped or recreated.

Every genuine SQL or execution error fails import, including permissions,
missing roles, data-load errors, and connection failures. The only allowed
nonzero result is a fully accounted-for inherited-partition constraint cleanup
error with matching `DROP CONSTRAINT` context and error count. Failure after
downtime triggers existing operator/AAP recovery. Preflight failures leave AAP
running. Recovery resumes services; it cannot roll back a partially restored
database. Raw connection and restore output is protected by `no_log`.

Live acceptance must separately exercise RPM AAP 2.6 export to OCP AAP 2.6 on
both standard RDS PostgreSQL and standard Aurora PostgreSQL. Verify all included
components, Controller partitions, Hub data/content behavior, unchanged target
connection settings, and unchanged source data. Ordinary CI does not provision
AWS resources. Existing Hub object-storage migration limitations still apply.
Database provisioning, Secrets Manager, IAM tokens, automatic failover recovery,
Aurora MySQL, DSQL, and Aurora Limitless are outside this workflow.
