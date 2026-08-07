"""Unit tests for validate_migration_artifact module."""

import hashlib
import os
import sys
import tempfile
import types

import pytest
import yaml

# Mock ansible.module_utils.basic before importing the module
_mock_ansible = types.ModuleType("ansible")
_mock_module_utils = types.ModuleType("ansible.module_utils")
_mock_basic = types.ModuleType("ansible.module_utils.basic")
_mock_basic.AnsibleModule = type("AnsibleModule", (), {})
_mock_basic.missing_required_lib = lambda lib, reason=None, url=None: f"Failed to import {lib}"
_mock_ansible.module_utils = _mock_module_utils
_mock_module_utils.basic = _mock_basic
sys.modules["ansible"] = _mock_ansible
sys.modules["ansible.module_utils"] = _mock_module_utils
sys.modules["ansible.module_utils.basic"] = _mock_basic

# Now import the module functions
import importlib.util

_module_path = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "plugins",
    "modules",
    "validate_migration_artifact.py",
)
_spec = importlib.util.spec_from_file_location("validate_mod", _module_path)
validate_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validate_mod)


@pytest.fixture
def artifact_dir():
    """Create a temporary artifact directory with valid structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "controller"))
        os.makedirs(os.path.join(tmpdir, "hub"))
        os.makedirs(os.path.join(tmpdir, "gateway"))
        os.makedirs(os.path.join(tmpdir, "eda"))

        for comp in ["controller", "hub", "gateway", "eda"]:
            pgc_path = os.path.join(tmpdir, comp, f"{comp}.pgc")
            with open(pgc_path, "wb") as f:
                f.write(b"fake pgc data for " + comp.encode())

        hub_content_path = os.path.join(tmpdir, "hub", "hub_content.tar")
        with open(hub_content_path, "wb") as f:
            f.write(b"fake hub content tar data")

        manifest = {
            "schema_version": "1.0",
            "aap_version": "2.6",
            "aap_version_patch": "3",
            "source_topology": "rpm",
            "export_timestamp": "2026-06-15T14:22:00Z",
            "exported_by": "ansible.aap_snapshot/1.0.0",
            "components": [
                {
                    "name": "controller",
                    "version": "4.6.15",
                    "database_name": "awx",
                    "has_custom_configs": True,
                },
                {
                    "name": "hub",
                    "version": "4.10.3",
                    "database_name": "automationhub",
                    "has_custom_configs": False,
                    "has_content_data": True,
                },
                {
                    "name": "gateway",
                    "version": "1.2.0",
                    "database_name": "gateway",
                    "has_custom_configs": False,
                },
                {
                    "name": "eda",
                    "version": "1.1.0",
                    "database_name": "automationedacontroller",
                    "has_custom_configs": False,
                },
            ],
            "database": {"type": "managed", "postgresql_version": "15"},
            "checksums": {"algorithm": "sha256", "file": "sha256sum.txt"},
        }

        with open(os.path.join(tmpdir, "manifest.yml"), "w") as f:
            yaml.dump(manifest, f)

        with open(os.path.join(tmpdir, "secrets.yml"), "w") as f:
            yaml.dump({"controller_secret_key": "test"}, f)

        checksums = []
        for comp in ["controller", "hub", "gateway", "eda"]:
            pgc_path = os.path.join(tmpdir, comp, f"{comp}.pgc")
            sha = hashlib.sha256()
            with open(pgc_path, "rb") as f:
                sha.update(f.read())
            checksums.append(f"{sha.hexdigest()}  {comp}/{comp}.pgc")

        sha = hashlib.sha256()
        with open(hub_content_path, "rb") as f:
            sha.update(f.read())
        checksums.append(f"{sha.hexdigest()}  hub/hub_content.tar")

        with open(os.path.join(tmpdir, "sha256sum.txt"), "w") as f:
            f.write("\n".join(checksums) + "\n")

        yield tmpdir


class TestCheckFileExists:
    def test_existing_file(self, artifact_dir):
        exists, path = validate_mod._check_file_exists(artifact_dir, "manifest.yml")
        assert exists is True
        assert path.endswith("manifest.yml")

    def test_missing_file(self, artifact_dir):
        exists, path = validate_mod._check_file_exists(artifact_dir, "nonexistent.yml")
        assert exists is False


class TestValidateChecksums:
    def test_valid_checksums(self, artifact_dir):
        failures = validate_mod._validate_checksums(artifact_dir)
        assert failures == []

    def test_corrupted_file(self, artifact_dir):
        pgc_path = os.path.join(artifact_dir, "controller", "controller.pgc")
        with open(pgc_path, "wb") as f:
            f.write(b"corrupted data")
        failures = validate_mod._validate_checksums(artifact_dir)
        assert len(failures) == 1
        assert "controller/controller.pgc" in failures[0]

    def test_missing_file_in_checksums(self, artifact_dir):
        os.remove(os.path.join(artifact_dir, "eda", "eda.pgc"))
        failures = validate_mod._validate_checksums(artifact_dir)
        assert len(failures) == 1
        assert "eda/eda.pgc" in failures[0]


class TestBuildReport:
    def test_valid_report(self, artifact_dir):
        with open(os.path.join(artifact_dir, "manifest.yml")) as f:
            manifest = yaml.safe_load(f)

        results = {c["name"]: True for c in manifest["components"]}
        report = validate_mod._build_report(manifest, results, True, True, True, [])
        assert "VALID" in report
        assert "2.6" in report
        assert "controller" in report

    def test_invalid_report(self, artifact_dir):
        with open(os.path.join(artifact_dir, "manifest.yml")) as f:
            manifest = yaml.safe_load(f)

        results = {"controller": True, "hub": False, "gateway": True, "eda": True}
        report = validate_mod._build_report(manifest, results, False, True, False, ["hub.pgc not found"])
        assert "INVALID" in report
        assert "hub.pgc not found" in report

    def test_report_omitted_dumps(self, artifact_dir):
        with open(os.path.join(artifact_dir, "manifest.yml")) as f:
            manifest = yaml.safe_load(f)
        manifest["database"]["has_dumps"] = False

        results = {c["name"]: True for c in manifest["components"]}
        report = validate_mod._build_report(manifest, results, True, True, True, [])
        assert "SKIPPED" in report
        assert "dumps: omitted" in report


class TestValidateComponents:
    def test_requires_pgc_by_default(self, artifact_dir):
        with open(os.path.join(artifact_dir, "manifest.yml")) as f:
            manifest = yaml.safe_load(f)
        os.remove(os.path.join(artifact_dir, "controller", "controller.pgc"))

        errors = []
        results, _hub = validate_mod._validate_components(artifact_dir, manifest, errors)
        assert results["controller"] is False
        assert any("controller.pgc not found" in e for e in errors)

    def test_skips_pgc_when_has_dumps_false(self, artifact_dir):
        with open(os.path.join(artifact_dir, "manifest.yml")) as f:
            manifest = yaml.safe_load(f)
        manifest["database"]["has_dumps"] = False
        for comp in ["controller", "hub", "gateway", "eda"]:
            os.remove(os.path.join(artifact_dir, comp, f"{comp}.pgc"))

        errors = []
        results, _hub = validate_mod._validate_components(artifact_dir, manifest, errors)
        assert all(results.values())
        assert not any(".pgc not found" in e for e in errors)

    def test_missing_has_dumps_requires_pgc(self, artifact_dir):
        with open(os.path.join(artifact_dir, "manifest.yml")) as f:
            manifest = yaml.safe_load(f)
        manifest["database"].pop("has_dumps", None)
        os.remove(os.path.join(artifact_dir, "eda", "eda.pgc"))

        errors = []
        validate_mod._validate_components(artifact_dir, manifest, errors)
        assert any("eda.pgc not found" in e for e in errors)
