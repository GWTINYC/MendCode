from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.task import TaskType
from app.schemas.verification import VerificationResult


class RunState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    task_id: str
    task_type: TaskType
    status: Literal["running", "completed", "failed"]
    current_step: Literal["bootstrap", "locate", "inspect", "patch", "verify", "summarize"]
    summary: str
    trace_path: str
    workspace_path: str | None = None
    selected_files: list[str] = Field(default_factory=list)
    applied_patch: bool = False
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    verification: VerificationResult | None = None
