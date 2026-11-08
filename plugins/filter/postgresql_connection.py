# Copyright: (c) 2026, Ansible
# GNU General Public License v3.0+ (see COPYING)
"""Shared PostgreSQL connection and TLS prerequisites."""

import base64
import shlex

_COMPONENTS = {
    'gateway': ('databaseConfigurationSecret', None),
    'controller': ('controllerDatabaseSecret', 'controllerName'),
    'hub': ('hubDatabaseSecret', 'hubName'),
    'eda': ('edaDatabaseSecret', 'edaName'),
}

_SSL_ENV = {'sslmode': 'PGSSLMODE', 'sslrootcert': 'PGSSLROOTCERT', 'sslcert': 'PGSSLCERT', 'sslkey': 'PGSSLKEY'}


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


def ca_mounts(references):
    """Build read-only, per-component mounts from namespace-local Secrets."""
    result = {'volumes': [], 'mounts': []}
    for component, reference in references.items():
        if component not in _COMPONENTS or not isinstance(reference, dict) or not reference.get('name'):
            raise ValueError('CA Secret references must map component names to {name, key}')
        name = 'postgres-ca-' + component
        result['volumes'].append({'name': name, 'secret': {'secretName': reference['name'], 'items': [{'key': reference.get('key', 'ca.crt'), 'path': 'ca.crt'}]}})
        result['mounts'].append({'name': name, 'mountPath': '/etc/aap-snapshot-ca/' + component, 'readOnly': True})
    return result


class FilterModule:
    def filters(self):
        return {
            "postgresql_resolve_secret": resolve_pg_secret,
            "postgresql_decode_secret": decode_pg_secret,
            "postgresql_client_command": client_command,
            "postgresql_ssl_environment": ssl_environment,
            "postgresql_ca_mounts": ca_mounts,
        }
