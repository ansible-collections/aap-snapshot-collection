"""Real PostgreSQL fixtures; opt in with AAP_SNAPSHOT_PG_INTEGRATION=1.

Uses an isolated disposable Podman container, without exposing a host port.
Override AAP_SNAPSHOT_PG_TEST_IMAGE with a PostgreSQL 15 SCL-compatible image.
"""

import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.environ.get('AAP_SNAPSHOT_PG_INTEGRATION') != '1', reason='opt-in PostgreSQL integration fixture')
ROOT = Path(__file__).parents[3]
spec = importlib.util.spec_from_file_location('pg_migration', ROOT / 'plugins/filter/postgresql_migration.py')
pg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pg)


@pytest.fixture(scope='module')
def database():
    name = 'aap-snapshot-pg-' + uuid.uuid4().hex[:12]
    image = os.environ.get('AAP_SNAPSHOT_PG_TEST_IMAGE', 'quay.io/sclorg/postgresql-15-c9s:latest')
    admin_password = uuid.uuid4().hex
    source_password = uuid.uuid4().hex
    subprocess.run(
        [
            'podman',
            'run',
            '--rm',
            '-d',
            '--name',
            name,
            '-e',
            'POSTGRESQL_USER=source_user',
            '-e',
            'POSTGRESQL_PASSWORD=' + source_password,
            '-e',
            'POSTGRESQL_DATABASE=source_db',
            '-e',
            'POSTGRESQL_ADMIN_PASSWORD=' + admin_password,
            image,
        ],
        check=True,
        capture_output=True,
    )

    def run(argv, check=True, data=None, user=None):
        prefix = ['podman', 'exec', '-i'] + (['--user', user] if user else []) + [name]
        return subprocess.run(prefix + argv, input=data, text=True, capture_output=True, check=check)

    def sql(query, db='postgres'):
        return run(['psql', '-XAt', '-U', 'postgres', '-d', pg.dbname_connection(db), '-v', 'ON_ERROR_STOP=1', '-c', query]).stdout.strip()

    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if run(['pg_isready', '-U', 'postgres', '-d', 'postgres'], check=False).returncode == 0:
                break
            time.sleep(0.5)
        else:
            pytest.fail('PostgreSQL test container did not become ready')
        # Password includes shell syntax; databases and roles differ across source/target.
        password = "fixture-'\"$()\\;" + uuid.uuid4().hex
        sql("CREATE ROLE target_user LOGIN PASSWORD '" + password.replace("'", "''") + "';")
        sql('CREATE DATABASE target_db OWNER target_user;')
        sql('CREATE ROLE source_grant_only;')
        sql(
            'CREATE EXTENSION hstore; SET ROLE source_user; '
            'CREATE TABLE app (id integer PRIMARY KEY, attributes hstore); '
            "INSERT INTO app VALUES (1, 'name=>source'); GRANT SELECT ON app TO source_grant_only;",
            'source_db',
        )
        sql(
            'CREATE EXTENSION hstore; SET ROLE target_user; ' 'CREATE TABLE app (id integer PRIMARY KEY, attributes hstore); ' "INSERT INTO app VALUES (99, 'name=>target');",
            'target_db',
        )
        settings = {'default': {'HOST': '127.0.0.1', 'PORT': '5432', 'NAME': 'target_db', 'USER': 'target_user', 'PASSWORD': password, 'OPTIONS': {'sslmode': 'disable'}}}
        run(['pg_dump', '-U', 'postgres', '-d', 'source_db', '-Fc', '-f', '/tmp/source.pgc'])
        sql('REVOKE SELECT ON app FROM source_grant_only;', 'source_db')
        sql('DROP ROLE source_grant_only;')
        toc = run(['pg_restore', '--list', '/tmp/source.pgc']).stdout
        schema = run(['pg_restore', '--verbose', '--schema-only', '--no-owner', '--no-acl', '-f', '-', '/tmp/source.pgc']).stdout
        archive = pg.archive_info(toc, schema)
        run(['sh', '-c', 'umask 077; cat > /tmp/restore.list'], data=archive['restore_toc'])
        yield run, sql, settings, archive
    finally:
        subprocess.run(['podman', 'stop', '--time', '1', name], capture_output=True, check=True)


def test_external_restore_preserves_admin_owned_extension_and_target_identity(database):
    run, sql, settings, archive = database
    before = sql("SELECT oid || ':' || extowner FROM pg_extension WHERE extname='hstore'", 'target_db')
    state = json.loads(
        run(shlex.split(pg.client_command(settings, ['psql', '-XAt', '-v', 'ON_ERROR_STOP=1', '-c', (ROOT / 'roles/postgresql/files/target_preflight.sql').read_text()]))).stdout
    )
    assert pg.validate_target(archive, state, run(['pg_restore', '--version']).stdout, 'hub')
    run(shlex.split(pg.client_command(settings, ['psql', '-XAt', '-v', 'ON_ERROR_STOP=1', '-c', pg.write_probe(archive)])))
    result = run(
        shlex.split(pg.client_command(settings, ['pg_restore', '--clean', '--if-exists', '--no-owner', '--no-acl', '--use-list', '/tmp/restore.list', '/tmp/source.pgc'])),
        check=False,
    )
    assert not pg.restore_failed({'rc': result.returncode, 'stderr': result.stderr}), result.stderr
    assert sql("SELECT oid || ':' || extowner FROM pg_extension WHERE extname='hstore'", 'target_db') == before
    assert sql("SELECT id || ':' || (attributes->'name') FROM app", 'target_db') == '1:source'
    assert sql('SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname=\'app\'', 'target_db') == 'target_user'
    assert sql("SELECT id || ':' || (attributes->'name') FROM app", 'source_db') == '1:source'
    assert sql("SELECT count(*) FROM pg_class WHERE relname LIKE '__aap_snapshot_probe_%'", 'target_db') == '0'


def test_missing_and_mismatched_extensions_rejected_before_data_changes(database):
    run, sql, settings, archive = database
    state = {
        'version': 150019,
        'writable': True,
        'database_create': True,
        'unowned_objects': 0,
        'schemas': {'public': {'usage': True, 'create': True, 'owned': True}},
        'extensions': {},
    }
    for extensions in [{}, {'hstore': 'other'}]:
        with pytest.raises(ValueError, match='hstore'):
            pg.validate_target(archive, state | {'extensions': extensions}, 'pg_restore (PostgreSQL) 15.19', 'hub')
    assert sql('SELECT count(*) FROM app', 'source_db') == '1'


def test_real_permission_and_connection_failures_are_rejected(database):
    run, sql, settings, archive = database
    sql('REVOKE CREATE ON SCHEMA public FROM target_user; ALTER SCHEMA public OWNER TO postgres;', 'target_db')
    # A role still owns its database, so exercise an object it does not own.
    sql('ALTER TABLE app OWNER TO postgres;', 'target_db')
    result = run(
        shlex.split(pg.client_command(settings, ['pg_restore', '--clean', '--if-exists', '--no-owner', '--no-acl', '--use-list', '/tmp/restore.list', '/tmp/source.pgc'])),
        check=False,
    )
    assert result.returncode != 0 and pg.restore_failed({'rc': result.returncode, 'stderr': result.stderr})
    bad = {'default': settings['default'] | {'PASSWORD': uuid.uuid4().hex}}
    result = run(shlex.split(pg.client_command(bad, ['pg_restore', '--no-owner', '--no-acl', '/tmp/source.pgc'])), check=False)
    assert result.returncode != 0 and pg.restore_failed({'rc': result.returncode, 'stderr': result.stderr})


def test_real_partition_cleanup_error_is_narrowly_classified(database):
    run, sql, settings, archive = database
    sql(
        'CREATE TABLE partition_parent (id integer, time integer UNIQUE) PARTITION BY RANGE (time); '
        'CREATE TABLE partition_child PARTITION OF partition_parent FOR VALUES FROM (0) TO (100); '
        'INSERT INTO partition_parent VALUES (1, 1);',
        'source_db',
    )
    run(['pg_dump', '-U', 'postgres', '-d', 'source_db', '-Fc', '-t', 'partition*', '-f', '/tmp/partitions.pgc'])
    run(['pg_restore', '-U', 'postgres', '-d', 'target_db', '--no-owner', '--no-acl', '/tmp/partitions.pgc'])
    result = run(['env', 'LC_ALL=C', 'pg_restore', '-U', 'postgres', '-d', 'target_db', '--clean', '--if-exists', '--no-owner', '--no-acl', '/tmp/partitions.pgc'], check=False)
    assert result.returncode == 1, result.stderr
    assert not pg.restore_failed({'rc': result.returncode, 'stderr': result.stderr}), result.stderr
    assert pg.restore_failed({'rc': result.returncode, 'stderr': result.stderr + '\npg_restore: error: COPY failed for table app: ERROR: invalid input syntax\n'})


def test_source_acl_roles_and_data_load_errors_are_real_failures(database):
    run, sql, settings, archive = database
    sql('CREATE DATABASE acl_target_db OWNER target_user;')
    sql('CREATE EXTENSION hstore;', 'acl_target_db')
    acl_settings = {'default': settings['default'] | {'NAME': 'acl_target_db'}}
    result = run(shlex.split(pg.client_command(acl_settings, ['pg_restore', '--no-owner', '--use-list', '/tmp/restore.list', '/tmp/source.pgc'])), check=False)
    assert 'source_grant_only' in result.stderr and 'does not exist' in result.stderr
    assert pg.restore_failed({'rc': result.returncode, 'stderr': result.stderr})
    result = run(shlex.split(pg.client_command(acl_settings, ['pg_restore', '--data-only', '--no-owner', '--no-acl', '/tmp/source.pgc'])), check=False)
    assert 'COPY failed' in result.stderr
    assert pg.restore_failed({'rc': result.returncode, 'stderr': result.stderr})


def test_extension_configuration_table_data_is_retained(database):
    run, sql, settings, archive = database
    # Install a test-only extension in the disposable container. Its config table
    # is administrator-owned, as with externally provisioned extensions.
    control = "default_version = '1.0'\nrelocatable = true\n"
    extension_sql = "CREATE TABLE fixture_config (id integer PRIMARY KEY, value text); SELECT pg_catalog.pg_extension_config_dump('fixture_config', '');"
    for filename, content in [('aap_snapshot_fixture.control', control), ('aap_snapshot_fixture--1.0.sql', extension_sql)]:
        run(['sh', '-c', 'cat > "/usr/share/pgsql/extension/$1"', 'sh', filename], data=content, user='0')
    sql('CREATE DATABASE config_source_db;')
    sql('CREATE DATABASE config_target_db OWNER target_user;')
    sql("CREATE EXTENSION aap_snapshot_fixture; INSERT INTO fixture_config VALUES (42, 'source extension data');", 'config_source_db')
    sql('CREATE EXTENSION aap_snapshot_fixture; GRANT SELECT, INSERT ON fixture_config TO target_user;', 'config_target_db')
    before = sql("SELECT oid FROM pg_extension WHERE extname='aap_snapshot_fixture'", 'config_target_db')
    run(['pg_dump', '-U', 'postgres', '-d', 'config_source_db', '-Fc', '-f', '/tmp/config.pgc'])
    archive = pg.archive_info(
        run(['pg_restore', '--list', '/tmp/config.pgc']).stdout, run(['pg_restore', '--verbose', '--schema-only', '--no-owner', '--no-acl', '-f', '-', '/tmp/config.pgc']).stdout
    )
    assert 'TABLE DATA public fixture_config' in archive['restore_toc']
    run(['sh', '-c', 'umask 077; cat > /tmp/config.list'], data=archive['restore_toc'])
    target = {'default': settings['default'] | {'NAME': 'config_target_db'}}
    result = run(
        shlex.split(pg.client_command(target, ['pg_restore', '--clean', '--if-exists', '--no-owner', '--no-acl', '--use-list', '/tmp/config.list', '/tmp/config.pgc'])), check=False
    )
    assert not pg.restore_failed({'rc': result.returncode, 'stderr': result.stderr}), result.stderr
    assert sql('SELECT value FROM fixture_config WHERE id=42', 'config_target_db') == 'source extension data'
    assert sql("SELECT oid FROM pg_extension WHERE extname='aap_snapshot_fixture'", 'config_target_db') == before


def test_rpm_dump_task_handles_special_source_user_and_database_names(database):
    """Render the shipped RPM task and run its argv against PostgreSQL."""
    import yaml
    from jinja2.nativetypes import NativeEnvironment

    run, sql, settings, archive = database
    user = 'source user; $HOME shell syntax'
    name = "source database='literal' \\ value"
    password = "fixture-'\"$()\\;" + uuid.uuid4().hex

    def identifier(value):
        return '"' + value.replace('"', '""') + '"'

    sql('CREATE ROLE ' + identifier(user) + " LOGIN PASSWORD '" + password.replace("'", "''") + "';")
    sql('CREATE DATABASE ' + identifier(name) + ' OWNER ' + identifier(user) + ';')
    sql('SET ROLE ' + identifier(user) + '; CREATE TABLE quoted_source (id integer); INSERT INTO quoted_source VALUES (7);', name)
    rpm_tasks = yaml.safe_load((ROOT / 'roles/postgresql/tasks/db_export.yml').read_text())[0]['block']
    task = next(task for task in rpm_tasks if task['name'] == 'Perform a PostgreSQL dump.')
    environment = NativeEnvironment()
    environment.filters['ansible.aap_snapshot.postgresql_dbname'] = pg.dbname_connection
    environment.filters['combine'] = lambda first, second: first | second
    variables = {
        'postgresql_auth_settings': {'default': settings['default'] | {'USER': user, 'NAME': name, 'PASSWORD': password}},
        'postgresql_pg_dump_env': {'PGSSLMODE': 'disable'},
        'postgresql_export_dir': '/tmp',
        'postgresql_component_name': 'quoted',
    }
    argv = [str(environment.from_string(value).render(variables)) for value in task['ansible.builtin.command']['argv']]
    env = environment.from_string(task['environment']).render(variables)
    run(['env'] + [key + '=' + value for key, value in env.items()] + argv)
    assert 'TABLE public quoted_source' in run(['pg_restore', '--list', '/tmp/quoted.pgc']).stdout


@pytest.mark.parametrize('extension_schema', ['public', 'extensions', 'custom schema'])
def test_restore_preserves_custom_extension_schema_with_spaced_source_owner(database, extension_schema):
    run, sql, settings, _ = database
    suffix = uuid.uuid4().hex[:8]
    source_db = 'schema_source_' + suffix
    target_db = 'schema_target_' + suffix
    owner = 'application owner ' + suffix
    other_schema = '"' + extension_schema + ' application"'
    quoted_schema = '"' + extension_schema.replace('"', '""') + '"'
    sql('CREATE ROLE "' + owner + '";')
    sql('CREATE DATABASE ' + source_db + ';')
    sql('CREATE DATABASE ' + target_db + ' OWNER target_user;')
    source_schema_sql = 'ALTER SCHEMA public OWNER TO "' + owner + '"; ' if extension_schema == 'public' else 'CREATE SCHEMA ' + quoted_schema + ' AUTHORIZATION "' + owner + '"; '
    sql(
        source_schema_sql + 'CREATE SCHEMA ' + other_schema + ' AUTHORIZATION source_user; '
        'CREATE TABLE ' + other_schema + '.other_payload (id integer); '
        'INSERT INTO ' + other_schema + '.other_payload VALUES (11); '
        'COMMENT ON SCHEMA ' + quoted_schema + " IS 'preserve extension schema'; "
        'CREATE EXTENSION hstore WITH SCHEMA ' + quoted_schema + '; '
        'CREATE TABLE public.payload (id integer, attributes ' + quoted_schema + '.hstore); '
        "INSERT INTO public.payload VALUES (7, 'name=>source');",
        source_db,
    )
    target_schema_sql = 'ALTER SCHEMA public OWNER TO target_user; ' if extension_schema == 'public' else 'CREATE SCHEMA ' + quoted_schema + ' AUTHORIZATION target_user; '
    sql(target_schema_sql + 'CREATE EXTENSION hstore WITH SCHEMA ' + quoted_schema + ';', target_db)
    before = sql("SELECT oid || ':' || extowner FROM pg_extension WHERE extname='hstore'", target_db)
    dump_path = '/tmp/schema-' + suffix + '.pgc'
    list_path = '/tmp/schema-' + suffix + '.list'
    run(['pg_dump', '-U', 'postgres', '-d', source_db, '-Fc', '-f', dump_path])
    archive = pg.archive_info(
        run(['pg_restore', '--list', dump_path]).stdout,
        run(['pg_restore', '--verbose', '--schema-only', '--no-owner', '--no-acl', '-f', '-', dump_path]).stdout,
    )
    target = {'default': settings['default'] | {'NAME': target_db}}
    state = json.loads(
        run(shlex.split(pg.client_command(target, ['psql', '-XAt', '-v', 'ON_ERROR_STOP=1', '-c', (ROOT / 'roles/postgresql/files/target_preflight.sql').read_text()]))).stdout
    )
    assert pg.validate_target(archive, state, run(['pg_restore', '--version']).stdout, 'hub')
    run(shlex.split(pg.client_command(target, ['psql', '-XAt', '-v', 'ON_ERROR_STOP=1', '-c', pg.write_probe(archive)])))
    run(['sh', '-c', 'umask 077; cat > "$1"', 'sh', list_path], data=archive['restore_toc'])
    result = run(
        shlex.split(pg.client_command(target, ['pg_restore', '--clean', '--if-exists', '--no-owner', '--no-acl', '--use-list', list_path, dump_path])),
        check=False,
    )
    assert not pg.restore_failed({'rc': result.returncode, 'stderr': result.stderr}), result.stderr
    assert sql("SELECT oid || ':' || extowner FROM pg_extension WHERE extname='hstore'", target_db) == before
    assert sql("SELECT id || ':' || attributes::text FROM public.payload", target_db) == '7:"name"=>"source"'
    assert sql("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname='payload'", target_db) == 'target_user'
    assert sql('SELECT id FROM ' + other_schema + '.other_payload', target_db) == '11'
