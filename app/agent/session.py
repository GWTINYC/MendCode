from pydantic import BaseModel, ConfigDict, Field

from app.agent.loop import AgentLoopResult


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


def _latest_verification_status(loop_result: AgentLoopResult) -> str:
    for step in reversed(loop_result.steps):
        if (
            step.action.type == "tool_call"
            and getattr(step.action, "action", None) == "run_command"
        ):
            return str(step.observation.payload.get("status", step.observation.status))
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
