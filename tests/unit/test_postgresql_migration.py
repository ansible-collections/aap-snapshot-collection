"""Contracts for migration into independently provisioned PostgreSQL databases."""

import base64
import importlib.util
from pathlib import Path
import shlex
import subprocess

import pytest


@pytest.fixture(scope='module')
def pg():
    path = Path(__file__).parents[2] / 'plugins/filter/postgresql_migration.py'
    assert path.exists(), 'PostgreSQL migration helpers have not been implemented'
    spec = importlib.util.spec_from_file_location('postgresql_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolved_status_wins_over_spec_and_other_deployments(pg):
    aap = {
        'metadata': {'name': 'selected', 'uid': 'chosen'},
        'status': {'controllerDatabaseSecret': 'resolved-db'},
        'spec': {'controller': {'postgres_configuration_secret': 'requested-db'}},
    }
    assert pg.resolve_pg_secret(aap, 'controller', []) == 'resolved-db'
    del aap['status']['controllerDatabaseSecret']
    crs = [
        {'metadata': {'ownerReferences': [{'uid': 'other'}]}, 'spec': {'postgres_configuration_secret': 'wrong'}},
        {'metadata': {'ownerReferences': [{'uid': 'chosen'}]}, 'spec': {'postgres_configuration_secret': 'effective-db'}},
    ]
    assert pg.resolve_pg_secret(aap, 'controller', crs) == 'effective-db'
    assert pg.resolve_pg_secret(aap, 'controller', []) == 'requested-db'
    assert pg.resolve_pg_secret({'metadata': {'name': 'selected'}}, 'hub', []) == 'selected-hub-postgres-configuration'


@pytest.mark.parametrize('component,field', [('gateway', 'databaseConfigurationSecret'), ('hub', 'hubDatabaseSecret'), ('eda', 'edaDatabaseSecret')])
def test_each_component_has_its_own_resolved_secret(pg, component, field):
    assert pg.resolve_pg_secret({'status': {field: component + '-external'}}, component, []) == component + '-external'


def test_password_only_secret_and_tls_without_admin_password(pg):
    data = {
        key: base64.b64encode(value.encode()).decode()
        for key, value in {'host': 'db.example', 'port': '5432', 'database': 'target-db', 'username': 'target-user', 'password': "a'\"$()\\word", 'sslmode': 'verify-full'}.items()
    }
    settings = pg.decode_pg_secret(data)
    assert settings['default']['NAME'] == 'target-db'
    assert settings['default']['USER'] == 'target-user'
    assert settings['default']['OPTIONS'] == {'sslmode': 'verify-full'}
    del data['host']
    with pytest.raises(ValueError, match='host'):
        pg.decode_pg_secret(data)


def test_tls_options_are_independent_and_reset_between_components(pg):
    assert pg.ssl_environment({'sslmode': 'verify-full', 'sslrootcert': '/root ca.pem'}) == {'PGSSLMODE': 'verify-full', 'PGSSLROOTCERT': '/root ca.pem'}
    assert pg.ssl_environment({'sslcert': '/client.pem'}) == {'PGSSLCERT': '/client.pem'}
    assert pg.ssl_environment({}) == {}


def test_command_preserves_password_and_identifiers_without_shell_execution(pg, tmp_path):
    executable = tmp_path / 'psql'
    executable.write_text('#!/usr/bin/env python3\nimport os,sys,json\nprint(json.dumps([os.environ["PGPASSWORD"], sys.argv[1:]]))\n')
    executable.chmod(0o700)
    settings = {
        'default': {
            'HOST': 'db; echo injected',
            'PORT': '5432',
            'USER': 'other user',
            'NAME': "dbname='source' \\ target",
            'PASSWORD': "'\"$(touch /tmp/unwanted);\\$word",
            'OPTIONS': {},
        }
    }
    command = pg.client_command(settings, [str(executable), '-At', '-c', 'SELECT 1'])
    result = subprocess.run(shlex.split(command), text=True, capture_output=True, check=True)
    import json

    password, argv = json.loads(result.stdout)
    assert password == settings['default']['PASSWORD']
    assert argv == ['--dbname', "dbname='dbname=\\'source\\' \\\\ target'", '-At', '-c', 'SELECT 1']
    assert not Path('/tmp/unwanted').exists()


KNOWN = '''pg_restore: while PROCESSING TOC:
pg_restore: from TOC entry 10; 2606 123 CONSTRAINT child child_pkey source
pg_restore: error: could not execute query: ERROR:  cannot drop inherited constraint "child_pkey" of relation "child"
Command was: ALTER TABLE ONLY public.child DROP CONSTRAINT IF EXISTS child_pkey;
pg_restore: warning: errors ignored on restore: 1
'''


@pytest.mark.parametrize(
    'rc,stderr,failed',
    [
        (0, '', False),
        (1, KNOWN, False),
        (2, KNOWN, True),
        (1, '', True),
        (1, 'pg_restore: error: connection to server failed: FATAL: password authentication failed', True),
        (1, 'pg_restore: error: could not execute query: ERROR: permission denied for table foo', True),
        (1, 'pg_restore: error: could not execute query: ERROR: role "source" does not exist', True),
        (1, 'pg_restore: error: COPY failed for table foo: ERROR: invalid input syntax', True),
        (0, 'pg_restore: error: bad SQL', True),
        (1, KNOWN.replace('DROP CONSTRAINT IF EXISTS child_pkey', 'ADD CONSTRAINT child_pkey'), True),
        (1, KNOWN.replace('child_pkey;', 'other_key;'), True),
        (1, KNOWN.replace('public.child DROP', 'public.other DROP'), True),
        (1, KNOWN + 'pg_restore: error: unexpected EOF', True),
        (1, KNOWN.replace('restore: 1', 'restore: 2'), True),
    ],
)
def test_only_identified_inherited_constraint_cleanup_can_be_ignored(pg, rc, stderr, failed):
    assert pg.restore_failed({'rc': rc, 'stderr': stderr}) is failed


TOC = ''';
; Dumped from database version: 15.7
; Dumped by pg_dump version: 15.7
;
1; 2615 2200 SCHEMA - public source
2; 3079 123 EXTENSION - hstore
3; 0 0 COMMENT - EXTENSION hstore
4; 1259 456 TABLE public app source
5; 0 456 TABLE DATA public app source
6; 0 999 TABLE DATA public extension_config source
'''
SCHEMA = '-- TOC entry 1 (class 2615 OID 2200)\nCREATE SCHEMA public;\n-- TOC entry 2 (class 3079 OID 123)\nCREATE EXTENSION IF NOT EXISTS hstore WITH SCHEMA public;\n'


def test_filter_preserves_application_and_extension_configuration_data(pg):
    archive = pg.archive_info(TOC, SCHEMA)
    assert archive['extensions'] == {'hstore': 'public'}
    assert 'EXTENSION' not in archive['restore_toc']
    assert 'SCHEMA - public' not in archive['restore_toc']
    assert 'TABLE DATA public extension_config source' in archive['restore_toc']
    assert 'TABLE public app source' in archive['restore_toc']
    assert archive['source_major'] == archive['dump_major'] == 15


def test_extension_schema_uses_quoted_sql_identifiers(pg):
    assert pg.archive_info(TOC, '-- TOC entry 1 (class 2615 OID 2200)\nCREATE SCHEMA "custom schema";\nCREATE EXTENSION IF NOT EXISTS hstore WITH SCHEMA "custom schema";')[
        'extensions'
    ] == {'hstore': 'custom schema'}


def target_state():
    return {
        'version': 150007,
        'writable': True,
        'database_create': True,
        'extensions': {'hstore': 'public'},
        'schemas': {'public': {'usage': True, 'create': True, 'owned': True}},
        'unowned_objects': 0,
    }


@pytest.mark.parametrize(
    'mutation,message',
    [
        ({'extensions': {}}, 'hstore'),
        ({'extensions': {'hstore': 'wrong'}}, 'hstore'),
        ({'writable': False}, 'writable'),
        ({'database_create': False}, 'CREATE'),
        ({'unowned_objects': 1}, 'ownership'),
        ({'schemas': {'public': {'usage': True, 'create': False, 'owned': True}}}, 'public'),
        ({'version': 140010}, 'downgrade'),
    ],
)
def test_target_deficiencies_fail_before_restore(pg, mutation, message):
    state = target_state() | mutation
    with pytest.raises(ValueError, match=message):
        pg.validate_target(pg.archive_info(TOC, SCHEMA), state, 'pg_restore (PostgreSQL) 15.7', 'hub')


def test_hub_requires_hstore_even_if_archive_omits_extension(pg):
    with pytest.raises(ValueError, match='hstore'):
        pg.validate_target(pg.archive_info(TOC.replace('2; 3079 123 EXTENSION - hstore\n', ''), ''), target_state() | {'extensions': {}}, 'pg_restore (PostgreSQL) 15.7', 'hub')


@pytest.mark.parametrize('dump,restore,target', [(16, 15, 16), (15, 15, 16), (16, 16, 15)])
def test_incompatible_clients_and_downgrades_are_rejected(pg, dump, restore, target):
    archive = pg.archive_info(TOC.replace('pg_dump version: 15', f'pg_dump version: {dump}'), SCHEMA)
    with pytest.raises(ValueError, match='version|client|downgrade'):
        pg.validate_target(archive, target_state() | {'version': target * 10000}, f'pg_restore (PostgreSQL) {restore}.1', 'hub')


def test_compatible_target_is_accepted(pg):
    assert pg.validate_target(pg.archive_info(TOC, SCHEMA), target_state(), 'pg_restore (PostgreSQL) 15.7', 'hub')


def test_ca_secret_mounts_are_component_scoped_read_only(pg):
    result = pg.ca_mounts({'hub': {'name': 'aws-ca'}, 'controller': {'name': 'other-ca', 'key': 'bundle.pem'}})
    assert result['volumes'][0]['secret'] == {'secretName': 'aws-ca', 'items': [{'key': 'ca.crt', 'path': 'ca.crt'}]}
    assert result['mounts'][0] == {'name': 'postgres-ca-hub', 'mountPath': '/etc/aap-snapshot-ca/hub', 'readOnly': True}
    assert result['volumes'][1]['secret']['items'][0]['key'] == 'bundle.pem'


def test_writability_probe_quotes_application_schemas_and_rolls_back(pg):
    archive = pg.archive_info(TOC, SCHEMA + 'CREATE TABLE public.app (id integer);\nCREATE TABLE "tenant\'s schema".app (id integer);')
    sql = pg.write_probe(archive)
    assert sql.startswith('BEGIN;') and sql.endswith('ROLLBACK;')
    assert '"tenant\'s schema".' in sql
    assert 'INSERT INTO' in sql


def test_extension_only_schemas_do_not_need_application_create_privilege(pg):
    archive = pg.archive_info(
        TOC.replace('SCHEMA - public', 'SCHEMA - extensions'),
        '-- TOC entry 1 (class 2615 OID 2200)\nCREATE SCHEMA extensions;\nCREATE EXTENSION IF NOT EXISTS hstore WITH SCHEMA extensions;\nCREATE TABLE public.app (id integer);',
    )
    state = target_state() | {
        'extensions': {'hstore': 'extensions'},
        'schemas': {'public': {'usage': True, 'create': True, 'owned': True}, 'extensions': {'usage': True, 'create': False, 'owned': False}},
    }
    assert pg.validate_target(archive, state, 'pg_restore (PostgreSQL) 15.7', 'hub')


def test_missing_application_schema_requires_provisioning_or_archive_schema_ddl(pg):
    archive = pg.archive_info(TOC, SCHEMA + 'CREATE TABLE other.app (id integer);')
    with pytest.raises(ValueError, match='other'):
        pg.validate_target(archive, target_state(), 'pg_restore (PostgreSQL) 15.7', 'hub')


@pytest.mark.parametrize('server,client', [('15.7', 'pg_dump (PostgreSQL) 14.12'), ('16.1', 'pg_dump (PostgreSQL) 15.7')])
def test_source_requires_compatible_dump_client(pg, server, client):
    with pytest.raises(ValueError, match='dump client'):
        pg.validate_dump_client(server, client)


def test_source_accepts_same_or_newer_dump_client(pg):
    assert pg.validate_dump_client('15.7', 'pg_dump (PostgreSQL) 15.19')
    assert pg.validate_dump_client('15.7', 'pg_dump (PostgreSQL) 16.1')


def test_archive_accepts_actual_pg_restore_indented_version_headers(pg):
    toc = TOC.replace('; Dumped', ';     Dumped')
    assert pg.archive_info(toc, SCHEMA)['source_major'] == 15


def test_real_pg15_partition_drop_uses_if_exists_before_only(pg):
    stderr = KNOWN.replace('ALTER TABLE ONLY', 'ALTER TABLE IF EXISTS ONLY')
    assert not pg.restore_failed({'rc': 1, 'stderr': stderr})


def test_archive_schema_names_with_spaces_do_not_create_phantom_schemas(pg):
    toc = TOC.replace('TABLE public app', 'TABLE custom schema app').replace('TABLE DATA public app', 'TABLE DATA custom schema app')
    archive = pg.archive_info(toc, SCHEMA + 'CREATE TABLE "custom schema".app (id integer);')
    assert archive['schemas'] == ['custom schema', 'public']


def test_configuration_table_permissions_are_checked_before_restore(pg):
    with pytest.raises(ValueError, match='configuration'):
        pg.validate_target(pg.archive_info(TOC, SCHEMA), target_state() | {'extension_config_privileges': {'hstore': False}}, 'pg_restore (PostgreSQL) 15.7', 'hub')


def test_rpm_tls_queries_use_service_key_owner():
    """Check the privilege contract sent to Ansible's task runner."""
    import yaml

    path = Path(__file__).parents[2] / 'roles/preflight/tasks/check_databases.yml'
    tasks = yaml.safe_load(path.read_text())[0]['block']
    queries = [task for task in tasks if 'community.postgresql.postgresql_query' in task]
    assert len(queries) == 4
    for component, user in [('controller', 'awx'), ('gateway', 'gateway'), ('hub', 'pulp'), ('EDA', 'eda')]:
        task = next(task for task in queries if component.lower() in task['name'].lower())
        assert task.get('become') is True, 'TLS query must run as private key owner'
        assert task.get('become_user') == user


def test_large_restore_lists_use_file_transfer_contract():
    """Large Controller TOCs must cross the API as files, rather than argv."""
    import yaml

    path = Path(__file__).parents[2] / 'roles/postgresql/tasks/stage_restore_list.yml'
    assert path.exists(), 'restore-list file transfer is missing'
    tasks = yaml.safe_load(path.read_text())
    operations = [task for block in tasks for task in block.get('block', [])]
    assert any('kubernetes.core.k8s_cp' in task for task in operations)
    assert not any('restore_toc' in task.get('kubernetes.core.k8s_exec', {}).get('command', '') for task in operations)


def test_rpm_dump_is_an_argv_command_with_independent_tls_environment():
    import yaml

    path = Path(__file__).parents[2] / 'roles/postgresql/tasks/db_export.yml'
    tasks = yaml.safe_load(path.read_text())[0]['block']
    dump = next(task for task in tasks if task['name'] == 'Perform a PostgreSQL dump.')
    assert 'ansible.builtin.command' in dump, 'module dump shell interpolation does not preserve source identifiers'
    assert 'argv' in dump['ansible.builtin.command']
    assert 'PGPASSWORD' in dump['environment']


def test_rpm_dump_does_not_expand_literal_dollar_identifiers():
    import yaml

    task = next(
        task
        for task in yaml.safe_load((Path(__file__).parents[2] / 'roles/postgresql/tasks/db_export.yml').read_text())[0]['block']
        if task['name'] == 'Perform a PostgreSQL dump.'
    )
    from jinja2.nativetypes import NativeEnvironment
    from packaging.version import Version

    environment = NativeEnvironment()
    environment.tests['version'] = lambda actual, expected, operator: Version(actual) >= Version(expected)
    environment.filters['ternary'] = lambda condition, yes, no: yes if condition else no
    option = task['ansible.builtin.command'].get('expand_argument_vars', 'missing')
    assert environment.from_string(option).render(ansible_version={'full': '2.16.0'}, omit='omitted') is False
    assert environment.from_string(option).render(ansible_version={'full': '2.14.0'}, omit='omitted') == 'omitted'


def test_unrelated_extension_config_tables_do_not_block_import(pg):
    state = target_state() | {'extension_config_privileges': {'unrelated_extension': False}}
    assert pg.validate_target(pg.archive_info(TOC, SCHEMA), state, 'pg_restore (PostgreSQL) 15.7', 'hub')


@pytest.mark.parametrize('extension_schema', ['extensions', 'custom schema'])
def test_extension_schema_filter_accepts_spaced_owners_without_removing_other_schemas(pg, extension_schema):
    other_schema = extension_schema + ' application'
    toc = TOC.replace('SCHEMA - public source', f'SCHEMA - {extension_schema} application owner')
    toc += f'7; 0 0 COMMENT - SCHEMA {extension_schema} application owner\n'
    toc += f'8; 2615 999 SCHEMA - {other_schema} source user\n'
    schema_sql = (
        f'-- TOC entry 1 (class 2615 OID 2200)\nCREATE SCHEMA "{extension_schema}";\n'
        f'-- TOC entry 7 (class 0 OID 0)\nCOMMENT ON SCHEMA "{extension_schema}" IS \'preserve\';\n'
        f'-- TOC entry 8 (class 2615 OID 999)\nCREATE SCHEMA "{other_schema}";\n'
        f'-- TOC entry 2 (class 3079 OID 123)\nCREATE EXTENSION IF NOT EXISTS hstore WITH SCHEMA "{extension_schema}";\n'
    )
    archive = pg.archive_info(toc, schema_sql)
    assert f'SCHEMA - {extension_schema} application owner' not in archive['restore_toc']
    assert f'SCHEMA - {other_schema} source user' in archive['restore_toc']
    assert archive['restored_schemas'] == [other_schema]


def test_extension_schema_filter_rejects_missing_toc_ids_before_restore(pg):
    with pytest.raises(ValueError, match='table-of-contents metadata'):
        pg.archive_info(TOC, 'CREATE SCHEMA public;\nCREATE EXTENSION IF NOT EXISTS hstore WITH SCHEMA public;')


def test_extension_schema_filter_handles_initdb_public_schema(pg):
    schema_sql = SCHEMA.replace('CREATE SCHEMA public;', '-- Name: public; Type: SCHEMA; Schema: -; Owner: -\n-- *not* creating schema, since initdb creates it')
    assert 'SCHEMA - public' not in pg.archive_info(TOC, schema_sql)['restore_toc']
