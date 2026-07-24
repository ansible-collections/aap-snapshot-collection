"""Unit tests for aap_component_info module."""

import os
import sys
import tempfile
import types

_mock_ansible = types.ModuleType("ansible")
_mock_module_utils = types.ModuleType("ansible.module_utils")
_mock_basic = types.ModuleType("ansible.module_utils.basic")
_mock_basic.AnsibleModule = type("AnsibleModule", (), {})
_mock_ansible.module_utils = _mock_module_utils
_mock_module_utils.basic = _mock_basic
sys.modules.setdefault("ansible", _mock_ansible)
sys.modules.setdefault("ansible.module_utils", _mock_module_utils)
sys.modules.setdefault("ansible.module_utils.basic", _mock_basic)

import importlib.util

_module_path = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "plugins",
    "modules",
    "aap_component_info.py",
)
_spec = importlib.util.spec_from_file_location("aap_component_info", _module_path)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


class TestComponentDefaults:
    def test_all_components_have_defaults(self):
        for component in ["controller", "hub", "gateway", "eda"]:
            assert component in mod.COMPONENT_DEFAULTS

    def test_all_components_have_manage_cmd(self):
        for component, defaults in mod.COMPONENT_DEFAULTS.items():
            assert "manage_cmd" in defaults, f"{component} missing manage_cmd"

    def test_all_components_have_package_name(self):
        for component, defaults in mod.COMPONENT_DEFAULTS.items():
            assert "package_name" in defaults, f"{component} missing package_name"

    def test_controller_defaults(self):
        d = mod.COMPONENT_DEFAULTS["controller"]
        assert d["manage_cmd"] == "awx-manage"
        assert d["package_name"] == "awx"
        assert d["secret_key_file"] == "/etc/tower/SECRET_KEY"

    def test_hub_defaults(self):
        d = mod.COMPONENT_DEFAULTS["hub"]
        assert d["manage_cmd"] == "pulpcore-manager"
        assert d["settings_module"] == "pulpcore.app.settings"

    def test_gateway_defaults(self):
        d = mod.COMPONENT_DEFAULTS["gateway"]
        assert d["manage_cmd"] == "aap-gateway-manage"
        assert "version_file" in d

    def test_eda_defaults(self):
        d = mod.COMPONENT_DEFAULTS["eda"]
        assert d["manage_cmd"] == "aap-eda-manage"


class TestReadFileSecret:
    def test_read_existing_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
            f.write("  my-secret-value  \n")
            f.flush()
            value, err = mod._read_file_secret(f.name)
        os.unlink(f.name)
        assert value == "my-secret-value"
        assert err is None

    def test_read_missing_file(self):
        value, err = mod._read_file_secret("/nonexistent/path/secret.key")
        assert value is None
        assert "not found" in err

    def test_read_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
            f.write("")
            f.flush()
            value, err = mod._read_file_secret(f.name)
        os.unlink(f.name)
        assert value == ""
        assert err is None


class TestGetHubSecretKey:
    def test_parse_simple_assignment(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write("SECRET_KEY = 'hub-secret-123'\n")
            f.flush()
            value, err = mod._get_hub_secret_key(f.name)
        os.unlink(f.name)
        assert value == "hub-secret-123"
        assert err is None

    def test_missing_secret_key(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write("OTHER_VAR = 'something'\n")
            f.flush()
            value, err = mod._get_hub_secret_key(f.name)
        os.unlink(f.name)
        assert value is None
        assert "not found" in err

    def test_nonexistent_file(self):
        value, err = mod._get_hub_secret_key("/nonexistent/settings.py")
        assert value is None
        assert "Failed to parse" in err


class TestGetVersion:
    def test_version_not_found(self):
        version, err = mod._get_version("/nonexistent/manage", "fakepkg")
        assert version is None
        assert "failed" in err.lower()


class TestGetDbCredentials:
    def test_missing_manage_cmd(self):
        creds, err = mod._get_db_credentials(
            "/nonexistent/manage", "controller", {}
        )
        assert creds is None
        assert "failed" in err.lower()


class TestGetSecrets:
    def test_missing_secret_key_file(self):
        defaults = {
            "secret_key_file": "/nonexistent/SECRET_KEY",
        }
        secrets, errors = mod._get_secrets("controller", defaults, "awx-manage")
        assert "controller_secret_key" not in secrets
        assert any("not found" in e for e in errors)

    def test_no_secret_key_file(self):
        defaults = {"secret_key_file": None}
        secrets, errors = mod._get_secrets("eda", defaults, "aap-eda-manage")
        assert errors == []

    def test_hub_with_missing_files(self):
        defaults = {
            "secret_key_file": None,
            "settings_file": "/nonexistent/settings.py",
            "db_fields_key_file": "/nonexistent/key",
        }
        secrets, errors = mod._get_secrets("hub", defaults, "pulpcore-manager")
        assert len(errors) == 2

    def test_hub_with_valid_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = os.path.join(tmpdir, "settings.py")
            with open(settings_path, "w") as f:
                f.write("SECRET_KEY = 'hub-key'\n")

            key_path = os.path.join(tmpdir, "db_fields.key")
            with open(key_path, "w") as f:
                f.write("db-encryption-key")

            defaults = {
                "secret_key_file": None,
                "settings_file": settings_path,
                "db_fields_key_file": key_path,
            }
            secrets, errors = mod._get_secrets("hub", defaults, "pulpcore-manager")
            assert secrets["hub_secret"] == "hub-key"
            assert secrets["hub_db_fields_encryption_key"] == "db-encryption-key"
            assert errors == []


class TestDbExtractTemplate:
    def test_template_produces_valid_python(self):
        cmd = mod._DB_EXTRACT_TEMPLATE.format(
            import_line="from django.conf import settings",
            settings_var="settings",
        )
        compile(cmd, "<test>", "exec")

    def test_template_hub_variant(self):
        cmd = mod._DB_EXTRACT_TEMPLATE.format(
            import_line="from dynaconf import settings as dynaconf_settings",
            settings_var="dynaconf_settings",
        )
        compile(cmd, "<test>", "exec")
