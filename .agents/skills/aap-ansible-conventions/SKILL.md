---
name: aap-ansible-conventions
description: >-
  Ansible coding style conventions, secret-handling rules, and the custom
  ansible-lint rules enforced in the aap-snapshot-collection. Use this skill
  whenever writing or reviewing Ansible tasks, defaults, or templates in this
  repository — especially anything touching `no_log`, `become`, boolean
  `when:` conditions, FQCN module names, YAML document markers, or database
  credentials. Also consult this when fixing a lint error, adding a new task
  file, touching any `.yml` file in `roles/` or `playbooks/`, or reviewing a
  diff that registers command/module output that might contain a secret.
  Even quick one-line fixes should follow these conventions — several were
  added specifically because a small change missed one of these rules.
---

# Ansible Coding Conventions for aap-snapshot-collection

These conventions exist because this collection exports/imports live AAP
credentials and database contents across platforms — a missed `no_log` or
an unguarded secret doesn't just look sloppy, it leaks a password into CI
logs or a support bundle. Three of the rules below are enforced by
project-specific ansible-lint rules in `rules/`, not just convention.

## `no_log` — Computed, Never Hardcoded

Every `no_log:` value in this repo must be exactly
`{{ not (disable_no_log | default(false) | bool) }}`, or a role-level alias
of that same expression defined once in `defaults/main.yml` (e.g.
`__postgresql_no_log`, `__operations_no_log`, `__artifact_no_log`,
`__preflight_no_log`, `__ocp_utils_no_log`). This is enforced by the custom
ansible-lint rule `custom-no-log` (`rules/no_log_consistency.py`) —
hardcoded `no_log: true`/`no_log: false` or any other expression will fail
lint.

```yaml
# Correct — role has its own alias
no_log: "{{ __postgresql_no_log }}"

# Correct — direct form (fine in a role with no alias defined)
no_log: "{{ not (disable_no_log | default(false) | bool) }}"

# Wrong — fails custom-no-log
no_log: true
```

The single global override, `disable_no_log` (default `false`), exists so
maintainers can temporarily unmask secrets while debugging locally — never
set it in a committed default.

**Apply `no_log` to every task that handles**: DB passwords/credentials
(`postgresql_auth_settings`, `PGPASSWORD`), component secret keys
(`SECRET_KEY`, resource-server keys), admin password resets, K8s Secret
manifests, and the `secrets.yml` artifact write.

**Check both sides of a dump/restore pair.** A real gap existed where the
OCP-path `pg_dump` exec task had `no_log` but the equivalent RPM/
containerized `community.postgresql.postgresql_db` dump task — which also
receives `login_password` — did not. When a task passes `login_password`
(or any password/token parameter) directly to a module, it needs `no_log`
regardless of which platform branch it's in, even if a sibling branch
already has it.

**Loop labels are part of the same protection.** The custom rule
`custom-loop-control` (`rules/loop_control_label.py`) requires every task
with `loop:` to define `loop_control` with a `label:` — without it, Ansible
prints each loop item (which may be a secret-bearing dict) to stdout even
when the task itself has `no_log`.

```yaml
- name: Restore per-component secrets
  ansible.builtin.set_fact:
    "{{ item.key }}": "{{ item.value }}"
  loop: "{{ artifact_secrets | dict2items }}"
  loop_control:
    label: "{{ item.key }}"
  no_log: "{{ __artifact_no_log }}"
```

## Play Boilerplate

Every play (that isn't an `import_playbook`) must set
`gather_facts: false` and `any_errors_fatal: true` — enforced by
`custom-play-boilerplate` (`rules/play_boilerplate.py`). This collection
doesn't rely on gathered facts for its core logic (everything comes from
explicit lookups/module calls), and a partial multi-host run
(export/import spanning 4+ components) should fail loudly rather than
silently skip a component.

## Boolean Filters — `| bool`

Every `when:` condition on a boolean-flavored variable must use `| bool`
(commonly `| default(false) | bool` when the variable might be undefined).
Ansible variables can arrive as strings (`"true"`, `"1"`) depending on how
they were set (inventory, extra-vars, CR spec), and without `| bool` the
string `"false"` evaluates as truthy because it's a non-empty string.

```yaml
# Correct
when: automationhub_export_hub_content | default(true) | bool

# Correct — list form for multiple conditions
when:
  - _operations_current_component.has_worker_discovery | bool
  - not (_preflight_artifact_has_hub | bool)
```

Multiple conditions use YAML list form under `when:`, not inline `and`.
Non-boolean comparisons (`aap_platform == 'rpm'`, `groups.get(...) | length
> 0`, `is defined`) correctly don't need `| bool` — don't add it reflexively
to every `when:`, only to genuine boolean flags.

## `become` — Only When Genuinely Needed

`become` is used specifically for: reading files/secrets owned by a
component's service user (`django_user`, pulp), running `manage.py`/Django
shell commands, and syncing root- or service-user-owned config directories.
It is explicitly turned off (`ansible_become: false`) for local artifact
packaging in `roles/artifact/tasks/package.yml`, and the standalone verify
playbook sets `become: false` at the play level, since verification never
needs privilege escalation. Don't add `become: true` to a task unless you
can name the specific file/command ownership that requires it.

## Fully Qualified Collection Names (FQCN)

Use FQCN for every module call — `ansible.builtin.copy`, not `copy`;
`community.postgresql.postgresql_db`, not `postgresql_db`;
`kubernetes.core.k8s_exec`, `containers.podman.podman_container_exec`,
`community.general.archive`, `ansible.posix.synchronize`. This is enforced
by ansible-lint's `production` profile (`fqcn[action]`/`fqcn[action-core]`)
and is followed consistently in this repo — there are no bare short-name
module calls to pattern-match against, so a diff introducing one is a lint
failure, not a style nitpick.

## YAML Style

- **Document markers**: every task/defaults/template file starts with `---`
  and ends with `...` on its own line. `.yamllint.yml` sets
  `document-end: enable`, so a missing trailing `...` fails lint even
  though `document-start` itself is not enforced by yamllint — the leading
  `---` is a repo convention layered on top.
- **Truthy values**: `.yamllint.yml` restricts `truthy` to lowercase
  `true`/`false` only — don't use `True`/`False`/`yes`/`no` in YAML.
- **Octal `mode:` values**: must be quoted strings (`mode: "0640"`), never
  bare octal literals — `.yamllint.yml` forbids both implicit and explicit
  octal.
- **Quoting**: Jinja expressions and dynamic strings generally use double
  quotes (`"{{ ... }}"`); static literal defaults generally use single
  quotes (`artifact_prefix: 'aap-snapshot'`). This is not perfectly
  enforced — don't block a review on quote style alone, but match the
  surrounding file's convention when adding new lines.

## Secrets: No Vault, Filesystem Permissions Instead

This collection does not use Ansible Vault. Secrets extracted during export
are written to the artifact's `secrets.yml` with `mode: '0600'`; the
manifest and checksum files use `mode: '0640'`; the export directory itself
uses `mode: "0750"`. `no_log` protects secrets in-flight (Ansible output);
file permissions protect them at rest inside the artifact. If you add a new
credential to the export flow, make sure it goes through the existing
`secrets.yml` assembly path (via `delegate_facts` aggregation, see the
structure skill) rather than a new standalone file — a second secrets file
would need its own permission and cleanup handling to match.

## Database Credentials Specifically

- Always pass `login_db` explicitly to `community.postgresql.*` module
  calls — don't assume the DB name equals the DB username. They can differ
  (PR #96 fixed a real bug where a version-check query worked because it
  happened to match, but the pattern wasn't safe in general).
- `PGPASSWORD` embedded in a shell command string (used for the OCP
  `k8s_exec` pg_dump/pg_restore paths) requires `no_log` on that task just
  as much as a `login_password:` module parameter does — a secret in a
  `command:`/`shell:` argument is exactly as exposed as one in a module
  parameter.

## Linting and Formatting Config Reference

- `.ansible-lint`: `profile: production`, custom rules loaded from `rules/`
  (`custom-no-log`, `custom-loop-control`, `custom-play-boilerplate` in
  `enable_list`; `no-log-password` in `warn_list`, i.e. warn-only).
- `.yamllint.yml`: extends `default`; `line-length: disable`;
  `document-end: enable`; `truthy: allowed-values: ["true", "false"]`;
  `octal-values`: forbidden (implicit and explicit).
- `.flake8`: `max-line-length=180`; `E402` ignored for `plugins/modules/*`
  and `tests/unit/*` (needed for the DOCUMENTATION/EXAMPLES/RETURN blocks
  that precede imports in plugin files).
- `.black.cfg`: `line-length = 180`, `skip-string-normalization = true`
  (black will not force double quotes in Python).
- `.pre-commit-config.yaml`: runs `end-of-file-fixer`, `trailing-whitespace`,
  `leaktk` (secret-leak scanning), `black --check --diff`, `flake8`,
  `ansible-lint`, and `pytest tests/unit/ -q` at `pre-push`.
