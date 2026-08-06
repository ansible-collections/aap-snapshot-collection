# Playbooks Checklist

Background: [Playbook Orchestration](../../aap-snapshot-collection-structure/references/playbook-orchestration.md).

## Boilerplate

- [ ] Every new play (non-`import_playbook`) sets `gather_facts: false` and
      `any_errors_fatal: true` — enforced by `custom-play-boilerplate`, but
      double-check anyway since the rule only runs in CI, not necessarily
      in a fast local edit loop.
- [ ] `max_fail_percentage: 0` is set on plays spanning multiple hosts,
      consistent with existing plays.

## Flow Control Consistency

- [ ] No new `tags:` introduced as the mechanism for conditional
      inclusion — this collection uses `when:` on `aap_platform`,
      `_snapshot_operation`, and inventory group membership exclusively.
      A PR introducing tags as a parallel flow-control mechanism creates
      two ways to skip the same logic and should be questioned.
- [ ] `when:` conditions that check "does this component apply" use
      inventory group membership (`groups.get('controller_groups', []) |
      length > 0` or `inventory_hostname in groups.get(...)`) — not a new
      boolean enablement flag, which would be inconsistent with how every
      existing component is gated.

## Start/Stop Ordering — Duplication Trap

- [ ] If the PR changes component start or stop order, both of these were
      updated together:
  - `playbooks/common/start_services.yaml` / `stop_services.yaml`
  - the inline per-host stop/import/start sequence inside
    `roles/artifact/tasks/consume.yml` (containerized import path)

  These are two independent implementations of the same ordering today —
  a PR that fixes ordering in one without the other reintroduces the
  inconsistency it was trying to fix.

## New Entry-Point Plays

- [ ] A new play added to `artifact_export.yaml`/`artifact_import.yaml`/
      `artifact_verify.yaml` is placed at the correct point in the existing
      5-play sequence (see the orchestration reference) — inserting export
      logic after `package.yml` or import logic before `extract.yml`, for
      example, would run out of order.
- [ ] `playbooks/common/validate_artifact.yaml` is only ever
      `import_playbook`'d from the export tail — a PR that starts calling
      it from the import path should clarify intent, since import-time
      artifact validation already happens in `artifact/extract.yml` and
      the preflight checks.
