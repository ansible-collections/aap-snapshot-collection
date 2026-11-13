"""Regression tests for Automation Hub content export reporting."""

from pathlib import Path

import pytest
import yaml


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
    condition = " ".join(metadata_task["when"].split())
    assert condition == (
        "(not (automationhub_export_hub_content | default(true) | bool)) "
        "or (_automationhub_skip_hub_content_export | default(false) | bool)"
    )
    assert ((not public_toggle) or detector_skip) is should_record
    if should_record:
        set_fact = metadata_task["ansible.builtin.set_fact"]
        assert set_fact["artifact_hub_content_export_skipped"] is True
        reason_template = " ".join(set_fact["artifact_hub_content_skip_reason"].split())
        if detector_skip:
            assert "Source Hub uses object-storage backend ' ~ _automationhub_storage_backend" in reason_template
        else:
            assert expected_reason in reason_template
