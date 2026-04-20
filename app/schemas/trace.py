from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    event_type: str
    message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        if "/" in value or "\\" in value or ".." in value:
            raise ValueError("run_id must be a safe filename")
        return value
