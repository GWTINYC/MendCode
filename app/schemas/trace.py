import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_RESERVED_RUN_ID_STEM = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)


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
        if not value:
            raise ValueError("run_id must be a safe filename")
        if not _RUN_ID_PATTERN.fullmatch(value):
            raise ValueError("run_id must be a safe filename")
        if value.endswith("."):
            raise ValueError("run_id must be a safe filename")
        if _RESERVED_RUN_ID_STEM.fullmatch(value.split(".", 1)[0]):
            raise ValueError("run_id must be a safe filename")
        return value
