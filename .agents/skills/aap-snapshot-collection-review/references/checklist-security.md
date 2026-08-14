# Security Checklist

Full conventions live in the
[aap-ansible-conventions](../../aap-ansible-conventions/SKILL.md) skill —
this checklist is the review-time application of those rules.

## `no_log`

- [ ] Every task passing a password, token, API key, or DB credential as a
      module parameter (`login_password:`, `password:`, secret dict
      values) has `no_log:` set to the canonical computed expression (see
      conventions skill) — not `true`/`false` hardcoded.
- [ ] Every task that embeds a secret in a shell/command string (e.g.
      `PGPASSWORD="{{ ... }}"` for `kubernetes.core.k8s_exec`) has the same
      `no_log` treatment as an equivalent module-parameter task — a secret
      in a shell string is not less exposed than one in a parameter.
- [ ] **Check both branches of a platform-conditional pair.** If a task
      exists in an RPM/containerized branch and an OCP branch performing
      the equivalent operation (e.g. dump/restore, secret read), verify
      `no_log` is present on both — it's easy to add it to one branch while
      fixing/reviewing and miss the sibling.
- [ ] `register:` results that indirectly capture a secret (e.g. registering
      the output of a command that prints a `client_secret` or connection
      string) have `no_log` on the *registering* task, not just a
      downstream `set_fact`.
- [ ] `no_log` is never applied to `ansible.builtin.assert` tasks — it
      would censor `fail_msg`, making preflight failures undebuggable.

## Loop Control

- [ ] Any `loop:` over a list/dict that might contain secret values
      (component secrets, credential dicts) has `loop_control.label` set to
      a non-secret field (e.g. `item.key`, `item.name`) — without it, each
      loop item is printed even when the task itself has `no_log`.

## Secrets at Rest

- [ ] New secrets added to the artifact go through the existing
      `secrets.yml` assembly (via `delegate_facts` aggregation +
      `package.yml`), not a new standalone file that would need its own
      permission/cleanup handling.
- [ ] File permission modes are preserved: `secrets.yml` at `0600`,
      `manifest.yml`/`sha256sum.txt` at `0640`, export directories at
      `0750`. A PR that changes `package.yml`'s archive/copy tasks should
      not silently drop a `mode:` argument.
- [ ] No new use of Ansible Vault is introduced inconsistently with the
      rest of the collection (which relies on `no_log` + file permissions,
      not encryption at rest) without a discussion of why this case is
      different.

## `become`

- [ ] `become: true` is only added where a specific file, command, or
      service-user ownership requires it (see the conventions skill) — not
      as a blanket fix for a permission error that might have a more
      targeted cause.
- [ ] Local-only tasks (artifact packaging, verification) don't gain
      unnecessary `become` — `roles/artifact/tasks/package.yml` and
      `playbooks/artifact_verify.yaml` intentionally disable it.

## Cross-Component Isolation

- [ ] A change to one component's role/task doesn't read, write, or delete
      another component's secrets, K8s resources, or DB. Cross-component
      data flows through `_operations_component_config`,
      `__ocp_utils_artifact_secret_mapping`, or shared facts — never direct
      resource access into another component's namespace.
