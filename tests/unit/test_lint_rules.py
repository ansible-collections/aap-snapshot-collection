"""Unit tests for custom ansible-lint rules.

These tests validate the rule logic directly without importing
ansiblelint, so they can run alongside tests that mock the ansible
package.
"""

import importlib.util
import os
import sys
import types

# Provide a minimal AnsibleLintRule stub so the rule modules can
# be imported without pulling in the full ansiblelint package (which
# requires a real ansible installation that conflicts with the mock
# ansible modules used by sibling test files).
_stub_rules = types.ModuleType("ansiblelint.rules")


class _StubRule:
    id = ""
    shortdesc = ""
    description = ""
    tags = []
    version_changed = ""

    def create_matcherror(self, **kwargs):
        return kwargs


_stub_rules.AnsibleLintRule = _StubRule

_stub_ansiblelint = types.ModuleType("ansiblelint")
_stub_ansiblelint.rules = _stub_rules

sys.modules.setdefault("ansiblelint", _stub_ansiblelint)
sys.modules.setdefault("ansiblelint.rules", _stub_rules)

_stub_file_utils = types.ModuleType("ansiblelint.file_utils")
sys.modules.setdefault("ansiblelint.file_utils", _stub_file_utils)

_rules_dir = os.path.join(os.path.dirname(__file__), "..", "..", "rules")

_spec_boilerplate = importlib.util.spec_from_file_location(
    "play_boilerplate",
    os.path.join(_rules_dir, "play_boilerplate.py"),
)
boilerplate_mod = importlib.util.module_from_spec(_spec_boilerplate)
_spec_boilerplate.loader.exec_module(boilerplate_mod)
PlayBoilerplateRule = boilerplate_mod.PlayBoilerplateRule

_spec_nolog = importlib.util.spec_from_file_location(
    "no_log_consistency",
    os.path.join(_rules_dir, "no_log_consistency.py"),
)
no_log_mod = importlib.util.module_from_spec(_spec_nolog)
_spec_nolog.loader.exec_module(no_log_mod)
NoLogConsistencyRule = no_log_mod.NoLogConsistencyRule
CANONICAL = no_log_mod.CANONICAL

_spec_loop = importlib.util.spec_from_file_location(
    "loop_control_label",
    os.path.join(_rules_dir, "loop_control_label.py"),
)
loop_mod = importlib.util.module_from_spec(_spec_loop)
_spec_loop.loader.exec_module(loop_mod)
LoopControlLabelRule = loop_mod.LoopControlLabelRule


class TestNoLogConsistencyRule:
    """Tests for custom-no-log rule."""

    def setup_method(self):
        self.rule = NoLogConsistencyRule()

    def _make_task(self, no_log=None):
        task = {"name": "Test task", "ansible.builtin.debug": {"msg": "hi"}}
        if no_log is not None:
            task["no_log"] = no_log
        return task

    def test_no_no_log_passes(self):
        assert self.rule.matchtask(self._make_task()) is False

    def test_canonical_pattern_passes(self):
        assert self.rule.matchtask(self._make_task(CANONICAL)) is False

    def test_canonical_pattern_extra_spaces_passes(self):
        loose = "{{  not ( disable_no_log | default(false) | bool )  }}"
        assert self.rule.matchtask(self._make_task(loose)) is False

    def test_hardcoded_true_fails(self):
        result = self.rule.matchtask(self._make_task(True))
        assert result
        assert "hard-coded" in result

    def test_hardcoded_false_fails(self):
        result = self.rule.matchtask(self._make_task(False))
        assert result
        assert "hard-coded" in result

    def test_ternary_pattern_fails(self):
        ternary = "{{ (disable_no_log | default(false) | bool) | ternary(false, true) }}"
        result = self.rule.matchtask(self._make_task(ternary))
        assert result
        assert "non-canonical" in result

    def test_role_var_passes(self):
        assert self.rule.matchtask(self._make_task("{{ __operations_no_log }}")) is False

    def test_role_var_with_spaces_passes(self):
        assert self.rule.matchtask(self._make_task("{{  __postgresql_no_log  }}")) is False

    def test_non_role_var_fails(self):
        result = self.rule.matchtask(self._make_task("{{ postgresql_no_log }}"))
        assert result
        assert "non-canonical" in result

    def test_arbitrary_var_fails(self):
        result = self.rule.matchtask(self._make_task("{{ some_other_var }}"))
        assert result
        assert "non-canonical" in result


class TestLoopControlLabelRule:
    """Tests for custom-loop-control rule."""

    def setup_method(self):
        self.rule = LoopControlLabelRule()

    def _make_task(self, has_loop=False, loop_control=None):
        task = {
            "name": "Test task",
            "ansible.builtin.debug": {"msg": "{{ item }}"},
        }
        if has_loop:
            task["loop"] = ["a", "b"]
        if loop_control is not None:
            task["loop_control"] = loop_control
        return task

    def test_no_loop_passes(self):
        assert self.rule.matchtask(self._make_task()) is False

    def test_loop_with_label_passes(self):
        task = self._make_task(has_loop=True, loop_control={"label": "{{ item }}"})
        assert self.rule.matchtask(task) is False

    def test_loop_without_control_fails(self):
        result = self.rule.matchtask(self._make_task(has_loop=True))
        assert result
        assert "without loop_control" in result

    def test_loop_control_without_label_fails(self):
        task = self._make_task(has_loop=True, loop_control={"pause": 1})
        result = self.rule.matchtask(task)
        assert result
        assert "missing label" in result


class _FakeLintable:
    def __init__(self, kind="playbook"):
        self.kind = kind


class TestPlayBoilerplateRule:
    """Tests for custom-play-boilerplate rule."""

    def setup_method(self):
        self.rule = PlayBoilerplateRule()

    def test_non_playbook_file_passes(self):
        result = self.rule.matchplay(_FakeLintable(kind="tasks"), {})
        assert result == []

    def test_import_playbook_passes(self):
        data = {"import_playbook": "other.yml"}
        assert self.rule.matchplay(_FakeLintable(), data) == []

    def test_fqcn_import_playbook_passes(self):
        data = {"ansible.builtin.import_playbook": "other.yml"}
        assert self.rule.matchplay(_FakeLintable(), data) == []

    def test_missing_both_fails(self):
        result = self.rule.matchplay(_FakeLintable(), {"__line__": 1})
        assert len(result) == 2

    def test_gather_facts_true_fails(self):
        data = {"gather_facts": True, "any_errors_fatal": True, "__line__": 1}
        result = self.rule.matchplay(_FakeLintable(), data)
        assert len(result) == 1
        assert "gather_facts" in result[0]["message"]

    def test_any_errors_fatal_false_fails(self):
        data = {"gather_facts": False, "any_errors_fatal": False, "__line__": 1}
        result = self.rule.matchplay(_FakeLintable(), data)
        assert len(result) == 1
        assert "any_errors_fatal" in result[0]["message"]

    def test_both_correct_passes(self):
        data = {"gather_facts": False, "any_errors_fatal": True}
        assert self.rule.matchplay(_FakeLintable(), data) == []
