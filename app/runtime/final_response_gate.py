import re

from app.agent.loop import AgentLoopStatus, AgentStep, FinalResponseAction, _HandledAction

_LOCAL_FACT_MARKERS = (
    "readme",
    ".md",
    ".py",
    "当前项目",
    "这个项目",
    "本项目",
    "当前仓库",
    "这个仓库",
    "本仓库",
    "当前目录",
    "当前文件夹",
)
_LOCAL_FACT_PATTERNS = (
    re.compile(r"\bgit\s+(status|diff|log|branch|show)\b", re.IGNORECASE),
    re.compile(r"git\s*(状态|分支|提交|差异|日志)", re.IGNORECASE),
    re.compile(r"(当前|这个|本)(项目|仓库|目录|文件夹)"),
    re.compile(r"代码.{0,4}(中|里|路径|文件)"),
    re.compile(r"(?:^|[\s`'\"])(?:\.{1,2}/|[/\w.-]+/)[\w.-]+"),
)


def apply_final_response_gate(
    *,
    steps: list[AgentStep],
    handled: _HandledAction,
) -> tuple[AgentLoopStatus, str]:
    if not isinstance(handled.step.action, FinalResponseAction):
        return handled.status, handled.summary

    last_patch_index = next(
        (
            index
            for index, step in reversed(list(enumerate(steps)))
            if _is_successful_patch_boundary(step)
        ),
        None,
    )
    observation_start_index = 0 if last_patch_index is None else last_patch_index + 1
    meaningful_steps = [
        step
        for step in steps[observation_start_index:]
        if step.action.type != "assistant_message"
    ]
    if handled.step.action.status == "completed" and last_patch_index is not None:
        last_post_patch_verification = next(
            (
                step.observation
                for step in reversed(steps[last_patch_index + 1 :])
                if step.action.type == "tool_call"
                and getattr(step.action, "action", None) == "run_command"
            ),
            None,
        )
        if (
            last_post_patch_verification is None
            or last_post_patch_verification.status != "succeeded"
        ):
            return "failed", "Agent loop ended with failed observations"
    if handled.step.action.status == "completed" and any(
        step.observation.status != "succeeded" for step in meaningful_steps
    ):
        return "failed", "Agent loop ended with failed observations"
    if (
        handled.step.action.status == "completed"
        and _looks_like_local_fact_answer(handled.step.action.summary)
        and not _has_successful_tool_observation(steps)
    ):
        return "failed", "Final response requires tool evidence for local repository facts"
    return handled.status, handled.summary


def _is_successful_patch_boundary(step: AgentStep) -> bool:
    if step.observation.status != "succeeded":
        return False
    if step.action.type == "patch_proposal":
        return True
    return (
        step.action.type == "tool_call"
        and getattr(step.action, "action", None)
        in {"apply_patch", "apply_patch_to_worktree"}
    )


def _has_successful_tool_observation(steps: list[AgentStep]) -> bool:
    return any(
        step.action.type == "tool_call" and step.observation.status == "succeeded"
        for step in steps
    )


def _looks_like_local_fact_answer(summary: str) -> bool:
    normalized = summary.lower()
    return any(marker in normalized for marker in _LOCAL_FACT_MARKERS) or any(
        pattern.search(summary) for pattern in _LOCAL_FACT_PATTERNS
    )
