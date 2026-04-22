from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ToolStatus = Literal["passed", "failed", "rejected"]


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    status: ToolStatus
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    workspace_path: str

    @model_validator(mode="after")
    def validate_status_error_message(self) -> "ToolResult":
        if self.status == "passed" and self.error_message is not None:
            raise ValueError("passed status requires error_message=None")
        if self.status in {"failed", "rejected"} and self.error_message is None:
            raise ValueError("failed and rejected statuses require error_message")
        return self
