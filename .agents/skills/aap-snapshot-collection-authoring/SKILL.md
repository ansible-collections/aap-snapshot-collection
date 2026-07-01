# AAP Snapshot Collection Authoring

Conventions for contributing to the `ansible.aap_snapshot` collection.

## Changelog Fragments

This project uses [antsibull-changelog](https://github.com/ansible-community/antsibull-changelog) to generate release notes.

### When to include a fragment

Every commit that changes user-facing behavior **must** include a changelog fragment in `changelogs/fragments/`. This includes bug fixes, new features, breaking changes, deprecations, and security fixes.

Commits that do **not** need a fragment:
- Documentation-only changes (README, CONTRIBUTING, comments)
- CI/CD pipeline changes
- Test-only changes with no behavior change
- Refactors with no user-visible effect
- Linter config or dev tooling updates

### Creating a fragment

1. Create a YAML file in `changelogs/fragments/` named after your change:

   ```
   changelogs/fragments/<short-description>.yaml
   ```

2. Add one or more entries keyed by change type:

   ```yaml
   ---
   bugfixes:
     - Fix hub content export when tarball path contains spaces.
   ```

### Section keys

| Key                   | When to use                                  |
|-----------------------|----------------------------------------------|
| `major_changes`       | Fundamental changes to the collection        |
| `minor_changes`       | New features or enhancements                 |
| `breaking_changes`    | Changes that break backward compatibility    |
| `deprecated_features` | Features marked for future removal           |
| `removed_features`    | Previously deprecated features now removed   |
| `security_fixes`      | Fixes for security vulnerabilities           |
| `bugfixes`            | Bug fixes                                    |
| `known_issues`        | Known issues in the release                  |

### Fragment description style

- Write in imperative mood ("Fix ...", "Add ...", "Remove ...").
- One line per entry. Keep it concise but specific enough to be useful in release notes.
- Reference the affected role, plugin, or playbook when the scope isn't obvious.

### Validating

```bash
antsibull-changelog lint
```
