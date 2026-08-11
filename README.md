# Ansible Collection - ansible.aap_snapshot

## Description

This collection provides a migration framework for Ansible Automation
Platform (AAP) clusters. It exports platform data into a portable artifact and
imports it into a new deployment.

**Supported migration paths:**

| Source | Target | Status |
|--------|--------|--------|
| RPM Installer | OCP Operator | Supported |
| RPM Installer | Containerized Installer | Planned |
| Containerized Installer | OCP Operator | Planned |
| Containerized Installer | Containerized Installer | Planned |
| OCP Operator | OCP Operator | Planned |

The collection handles four AAP components: Controller, Hub (with Pulp
content), Gateway, and EDA. Components are processed conditionally based on
what is present in the inventory and artifact.

## Requirements

- Ansible core >= 2.16.0
- PyYAML
- kubernetes

### Collection Dependencies

| Collection | Version |
|------------|---------|
| `ansible.posix` | `>=1.6.0` |
| `community.postgresql` | `>=3.0.0` |
| `containers.podman` | `>=1.14.0` |
| `community.general` | `>=10.7.0` |
| `kubernetes.core` | `>=3.0.0` |

> **Community dependency disclaimer:** This collection depends on
> `community.postgresql` and `community.general`, which are community-maintained
> Ansible collections. Red Hat provides full support for these dependencies when
> used as part of `ansible.aap_snapshot` through Ansible Automation Platform
> subscriptions. Red Hat will work toward replacing these community dependencies
> with certified equivalents as they become available.

### Platform Requirements

- **RPM export:** SSH access to component hosts, `become` privileges
- **OCP Operator import:** `kubeconfig` with cluster-admin or namespace-admin access
- **Containerized:** SSH access to component hosts, podman access *(planned)*

## Installation

Red Hat customers install certified collections from
[Red Hat Ansible Automation Hub](https://console.redhat.com/ansible/automation-hub/).

### Installing the collection

Install this collection with the Ansible Galaxy CLI:

```bash
ansible-galaxy collection install ansible.aap_snapshot
```

### Installing from a requirements file

Include this collection in a `requirements.yml` file and install it with
`ansible-galaxy collection install -r requirements.yml`:

```yaml
collections:
  - name: ansible.aap_snapshot
```

### Installing a specific version

Use the following syntax to install version 1.0.0:

```bash
ansible-galaxy collection install ansible.aap_snapshot:==1.0.0
```

See [using Ansible collections](https://docs.ansible.com/ansible/devel/user_guide/collections_using.html) for more details.

### Upgrading the collection

To upgrade the collection to the latest available version:

```bash
ansible-galaxy collection install ansible.aap_snapshot --upgrade
```

## Use Cases

### Export a migration artifact

Create a migration artifact from a running RPM deployment:

```bash
ansible-playbook -i inventory ansible.aap_snapshot.artifact_export -e aap_platform=rpm
```

### Import a migration artifact

Restore a migration artifact into an OCP operator deployment:

```bash
ansible-playbook -i inventory ansible.aap_snapshot.artifact_import \
  -e aap_platform=operator \
  -e artifact_file=/path/to/aap-snapshot-2.6-20260701-120000.tar \
  -e ocp_namespace=aap \
  -e aap_instance_name=aap
```

### Verify an artifact

Validate an artifact without importing it:

```bash
ansible-playbook ansible.aap_snapshot.artifact_verify \
  -e artifact_file=/path/to/aap-snapshot-2.6-20260701-120000.tar
```

## Key Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `aap_platform` | Yes | - | Platform type: `rpm` (export) or `operator` (import); `containerized` is planned |
| `artifact_dir` | No | `$PWD` | Directory for artifact creation/extraction |
| `artifact_file` | Import/Verify | - | Path to the artifact archive |
| `ocp_namespace` | OCP | `aap` | OpenShift namespace |
| `aap_instance_name` | OCP | `aap` | AAP CR instance name |
| `artifact_export_hub_content` | No | `true` | Include Pulp content data in artifact |
| `artifact_skip_postgres` | No | `false` | Skip PostgreSQL dumps on export and restores on import (auto-skip restore if artifact has no dumps) |
| `artifact_postgresql_db_type` | No | `managed` | Database topology: `managed` or `external` |

See the [variables reference](https://github.com/ansible-collections/aap-snapshot-collection/blob/main/docs/variables.md) for the complete list.

## Testing

The collection supports RPM export and OCP operator import on RHEL 8 and RHEL 9.

Dev dependencies: `pip install pytest pyyaml ansible-lint`

```bash
make lint
make syntax-check
pytest tests/unit/ -v
```

## Contributing

We welcome contributions. See [CONTRIBUTING.md](https://github.com/ansible-collections/aap-snapshot-collection/blob/main/CONTRIBUTING.md) for development setup, testing, and the pull request process.

To report a bug or request a feature, please [open an issue](https://github.com/ansible-collections/aap-snapshot-collection/issues).

## Support

This collection is maintained by the Red Hat AAP Installer team.

As Red Hat Ansible Certified Content, this collection is entitled
to support through the Ansible Automation Platform (AAP) using the
**Create issue** button on the top right corner of
[Automation Hub](https://console.redhat.com/ansible/automation-hub/).
If a support case cannot be opened with Red Hat and the collection
has been obtained either from Galaxy or GitHub, there may be community
help available on the [Ansible Forum](https://forum.ansible.com/).

## Release Notes

See the [changelog](https://github.com/ansible-collections/aap-snapshot-collection/blob/main/CHANGELOG.md) for release notes.

## Related Information

- [Architecture](https://github.com/ansible-collections/aap-snapshot-collection/blob/main/docs/architecture.md) - collection structure, role hierarchy, plugin catalog
- [Artifact Format](https://github.com/ansible-collections/aap-snapshot-collection/blob/main/docs/artifact-format.md) - SDP v1.0 artifact specification
- [Variables](https://github.com/ansible-collections/aap-snapshot-collection/blob/main/docs/variables.md) - complete variable reference
- [Workflows](https://github.com/ansible-collections/aap-snapshot-collection/blob/main/docs/workflows.md) - step-by-step export, import, and reconcile workflows
- [Debugging](https://github.com/ansible-collections/aap-snapshot-collection/blob/main/docs/debugging.md) - failure recovery procedures for import and export
- [Red Hat Ansible Automation Platform Life Cycle](https://access.redhat.com/support/policy/updates/ansible-automation-platform)

## License

GNU General Public License v3.0 or later.

See [LICENSE](https://github.com/ansible-collections/aap-snapshot-collection/blob/main/LICENSE) for the full text.
