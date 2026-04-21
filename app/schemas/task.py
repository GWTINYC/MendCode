import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    task_type: Literal["ci_fix", "test_regression_fix", "pr_review"]
    title: str
    repo_path: str
    entry_artifacts: dict[str, Any]
    verification_commands: list[str]
    allowed_tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def load_task_spec(path: str | Path) -> TaskSpec:
    file_path = Path(path)
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    return TaskSpec.model_validate(payload)
