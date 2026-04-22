from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ToolStatus = Literal["passed", "failed", "rejected"]


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    status: ToolStatus
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    workspace_path: str
