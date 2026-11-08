# Copyright: (c) 2026, Red Hat, Inc.
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Contracts for DBA-managed migrations. Never put credentials in recovery records."""


def check_interface(skip, phase, platform, operation, quiesced):
    if phase not in ('all', 'prepare', 'validate', 'finalize'):
        raise ValueError('Unknown artifact_import_phase')
    if not skip:
        if phase != 'all':
            raise ValueError('Phased import requires postgres_skip_data=true')
        return True
    if operation == 'import':
        if platform != 'operator' or phase == 'all':
            raise ValueError('DBA import requires OCP and an explicit prepare, validate or finalize phase')
    else:
        if platform != 'rpm':
            raise ValueError('DBA export currently supports RPM only')
        if phase != 'all':
            raise ValueError('Export does not accept import phases')
        if not quiesced:
            raise ValueError('Confirm source writers are quiesced with artifact_source_quiesced=true')
    return True


def check_record(record, uid, digest, components, phase):
    if not record:
        if phase != 'prepare':
            raise ValueError('Run prepare first; no migration record exists')
        return True
    if record.get('target_uid') != uid or record.get('artifact_sha256') != digest or sorted(record.get('components', [])) != sorted(components):
        raise ValueError('A matching target UID, artifact SHA-256 and component set is required; retain the existing recovery record')
    if record.get('phase') == 'complete' and phase != 'finalize':
        raise ValueError('Migration already completed; only an idempotent finalize retry is permitted. Archive the completed record before another migration')
    if phase in ('validate', 'finalize') and record.get('phase') == 'preparing':
        raise ValueError('Run prepare again to finish holding the target')
    return True


def hold_resource(resource):
    metadata = resource['metadata']
    spec = resource.get('spec', {})
    if resource['kind'] == 'AnsibleAutomationPlatform':
        original = {'idle_aap': spec.get('idle_aap'), 'database': {'idle_disabled': spec.get('database', {}).get('idle_disabled')}}
        held = {'idle_aap': True, 'database': {'idle_disabled': True}}
    elif resource['kind'] == 'CronJob':
        original, held = {'suspend': spec.get('suspend')}, {'suspend': True}
    elif resource['kind'] == 'Deployment':
        original, held = {'replicas': spec.get('replicas', 1)}, {'replicas': 0}
    else:
        original, held = {'idle_deployment': spec.get('idle_deployment')}, {'idle_deployment': True}
    return {
        'apiVersion': resource['apiVersion'],
        'kind': resource['kind'],
        'name': metadata['name'],
        'namespace': metadata['namespace'],
        'uid': metadata['uid'],
        'original': original,
        'held': held,
    }


def validate_database(state, source, component, declared_source_version=''):
    if not state.get('writable'):
        raise ValueError('Target must be writable: check recovery and default_transaction_read_only')
    if not state.get('database_create'):
        raise ValueError('Application user needs CREATE privilege on its database')
    if not state.get('object_privileges'):
        raise ValueError('Application table/sequence ownership or privileges are insufficient')
    if not state.get('tables'):
        raise ValueError('Application tables are missing')
    if not state.get('migrations'):
        raise ValueError('Application migration metadata is missing')
    schemas = source.get('schemas', {}) or {'public': {}}
    for schema in schemas:
        rights = state.get('schemas', {}).get(schema, {})
        if not rights.get('usage') or not rights.get('create'):
            raise ValueError('Application schema requires USAGE and CREATE: ' + schema)
    extensions = source.get('extensions', {}).copy()
    if component == 'hub':
        extensions.setdefault('hstore', 'public')
    for extension, schema in extensions.items():
        if state.get('extensions', {}).get(extension) != schema:
            raise ValueError('Provision required extension in matching schema: ' + extension)
    source_major = int(source['version']) // 10000 if source else int(str(declared_source_version).split('.')[0]) if declared_source_version else 0
    if int(state['version']) // 10000 < source_major:
        raise ValueError('PostgreSQL downgrade is unsupported')
    if set(source.get('migrations', [])) - set(state.get('migrations', [])):
        raise ValueError('Source application migration records are missing from target')
    if set(source.get('tables', [])) - set(state.get('tables', [])):
        raise ValueError('Source application tables are missing from target')
    return {
        'ready': True,
        'verification': 'source metadata compared' if source else 'reduced: legacy artifact has no source database metadata',
        'warning': 'Readiness does not prove restore completion or data completeness; DBA confirmation is mandatory',
    }


def target_resources(resources, parent, child_uids):
    """Scope workloads to the selected CR ownership tree, plus named auxiliary apps."""
    roots = set(child_uids) | {parent['metadata']['uid']}
    names = [parent['metadata']['name'] + suffix for suffix in ('', '-controller', '-hub', '-eda', '-lightspeed', '-mcp')]
    return [
        r
        for r in resources
        if any(o.get('uid') in roots for o in r.get('metadata', {}).get('ownerReferences', [])) or r.get('metadata', {}).get('labels', {}).get('app.kubernetes.io/part-of') in names
    ]


def active_writers(pods, recovery, replicasets, jobs):
    roots = {r['uid'] for r in recovery} | {r['metadata']['uid'] for r in jobs}
    roots |= {r['metadata']['uid'] for r in replicasets if any(o.get('uid') in roots for o in r['metadata'].get('ownerReferences', []))}
    active = [
        p['metadata']['name']
        for p in pods
        if p.get('status', {}).get('phase') not in ('Succeeded', 'Failed') and any(o.get('uid') in roots for o in p['metadata'].get('ownerReferences', []))
    ]
    active += ['job/' + j['metadata']['name'] for j in jobs if not job_complete(j)]
    return active


def new_workloads(resources, recovery):
    captured = {(r['kind'], r.get('namespace', ''), r['name']): r['uid'] for r in recovery}
    added = []
    for resource in resources:
        metadata = resource['metadata']
        key = (resource['kind'], metadata.get('namespace', ''), metadata['name'])
        if key in captured and captured[key] != metadata['uid']:
            raise ValueError('A captured workload was replaced; retain the recovery record and investigate: ' + metadata['name'])
        if key not in captured:
            added.append(resource)
    return added


def job_complete(job):
    status = job.get('status', {})
    return not status.get('active', 0) and any(c.get('type') == 'Complete' and c.get('status') == 'True' for c in status.get('conditions', []))


def controller_jobs(jobs, name):
    selected = []
    labels = {'app.kubernetes.io/component': 'automationcontroller', 'app.kubernetes.io/managed-by': 'automationcontroller-operator', 'app.kubernetes.io/part-of': name}
    for job in jobs:
        metadata = job['metadata']
        if not metadata['name'].startswith(name + '-migration-') or any(metadata.get('labels', {}).get(k) != v for k, v in labels.items()):
            continue
        if not job_complete(job):
            raise ValueError('Resolve unfinished Controller migration job before finalization: ' + metadata['name'])
        selected.append({'name': metadata['name'], 'uid': metadata['uid']})
    return selected


class FilterModule:
    def filters(self):
        return {
            'snapshot_manual_interface': check_interface,
            'snapshot_manual_record': check_record,
            'snapshot_hold_resource': hold_resource,
            'snapshot_target_resources': target_resources,
            'snapshot_active_writers': active_writers,
            'snapshot_new_workloads': new_workloads,
            'snapshot_controller_jobs': controller_jobs,
            'snapshot_validate_database': validate_database,
        }
