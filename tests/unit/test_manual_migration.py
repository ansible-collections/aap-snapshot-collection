"""Contracts for durable DBA migration phases and read-only readiness checks."""

import copy
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('manual', Path(__file__).parents[2] / 'plugins/filter/manual_migration.py')
manual = importlib.util.module_from_spec(spec) if spec else None
if spec and spec.loader and Path(spec.origin).exists():
    spec.loader.exec_module(manual)


def test_manual_requires_explicit_supported_phase_before_mutation():
    with pytest.raises(ValueError, match='explicit'):
        manual.check_interface(True, 'all', 'operator', 'import', False)
    with pytest.raises(ValueError, match='RPM'):
        manual.check_interface(True, 'all', 'containerized', 'export', True)
    with pytest.raises(ValueError, match='quiesced'):
        manual.check_interface(True, 'all', 'rpm', 'export', False)
    assert manual.check_interface(False, 'all', 'operator', 'import', False)
    with pytest.raises(ValueError):
        manual.check_interface(False, 'prepare', 'operator', 'import', False)


def test_binding_rejects_changed_target_archive_or_components():
    record = {'target_uid': 'uid1', 'artifact_sha256': 'a' * 64, 'components': ['controller', 'gateway'], 'phase': 'prepared'}
    assert manual.check_record(record, 'uid1', 'a' * 64, ['gateway', 'controller'], 'validate')
    for uid, digest, components in [('uid2', 'a' * 64, ['controller', 'gateway']), ('uid1', 'b' * 64, ['controller', 'gateway']), ('uid1', 'a' * 64, ['gateway'])]:
        with pytest.raises(ValueError, match='matching'):
            manual.check_record(record, uid, digest, components, 'validate')
    with pytest.raises(ValueError, match='prepare'):
        manual.check_record({}, 'uid1', 'a' * 64, ['gateway'], 'validate')


def test_capture_records_only_recovery_fields():
    parent = {
        'apiVersion': 'aap/v1',
        'kind': 'AnsibleAutomationPlatform',
        'metadata': {'name': 'test', 'uid': 'uid1', 'namespace': 'ns'},
        'spec': {'database': {'password': 'never-store'}, 'admin_password': 'never-store'},
    }
    resource = manual.hold_resource(parent)
    assert resource['original'] == {'idle_aap': None, 'database': {'idle_disabled': None}}
    assert 'never-store' not in str(resource)
    assert resource['held'] == {'idle_aap': True, 'database': {'idle_disabled': True}}


def target_state():
    return {
        'version': 150006,
        'writable': True,
        'database_create': True,
        'schemas': {'public': {'usage': True, 'create': True}},
        'object_privileges': True,
        'extensions': {'hstore': 'public'},
        'migrations': ['core:0001', 'core:0002'],
        'tables': ['public.django_migrations', 'public.core_data'],
    }


@pytest.mark.parametrize('component', ['controller', 'gateway', 'hub', 'eda'])
def test_readiness_compares_schema_metadata(component):
    state = target_state()
    source = copy.deepcopy(state)
    assert manual.validate_database(state, source, component)['ready']
    state['migrations'].remove('core:0002')
    with pytest.raises(ValueError, match='migration'):
        manual.validate_database(state, source, component)


@pytest.mark.parametrize(
    'field,value,error',
    [('writable', False, 'writable'), ('database_create', False, 'CREATE'), ('object_privileges', False, 'privileges'), ('extensions', {}, 'extension'), ('tables', [], 'table')],
)
def test_readiness_rejects_unrestored_or_unusable_databases(field, value, error):
    state = target_state()
    source = copy.deepcopy(state)
    state[field] = value
    with pytest.raises(ValueError, match=error):
        manual.validate_database(state, source, 'hub')


def test_legacy_verification_is_explicitly_reduced():
    result = manual.validate_database(target_state(), {}, 'controller')
    assert result['ready']
    assert 'reduced' in result['verification']


def test_target_selection_uses_owner_uid_and_preserves_unrelated_deployments():
    parent = {'metadata': {'uid': 'parent', 'name': 'aap'}}
    owned = {'kind': 'Deployment', 'metadata': {'name': 'app', 'uid': 'deploy', 'ownerReferences': [{'uid': 'child'}]}}
    unrelated = {'kind': 'Deployment', 'metadata': {'name': 'other', 'uid': 'other', 'labels': {'app.kubernetes.io/part-of': 'other'}}}
    assert manual.target_resources([owned, unrelated], parent, ['child']) == [owned]


def test_active_migration_jobs_and_terminating_writer_pods_block_prepare():
    recovery = [{'uid': 'deploy'}]
    replica = {'metadata': {'uid': 'rs', 'ownerReferences': [{'uid': 'deploy'}]}}
    pod = {'metadata': {'name': 'writer', 'uid': 'pod', 'ownerReferences': [{'uid': 'rs'}], 'deletionTimestamp': 'now'}, 'status': {'phase': 'Running'}}
    job = {'metadata': {'uid': 'job', 'name': 'migration'}, 'status': {'active': 1}}
    assert manual.active_writers([pod], recovery, [replica], [job]) == ['writer', 'job/migration']
    pod['status']['phase'] = 'Succeeded'
    job['status'] = {'succeeded': 1, 'active': 0, 'conditions': [{'type': 'Complete', 'status': 'True'}]}
    assert manual.active_writers([pod], recovery, [replica], [job]) == []


def test_new_workload_hold_is_append_only_and_replacements_are_rejected():
    recovery = [{'uid': 'old', 'kind': 'Deployment', 'name': 'existing'}]
    existing = {'kind': 'Deployment', 'metadata': {'uid': 'old', 'name': 'existing'}}
    new = {'kind': 'Deployment', 'metadata': {'uid': 'new', 'name': 'new-writer'}}
    assert manual.new_workloads([existing, new], recovery) == [new]
    existing['metadata']['uid'] = 'replacement'
    with pytest.raises(ValueError, match='replaced'):
        manual.new_workloads([existing], recovery)


def test_only_completed_selected_controller_migration_jobs_are_reset():
    job = {
        'metadata': {
            'name': 'aap-controller-migration-4.6.16',
            'uid': 'job1',
            'labels': {
                'app.kubernetes.io/component': 'automationcontroller',
                'app.kubernetes.io/managed-by': 'automationcontroller-operator',
                'app.kubernetes.io/part-of': 'aap-controller',
            },
        },
        'status': {'succeeded': 1, 'conditions': [{'type': 'Complete', 'status': 'True'}]},
    }
    other = {'metadata': {'name': 'unrelated-migration', 'uid': 'other'}, 'status': {'succeeded': 1}}
    assert manual.controller_jobs([job, other], 'aap-controller') == [{'name': 'aap-controller-migration-4.6.16', 'uid': 'job1'}]
    job['status'] = {'active': 1}
    with pytest.raises(ValueError, match='unfinished'):
        manual.controller_jobs([job], 'aap-controller')


def test_scheduled_database_writers_are_suspended_with_original_state_retained():
    cron = {
        'apiVersion': 'batch/v1',
        'kind': 'CronJob',
        'metadata': {'name': 'metrics', 'namespace': 'aap', 'uid': 'cron'},
        'spec': {'schedule': '0 * * * *', 'jobTemplate': {'credentials': 'never-store'}},
    }
    held = manual.hold_resource(cron)
    assert held['held'] == {'suspend': True}
    assert held['original'] == {'suspend': None}
    assert 'never-store' not in str(held)


def test_partially_succeeded_migration_job_remains_a_writer():
    job = {
        'metadata': {
            'uid': 'partial',
            'name': 'aap-controller-migration-v1',
            'labels': {
                'app.kubernetes.io/component': 'automationcontroller',
                'app.kubernetes.io/managed-by': 'automationcontroller-operator',
                'app.kubernetes.io/part-of': 'aap-controller',
            },
        },
        'spec': {'completions': 2},
        'status': {'succeeded': 1},
    }
    assert manual.active_writers([], [], [], [job]) == ['job/aap-controller-migration-v1']
    with pytest.raises(ValueError, match='unfinished'):
        manual.controller_jobs([job], 'aap-controller')


def test_legacy_declared_postgresql_version_still_prevents_downgrade():
    state = target_state()
    state['version'] = 140019
    with pytest.raises(ValueError, match='downgrade'):
        manual.validate_database(state, {}, 'controller', '15')


def test_completed_record_allows_only_idempotent_finalization_retry():
    record = {'target_uid': 'uid', 'artifact_sha256': 'a' * 64, 'components': ['gateway'], 'phase': 'complete'}
    for phase in ['prepare', 'validate']:
        with pytest.raises(ValueError, match='completed'):
            manual.check_record(record, 'uid', 'a' * 64, ['gateway'], phase)
    assert manual.check_record(record, 'uid', 'a' * 64, ['gateway'], 'finalize')
