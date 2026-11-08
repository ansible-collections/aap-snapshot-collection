"""Controlled Kubernetes boundary for real Ansible workflow tests.

Installed only into the temporary test collection. It models persisted resources,
application holds and operator-created pods; it never contacts a Kubernetes API.
"""

import copy
import json
import os
import shlex
from pathlib import Path

from ansible.module_utils.basic import AnsibleModule


def merge(target, patch):
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict):
            merge(target.setdefault(key, {}), value)
        else:
            target[key] = value


def main(operation):
    module = AnsibleModule(
        argument_spec={
            'api_version': {'type': 'str'},
            'kind': {'type': 'str'},
            'name': {'type': 'str'},
            'namespace': {'type': 'str'},
            'state': {'type': 'str'},
            'definition': {'type': 'dict'},
            'merge_type': {'type': 'str'},
            'label_selectors': {'type': 'list', 'elements': 'str', 'default': []},
            'field_selectors': {'type': 'list', 'elements': 'str', 'default': []},
            'pod': {'type': 'str'},
            'container': {'type': 'str'},
            'command': {'type': 'str'},
            'local_path': {'type': 'str'},
            'remote_path': {'type': 'str'},
            'delete_options': {'type': 'dict'},
            'wait': {'type': 'bool'},
            'wait_timeout': {'type': 'int'},
        }
    )
    path = Path(os.environ['SNAPSHOT_BOUNDARY_STATE'])
    state = json.loads(path.read_text())
    args = module.params
    definition = args.get('definition') or {}
    kind = args.get('kind') or definition.get('kind')
    name = args.get('name') or definition.get('metadata', {}).get('name')
    namespace = args.get('namespace') or definition.get('metadata', {}).get('namespace', 'aap')
    parent = next(r for r in state['resources'] if r['kind'] == 'AnsibleAutomationPlatform')
    held = parent['spec'].get('idle_aap', False)
    event = {'operation': operation, 'kind': kind, 'name': name}
    result = {'changed': False}
    if operation == 'k8s_info':
        resources = [
            copy.deepcopy(r) for r in state['resources'] if r['kind'] == kind and r['metadata'].get('namespace') == namespace and (not name or r['metadata']['name'] == name)
        ]
        if kind == 'Pod' and held:
            resources = [r for r in resources if r['metadata'].get('labels', {}).get('app', '').startswith('aap-migrate-')]
        for selector in args['label_selectors']:
            key, _, value = selector.partition('=')
            resources = [r for r in resources if key in r['metadata'].get('labels', {}) and (not value or r['metadata']['labels'][key] == value)]
        if kind == 'Deployment':
            for resource in resources:
                count = resource['spec'].get('replicas', 1)
                resource['status'] = {'replicas': count, 'updatedReplicas': count, 'availableReplicas': count, 'observedGeneration': 1}
        result['resources'] = resources
    elif operation == 'k8s':
        event['state'] = args['state']
        existing = next((r for r in state['resources'] if r['kind'] == kind and r['metadata']['name'] == name and r['metadata'].get('namespace') == namespace), None)
        if args['state'] == 'absent':
            if existing:
                uid = (args.get('delete_options') or {}).get('preconditions', {}).get('uid')
                if uid and existing['metadata']['uid'] != uid:
                    module.fail_json(msg='UID precondition failed')
                state['resources'].remove(existing)
            if kind == 'Deployment':
                state['resources'] = [r for r in state['resources'] if r['kind'] != 'Pod' or r['metadata'].get('labels', {}).get('app') != name]
        else:
            if args['state'] == 'patched' and not existing:
                module.fail_json(msg='Test fixture resource missing: ' + str(kind) + '/' + str(name))
            if not existing:
                existing = {'apiVersion': definition.get('apiVersion', 'v1'), 'kind': kind, 'metadata': {'name': name, 'namespace': namespace, 'uid': name + '-uid'}}
                state['resources'].append(existing)
            merge(existing, definition)
            if kind == 'ConfigMap' and state.get('interrupt_phase'):
                record = json.loads(existing['data']['record'])
                if record.get(state['interrupt_phase']):
                    state['interrupt_phase'] = ''
                    path.write_text(json.dumps(state))
                    module.fail_json(msg='Injected interrupted phase after durable checkpoint')
            if kind == 'Deployment' and name.startswith('aap-migrate-'):
                pod = {
                    'apiVersion': 'v1',
                    'kind': 'Pod',
                    'metadata': {'name': name + '-pod', 'namespace': namespace, 'uid': name + '-pod-uid', 'labels': {'app': name}},
                    'spec': {'containers': [{'name': 'postgres'}]},
                    'status': {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'}], 'containerStatuses': [{'name': 'postgres', 'ready': True}]},
                }
                state['resources'] = [r for r in state['resources'] if r['kind'] != 'Pod' or r['metadata']['name'] != pod['metadata']['name']] + [pod]
        result['changed'] = True
    elif operation == 'k8s_exec':
        command = args['command']
        event['command'] = command
        output, rc = '', 0
        if any(word in command for word in ['pg_dump', 'pg_restore', 'precreate_partitions']):
            module.fail_json(msg='Forbidden data-transfer command in manual workflow')
        if 'psql' in shlex.split(command):
            component = next(c for c in ['controller', 'gateway', 'hub', 'eda'] if 'PGUSER=' + c + '_app' in command)
            output = json.dumps(state['database'][component])
            if state.get('failed_database') == component:
                rc = 1
        elif 'importlib.metadata' in command:
            output = '4.6.15' if 'awx' in command else '4.10.3' if 'pulpcore' in command else '1.1.0' if 'aap_eda' in command else '1.2.0'
        elif 'django.VERSION' in command:
            output = '5'
        elif '/VERSION' in command:
            output = '2.6.3'
        elif 'sha1sum' in command:
            rc = 1
        elif 'json.dumps(orphans)' in command:
            output = '[]'
        elif 'DEFAULT_FILE_STORAGE' in command or 'STORAGES' in command:
            output = json.dumps({'DEFAULT_FILE_STORAGE': 'django.core.files.storage.FileSystemStorage'})
        result.update(rc=rc, stdout=output, stdout_lines=output.splitlines(), stderr='')
    state.setdefault('events', []).append(event)
    path.write_text(json.dumps(state))
    module.exit_json(**result)
