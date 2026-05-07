from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ToolStatus = Literal["passed", "failed", "rejected"]


def count_text_lines(text: str) -> int:
    if text == "":
        return 0
    return len(text.splitlines())


def build_write_preview(
    *,
    paths: list[str],
    additions: int = 0,
    deletions: int = 0,
    requires_confirmation: bool = True,
    reason: str | None = None,
) -> dict[str, Any]:
    unique_paths = _unique_non_empty(paths)
    preview: dict[str, Any] = {
        "paths": unique_paths,
        "diff_stat": {
            "files": len(unique_paths),
            "additions": max(additions, 0),
            "deletions": max(deletions, 0),
        },
        "requires_confirmation": requires_confirmation,
    }
    if reason is not None:
        preview["reason"] = reason
    return preview


def build_patch_preview(
    *,
    paths: list[str],
    patch: str,
    requires_confirmation: bool = True,
    reason: str | None = None,
) -> dict[str, Any]:
    additions = 0
    deletions = 0
    for line in patch.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return build_write_preview(
        paths=paths,
        additions=additions,
        deletions=deletions,
        requires_confirmation=requires_confirmation,
        reason=reason,
    )


def _unique_non_empty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    status: ToolStatus
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    preview: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    workspace_path: str

    @model_validator(mode="after")
    def validate_status_error_message(self) -> "ToolResult":
        if self.status == "passed" and self.error_message is not None:
            raise ValueError("passed status requires error_message=None")
        if self.status in {"failed", "rejected"} and self.error_message is None:
            raise ValueError("failed and rejected statuses require error_message")
        return self
