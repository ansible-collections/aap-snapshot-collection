"""Regression tests for Automation Hub content export reporting."""

from pathlib import Path

import pytest
import yaml
from jinja2 import Environment


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_EXPORT_TASKS_PATH = _REPOSITORY_ROOT / "roles/automationhub/tasks/export.yml"


@pytest.mark.parametrize(
    ("public_toggle", "detector_skip", "should_record", "expected_reason"),
    [
        (True, True, True, "Source Hub uses object-storage backend S3Storage"),
        (True, False, False, None),
        (False, False, True, "Hub content export disabled by configuration"),
    ],
)
def test_skipped_content_metadata_condition(public_toggle, detector_skip, should_record, expected_reason):
    tasks = yaml.safe_load(_EXPORT_TASKS_PATH.read_text())
    metadata_task = next(task for task in tasks if task["name"] == "Record skipped Hub content export for artifact reports")
    context = {
        "automationhub_export_hub_content": public_toggle,
        "_automationhub_skip_hub_content_export": detector_skip,
        "_automationhub_storage_backend": "S3Storage",
    }

    environment = Environment()
    environment.filters["bool"] = bool
    record_condition = environment.compile_expression(metadata_task["when"])

    assert record_condition(**context) is should_record
    if should_record:
        set_fact = metadata_task["ansible.builtin.set_fact"]
        assert set_fact["artifact_hub_content_export_skipped"] is True
        reason_template = environment.from_string(set_fact["artifact_hub_content_skip_reason"])
        assert reason_template.render(**context).strip() == expected_reason
