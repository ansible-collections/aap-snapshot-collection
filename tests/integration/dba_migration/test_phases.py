"""Run real collection tasks in distinct Ansible processes at a controlled K8s boundary."""

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import io
import tarfile
import zipfile

import pytest
import yaml

ROOT = Path(__file__).parents[3]
COMPONENTS = ['controller', 'gateway', 'hub', 'eda']


def resource(kind, name, spec=None, labels=None, owner=None, api='v1'):
    result = {'apiVersion': api, 'kind': kind, 'metadata': {'name': name, 'namespace': 'aap', 'uid': name + '-uid', 'generation': 1, 'labels': labels or {}}, 'spec': spec or {}}
    if owner:
        result['metadata']['ownerReferences'] = [{'uid': owner + '-uid'}]
    return result


def state_fixture():
    parent = resource('AnsibleAutomationPlatform', 'aap', {'controller': {}, 'hub': {}, 'eda': {}, 'database': {}}, api='aap.ansible.com/v1alpha1')
    parent['status'] = {'conditions': [{'type': 'Successful', 'reason': 'Successful', 'status': 'True'}]}
    cron = resource('CronJob', 'aap-controller-metrics', {'schedule': '0 * * * *'}, owner='aap-controller', api='batch/v1')
    completed = resource(
        'Job',
        'aap-controller-migration-4.6.15',
        labels={
            'app.kubernetes.io/component': 'automationcontroller',
            'app.kubernetes.io/managed-by': 'automationcontroller-operator',
            'app.kubernetes.io/part-of': 'aap-controller',
        },
        owner='aap-controller',
        api='batch/v1',
    )
    completed['status'] = {'succeeded': 1, 'conditions': [{'type': 'Complete', 'status': 'True'}]}
    resources = [parent, cron, completed]
    types = {
        'controller': ('AutomationController', 'automationcontroller.ansible.com/v1beta1'),
        'hub': ('AutomationHub', 'automationhub.ansible.com/v1beta1'),
        'eda': ('EDA', 'eda.ansible.com/v1alpha1'),
    }
    for component in COMPONENTS:
        name = 'aap-' + component
        if component in types:
            kind, api = types[component]
            cr = resource(kind, name, owner='aap', api=api)
            cr['status'] = {'conditions': [{'type': 'Automationhub-API-Ready', 'status': 'True'}]}
            resources.append(cr)
        labels = {
            'app.kubernetes.io/part-of': 'aap',
            'app.kubernetes.io/component': {'gateway': 'aap-gateway', 'controller': 'automationcontroller', 'eda': 'eda-api', 'hub': 'api'}[component],
            'app.kubernetes.io/name': {'gateway': 'aap', 'controller': 'aap-controller-task', 'eda': 'aap-eda', 'hub': 'automationhub-api'}[component],
        }
        if component == 'hub':
            labels.update(
                {'app.kubernetes.io/part-of': 'automationhub', 'app.kubernetes.io/managed-by': 'automationhub-operator', 'app.kubernetes.io/instance': 'automationhub-api-aap-hub'}
            )
        deployment = resource('Deployment', name, {'replicas': 2}, labels, 'aap' if component == 'gateway' else name, 'apps/v1')
        resources.append(deployment)
        resources.append(resource('ReplicaSet', name + '-rs', owner=name, api='apps/v1'))
        pod = resource('Pod', name + '-pod', {'containers': [{'name': 'api'}]}, labels, name + '-rs')
        pod['status'] = {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'}], 'containerStatuses': [{'name': 'api', 'ready': True}]}
        resources.append(pod)
        secret = resource('Secret', name + '-postgres-configuration')
        secret['data'] = {
            k: base64.b64encode(v.encode()).decode()
            for k, v in {
                'host': component + '.database.test',
                'port': '5432',
                'database': component + '_data',
                'username': component + '_app',
                'password': 'fixture-' + component,
                'sslmode': 'verify-full',
            }.items()
        }
        resources.append(secret)
    for name in [
        'aap-db-fields-encryption-secret',
        'aap-controller-secret-key',
        'aap-hub-db-fields-encryption',
        'aap-eda-secret-key',
        'aap-eda-db-fields-encryption-secret',
        'aap-resource-server',
        'aap-admin-password',
    ]:
        secret = resource('Secret', name)
        secret['data'] = {'password': base64.b64encode(b'fixture-admin').decode()}
        resources.append(secret)
    csv = resource('ClusterServiceVersion', 'aap-operator', {'version': '2.6.3'}, {'operators.coreos.com/ansible-automation-platform-operator.aap': ''})
    resources.append(csv)
    database = {
        c: {
            'version': 150019,
            'writable': True,
            'database_create': True,
            'schemas': {'public': {'usage': True, 'create': True}},
            'object_privileges': True,
            'extensions': {'hstore': 'public'},
            'migrations': ['core:0001'],
            'tables': ['public.django_migrations', 'public.core_data'],
        }
        for c in COMPONENTS
    }
    return {'resources': resources, 'database': database, 'events': []}


class Workflow:
    def __init__(self, tmp):
        self.tmp = tmp
        self.state = tmp / 'state.json'
        self.state.write_text(json.dumps(state_fixture()))
        collections = tmp / 'collections/ansible_collections'
        collection = collections / 'ansible/aap_snapshot'
        collection.parent.mkdir(parents=True)
        collection.symlink_to(ROOT, target_is_directory=True)
        modules = collections / 'kubernetes/core/plugins/modules'
        modules.mkdir(parents=True)
        source = (Path(__file__).with_name('kubernetes_boundary.py')).read_text()
        for operation in ['k8s', 'k8s_info', 'k8s_exec', 'k8s_cp']:
            (modules / (operation + '.py')).write_text(source + '\nmain(' + repr(operation) + ')\n')
        artifact = tmp / 'artifact'
        artifact.mkdir()
        manifest = {
            'schema_version': '1.2',
            'source_topology': 'rpm',
            'aap_version': '2.6',
            'components': [
                {
                    'name': c,
                    'version': '1.0.0',
                    'database_name': c + '_source',
                    'has_database_dump': False,
                    'has_content_data': False,
                    'database_metadata': self.load()['database'][c],
                }
                for c in COMPONENTS
            ],
        }
        (artifact / 'manifest.yml').write_text(yaml.safe_dump(manifest))
        keys = {k: base64.b64encode(b'original-source-key').decode() for k in ['controller_secret_key', 'gateway_secret_key', 'hub_db_fields_encryption_key', 'eda_secret_key']}
        (artifact / 'secrets.yml').write_text(yaml.safe_dump(keys))
        sums = [hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name for p in artifact.iterdir()]
        (artifact / 'sha256sum.txt').write_text('\n'.join(sums) + '\n')
        archive = tmp / 'snapshot.zip'
        with zipfile.ZipFile(archive, 'w') as archive_file:
            for payload in artifact.iterdir():
                archive_file.write(payload, 'artifact/' + payload.name)
        self.variables = tmp / 'variables.yml'
        self.variables.write_text(
            yaml.safe_dump(
                {
                    'aap_platform': 'operator',
                    'postgres_skip_data': True,
                    'artifact_file': str(archive),
                    'ocp_namespace': 'aap',
                    'ocp_utils_scale_wait_retries': 1,
                    'ocp_utils_scale_wait_delay': 0,
                    'postgresql_ocp_ssl_options': {c: {'sslmode': 'verify-full'} for c in COMPONENTS},
                    'postgresql_ocp_ssl_rootcert_secrets': {c: {'name': c + '-ca'} for c in COMPONENTS},
                }
            )
        )
        self.env = dict(
            os.environ,
            ANSIBLE_COLLECTIONS_PATH=str(tmp / 'collections') + ':' + str(Path.home() / '.ansible/collections'),
            ANSIBLE_LOCAL_TEMP=str(tmp / 'ansible-local'),
            ANSIBLE_REMOTE_TEMP=str(tmp / 'ansible-remote'),
            ANSIBLE_NOCOLOR='1',
            SNAPSHOT_BOUNDARY_STATE=str(self.state),
        )

    def load(self):
        return json.loads(self.state.read_text())

    def edit(self, **changes):
        state = self.load()
        state.update(changes)
        self.state.write_text(json.dumps(state))

    def run(self, phase, confirmed=False, success=True):
        args = [
            'ansible-playbook',
            '-i',
            'localhost,',
            '-c',
            'local',
            str(ROOT / 'playbooks/artifact_import.yaml'),
            '-e',
            '@' + str(self.variables),
            '-e',
            'artifact_import_phase=' + phase,
        ]
        if confirmed:
            args += ['-e', 'artifact_db_restore_confirmed=true']
        result = subprocess.run(args, env=self.env, cwd=self.tmp, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        (self.tmp / (phase + '.log')).write_text(result.stdout)
        assert (result.returncode == 0) == success, result.stdout[-10000:]
        return result.stdout

    def record(self):
        return json.loads(next(r for r in self.load()['resources'] if r['kind'] == 'ConfigMap')['data']['record'])

    def held(self):
        return next(r for r in self.load()['resources'] if r['kind'] == 'AnsibleAutomationPlatform')['spec'].get('idle_aap', False)


@pytest.fixture
def workflow(tmp_path):
    if not shutil.which('ansible-playbook'):
        pytest.skip('ansible-playbook is required')
    return Workflow(tmp_path)


def test_prepare_validate_finalize_across_processes(workflow):
    output = workflow.run('prepare')
    assert workflow.held()
    original = workflow.record()['recovery']
    assert 'Migration Complete' not in output
    workflow.run('prepare')
    assert workflow.record()['recovery'] == original
    workflow.run('validate')
    assert workflow.held()
    assert workflow.record()['validation_passed']
    workflow.run('finalize', success=False)
    assert workflow.held()
    output = workflow.run('finalize', confirmed=True)
    assert 'Migration Complete' in output
    assert workflow.record()['phase'] == 'complete'
    assert workflow.record()['controller_jobs_reset']
    assert not any(r['kind'] == 'Job' and '-migration-' in r['metadata']['name'] for r in workflow.load()['resources'])
    assert not next(r for r in workflow.load()['resources'] if r['kind'] == 'CronJob')['spec'].get('suspend', False)
    assert not workflow.held()
    assert workflow.record()['recovery'] == original
    commands = [e.get('command', '') for e in workflow.load()['events']]
    assert not any('pg_dump' in c or 'pg_restore' in c or 'precreate_partitions' in c for c in commands)
    for component in COMPONENTS:
        command = next(c for c in commands if 'psql' in c and 'PGUSER=' + component + '_app' in c)
        assert 'PGDATABASE' not in command
        assert component + '_data' in command
        assert '/etc/aap-snapshot-ca/' + component + '/ca.crt' in command
    assert all('fixture-' not in str(r) and 'original-source-key' not in str(r) for r in [workflow.record()])


def test_failed_validation_and_interrupted_finalize_preserve_holds(workflow):
    workflow.run('prepare')
    workflow.edit(failed_database='hub')
    workflow.run('validate', success=False)
    assert workflow.held()
    assert not workflow.record()['validation_passed']
    workflow.edit(failed_database='', interrupt_phase='keys_installed')
    workflow.run('finalize', confirmed=True, success=False)
    assert workflow.held()
    assert workflow.record()['keys_installed']
    workflow.run('finalize', confirmed=True)
    assert workflow.record()['phase'] == 'complete'


def test_invalid_phases_missing_record_and_changed_bindings_fail_before_mutation(workflow):
    workflow.run('all', success=False)
    workflow.run('validate', success=False)
    assert not workflow.held()
    assert not any(e['operation'] == 'k8s' for e in workflow.load()['events'])
    workflow.run('prepare')
    original = workflow.record()['recovery']
    archive = workflow.tmp / 'snapshot.zip'
    contents = archive.read_bytes()
    archive.write_bytes(contents + b'changed archive identity')
    workflow.run('validate', success=False)
    assert workflow.record()['recovery'] == original
    archive.write_bytes(contents)
    state = workflow.load()
    next(r for r in state['resources'] if r['kind'] == 'AnsibleAutomationPlatform')['metadata']['uid'] = 'replacement-target'
    workflow.state.write_text(json.dumps(state))
    workflow.run('validate', success=False)
    assert workflow.held()
    assert workflow.record()['target_uid'] == 'aap-uid'


def test_prepare_retries_unfinished_jobs_and_preserves_auxiliary_replica_settings(workflow):
    state = workflow.load()
    job = resource('Job', 'aap-controller-migration', owner='aap-controller', api='batch/v1')
    job['status'] = {'active': 1}
    state['resources'] += [
        job,
        resource('Deployment', 'aap-mcp', {'replicas': 3}, {'app.kubernetes.io/part-of': 'aap-mcp'}, 'aap', 'apps/v1'),
        resource('Deployment', 'ansible-mcp-server-operator-controller-manager', {'replicas': 2}, api='apps/v1'),
    ]
    workflow.state.write_text(json.dumps(state))
    workflow.run('prepare', success=False)
    assert workflow.held()
    original = workflow.record()['recovery']
    assert next(r for r in original if r['name'] == 'aap-mcp')['original'] == {'replicas': 3}
    assert next(r for r in original if r['name'] == 'ansible-mcp-server-operator-controller-manager')['original'] == {'replicas': 2}
    state = workflow.load()
    next(r for r in state['resources'] if r['kind'] == 'Job' and r['metadata']['name'] == 'aap-controller-migration')['status'] = {
        'succeeded': 1,
        'conditions': [{'type': 'Complete', 'status': 'True'}],
    }
    workflow.state.write_text(json.dumps(state))
    workflow.run('prepare')
    assert workflow.record()['recovery'] == original
    assert workflow.record()['phase'] == 'prepared'


def test_manual_export_discovers_each_database_without_dump_or_partition_commands(workflow):
    collection = workflow.tmp / 'collections/ansible_collections/ansible/aap_snapshot'
    collection.unlink()
    collection.mkdir()
    (collection / 'roles').symlink_to(ROOT / 'roles', target_is_directory=True)
    (collection / 'plugins').mkdir()
    (collection / 'plugins/filter').symlink_to(ROOT / 'plugins/filter', target_is_directory=True)
    modules = collection / 'plugins/modules'
    modules.mkdir()
    (modules / 'aap_component_info.py').write_text('''from ansible.module_utils.basic import AnsibleModule
m = AnsibleModule(argument_spec=dict(component=dict(type='str'), gather=dict(type='list', elements='str'), environment=dict(type='dict')))
c = m.params['component']
m.exit_json(changed=False, db_credentials=dict(host=c+'.source.test', port=5432,
    name=c+'_source_database', user=c+'_source_login', password='fixture-source',
    options={'sslmode':'verify-full','sslrootcert':'/fixture/ca.crt'}))
''')
    pg = workflow.tmp / 'collections/ansible_collections/community/postgresql/plugins/modules'
    pg.mkdir(parents=True)
    (pg / 'postgresql_query.py').write_text('''import json, os
from pathlib import Path
from ansible.module_utils.basic import AnsibleModule
fields = ['login_db','login_host','login_port','login_user','login_password','ssl_mode','ca_cert','ssl_cert','ssl_key','query']
m = AnsibleModule(argument_spec={k:dict(type='str') for k in fields} | {'connect_params':dict(type='dict')})
c = m.params['login_user'].split('_')[0]
assert m.params['login_db'] == c + '_source_database'
assert 'default_transaction_read_only=on' in m.params['connect_params']['options']
assert m.params['ssl_mode'] == 'verify-full'
assert m.params['ca_cert'] == '/fixture/ca.crt'
p = Path(os.environ['SNAPSHOT_BOUNDARY_STATE']); s=json.loads(p.read_text())
s['events'].append({'operation':'source_query','component':c})
p.write_text(json.dumps(s)); m.exit_json(changed=False, query_result=[{'metadata':s['database'][c]}])
''')
    play = workflow.tmp / 'export.yml'
    play.write_text(
        yaml.safe_dump(
            [
                {
                    'name': 'Metadata-only export',
                    'hosts': 'localhost',
                    'gather_facts': False,
                    'any_errors_fatal': True,
                    'vars': {'aap_platform': 'rpm', 'postgres_skip_data': True, 'ansible_become': False},
                    'tasks': [
                        {
                            'name': 'Export database metadata for every component',
                            'ansible.builtin.include_role': {'name': 'ansible.aap_snapshot.operations', 'tasks_from': 'db_export.yml'},
                            'vars': {'component_name': '{{ item }}'},
                            'loop': COMPONENTS,
                            'loop_control': {'label': '{{ item }}'},
                        },
                        {
                            'name': 'Verify original database names and metadata',
                            'ansible.builtin.assert': {
                                'that': [
                                    "_snapshot_database_metadata | length == 4",
                                    "_controller_db_name == 'controller_source_database'",
                                    "_hub_db_name == 'hub_source_database'",
                                    "_eda_db_name == 'eda_source_database'",
                                    "_gateway_db_name == 'gateway_source_database'",
                                ]
                            },
                        },
                    ],
                }
            ]
        )
    )
    result = subprocess.run(
        ['ansible-playbook', '-i', 'localhost,', '-c', 'local', str(play)],
        env=workflow.env,
        cwd=workflow.tmp,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout[-8000:]
    assert [e['component'] for e in workflow.load()['events'] if e['operation'] == 'source_query'] == COMPONENTS
    assert not list(workflow.tmp.rglob('*.pgc'))


def test_new_target_workloads_are_held_and_require_revalidation(workflow):
    workflow.run('prepare')
    original = workflow.record()['recovery']
    state = workflow.load()
    state['resources'].append(resource('Deployment', 'new-writer', {'replicas': 3}, owner='aap-controller', api='apps/v1'))
    state['resources'].append(resource('ReplicaSet', 'new-writer-rs', owner='new-writer', api='apps/v1'))
    pod = resource('Pod', 'new-writer-pod', owner='new-writer-rs')
    pod['status'] = {'phase': 'Running'}
    state['resources'].append(pod)
    workflow.state.write_text(json.dumps(state))
    workflow.run('validate', success=False)
    record = workflow.record()
    assert record['recovery'][: len(original)] == original
    assert record['recovery'][-1]['original'] == {'replicas': 3}
    assert not record['validation_passed']
    assert next(r for r in workflow.load()['resources'] if r['kind'] == 'Deployment' and r['metadata']['name'] == 'new-writer')['spec']['replicas'] == 0
    workflow.run('validate')
    assert workflow.record()['validation_passed']


def test_scheduled_job_owned_by_target_cronjob_blocks_handoff(workflow):
    state = workflow.load()
    job = resource('Job', 'metrics-with-no-labels', owner='aap-controller-metrics', api='batch/v1')
    job['status'] = {'active': 1}
    state['resources'].append(job)
    workflow.state.write_text(json.dumps(state))
    workflow.run('prepare', success=False)
    assert workflow.held()
    cron = next(r for r in workflow.load()['resources'] if r['kind'] == 'CronJob')
    assert cron['spec']['suspend']
    assert workflow.record()['phase'] == 'preparing'


def test_hub_content_checkpoint_reuses_pvc_without_reextracting_on_retry(workflow):
    artifact = workflow.tmp / 'artifact'
    manifest = yaml.safe_load((artifact / 'manifest.yml').read_text())
    next(c for c in manifest['components'] if c['name'] == 'hub')['has_content_data'] = True
    (artifact / 'manifest.yml').write_text(yaml.safe_dump(manifest))
    (artifact / 'hub').mkdir()
    with tarfile.open(artifact / 'hub/hub_content.tar', 'w') as archive:
        payload = b'existing collection and custom EE fixture'
        member = tarfile.TarInfo('artifact/example-content')
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    files = [p for p in artifact.rglob('*') if p.is_file() and p.name != 'sha256sum.txt']
    (artifact / 'sha256sum.txt').write_text('\n'.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + str(p.relative_to(artifact)) for p in files) + '\n')
    with zipfile.ZipFile(workflow.tmp / 'snapshot.zip', 'w') as archive:
        for payload in artifact.rglob('*'):
            if payload.is_file():
                archive.write(payload, 'artifact/' + str(payload.relative_to(artifact)))
    state = workflow.load()
    state['resources'].append(
        resource(
            'PersistentVolumeClaim',
            'existing-hub-media',
            labels={
                'app.kubernetes.io/name': 'automationhub-storage',
                'app.kubernetes.io/managed-by': 'automationhub-operator',
                'app.kubernetes.io/instance': 'automationhub-storage-aap-hub',
            },
        )
    )
    workflow.state.write_text(json.dumps(state))
    workflow.run('prepare')
    workflow.edit(interrupt_phase='hub_content_restored')
    workflow.run('finalize', confirmed=True, success=False)
    assert workflow.held()
    assert workflow.record()['hub_content_restored']
    workflow.run('finalize', confirmed=True)
    events = workflow.load()['events']
    assert sum('tar xf' in e.get('command', '') and '/mnt/hub-storage/media/' in e['command'] for e in events) == 1
    assert not any(e['operation'] == 'k8s' and e.get('state') == 'absent' and e['name'] == 'existing-hub-media' for e in events)


def test_optional_hub_application_key_is_installed_while_held(workflow):
    # Exercise the same shared component-specific key path used by finalization,
    # without resuming/reconciling the controlled target.
    state = workflow.load()
    state['resources'].append(resource('Secret', 'aap-hub-secret-key'))
    workflow.state.write_text(json.dumps(state))
    play = workflow.tmp / 'hub-keys.yml'
    play.write_text(
        yaml.safe_dump(
            [
                {
                    'name': 'Restore Hub keys while held',
                    'hosts': 'localhost',
                    'gather_facts': False,
                    'any_errors_fatal': True,
                    'vars': {'aap_platform': 'operator', 'artifact_secrets': {'hub_db_fields_encryption_key': 'ZGJrZXk=', 'hub_secret': 'c2Vzc2lvbmtleQ=='}},
                    'tasks': [
                        {
                            'name': 'Install component keys',
                            'ansible.builtin.include_role': {'name': 'ansible.aap_snapshot.operations', 'tasks_from': 'update_secret.yml'},
                            'vars': {'component_name': 'hub'},
                        }
                    ],
                }
            ]
        )
    )
    result = subprocess.run(
        ['ansible-playbook', '-i', 'localhost,', '-c', 'local', str(play)],
        env=workflow.env,
        cwd=workflow.tmp,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout[-6000:]
    secret = next(r for r in workflow.load()['resources'] if r['kind'] == 'Secret' and r['metadata']['name'] == 'aap-hub-secret-key')
    assert secret['data']['secret_key'] == 'c2Vzc2lvbmtleQ=='


def test_operator_upgrade_during_handoff_is_rejected_without_resuming(workflow):
    workflow.run('prepare')
    state = workflow.load()
    next(r for r in state['resources'] if r['kind'] == 'ClusterServiceVersion')['spec']['version'] = '2.7.0'
    workflow.state.write_text(json.dumps(state))
    workflow.run('validate', success=False)
    assert workflow.held()
    assert workflow.record()['phase'] == 'prepared'
