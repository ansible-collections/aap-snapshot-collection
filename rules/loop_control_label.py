"""Require loop_control with label on all loops."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ansiblelint.rules import AnsibleLintRule

if TYPE_CHECKING:
    from ansiblelint.file_utils import Lintable
    from ansiblelint.utils import Task


class LoopControlLabelRule(AnsibleLintRule):
    id = "custom-loop-control"
    version_changed = "1.0.5"
    shortdesc = "Loops must have loop_control with label"
    description = (
        "Every task using loop must define loop_control with a label "
        "to prevent sensitive data from appearing in output."
    )
    tags = ["custom", "security"]

    def matchtask(self, task: Task, file: Lintable | None = None) -> bool | str:
        if "loop" not in task:
            return False

        loop_control = task.get("loop_control")
        if not loop_control:
            return "loop without loop_control"

        if "label" not in loop_control:
            return "loop_control missing label"

        return False
