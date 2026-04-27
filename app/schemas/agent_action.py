from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

ActionType = Literal[
    "assistant_message",
    "tool_call",
    "patch_proposal",
    "user_confirmation_request",
    "final_response",
]
ToolName = Literal[
    "repo_status",
    "detect_project",
    "run_command",
    "run_shell_command",
    "read_file",
    "list_dir",
    "glob_file_search",
    "search_code",
    "rg",
    "git",
    "apply_patch",
    "apply_patch_to_worktree",
    "write_file",
    "edit_file",
    "todo_write",
    "session_status",
    "tool_search",
    "show_diff",
    "process_start",
    "process_poll",
    "process_write",
    "process_stop",
    "process_list",
    "lsp",
]
ObservationStatus = Literal["succeeded", "failed", "rejected"]
RiskLevel = Literal["low", "medium", "high", "critical"]
FinalResponseStatus = Literal["completed", "failed", "needs_user_confirmation"]


class AssistantMessageAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["assistant_message"]
    message: str


class ToolCallAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["tool_call"]
    action: ToolName
    reason: str
    args: dict[str, Any] = Field(default_factory=dict)


class PatchProposalAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["patch_proposal"]
    reason: str
    files_to_modify: list[str] = Field(default_factory=list)
    patch: str


class UserConfirmationRequestAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["user_confirmation_request"]
    prompt: str
    risk_level: RiskLevel
    options: list[str]


class FinalResponseAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["final_response"]
    status: FinalResponseStatus
    summary: str
    recommended_actions: list[str] = Field(default_factory=list)


MendCodeAction = Annotated[
    AssistantMessageAction
    | ToolCallAction
    | PatchProposalAction
    | UserConfirmationRequestAction
    | FinalResponseAction,
    Field(discriminator="type"),
]

_ACTION_ADAPTER = TypeAdapter(MendCodeAction)


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ObservationStatus
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_error_message(self) -> "Observation":
        if self.status == "succeeded" and self.error_message is not None:
            raise ValueError("succeeded observations require error_message=None")
        if self.status in {"failed", "rejected"} and self.error_message is None:
            raise ValueError("failed and rejected observations require error_message")
        return self


def parse_mendcode_action(payload: dict[str, Any]) -> MendCodeAction:
    return _ACTION_ADAPTER.validate_python(payload)


def build_invalid_action_observation(
    *,
    payload: dict[str, Any],
    error_message: str,
) -> Observation:
    return Observation(
        status="rejected",
        summary="Invalid MendCode action",
        payload=payload,
        error_message=error_message,
    )
