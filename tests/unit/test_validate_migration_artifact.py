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


class TestValidateSourceAAPCR:
    def _make_operator_source(self, artifact_dir):
        cr_definition = {
            "apiVersion": "aap.ansible.com/v1alpha1",
            "kind": "AnsibleAutomationPlatform",
            "metadata": {"name": "aap", "namespace": "aap"},
            "spec": {"controller": {}, "hub": {}},
        }
        cr_path = os.path.join(artifact_dir, "aap_cr.yml")
        with open(cr_path, "w") as f:
            yaml.safe_dump(cr_definition, f)

        with open(cr_path, "rb") as f:
            cr_checksum = hashlib.sha256(f.read()).hexdigest()
        with open(os.path.join(artifact_dir, "sha256sum.txt"), "a") as f:
            f.write(f"{cr_checksum}  aap_cr.yml\n")

        return cr_path

    def test_valid_operator_cr_reference_and_checksum(self, artifact_dir):
        self._make_operator_source(artifact_dir)
        assert validate_mod._validate_source_aap_cr(artifact_dir, "operator") == []

    def test_missing_operator_cr_reference(self, artifact_dir):
        failures = validate_mod._validate_source_aap_cr(artifact_dir, "operator")
        assert failures == ["OCP-source artifact is missing aap_cr.yml"]

    def test_operator_cr_must_be_listed_in_checksums(self, artifact_dir):
        cr_path = os.path.join(artifact_dir, "aap_cr.yml")
        with open(cr_path, "w") as f:
            yaml.safe_dump(
                {
                    "apiVersion": "aap.ansible.com/v1alpha1",
                    "kind": "AnsibleAutomationPlatform",
                    "metadata": {"name": "aap"},
                    "spec": {},
                },
                f,
            )
        failures = validate_mod._validate_source_aap_cr(artifact_dir, "operator")
        assert "aap_cr.yml is not listed in sha256sum.txt" in failures

    def test_non_operator_artifact_does_not_require_cr_reference(self, artifact_dir):
        assert validate_mod._validate_source_aap_cr(artifact_dir, "rpm") == []


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


class ModuleResult(Exception):
    def __init__(self, result):
        self.result = result


def run_validation(monkeypatch, path):
    class Module:
        params = {'artifact_dir': path, 'supported_schema_versions': ['1.0', '1.1', '1.2'], 'target_aap_version': None}

        def exit_json(self, **result):
            raise ModuleResult(result)

        def fail_json(self, **result):
            raise ModuleResult(result)

    monkeypatch.setattr(validate_mod, 'AnsibleModule', lambda **kwargs: Module())
    with pytest.raises(ModuleResult) as result:
        validate_mod.main()
    return result.value.result


def make_manual_artifact(path):
    with open(os.path.join(path, 'manifest.yml')) as stream:
        manifest = yaml.safe_load(stream)
    manifest['schema_version'] = '1.2'
    for comp in manifest['components']:
        comp['has_database_dump'] = False
        comp['has_content_data'] = False
        os.remove(os.path.join(path, comp['name'], comp['name'] + '.pgc'))
    os.remove(os.path.join(path, 'hub', 'hub_content.tar'))
    with open(os.path.join(path, 'manifest.yml'), 'w') as stream:
        yaml.safe_dump(manifest, stream)
    lines = []
    for name in ['manifest.yml', 'secrets.yml']:
        with open(os.path.join(path, name), 'rb') as stream:
            lines.append(hashlib.sha256(stream.read()).hexdigest() + '  ' + name)
    with open(os.path.join(path, 'sha256sum.txt'), 'w') as stream:
        stream.write('\n'.join(lines) + '\n')
    return manifest


def test_omitted_dumps_with_no_media_are_valid(monkeypatch, artifact_dir):
    make_manual_artifact(artifact_dir)
    result = run_validation(monkeypatch, artifact_dir)
    assert result['valid'], result['errors']
    assert 'DBA' in result['report']


def test_omission_requires_new_schema(monkeypatch, artifact_dir):
    manifest = make_manual_artifact(artifact_dir)
    manifest['schema_version'] = '1.1'
    with open(os.path.join(artifact_dir, 'manifest.yml'), 'w') as stream:
        yaml.safe_dump(manifest, stream)
    assert not run_validation(monkeypatch, artifact_dir)['valid']


def test_missing_legacy_dump_remains_invalid(monkeypatch, artifact_dir):
    os.remove(os.path.join(artifact_dir, 'controller', 'controller.pgc'))
    assert not run_validation(monkeypatch, artifact_dir)['valid']


def test_omitted_artifact_requires_every_payload_checksum(monkeypatch, artifact_dir):
    make_manual_artifact(artifact_dir)
    with open(os.path.join(artifact_dir, 'sha256sum.txt'), 'w') as stream:
        stream.write('')
    result = run_validation(monkeypatch, artifact_dir)
    assert not result['valid']
    assert any('checksum' in error.lower() for error in result['errors'])


def test_legacy_dump_must_be_checksummed(monkeypatch, artifact_dir):
    with open(os.path.join(artifact_dir, 'sha256sum.txt'), 'w') as stream:
        stream.write('')
    assert not run_validation(monkeypatch, artifact_dir)['valid']
