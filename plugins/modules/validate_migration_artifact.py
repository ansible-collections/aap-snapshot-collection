#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, Red Hat, Inc.
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: validate_migration_artifact
author: Red Hat (@RedHatOfficial)
short_description: Validate an AAP migration artifact
description:
  - Validates the structure and integrity of an AAP migration artifact.
  - Checks manifest schema, required files, component data, checksums,
    and optionally validates AAP version compatibility with a target.
  - Returns a human-readable validation report.
version_added: "1.0.0"

options:
  artifact_dir:
    description:
      - Path to the extracted artifact directory.
    required: true
    type: str
  supported_schema_versions:
    description:
      - List of schema versions this collection supports.
    type: list
    elements: str
    default: ["1.0"]
  target_aap_version:
    description:
      - If set, validates that the artifact's AAP version (X.Y) matches this value.
      - Use for import-side validation to prevent cross-version migration.
    type: str
"""

EXAMPLES = r"""
- name: Validate an extracted artifact
  ansible.aap_snapshot.validate_migration_artifact:
    artifact_dir: /tmp/artifact
  register: validation

- name: Print validation report
  ansible.builtin.debug:
    msg: "{{ validation.report }}"

- name: Validate with version check for import
  ansible.aap_snapshot.validate_migration_artifact:
    artifact_dir: /tmp/artifact
    target_aap_version: "2.6"
"""

RETURN = r"""
valid:
  description: Whether the artifact passed all validation checks.
  returned: always
  type: bool
manifest:
  description: Parsed manifest content.
  returned: when manifest.yml is valid
  type: dict
report:
  description: Human-readable validation report.
  returned: always
  type: str
errors:
  description: List of validation error messages. Empty if valid.
  returned: always
  type: list
  elements: str
"""

import hashlib
import os
import traceback

YAML_IMP_ERR = None
try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False
    YAML_IMP_ERR = traceback.format_exc()

from ansible.module_utils.basic import AnsibleModule, missing_required_lib


def _check_file_exists(artifact_dir, filename):
    path = os.path.join(artifact_dir, filename)
    return os.path.isfile(path), path


def _validate_checksums(artifact_dir):
    checksum_file = os.path.join(artifact_dir, "sha256sum.txt")
    failures = []

    with open(checksum_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("  ", 1)
            if len(parts) != 2:
                failures.append(f"Malformed checksum line: {line}")
                continue

            expected_hash, filepath = parts
            full_path = os.path.join(artifact_dir, filepath)

            if not os.path.realpath(full_path).startswith(os.path.realpath(artifact_dir) + os.sep):
                failures.append(f"Path traversal detected in checksum file: {filepath}")
                continue

            if not os.path.isfile(full_path):
                failures.append(f"File listed in checksums not found: {filepath}")
                continue

            sha256 = hashlib.sha256()
            with open(full_path, "rb") as bf:
                for chunk in iter(lambda: bf.read(65536), b""):
                    sha256.update(chunk)

            actual_hash = sha256.hexdigest()
            if actual_hash != expected_hash:
                failures.append(f"Checksum mismatch for {filepath}: " f"expected {expected_hash[:16]}..., got {actual_hash[:16]}...")

    return failures


def _build_report(manifest, component_results, hub_content_ok, checksum_ok, secrets_ok, errors):
    lines = [
        "",
        "=" * 63,
        "  AAP Migration Artifact Validation Report",
        "=" * 63,
        f"  Schema Version:    {manifest.get('schema_version', 'unknown')}",
        f"  AAP Version:       {manifest.get('aap_version', '?')}.{manifest.get('aap_version_patch', '0')}",
        f"  Source Topology:   {manifest.get('source_topology', 'unknown')}",
        f"  Exported By:       {manifest.get('exported_by', 'unknown')}",
        f"  Export Timestamp:  {manifest.get('export_timestamp', 'unknown')}",
        "-" * 63,
        "  Components:",
    ]

    has_dumps = manifest.get("database", {}).get("has_dumps", True)

    for comp in manifest.get("components", []):
        name = comp.get("name", "?")
        version = comp.get("version", "?")
        db_name = comp.get("database_name", "?")
        if not has_dumps:
            pgc_status = "SKIPPED"
        else:
            pgc_status = "OK" if component_results.get(name, False) else "MISSING"
        entry = f"    - {name:<16} v{version:<12} {db_name}  [pgc: {pgc_status}]"

        if comp.get("has_content_data", False):
            content_status = "OK" if hub_content_ok else "MISSING"
            entry += f" [content: {content_status}]"

        lines.append(entry)

    db_info = manifest.get("database", {})
    dumps_label = "included" if has_dumps else "omitted"
    lines.extend(
        [
            "-" * 63,
            f"  Database:          {db_info.get('type', '?')} (PostgreSQL {db_info.get('postgresql_version', '?')}, dumps: {dumps_label})",
            f"  Checksums:         {'PASS' if checksum_ok else 'FAIL'}",
            f"  Secrets:           {'present' if secrets_ok else 'MISSING'}",
            "=" * 63,
            f"  Result: {'VALID' if not errors else 'INVALID'}",
            "=" * 63,
        ]
    )

    if errors:
        lines.append("")
        lines.append("  Errors:")
        for err in errors:
            lines.append(f"    - {err}")

    return "\n".join(lines)


def _validate_components(artifact_dir, manifest, errors):
    """Validate per-component dump files and optional hub content.

    When ``database.has_dumps`` is false, ``.pgc`` files are not required.
    Missing ``has_dumps`` is treated as true for backward compatibility.
    """
    component_results = {}
    hub_content_ok = False
    has_dumps = manifest.get("database", {}).get("has_dumps", True)

    for comp in manifest.get("components", []):
        name = comp.get("name", "")
        pgc_path = os.path.join(artifact_dir, name, f"{name}.pgc")

        if not os.path.realpath(pgc_path).startswith(os.path.realpath(artifact_dir)):
            errors.append(f"Component name '{name}' would escape artifact directory")
            component_results[name] = False
            continue

        pgc_exists = os.path.isfile(pgc_path)
        component_results[name] = pgc_exists if has_dumps else True

        if has_dumps and not pgc_exists:
            errors.append(f"Component '{name}' listed in manifest but {name}.pgc not found")

        if name == "hub" and comp.get("has_content_data", False):
            content_path = os.path.join(artifact_dir, "hub", "hub_content.tar")
            hub_content_ok = os.path.isfile(content_path)
            if not hub_content_ok:
                errors.append("Hub content data flagged in manifest but hub_content.tar not found")

    return component_results, hub_content_ok


def main():
    module = AnsibleModule(
        argument_spec=dict(
            artifact_dir=dict(type="str", required=True),
            supported_schema_versions=dict(type="list", elements="str", default=["1.0"]),
            target_aap_version=dict(type="str", default=None),
        ),
        supports_check_mode=True,
    )

    if not HAS_YAML:
        module.fail_json(msg=missing_required_lib("PyYAML"), exception=YAML_IMP_ERR)

    artifact_dir = module.params["artifact_dir"]
    supported_versions = module.params["supported_schema_versions"]
    target_version = module.params["target_aap_version"]

    errors = []
    manifest = {}
    checksum_ok = False
    secrets_ok = False

    if not os.path.isdir(artifact_dir):
        module.fail_json(msg=f"Artifact directory does not exist: {artifact_dir}")

    exists, _path = _check_file_exists(artifact_dir, "manifest.yml")
    if not exists:
        errors.append("Artifact is missing manifest.yml")
    else:
        manifest_path = os.path.join(artifact_dir, "manifest.yml")
        try:
            with open(manifest_path, "r") as f:
                manifest = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            errors.append(f"manifest.yml contains invalid YAML: {e}")

        if manifest:
            schema = manifest.get("schema_version")
            if schema not in supported_versions:
                errors.append(f"Schema version '{schema}' not supported. " f"Supported: {', '.join(supported_versions)}")

            if target_version:
                artifact_version = manifest.get("aap_version", "")
                if artifact_version != target_version:
                    errors.append(
                        f"Artifact from AAP {artifact_version} but target is "
                        f"AAP {target_version}. Migrate to same version first, "
                        f"then upgrade in place."
                    )

    exists, _path = _check_file_exists(artifact_dir, "secrets.yml")
    if not exists:
        errors.append("Artifact is missing secrets.yml")
    else:
        secrets_ok = True

    exists, _path = _check_file_exists(artifact_dir, "sha256sum.txt")
    if not exists:
        errors.append("Artifact is missing sha256sum.txt")
    else:
        checksum_failures = _validate_checksums(artifact_dir)
        if checksum_failures:
            errors.extend(checksum_failures)
        else:
            checksum_ok = True

    component_results, hub_content_ok = _validate_components(artifact_dir, manifest, errors)

    report = _build_report(manifest, component_results, hub_content_ok, checksum_ok, secrets_ok, errors)

    result = dict(
        changed=False,
        valid=len(errors) == 0,
        manifest=manifest,
        report=report,
        errors=errors,
    )

    if errors:
        module.fail_json(msg="Artifact validation failed", **result)
    else:
        module.exit_json(**result)


if __name__ == "__main__":
    main()
