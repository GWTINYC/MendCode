from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_action import Observation

ProviderStatus = str


class AgentProviderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_statement: str
    verification_commands: list[str]
    patch_proposal: dict[str, Any] | None = None


class ProviderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ProviderStatus
    actions: list[dict[str, object]] = Field(default_factory=list)
    observation: Observation | None = None

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
        if self.status == "succeeded" and not self.actions:
            raise ValueError("succeeded provider responses require actions")
        if self.status == "failed" and self.observation is None:
            raise ValueError("failed provider responses require observation")
        return self


class ScriptedAgentProvider:
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
