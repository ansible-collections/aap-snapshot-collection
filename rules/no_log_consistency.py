"""Enforce consistent no_log toggle pattern."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ansiblelint.rules import AnsibleLintRule

if TYPE_CHECKING:
    from ansiblelint.file_utils import Lintable
    from ansiblelint.utils import Task

CANONICAL = "{{ not (disable_no_log | default(false) | bool) }}"

_CANONICAL_NORM = CANONICAL.replace(" ", "")

_ROLE_VAR_RE = re.compile(r"\{\{\s*__\w{1,100}_no_log\s*\}\}")

_DESCRIPTION = f"All no_log directives must use: {CANONICAL!r} or a __<role>_no_log variable. Hard-coded values are not allowed."


def _normalize(value: str) -> str:
    return value.strip().replace(" ", "")


class NoLogConsistencyRule(AnsibleLintRule):
    id = "custom-no-log"
    version_changed = "1.0.5"
    shortdesc = "no_log must use the canonical toggle pattern"
    description = _DESCRIPTION
    tags = ["custom", "security"]

    def matchtask(self, task: Task, file: Lintable | None = None) -> bool | str:
        no_log = task.get("no_log")
        if no_log is None:
            return False

        if isinstance(no_log, bool):
            return f"no_log is hard-coded {no_log}; use {CANONICAL!r}"

        if isinstance(no_log, str):
            if _normalize(no_log) == _CANONICAL_NORM:
                return False
            if _ROLE_VAR_RE.match(no_log.strip()):
                return False
            return f"no_log uses non-canonical expression; use {CANONICAL!r}"

        return False
