"""Read-only readiness checks against disposable real PostgreSQL 15 databases.

Run explicitly: pytest tests/integration/dba_migration/test_postgresql.py -q
Requires Podman; never connects to a user's database.
"""

import importlib.util
from pathlib import Path
import subprocess
import time
import uuid

import psycopg
import pytest

ROOT = Path(__file__).parents[3]
spec = importlib.util.spec_from_file_location('manual', ROOT / 'plugins/filter/manual_migration.py')
manual = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manual)
SQL = (ROOT / 'roles/postgresql/files/migration_metadata.sql').read_text()


def podman(*args):
    return subprocess.check_output(['podman', *args], text=True, stderr=subprocess.STDOUT).strip()


@pytest.fixture(scope='module')
def server():
    name = 'snapshot-dba-test-' + uuid.uuid4().hex[:8]
    podman(
        'run',
        '--rm',
        '-d',
        '--name',
        name,
        '-p',
        '127.0.0.1::5432',
        '-e',
        'POSTGRESQL_USER=fixture',
        '-e',
        'POSTGRESQL_PASSWORD=fixture-only',
        '-e',
        'POSTGRESQL_DATABASE=fixture',
        'quay.io/sclorg/postgresql-15-c9s:latest',
    )
    try:
        for _ in range(60):
            try:
                podman('exec', name, 'psql', '-U', 'postgres', '-d', 'postgres', '-Atc', 'SELECT 1')
                break
            except subprocess.CalledProcessError:
                time.sleep(1)
        else:
            pytest.fail('Disposable PostgreSQL fixture did not start')
        port = int(podman('port', name, '5432/tcp').rsplit(':', 1)[1])
        for component in ['controller', 'gateway', 'hub', 'eda']:
            podman('exec', name, 'psql', '-U', 'postgres', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-c', f"CREATE ROLE {component}_app LOGIN PASSWORD 'fixture-only';")
            podman('exec', name, 'psql', '-U', 'postgres', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-c', f'CREATE DATABASE {component}_data OWNER {component}_app;')
            if component == 'hub':
                podman('exec', name, 'psql', '-U', 'postgres', '-d', 'hub_data', '-v', 'ON_ERROR_STOP=1', '-c', 'CREATE EXTENSION hstore;')
            with psycopg.connect(host='127.0.0.1', port=port, dbname=component + '_data', user=component + '_app', password='fixture-only') as conn:
                conn.execute(
                    "CREATE TABLE django_migrations (app text, name text); "
                    "INSERT INTO django_migrations VALUES ('core','0001'); CREATE TABLE core_data (id serial PRIMARY KEY, value text)"
                )
        yield port
    finally:
        podman('stop', '-t', '1', name)


def connection(server, component):
    return psycopg.connect(host='127.0.0.1', port=server, dbname=component + '_data', user=component + '_app', password='fixture-only')


def metadata(conn):
    conn.execute('BEGIN READ ONLY')
    conn.execute('SET LOCAL statement_timeout=10000')
    result = conn.execute(SQL).fetchone()[0]
    conn.rollback()
    return result


@pytest.mark.parametrize('component', ['controller', 'gateway', 'hub', 'eda'])
def test_each_application_user_can_validate_without_dba_credentials(server, component):
    with connection(server, component) as conn:
        state = metadata(conn)
        assert manual.validate_database(state, state, component)['ready']
        assert conn.execute('SELECT count(*) FROM django_migrations').fetchone()[0] == 1
        assert state['migrations'] == ['core:0001']


def test_rejects_missing_schema_migrations_and_extension(server):
    with connection(server, 'hub') as conn:
        source = metadata(conn)
        conn.execute('DELETE FROM django_migrations')
        conn.commit()
        with pytest.raises(ValueError, match='migration'):
            manual.validate_database(metadata(conn), source, 'hub')
        conn.execute("INSERT INTO django_migrations VALUES ('core','0001')")
        conn.commit()
        source['extensions']['not_installed'] = 'public'
        with pytest.raises(ValueError, match='extension'):
            manual.validate_database(metadata(conn), source, 'hub')


def test_readiness_requires_all_dml_privileges(server):
    with connection(server, 'controller') as conn:
        source = metadata(conn)
        conn.execute('REVOKE INSERT ON core_data FROM controller_app')
        conn.commit()
        try:
            with pytest.raises(ValueError, match='privileges'):
                manual.validate_database(metadata(conn), source, 'controller')
        finally:
            conn.execute('GRANT INSERT ON core_data TO controller_app')
            conn.commit()


def test_default_read_only_server_is_rejected(server):
    with connection(server, 'eda') as conn:
        conn.execute("SET default_transaction_read_only=on")
        conn.commit()
        with pytest.raises(ValueError, match='writable'):
            manual.validate_database(metadata(conn), {}, 'eda')
