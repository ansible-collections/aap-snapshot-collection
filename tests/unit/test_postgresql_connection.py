"""Shared prerequisites retain independent identities and safe libpq arguments."""

import base64
import importlib.util
from pathlib import Path
import shlex

import pytest

spec = importlib.util.spec_from_file_location('connection', Path(__file__).parents[2] / 'plugins/filter/postgresql_connection.py')
connection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connection)


def test_credentials_and_tls_are_component_specific():
    for component in ['controller', 'gateway', 'hub', 'eda']:
        values = {'host': component + '.test', 'port': '5432', 'database': component + ' database', 'username': component + '_app', 'password': "odd ' $(value)"}
        settings = connection.decode_pg_secret({k: base64.b64encode(v.encode()).decode() for k, v in values.items()})
        settings['default']['OPTIONS'] = {'sslmode': 'verify-full', 'sslrootcert': '/ca/' + component}
        command = connection.client_command(settings, ['psql', '-XqAt', '--command', 'SELECT 1'])
        args = shlex.split(command)
        assert 'PGPASSWORD=odd \' $(value)' in args
        assert 'PGSSLROOTCERT=/ca/' + component in args
        assert 'PGUSER=' + component + '_app' in args
        assert args[args.index('--dbname') + 1] == "dbname='" + component + " database'"
        assert 'PGCONNECT_TIMEOUT=10' in args


def test_effective_status_secret_wins_over_parent_and_unrelated_children():
    parent = {'metadata': {'name': 'aap', 'uid': 'selected'}, 'status': {'controllerDatabaseSecret': 'effective'}}
    unrelated = {'metadata': {'name': 'other', 'ownerReferences': [{'uid': 'other'}]}, 'spec': {'postgres_configuration_secret': 'wrong'}}
    assert connection.resolve_pg_secret(parent, 'controller', [unrelated]) == 'effective'
    parent['status'] = {}
    assert connection.resolve_pg_secret(parent, 'controller', [unrelated]) == 'aap-controller-postgres-configuration'


def test_ca_secret_keys_and_mounts_remain_independent():
    resources = connection.ca_mounts({'hub': {'name': 'hub-ca', 'key': 'root.pem'}, 'eda': {'name': 'eda-ca'}})
    assert resources['volumes'][0]['secret']['items'] == [{'key': 'root.pem', 'path': 'ca.crt'}]
    assert resources['mounts'][1] == {'name': 'postgres-ca-eda', 'mountPath': '/etc/aap-snapshot-ca/eda', 'readOnly': True}
    with pytest.raises(ValueError):
        connection.ca_mounts({'unknown': {'name': 'ca'}})
