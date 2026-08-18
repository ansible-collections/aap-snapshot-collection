# Artifact Role (`roles/artifact`)

Owns the tarball lifecycle end to end — the one role invoked directly from
every entry-point playbook.

```
roles/artifact/
├── defaults/main.yml   # __artifact_build_dir, __artifact_dest_dir, __artifact_filename
│                         # (internal, derived from public artifact_build_dir/dest_dir/prefix)
│                         # artifact_checksum_algo: sha256
│                         # artifact_export_hub_content: true
│                         # artifact_postgresql_db_type: managed
├── handlers/            # "Remove the artifact build directory" (notified by package.yml)
├── meta/
├── templates/manifest.yaml.j2
└── tasks/
    ├── init.yml
    ├── build.yml
    ├── package.yml
    ├── extract.yml
    ├── consume.yml       # ~440 lines — the full import orchestrator
    ├── verify.yml
    ├── verify_local.yml
    └── verify_content.yml
```

Task file names are lifecycle phases, not a strict export/import/verify
split — `build.yml` and `package.yml` are both part of export; `consume.yml`
does the entire import (both containerized and OCP); `verify*.yml` are
checksum-only checks with no import side effects.

## Export Path: `init.yml` → `build.yml` → `package.yml`

- **`init.yml`** — creates the build directory structure under
  `__artifact_build_dir`.
- **`build.yml`** — loops over the 4 components (gated by inventory group
  membership), calling each one's `export.yml`.
- **`package.yml`** — templates `manifest.yml` (from `manifest.yaml.j2`,
  assembled from `hostvars` across all hosts via `groups['all'] |
  map('extract', hostvars)`), writes `secrets.yml` (`mode: '0600'`) and
  `sha256sum.txt` (`mode: '0640'`), archives with
  `community.general.archive`, computes the top-level checksum. Runs with
  `ansible_become: false` — packaging is local-only and needs no privilege
  escalation.

## Artifact Tarball Layout

```
aap-snapshot-{version}-{timestamp}.tar
├── manifest.yml
├── secrets.yml (0600)
├── sha256sum.txt
├── controller/controller.pgc [+ custom_configs/{hostname}/ — RPM only]
├── eda/eda.pgc
├── gateway/gateway.pgc
└── hub/hub.pgc [+ hub_content.tar — when artifact_export_hub_content: true]
```

## Import Path: `extract.yml` → `consume.yml`

- **`extract.yml`** — unarchives, validates, loads `artifact_secrets` and
  `artifact_manifest`; sets `_artifact_path`, `artifact_filename`,
  `artifact_dir`.
- **`consume.yml`** — the real orchestrator. The entire OCP import is a
  single `block/rescue/always`:
  - `block:` — validate version match, choose fresh-namespace vs. existing
    CR, create CR / idle AAP, scale down operators, create temp
    PVC/pod, transfer the artifact in, import each component's DB
    (delegating through `operations`/`postgresql`), restore secrets, scale
    back up, resume AAP, wait for pods, discover components, reconcile.
  - `rescue:` — scales operators back up and un-idles the AAP CR so a
    failed import doesn't leave the cluster stuck mid-migration.
  - `always:` — calls `ocp_utils/cleanup_temp_resources.yml`, gated on
    `_artifact_import_succeeded` or `not keep_temp_on_failure` (so a failed
    run can optionally leave the temp resources behind for debugging).

  The containerized import path (also in `consume.yml`, `when: aap_platform
  == 'containerized'`) re-implements the stop/import/start/reconcile
  sequence inline, per-host, rather than calling
  `playbooks/common/stop_services.yaml`/`start_services.yaml` — see
  [Playbook Orchestration](playbook-orchestration.md) for why that matters
  when changing service ordering.

## Verify-Only Path

`verify.yml`, `verify_local.yml`, `verify_content.yml` do checksum/manifest
validation without importing anything — used by `playbooks/artifact_verify.yaml`
and standalone sanity checks. If you add a new artifact field in
`package.yml`, check whether `validate_migration_artifact` (the plugin
module backing these) needs to know about it too.
