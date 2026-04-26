from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent_action import MendCodeAction, Observation
from app.tools.structured import AllowedTools

RuntimeStatus = Literal["completed", "failed", "needs_user_confirmation"]


class RuntimeTurnInput(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    problem_statement: str
    repo_path: Path | None = None
    verification_commands: list[str] = Field(default_factory=list)
    allowed_tools: AllowedTools = None
    step_budget: int = Field(default=12, ge=1)


class RuntimeToolStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    action: MendCodeAction
    observation: Observation


class RuntimeTurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: RuntimeStatus
    summary: str
    trace_path: str | None
    workspace_path: str | None = None
    steps: list[RuntimeToolStep] = Field(default_factory=list)
