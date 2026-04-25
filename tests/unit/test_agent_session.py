from app.agent.loop import AgentLoopResult, AgentStep
from app.agent.session import ReviewSummary, build_review_summary
from app.schemas.agent_action import Observation, ToolCallAction


def tool_step(index: int, action: str, observation: Observation) -> AgentStep:
    return AgentStep(
        index=index,
        action=ToolCallAction(
            type="tool_call",
            action=action,
            reason=f"run {action}",
            args={},
        ),
        observation=observation,
    )


def test_review_summary_is_verified_only_after_passed_verification() -> None:
    loop_result = AgentLoopResult(
        run_id="agent-1",
        status="completed",
        summary="verification passed",
        trace_path="data/traces/agent-1.jsonl",
        workspace_path=".worktrees/agent-1",
        steps=[
            tool_step(
                1,
                "run_command",
                Observation(
                    status="succeeded",
                    summary="Ran command",
                    payload={"status": "passed", "command": "python -m pytest -q"},
                ),
            ),
            tool_step(
                2,
                "show_diff",
                Observation(
                    status="succeeded",
                    summary="Read diff summary",
                    payload={"diff_stat": " calculator.py | 2 +-\n"},
                ),
            ),
        ],
    )

    summary = build_review_summary(loop_result)

    assert summary == ReviewSummary(
        status="verified",
        workspace_path=".worktrees/agent-1",
        trace_path="data/traces/agent-1.jsonl",
        changed_files=["calculator.py"],
        diff_stat=" calculator.py | 2 +-\n",
        verification_status="passed",
        summary="verification passed",
        recommended_actions=["view_diff", "view_trace", "discard", "apply"],
    )


def test_review_summary_is_failed_when_latest_verification_failed() -> None:
    loop_result = AgentLoopResult(
        run_id="agent-2",
        status="failed",
        summary="Agent loop ended with failed observations",
        trace_path="data/traces/agent-2.jsonl",
        workspace_path=".worktrees/agent-2",
        steps=[
            tool_step(
                1,
                "run_command",
                Observation(
                    status="failed",
                    summary="Ran command",
                    payload={"status": "failed", "command": "python -m pytest -q"},
                    error_message="1 failed",
                ),
            )
        ],
    )

    summary = build_review_summary(loop_result)

    assert summary.status == "failed"
    assert summary.verification_status == "failed"
    assert summary.recommended_actions == ["view_trace", "discard"]


def test_review_summary_is_failed_when_loop_failed_after_passed_verification() -> None:
    loop_result = AgentLoopResult(
        run_id="agent-3",
        status="failed",
        summary="Agent loop failed after verification",
        trace_path="data/traces/agent-3.jsonl",
        workspace_path=".worktrees/agent-3",
        steps=[
            tool_step(
                1,
                "run_command",
                Observation(
                    status="succeeded",
                    summary="Ran command",
                    payload={"status": "passed", "command": "python -m pytest -q"},
                ),
            )
        ],
    )

    summary = build_review_summary(loop_result)

    assert summary.status == "failed"
    assert summary.verification_status == "passed"
    assert summary.recommended_actions == ["view_trace", "discard"]
