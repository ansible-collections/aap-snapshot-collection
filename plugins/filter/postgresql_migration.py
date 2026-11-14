# Copyright: (c) 2026, Ansible
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Connection and archive validation for PostgreSQL logical migrations.

These filters deliberately never include credentials or raw SQL in errors.
"""

import base64
import re
import shlex
import uuid

_COMPONENTS = {
    'gateway': ('databaseConfigurationSecret', None),
    'controller': ('controllerDatabaseSecret', 'controllerName'),
    'hub': ('hubDatabaseSecret', 'hubName'),
    'eda': ('edaDatabaseSecret', 'edaName'),
}
_SSL_ENV = {'sslmode': 'PGSSLMODE', 'sslrootcert': 'PGSSLROOTCERT', 'sslcert': 'PGSSLCERT', 'sslkey': 'PGSSLKEY'}
_IDENT = r'(?:"(?:[^"\n]|"")+"|[a-zA-Z_][a-zA-Z_0-9$]*)'


def _identifier(value):
    return value[1:-1].replace('""', '"') if value.startswith('"') else value


def _reference(spec, component):
    if component == 'gateway':
        return (spec.get('database') or {}).get('database_secret', '')
    if component == 'eda':
        return (spec.get('database') or {}).get('database_secret', '')
    return spec.get('postgres_configuration_secret', '')


def resolve_pg_secret(aap, component, component_crs):
    """Prefer resolved parent status, then the selected deployment's child CR."""
    if component not in _COMPONENTS:
        raise ValueError('Unknown PostgreSQL component')
    status_field, name_field = _COMPONENTS[component]
    status = aap.get('status') or {}
    if status.get(status_field):
        return status[status_field]
    uid = aap.get('metadata', {}).get('uid')
    matches = []
    for cr in component_crs:
        metadata = cr.get('metadata', {})
        owned = uid and any(owner.get('uid') == uid for owner in metadata.get('ownerReferences', []))
        named = name_field and status.get(name_field) and metadata.get('name') == status[name_field]
        if owned or named:
            matches.append(cr)
    if len(matches) > 1:
        raise ValueError('Ambiguous effective component CR for PostgreSQL Secret discovery')
    if matches:
        reference = _reference(matches[0].get('spec', {}), component)
        if reference:
            return reference
    spec = aap.get('spec') or {}
    reference = _reference(spec if component == 'gateway' else spec.get(component) or {}, component)
    return reference or '{}-{}-postgres-configuration'.format(aap.get('metadata', {}).get('name', 'aap'), component)


def decode_pg_secret(data):
    """Return Django-style connection settings without any admin credential."""
    result = {}
    for key, field in {'host': 'HOST', 'port': 'PORT', 'database': 'NAME', 'username': 'USER', 'password': 'PASSWORD'}.items():
        try:
            value = base64.b64decode(data[key], validate=True).decode('utf-8')
            if not value or '\x00' in value:
                raise ValueError()
        except (KeyError, ValueError, UnicodeError):
            raise ValueError('PostgreSQL Secret is missing a valid required field: ' + key) from None
        result[field] = value
    if not result['PORT'].isdigit() or not 0 < int(result['PORT']) < 65536:
        raise ValueError('PostgreSQL Secret port must be between 1 and 65535')
    options = {}
    if 'sslmode' in data:
        try:
            options['sslmode'] = base64.b64decode(data['sslmode'], validate=True).decode('utf-8')
        except (ValueError, UnicodeError):
            raise ValueError('PostgreSQL Secret has an invalid sslmode') from None
        if options['sslmode'] not in ('disable', 'allow', 'prefer', 'require', 'verify-ca', 'verify-full'):
            raise ValueError('PostgreSQL Secret has an invalid sslmode')
    result['OPTIONS'] = options
    return {'default': result}


def ssl_environment(options):
    """Compute a fresh environment; CA and client certificates are independent."""
    return {variable: str(options[key]) for key, variable in _SSL_ENV.items() if options.get(key)}


def dbname_connection(name):
    """Quote a literal database name for libpq's explicit dbname parameter."""
    return "dbname='" + str(name).replace('\\', '\\\\').replace("'", "\\'") + "'"


def client_command(settings, argv):
    """Build an exec command that survives k8s_exec's shlex.split unchanged.

    No shell is needed. Explicit dbname conninfo prevents libpq interpreting
    a database name containing '=' as additional connection parameters.
    """
    environment = {'LC_ALL': 'C', 'PGCONNECT_TIMEOUT': '10'}
    args = list(argv)
    if settings:
        db = settings['default']
        environment.update(ssl_environment(db.get('OPTIONS') or {}))
        environment.update({'PGHOST': str(db['HOST']), 'PGPORT': str(db['PORT']), 'PGUSER': str(db['USER']), 'PGPASSWORD': db.get('PASSWORD') or ''})
        args[1:1] = ['--dbname', dbname_connection(db['NAME'])]
    return shlex.join(['env'] + [key + '=' + value for key, value in environment.items()] + args)


def restore_failed(result):
    """Accept only fully accounted-for inherited-constraint cleanup errors."""
    rc = result.get('rc')
    stderr = result.get('stderr') or ''
    if rc == 0:
        return bool(re.search(r'(?i)\b(?:error|fatal|panic)\b', stderr))
    if rc != 1:
        return True
    error = re.compile(
        r'pg_restore: error: could not execute query: ERROR:\s+cannot drop inherited constraint "(?P<constraint>[^"\n]+)" '
        r'of relation "(?P<table>[^"\n]+)"\s*\nCommand was: ALTER TABLE (?:IF EXISTS )?ONLY '
        r'(?P<schema>' + _IDENT + r')\.(?P<relation>' + _IDENT + r')\s+DROP CONSTRAINT (?:IF EXISTS )?(?P<key>' + _IDENT + r');\s*\n?',
    )
    count = 0

    def consume(match):
        nonlocal count
        if _identifier(match['relation']) != match['table'] or _identifier(match['key']) != match['constraint']:
            return match[0]
        count += 1
        return ''

    remaining = error.sub(consume, stderr)
    remaining = re.sub(r'^pg_restore: (?:while PROCESSING TOC:|from TOC entry [^\n]*)\n?', '', remaining, flags=re.M)
    summaries = re.findall(r'^pg_restore: warning: errors ignored on restore: (\d+)\s*$', remaining, flags=re.M)
    remaining = re.sub(r'^pg_restore: warning: errors ignored on restore: \d+\s*$', '', remaining, flags=re.M)
    return not (count > 0 and summaries == [str(count)] and not remaining.strip())


def _major(version):
    match = re.search(r'(?:PostgreSQL\)?\s+)?(\d+)(?:\.\d+)?', str(version))
    if not match or int(match[1]) < 10:
        raise ValueError('Cannot determine a supported PostgreSQL version (10 or newer required)')
    return int(match[1])


def validate_dump_client(server_version, client_version):
    if _major(client_version) < _major(server_version):
        raise ValueError('PostgreSQL dump client is older than the source server; install or select a compatible client')
    return True


def archive_info(toc, schema_sql):
    """Omit extension DDL and its schema DDL, retaining extension table data."""
    versions = {}
    for label, key in [('database', 'source_major'), ('pg_dump', 'dump_major')]:
        match = re.search(r'^;\s*Dumped (?:from|by) ' + label + r' version: (.+)$', toc, re.M)
        if not match:
            raise ValueError('Archive is missing PostgreSQL version metadata')
        versions[key] = _major(match[1])
    extensions = {}
    for match in re.finditer(r'CREATE EXTENSION IF NOT EXISTS (' + _IDENT + r') WITH SCHEMA (' + _IDENT + r');', schema_sql):
        extensions[_identifier(match[1])] = _identifier(match[2])
    extension_entries = [line for line in toc.splitlines() if re.match(r'^\d+; \d+ \d+ EXTENSION ', line)]
    if len(extension_entries) != len(extensions):
        raise ValueError('Cannot determine all archive extension schemas')
    lines = []
    schemas = set(extensions.values())
    schema_names_by_id = {}
    for entry in re.finditer(r'^-- TOC entry (\d+) [^\n]*\n(.*?)(?=^-- TOC entry |\Z)', schema_sql, re.M | re.S):
        schema = re.search(r'^(?:CREATE SCHEMA|COMMENT ON SCHEMA) (' + _IDENT + r')(?:;| IS )', entry[2], re.M)
        if schema:
            schema_names_by_id[entry[1]] = _identifier(schema[1])
        elif re.search(r'^-- Name: public; Type: SCHEMA; Schema: -; Owner: -$', entry[2], re.M) and re.search(
            r'^-- \*not\* creating schema, since initdb creates it$',
            entry[2],
            re.M,
        ):
            schema_names_by_id[entry[1]] = 'public'
    for line in toc.splitlines():
        if re.match(r'^\d+; \d+ \d+ (?:EXTENSION |COMMENT - EXTENSION )', line):
            continue
        # A preserved extension makes DROP SCHEMA fail, even with --no-owner.
        schema_entry = re.match(r'^(\d+); \d+ \d+ (?:SCHEMA - |COMMENT - SCHEMA )', line)
        if schema_entry and schemas:
            # TOC names and owners are unquoted and can be indistinguishable.
            # Verbose schema SQL associates each quoted identifier with its ID.
            if schema_entry[1] not in schema_names_by_id:
                raise ValueError('Archive schema inspection is missing table-of-contents metadata')
            if schema_names_by_id[schema_entry[1]] in schemas:
                continue
        lines.append(line)
    application_schemas = set()
    for match in re.finditer(
        r'CREATE (?:UNLOGGED )?(?:TABLE|SEQUENCE|VIEW|MATERIALIZED VIEW|FOREIGN TABLE|TYPE|DOMAIN|FUNCTION|PROCEDURE) (' + _IDENT + r')\.',
        schema_sql,
    ):
        application_schemas.add(_identifier(match[1]))
    # Match complete schema names against SQL-derived namespaces. TOC names
    # are not quoted and may themselves contain whitespace.
    known_schemas = application_schemas | set(extensions.values()) | {'public'}
    for line in toc.splitlines():
        match = re.match(r'^\d+; \d+ \d+ (?:TABLE DATA|TABLE|SEQUENCE|FUNCTION|TYPE) (.+)', line)
        if match:
            for schema in sorted(known_schemas, key=len, reverse=True):
                if match[1].startswith(schema + ' '):
                    application_schemas.add(schema)
                    break
    restored_schemas = [_identifier(match[1]) for match in re.finditer(r'CREATE SCHEMA (' + _IDENT + r');', schema_sql)]
    return dict(
        versions,
        extensions=extensions,
        schemas=sorted(application_schemas),
        restored_schemas=[schema for schema in restored_schemas if schema not in schemas],
        restore_toc='\n'.join(lines) + '\n',
    )


def validate_target(archive, state, restore_version, component):
    """Fail closed on prerequisites before application downtime or cleanup."""
    restore = _major(restore_version)
    target = int(state['version']) // 10000
    if target < max(archive['source_major'], archive['dump_major']):
        raise ValueError('PostgreSQL downgrade is unsupported: target version must be at least source and dump versions')
    if restore < max(archive['dump_major'], target):
        raise ValueError('PostgreSQL restore client version is incompatible; select a client image at least as new as dump and target')
    if not state.get('writable'):
        raise ValueError('Target database must be writable')
    if not state.get('database_create'):
        raise ValueError('Target user requires CREATE privilege on the database')
    if state.get('unowned_objects', 0):
        raise ValueError('Target application-object ownership must belong to the target database user or an inherited role')
    for schema in archive['schemas']:
        rights = state.get('schemas', {}).get(schema)
        if rights is None and schema in archive['restored_schemas']:
            continue
        if not rights or not rights['usage'] or not rights['create']:
            raise ValueError('Provision target schema with USAGE and CREATE privileges: ' + schema)
    for schema in archive['restored_schemas']:
        if schema in state.get('schemas', {}) and not state['schemas'][schema]['owned']:
            raise ValueError('Target schema ownership is required for cleanup: ' + schema)
    required = dict(archive['extensions'])
    if component == 'hub' and 'hstore' not in required:
        required['hstore'] = 'public'
    for extension, schema in required.items():
        if not state.get('extension_config_privileges', {}).get(extension, True):
            raise ValueError('Target extension configuration tables require INSERT privilege: ' + extension)
        if state.get('extensions', {}).get(extension) != schema:
            raise ValueError('Provision target extension {} in schema {} before import'.format(extension, schema))
    return True


def write_probe(archive):
    """Exercise CREATE and INSERT as the real target user without leaving data."""

    def quote_ident(value):
        return '"' + value.replace('"', '""') + '"'

    table = quote_ident('__aap_snapshot_probe_' + uuid.uuid4().hex)
    statements = ['BEGIN;']
    for schema in archive['schemas']:
        qualified = quote_ident(schema) + '.' + table
        statements.extend(
            [
                'CREATE SCHEMA IF NOT EXISTS ' + quote_ident(schema) + ';',
                'CREATE TABLE ' + qualified + ' (value integer);',
                'INSERT INTO ' + qualified + ' VALUES (1);',
            ],
        )
    statements.append('ROLLBACK;')
    return '\n'.join(statements)


def ca_mounts(references):
    """Build read-only, per-component mounts from namespace-local Secrets."""
    result = {'volumes': [], 'mounts': []}
    for component, reference in references.items():
        if component not in _COMPONENTS or not isinstance(reference, dict) or not reference.get('name'):
            raise ValueError('CA Secret references must map component names to {name, key}')
        name = 'postgres-ca-' + component
        result['volumes'].append(
            {'name': name, 'secret': {'secretName': reference['name'], 'items': [{'key': reference.get('key', 'ca.crt'), 'path': 'ca.crt'}]}},
        )
        result['mounts'].append({'name': name, 'mountPath': '/etc/aap-snapshot-ca/' + component, 'readOnly': True})
    return result


class FilterModule:
    def filters(self):
        return {
            'postgresql_resolve_secret': resolve_pg_secret,
            'postgresql_decode_secret': decode_pg_secret,
            'postgresql_ssl_environment': ssl_environment,
            'postgresql_client_command': client_command,
            'postgresql_dbname': dbname_connection,
            'postgresql_restore_failed': restore_failed,
            'postgresql_archive_info': archive_info,
            'postgresql_validate_target': validate_target,
            'postgresql_ca_mounts': ca_mounts,
            'postgresql_major_version': _major,
            'postgresql_validate_dump_client': validate_dump_client,
            'postgresql_write_probe': write_probe,
        }
