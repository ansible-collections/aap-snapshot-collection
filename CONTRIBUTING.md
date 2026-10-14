## Contributing

We welcome contributions to the AAP Migration Collection. This guide covers the development setup, testing, and contribution process.

## Setup Development Environment

```bash
mkdir -p ansible_collections/ansible/
git clone git@github.com:ansible-automation-platform/aap-snapshot-collection ansible_collections/ansible/aap_snapshot
cd ansible_collections/ansible/aap_snapshot
```

The directory structure is important. `ansible_collections/ansible/aap_snapshot` is where this repo should live for Ansible to resolve it correctly.

```
ansible_collections
└── ansible
    └── aap_snapshot
        ├── galaxy.yml
        ├── LICENSE
        ├── playbooks
        ├── plugins
        ├── README.md
        ├── roles
        └── tests
```

### Install Dependencies

```bash
pip install ansible-core ansible-lint black flake8 antsibull-changelog
ansible-galaxy collection install -r requirements.yml
```

When adding, removing, or changing a collection dependency, update both the root
`galaxy.yml` and `requirements.yml` in the same change. Keep the dependency's
fully qualified collection name and version requirement aligned across both
files. If `requirements.yml` uses a vendored archive, make sure it provides the
fully qualified collection named by the corresponding dependency entry in
`galaxy.yml`. Do not update only one file.

## Testing

### Linting

```bash
ansible-lint roles/
```

### Syntax Check

```bash
ansible-playbook --syntax-check playbooks/artifact_export.yaml
ansible-playbook --syntax-check playbooks/artifact_import.yaml
```

### Unit Tests

```bash
python -m pytest tests/unit/ -v
```

### Pre-commit

This project uses pre-commit hooks for code quality. Install and run:

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

## Changelog Fragments

This project uses [antsibull-changelog](https://github.com/ansible-community/antsibull-changelog)
to generate release notes. Every pull request that changes user-facing behavior
**must** include a changelog fragment.

### Creating a fragment

Create a YAML file in `changelogs/fragments/` named after your change:

```bash
# Use a descriptive filename — it is discarded after release
touch changelogs/fragments/fix-hub-content-export.yaml
```

Add one or more entries keyed by change type:

```yaml
---
bugfixes:
  - Fix hub content export when tarball path contains spaces.
```

Available section keys:

| Key | When to use |
|-----|-------------|
| `major_changes` | Fundamental changes to the collection |
| `minor_changes` | New features or enhancements |
| `breaking_changes` | Changes that break backward compatibility |
| `deprecated_features` | Features marked for future removal |
| `removed_features` | Previously deprecated features now removed |
| `security_fixes` | Fixes for security vulnerabilities |
| `bugfixes` | Bug fixes |
| `known_issues` | Known issues in the release |

### Validating fragments

```bash
antsibull-changelog lint
```

### How releases work

At release time, a maintainer runs:

```bash
antsibull-changelog release --version <version>
```

This collects all fragments into `CHANGELOG.rst`, updates
`changelogs/changelog.yaml`, and removes the consumed fragment files.

## Excluding Paths from Collection Build

When adding files for testing, documentation, or CI, exclude them in `galaxy.yml` under `build_ignore:` so they do not ship in the collection tarball.

Verify your exclusion:

```bash
ansible-galaxy collection build . --force --output-path=./
tar -tf aap-snapshot-*.tar.gz | head -30
```

## Pull Request Process

1. Fork the repository and create a feature branch.
2. Make your changes, ensuring all lint checks and tests pass.
3. Sign off your commits (`git commit -s`) to certify the [Developer Certificate of Origin](DCO).
4. Open a pull request with a clear description of the change.

## Reporting Issues

To report a bug or request a feature, open an issue in this repository.

If you have a fix, please open a pull request and reference the issue.
