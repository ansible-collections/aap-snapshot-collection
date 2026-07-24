"""Require gather_facts and any_errors_fatal on all plays."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ansiblelint.rules import AnsibleLintRule

if TYPE_CHECKING:
    from ansiblelint.file_utils import Lintable


class PlayBoilerplateRule(AnsibleLintRule):
    id = "custom-play-boilerplate"
    version_changed = "1.0.5"
    shortdesc = "Plays must set gather_facts: false and any_errors_fatal: true"
    description = (
        "All plays in this collection must explicitly set "
        "gather_facts: false and any_errors_fatal: true."
    )
    tags = ["custom"]

    def matchplay(self, file: Lintable, data: dict) -> list:
        results = []

        if file.kind != "playbook":
            return results

        if "ansible.builtin.import_playbook" in data or "import_playbook" in data:
            return results

        if data.get("gather_facts") is not False:
            results.append(
                self.create_matcherror(
                    message="Play missing gather_facts: false",
                    filename=file,
                    lineno=data.get("__line__", 1),
                )
            )

        if data.get("any_errors_fatal") is not True:
            results.append(
                self.create_matcherror(
                    message="Play missing any_errors_fatal: true",
                    filename=file,
                    lineno=data.get("__line__", 1),
                )
            )

        return results
