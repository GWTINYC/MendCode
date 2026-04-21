from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.task import TaskType
from app.schemas.verification import VerificationResult


class RunState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    task_id: str
    task_type: TaskType
    status: Literal["running", "completed", "failed"]
    current_step: Literal["bootstrap", "verify", "summarize"]
    summary: str
    trace_path: str
    verification: VerificationResult | None = None
