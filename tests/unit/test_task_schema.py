import json

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


def test_load_task_spec_from_json_file(tmp_path):
    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "task_id": "demo-ci-001",
                "task_type": "ci_fix",
                "title": "Fix failing unit test",
                "repo_path": str(tmp_path),
                "entry_artifacts": {"log": "pytest failed"},
                "verification_commands": ["pytest -q"],
                "allowed_tools": ["read_file", "search_code"],
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )

    task = load_task_spec(task_file)

    assert task.task_id == "demo-ci-001"
