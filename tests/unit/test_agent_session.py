from app.agent.loop import AgentLoopResult, AgentStep
from app.agent.session import (
    AttemptRecord,
    ReviewSummary,
    build_attempt_records,
    build_review_summary,
)
from app.schemas.agent_action import Observation, PatchProposalAction, ToolCallAction


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


def patch_step(index: int, status: str, error_message: str | None = None) -> AgentStep:
    return AgentStep(
        index=index,
        action=PatchProposalAction(
            type="patch_proposal",
            reason="fix add",
            files_to_modify=["calculator.py"],
            patch="diff --git a/calculator.py b/calculator.py\n",
        ),
        observation=Observation(
            status=status,
            summary="Applied patch proposal"
            if status == "succeeded"
            else "Unable to apply patch proposal",
            payload={"files_to_modify": ["calculator.py"]},
            error_message=error_message,
        ),
    )


def test_attempt_record_is_created_for_failed_patch_apply() -> None:
    loop_result = AgentLoopResult(
        run_id="agent-3",
        status="failed",
        summary="patch failed",
        trace_path="data/traces/agent-3.jsonl",
        workspace_path=".worktrees/agent-3",
        steps=[patch_step(1, "failed", "patch does not apply")],
    )

    attempts = build_attempt_records(loop_result)

    assert attempts == [
        AttemptRecord(
            index=1,
            patch_summary=["calculator.py"],
            patch_status="failed",
            verification_status="not_run",
            error_message="patch does not apply",
        )
    ]


def test_attempt_record_is_created_for_patch_verification_failure() -> None:
    loop_result = AgentLoopResult(
        run_id="agent-4",
        status="failed",
        summary="verification failed",
        trace_path="data/traces/agent-4.jsonl",
        workspace_path=".worktrees/agent-4",
        steps=[
            patch_step(1, "succeeded"),
            tool_step(
                2,
                "run_command",
                Observation(
                    status="failed",
                    summary="Ran command",
                    payload={"status": "failed"},
                    error_message="tests failed",
                ),
            ),
        ],
    )

    attempts = build_attempt_records(loop_result)

    assert attempts == [
        AttemptRecord(
            index=1,
            patch_summary=["calculator.py"],
            patch_status="applied",
            verification_status="failed",
            error_message="tests failed",
        )
    ]


def test_attempt_record_tracks_failed_verification_after_passed_command() -> None:
    loop_result = AgentLoopResult(
        run_id="agent-5",
        status="failed",
        summary="verification failed",
        trace_path="data/traces/agent-5.jsonl",
        workspace_path=".worktrees/agent-5",
        steps=[
            patch_step(1, "succeeded"),
            tool_step(
                2,
                "run_command",
                Observation(
                    status="succeeded",
                    summary="Ran command",
                    payload={"status": "passed"},
                ),
            ),
            tool_step(
                3,
                "run_command",
                Observation(
                    status="failed",
                    summary="Ran command",
                    payload={"status": "failed"},
                    error_message="integration tests failed",
                ),
            ),
        ],
    )

    attempts = build_attempt_records(loop_result)

    assert attempts == [
        AttemptRecord(
            index=1,
            patch_summary=["calculator.py"],
            patch_status="applied",
            verification_status="failed",
            error_message="integration tests failed",
        )
    ]


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
