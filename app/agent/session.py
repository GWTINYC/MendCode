from pydantic import BaseModel, ConfigDict, Field

from app.agent.loop import AgentLoopInput, AgentLoopResult, run_agent_loop
from app.agent.permission import PermissionMode
from app.config.settings import Settings, get_settings
from app.schemas.agent_action import Observation


class ReviewSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    workspace_path: str | None
    trace_path: str | None
    changed_files: list[str] = Field(default_factory=list)
    diff_stat: str | None = None
    verification_status: str
    summary: str
    recommended_actions: list[str] = Field(default_factory=list)


class AttemptRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    patch_summary: list[str] = Field(default_factory=list)
    patch_status: str
    verification_status: str
    error_message: str | None = None


class ToolCallSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    action: str
    status: str
    summary: str


class AgentSessionTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    problem_statement: str
    result: AgentLoopResult
    review: ReviewSummary
    attempts: list[AttemptRecord] = Field(default_factory=list)
    tool_summaries: list[ToolCallSummary] = Field(default_factory=list)


class AgentSession:
    def __init__(
        self,
        *,
        repo_path,
        provider,
        settings: Settings | None = None,
        permission_mode: PermissionMode = "guided",
    ) -> None:
        self.repo_path = repo_path
        self.provider = provider
        self.settings = settings or get_settings()
        self.permission_mode: PermissionMode = permission_mode
        self.turns: list[AgentSessionTurn] = []

    def run_turn(
        self,
        *,
        problem_statement: str,
        verification_commands: list[str],
        step_budget: int = 12,
    ) -> AgentSessionTurn:
        result = run_agent_loop(
            AgentLoopInput(
                repo_path=self.repo_path,
                problem_statement=problem_statement,
                provider=self.provider,
                verification_commands=verification_commands,
                permission_mode=self.permission_mode,
                step_budget=step_budget,
                use_worktree=True,
            ),
            self.settings,
        )
        turn = AgentSessionTurn(
            index=len(self.turns) + 1,
            problem_statement=problem_statement,
            result=result,
            review=build_review_summary(result),
            attempts=build_attempt_records(result),
            tool_summaries=build_tool_summaries(result),
        )
        self.turns.append(turn)
        return turn


def build_tool_summaries(loop_result: AgentLoopResult) -> list[ToolCallSummary]:
    summaries: list[ToolCallSummary] = []
    for step in loop_result.steps:
        if step.action.type != "tool_call":
            continue
        action_name = getattr(step.action, "action", step.action.type)
        summaries.append(
            ToolCallSummary(
                index=step.index,
                action=str(action_name),
                status=step.observation.status,
                summary=step.observation.summary,
            )
        )
    return summaries


def _raw_tool_payload(observation: Observation) -> dict[str, object]:
    raw_payload = observation.payload.get("payload")
    return raw_payload if isinstance(raw_payload, dict) else {}


def _verification_status_from_observation(observation: Observation) -> str:
    raw_status = _raw_tool_payload(observation).get("status")
    if raw_status is not None:
        return str(raw_status)
    return str(observation.payload.get("status", observation.status))


def _latest_verification_status(loop_result: AgentLoopResult) -> str:
    for step in reversed(loop_result.steps):
        if (
            step.action.type == "tool_call"
            and getattr(step.action, "action", None) == "run_command"
        ):
            return _verification_status_from_observation(step.observation)
    return "not_run"


def _diff_stat(loop_result: AgentLoopResult) -> str | None:
    for step in reversed(loop_result.steps):
        if step.action.type == "tool_call" and getattr(step.action, "action", None) == "show_diff":
            value = step.observation.payload.get("diff_stat")
            return str(value) if value is not None else None
    return None


def _changed_files_from_diff_stat(diff_stat: str | None) -> list[str]:
    if diff_stat is None:
        return []
    files: list[str] = []
    for line in diff_stat.splitlines():
        stripped = line.strip()
        if not stripped or "|" not in stripped:
            continue
        files.append(stripped.split("|", 1)[0].strip())
    return files


def build_attempt_records(loop_result: AgentLoopResult) -> list[AttemptRecord]:
    attempts: list[AttemptRecord] = []
    attempt_index = 1
    for index, step in enumerate(loop_result.steps):
        if step.action.type != "patch_proposal":
            continue
        files = list(getattr(step.action, "files_to_modify", []))
        if step.observation.status != "succeeded":
            attempts.append(
                AttemptRecord(
                    index=attempt_index,
                    patch_summary=files,
                    patch_status="failed",
                    verification_status="not_run",
                    error_message=step.observation.error_message,
                )
            )
            attempt_index += 1
            continue
        verification_status = "not_run"
        error_message = None
        for next_step in loop_result.steps[index + 1 :]:
            if next_step.action.type == "patch_proposal":
                break
            if (
                next_step.action.type == "tool_call"
                and getattr(next_step.action, "action", None) == "run_command"
            ):
                verification_status = _verification_status_from_observation(
                    next_step.observation
                )
                error_message = next_step.observation.error_message
                if verification_status != "passed":
                    break
        if verification_status != "passed":
            attempts.append(
                AttemptRecord(
                    index=attempt_index,
                    patch_summary=files,
                    patch_status="applied",
                    verification_status=verification_status,
                    error_message=error_message,
                )
            )
        attempt_index += 1
    return attempts


def build_review_summary(loop_result: AgentLoopResult) -> ReviewSummary:
    verification_status = _latest_verification_status(loop_result)
    diff_stat = _diff_stat(loop_result)
    status = (
        "verified"
        if verification_status == "passed" and loop_result.status == "completed"
        else "failed"
    )
    recommended_actions = (
        ["view_diff", "view_trace", "discard", "apply"]
        if status == "verified"
        else ["view_trace", "discard"]
    )
    return ReviewSummary(
        status=status,
        workspace_path=loop_result.workspace_path,
        trace_path=loop_result.trace_path,
        changed_files=_changed_files_from_diff_stat(diff_stat),
        diff_stat=diff_stat,
        verification_status=verification_status,
        summary=loop_result.summary,
        recommended_actions=recommended_actions,
    )
