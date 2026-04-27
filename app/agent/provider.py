from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.permissions.policy import PermissionMode
from app.schemas.agent_action import MendCodeAction, Observation
from app.tools.structured import ToolInvocation

ProviderStatus = str


class AgentProviderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_statement: str
    verification_commands: list[str]
    patch_proposal: dict[str, Any] | None = None


class AgentObservationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: MendCodeAction | None = None
    tool_invocation: ToolInvocation | None = None
    observation: Observation


class AgentProviderStepInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_statement: str
    verification_commands: list[str]
    step_index: int = Field(ge=1)
    remaining_steps: int = Field(ge=0)
    observations: list[AgentObservationRecord] = Field(default_factory=list)
    context: str | None = None
    allowed_tools: set[str] | None = None
    permission_mode: PermissionMode = "guided"


class ProviderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ProviderStatus
    actions: list[dict[str, object]] = Field(default_factory=list)
    tool_invocations: list[ToolInvocation] = Field(default_factory=list)
    observation: Observation | None = None

    @property
    def action(self) -> dict[str, object] | None:
        return self.actions[0] if self.actions else None

    @classmethod
    def failed(cls, error_message: str) -> "ProviderResponse":
        return cls(
            status="failed",
            observation=Observation(
                status="failed",
                summary="Provider failed",
                payload={},
                error_message=error_message,
            ),
        )

    @model_validator(mode="after")
    def validate_response_shape(self) -> "ProviderResponse":
        if self.status == "succeeded":
            if self.actions and self.tool_invocations:
                raise ValueError("provider responses must not mix actions and tool invocations")
            if not self.actions and not self.tool_invocations:
                raise ValueError(
                    "succeeded provider responses require either actions or tool invocations"
                )
        if self.status == "failed" and self.observation is None:
            raise ValueError("failed provider responses require observation")
        return self


class AgentProvider(Protocol):
    def next_action(self, step_input: AgentProviderStepInput) -> ProviderResponse:
        ...


class ScriptedAgentProvider:
    def next_action(self, step_input: AgentProviderStepInput) -> ProviderResponse:
        plan_response = self.plan_actions(
            AgentProviderInput(
                problem_statement=step_input.problem_statement,
                verification_commands=step_input.verification_commands,
            )
        )
        if plan_response.status != "succeeded":
            return plan_response

        action_index = step_input.step_index - 1
        if action_index >= len(plan_response.actions):
            return ProviderResponse(
                status="succeeded",
                actions=[
                    {
                        "type": "final_response",
                        "status": "completed",
                        "summary": "Agent loop completed requested verification commands",
                    }
                ],
            )

        return _scripted_provider_response_for_action(
            plan_response.actions[action_index],
            index=action_index + 1,
        )

    def plan_actions(self, provider_input: AgentProviderInput) -> ProviderResponse:
        if not provider_input.verification_commands:
            return ProviderResponse.failed("at least one verification command is required")

        actions: list[dict[str, object]] = [
            {
                "type": "tool_call",
                "action": "repo_status",
                "reason": "inspect repository state before attempting a fix",
                "args": {},
            },
            {
                "type": "tool_call",
                "action": "detect_project",
                "reason": "detect project type and likely verification commands",
                "args": {},
            },
        ]
        actions.extend(
            {
                "type": "tool_call",
                "action": "run_command",
                "reason": "run requested verification command",
                "args": {"command": command},
            }
            for command in provider_input.verification_commands
        )

        if provider_input.patch_proposal is not None:
            actions.append(
                {
                    "type": "patch_proposal",
                    "reason": str(provider_input.patch_proposal["reason"]),
                    "files_to_modify": list(provider_input.patch_proposal["files_to_modify"]),
                    "patch": str(provider_input.patch_proposal["patch"]),
                }
            )
            actions.extend(
                {
                    "type": "tool_call",
                    "action": "run_command",
                    "reason": "verify patch proposal",
                    "args": {"command": command},
                }
                for command in provider_input.verification_commands
            )
            actions.append(
                {
                    "type": "tool_call",
                    "action": "show_diff",
                    "reason": "summarize worktree changes",
                    "args": {},
                }
            )

        actions.append(
            {
                "type": "final_response",
                "status": "completed",
                "summary": "Agent loop completed requested verification commands",
            }
        )
        return ProviderResponse(status="succeeded", actions=actions)

    def plan_failure_location_actions(
        self,
        *,
        failed_node: str | None,
        file_path: str | None,
        test_name: str | None,
    ) -> ProviderResponse:
        if file_path is None:
            return ProviderResponse.failed("failure insight did not include a file path")

        query = test_name or failed_node or file_path
        return ProviderResponse(
            status="succeeded",
            actions=[
                {
                    "type": "tool_call",
                    "action": "read_file",
                    "reason": "inspect failing test file",
                    "args": {"relative_path": file_path, "max_chars": 12000},
                },
                {
                    "type": "tool_call",
                    "action": "search_code",
                    "reason": "locate implementation related to failing test",
                    "args": {"query": query, "glob": "*.py", "max_results": 20},
                },
                {
                    "type": "final_response",
                    "status": "completed",
                    "summary": "Failure location context collected",
                },
            ],
        )


def _scripted_provider_response_for_action(
    action: dict[str, object],
    *,
    index: int,
) -> ProviderResponse:
    action_type = action.get("type")
    if action_type == "final_response":
        return ProviderResponse(status="succeeded", actions=[action])
    if action_type == "tool_call":
        tool_name = str(action.get("action", ""))
        args = action.get("args", {})
        if not isinstance(args, dict):
            return ProviderResponse.failed("scripted provider tool_call args must be an object")
        return ProviderResponse(
            status="succeeded",
            tool_invocations=[
                ToolInvocation(
                    id=f"scripted_{index}_{tool_name}",
                    name=tool_name,
                    args=args,
                    source="json_action",
                )
            ],
        )
    return ProviderResponse.failed(
        f"scripted provider action is not supported in provider mode: {action_type}"
    )
