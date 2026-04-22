from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.task import TaskSpec, load_task_spec


def test_task_spec_accepts_valid_payload(tmp_path):
    payload = {
        "task_id": "demo-ci-001",
        "task_type": "ci_fix",
        "title": "Fix failing unit test",
        "repo_path": str(tmp_path),
        "entry_artifacts": {"log": "pytest failed"},
        "verification_commands": ["pytest -q"],
        "allowed_tools": ["read_file", "search_code"],
        "metadata": {},
    }

    task = TaskSpec.model_validate(payload)

    assert task.task_id == "demo-ci-001"
    assert task.task_type == "ci_fix"
    assert task.repo_path == str(tmp_path)
    assert task.allowed_tools == ["read_file", "search_code"]
    assert task.metadata == {}


def test_task_spec_rejects_invalid_task_type(tmp_path):
    payload = {
        "task_id": "bad-001",
        "task_type": "deploy",
        "title": "Bad task",
        "repo_path": str(tmp_path),
        "entry_artifacts": {"log": "bad"},
        "verification_commands": ["pytest -q"],
        "allowed_tools": [],
        "metadata": {},
    }

    with pytest.raises(ValidationError):
        TaskSpec.model_validate(payload)


def test_task_spec_rejects_unexpected_extra_field(tmp_path):
    payload = {
        "task_id": "extra-001",
        "task_type": "ci_fix",
        "title": "Extra field task",
        "repo_path": str(tmp_path),
        "entry_artifacts": {"log": "bad"},
        "verification_commands": ["pytest -q"],
        "allowed_tools": [],
        "metadata": {},
        "unexpected": "value",
    }

    with pytest.raises(ValidationError):
        TaskSpec.model_validate(payload)


def test_task_spec_defaults_optional_fields_when_omitted(tmp_path):
    payload = {
        "task_id": "default-001",
        "task_type": "ci_fix",
        "title": "Defaults task",
        "repo_path": str(tmp_path),
        "entry_artifacts": {"log": "ok"},
        "verification_commands": ["pytest -q"],
    }

    task = TaskSpec.model_validate(payload)

    assert task.allowed_tools == []
    assert task.metadata == {}


def test_task_spec_defaults_base_ref_to_none(tmp_path):
    payload = {
        "task_id": "default-base-ref-001",
        "task_type": "ci_fix",
        "title": "Defaults base_ref",
        "repo_path": str(tmp_path),
        "entry_artifacts": {"log": "ok"},
        "verification_commands": ["pytest -q"],
    }

    task = TaskSpec.model_validate(payload)

    assert task.base_ref is None


def test_load_task_spec_from_fixture():
    fixture_path = Path(__file__).resolve().parents[2] / "data" / "tasks" / "demo.json"
    task = load_task_spec(fixture_path)

    assert task.task_id == "demo-ci-001"
    assert task.allowed_tools == ["read_file", "search_code", "apply_patch"]
    assert task.entry_artifacts["search_query"] == "JSONL trace output for task runs"
    assert task.entry_artifacts["new_text"] == "JSONL trace output for fixed-flow task runs"
