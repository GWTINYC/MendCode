from pydantic import BaseModel, ConfigDict, model_validator

from app.tools.schemas import ToolResult


class FixedFlowArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search_query: str | None = None
    target_path_glob: str | None = None
    read_target_path: str | None = None
    read_start_line: int | None = None
    read_end_line: int | None = None
    old_text: str
    new_text: str
    expected_verification_hint: str | None = None

    @model_validator(mode="after")
    def validate_targeting(self) -> "FixedFlowArtifacts":
        if self.read_target_path is not None and not self.read_target_path.strip():
            raise ValueError("read_target_path must not be empty")
        if self.read_target_path is None and (self.search_query is None or not self.search_query.strip()):
            raise ValueError("either read_target_path or search_query is required")
        if self.read_start_line is not None and self.read_start_line <= 0:
            raise ValueError("read_start_line must be greater than 0")
        if self.read_end_line is not None and self.read_end_line <= 0:
            raise ValueError("read_end_line must be greater than 0")
        if (
            self.read_start_line is not None
            and self.read_end_line is not None
            and self.read_end_line < self.read_start_line
        ):
            raise ValueError("read_end_line must be greater than or equal to read_start_line")
        return self


def load_fixed_flow_artifacts(payload: dict[str, object]) -> FixedFlowArtifacts:
    return FixedFlowArtifacts.model_validate(payload)


def summarize_tool_result(result: ToolResult) -> dict[str, object]:
    return {
        "tool_name": result.tool_name,
        "status": result.status,
        "summary": result.summary,
        "error_message": result.error_message,
        "payload": {
            key: value
            for key, value in result.payload.items()
            if key not in {"content", "matches"}
        },
    }
