# postgresql

Database export, import, and authentication operations. OCP imports restore as
the configured target component user into an existing database, preserving
provisioned extensions and target credentials. Database admin passwords and
CREATEDB grants are not required.

See [external PostgreSQL migration](../../docs/external-postgresql.md) and the
[variable reference](../../docs/variables.md) for TLS, prerequisites, and client
image selection.
