from typing import Any

from pydantic import BaseModel, ConfigDict


class AgentProviderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_statement: str
    verification_commands: list[str]
    patch_proposal: dict[str, Any] | None = None


class ScriptedAgentProvider:
    def plan_actions(self, provider_input: AgentProviderInput) -> list[dict[str, object]]:
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
        return actions
