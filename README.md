# Ansible Collection - ansible.aap_snapshot

## Description

This collection provides a migration framework for Ansible Automation
Platform (AAP) clusters. It exports platform data into a portable artifact and
imports it into a new deployment.

**Supported migration paths:**

| Source | Target | Status |
|--------|--------|--------|
| RPM Installer | OCP Operator | Supported |
| RPM Installer | Containerized Installer | Supported |
| Containerized Installer | OCP Operator | Supported |
| Containerized Installer | Containerized Installer | Supported |
| OCP Operator | OCP Operator | Supported |
| OCP Operator | Containerized Installer | Supported |

The collection handles four AAP components: Controller, Hub, Gateway, and
EDA. Hub (Pulp) content can only be imported into file-based storage; importing
that content into S3-compatible or Azure Blob object storage is not supported
for any of the migration paths above. See
[Automation Hub Content Storage](#automation-hub-content-storage) for target
storage requirements and preparation for object-storage targets. Components
are processed conditionally based on what is present in the inventory and
artifact.

## Requirements

- Ansible Automation Platform (AAP) 2.6 or later
- Ansible core >= 2.14.0
- `rsync` on both the Ansible execution host (including the execution
  environment) and the managed AAP host for RPM/containerized database exports.
  If rsync cannot run, the collection uses Ansible `fetch` as a fallback
  (which may use substantial memory for large dumps).
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
- **OCP Operator export/import:** `kubeconfig` with permissions to inspect AAP resources and secrets, execute commands in component pods, and copy files from pods
- **Containerized export:** SSH access to component hosts, podman access on component hosts
- **Containerized import:** SSH access to component hosts, podman access on component hosts

## Pre-Import Setup

The target environment must be installed and configured **before** running an import. This includes:

- Authentication (LDAP, SAML, OAuth, local users)
- TLS certificates and encryption settings
- Remote Execution Environments (REEs)
- Network and firewall configuration
- Any other environment-specific customization

### Automation Hub Content Storage

**The collection does not currently support importing Automation Hub content
into S3-compatible or Azure Blob object storage.** Hub content import supports
Pulp's FileSystem storage, including NFS-backed storage and filesystem-backed
PVCs on OpenShift.

If the target Hub uses S3-compatible or Azure Blob object storage:

1. Pre-populate the target bucket or container with the source Hub content
   outside the collection before running the import. Preserve the content paths
   referenced by the source Hub database so the imported database can locate
   those resources.
2. Export an artifact without Hub content by setting
   `automationhub_export_hub_content=false` on `artifact_export`. If an existing
   artifact includes Hub content, re-export it with this setting.
3. Run `artifact_import` with that artifact to migrate the database and other
   platform data into the configured target environment.

Pre-populating object storage does not allow an artifact containing Hub content
to be imported into that backend; the collection rejects that combination.
Customers are responsible for transferring the content and ensuring it matches
the imported Hub database. The collection does not populate the bucket or
container for them.

Automating Hub content import into object storage is a
[feature for consideration](ROADMAP.md#features-for-consideration), with no
currently scoped work or committed delivery timeline.

### Version Matching Requirement

**The target AAP version must match the source AAP version exactly (major.minor).** For example:
- A 2.6 artifact can only be imported into a 2.6 target
- A 2.7 artifact can only be imported into a 2.7 target
- Cross-version imports (e.g., 2.6 source → 2.7 target) are not supported

Cross-version database restores cause migration failures due to schema mismatches. If you need to migrate to a different AAP version, export a new artifact from a source running the target AAP version.

### Target Configuration Independence

**Important:** The import process transfers data (objects, configurations, and
Hub content when the target uses supported file-based storage) from the source
environment but does **not** override target environment configuration. Hub
content for S3-compatible or Azure Blob targets must be transferred separately
before import, as described in
[Automation Hub Content Storage](#automation-hub-content-storage). The target
must be set up according to your deployment patterns and requirements *before*
import runs. This ensures:

- Customer-configured settings are preserved
- Target environment follows the intended design
- No unexpected configuration changes occur during import
- Each target deployment remains independent and customized

See [Workflows](https://github.com/ansible-collections/aap-snapshot-collection/blob/main/docs/workflows.md) for detailed pre-import checklist steps.

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

Export from an RPM deployment:

```bash
ansible-playbook -i inventory ansible.aap_snapshot.artifact_export -e aap_platform=rpm
```

Export from a containerized deployment:

```bash
ansible-playbook -i inventory ansible.aap_snapshot.artifact_export -e aap_platform=containerized
```

Export from an OCP operator deployment using a localhost inventory:

```bash
ansible-playbook -i localhost, ansible.aap_snapshot.artifact_export \
  -e aap_platform=operator \
  -e ocp_namespace=aap \
  -e aap_instance_name=aap
```

OCP exports include a sanitized `aap_cr.yml` reference in the artifact. Hub
content export supports file-storage PVCs; set
`artifact_export_hub_content=false` to omit Hub content. OCP Hub content on
S3 or Azure Blob is not supported.

### Import a migration artifact

If the artifact includes Hub content, the target Hub must use file-based
storage, such as NFS or a filesystem-backed PVC. For S3-compatible or Azure
Blob targets, pre-populate the object storage and use an artifact exported
without Hub content, as described in
[Automation Hub Content Storage](#automation-hub-content-storage), before
running either import command below.

Restore into an OCP operator deployment:

```bash
ansible-playbook -i inventory ansible.aap_snapshot.artifact_import \
  -e aap_platform=operator \
  -e artifact_file=/path/to/aap-snapshot-2.6-20260701-120000.tar \
  -e ocp_namespace=aap \
  -e aap_instance_name=aap
```

Restore into a containerized deployment:

```bash
ansible-playbook -i inventory ansible.aap_snapshot.artifact_import \
  -e aap_platform=containerized \
  -e artifact_file=/path/to/aap-snapshot-2.6-20260701-120000.tar
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
| `aap_platform` | Yes | - | Source/target platform: `rpm`, `containerized`, or `operator` |
| `artifact_dest_dir` | No | `$PWD` | Directory where the final artifact `.tar` is written (export) |
| `artifact_build_dir` | No | `$PWD/artifact` | Scratch directory used during artifact assembly (export) |
| `artifact_file` | Import/Verify | - | Path to the artifact archive |
| `ocp_namespace` | OCP | `aap` | OpenShift namespace |
| `aap_instance_name` | OCP | `aap` | AAP CR instance name |
| `automationhub_export_hub_content` | No | `true` | Include Hub (Pulp) content in the export. Set to `false` for S3-compatible or Azure Blob targets and pre-populate their content separately; see [storage prerequisites](#automation-hub-content-storage). |
| `automationhub_import_hub_content` | No | `true` | Restore Hub (Pulp) content on containerized targets. Set to `false` to skip content restoration. This does not bypass the [storage prerequisites](#automation-hub-content-storage) or enable S3-compatible or Azure Blob content import. |
| `artifact_postgresql_db_type` | No | `managed` | Database topology: `managed` or `external` |

See the [variables reference](docs/variables.md) for the complete list.

## Testing

The collection supports RPM, containerized, and OCP operator export, and OCP
operator and containerized import. RPM and containerized paths run on RHEL 8
and RHEL 9.

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

See the [changelog](https://github.com/ansible-collections/aap-snapshot-collection/blob/main/CHANGELOG.rst) for release notes.

## Related Information

- [Architecture](https://github.com/ansible-collections/aap-snapshot-collection/blob/main/docs/architecture.md) - collection structure, role hierarchy, plugin catalog
- [Artifact Format](https://github.com/ansible-collections/aap-snapshot-collection/blob/main/docs/artifact-format.md) - SDP v1.0 artifact specification
- [Variables](docs/variables.md) - complete variable reference
- [Workflows](https://github.com/ansible-collections/aap-snapshot-collection/blob/main/docs/workflows.md) - step-by-step export, import, and reconcile workflows
- [Debugging](https://github.com/ansible-collections/aap-snapshot-collection/blob/main/docs/debugging.md) - failure recovery procedures for import and export
- [Red Hat Ansible Automation Platform Life Cycle](https://access.redhat.com/support/policy/updates/ansible-automation-platform)

## License

GNU General Public License v3.0 or later.

See [LICENSE](https://github.com/ansible-collections/aap-snapshot-collection/blob/main/LICENSE) for the full text.
