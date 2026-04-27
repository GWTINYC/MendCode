import subprocess

from app.agent.loop import AgentLoopResult, AgentStep
from app.agent.provider import AgentProviderStepInput, ProviderResponse
from app.agent.session import (
    AgentSession,
    AgentSessionTurn,
    AttemptRecord,
    ReviewSummary,
    build_attempt_records,
    build_review_summary,
)
from app.schemas.agent_action import Observation, PatchProposalAction, ToolCallAction
from app.tools.structured import ToolInvocation


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


def init_session_repo(repo_path) -> None:
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (repo_path / "README.md").write_text("demo\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )


class SessionFakeProvider:
    def __init__(self) -> None:
        self.calls: list[AgentProviderStepInput] = []

    def next_action(self, step_input: AgentProviderStepInput) -> ProviderResponse:
        self.calls.append(step_input)
        if len(self.calls) == 1:
            return ProviderResponse(
                status="succeeded",
                tool_invocations=[
                    ToolInvocation(
                        id="call_verify",
                        name="run_command",
                        args={"command": step_input.verification_commands[0]},
                        source="openai_tool_call",
                    )
                ],
            )
        return ProviderResponse(
            status="succeeded",
            actions=[
                {
                    "type": "final_response",
                    "status": "completed",
                    "summary": "turn complete",
                }
            ],
        )


def test_agent_session_run_turn_records_review_and_tool_summaries(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    repo_path = tmp_path / "repo"
    init_session_repo(repo_path)
    provider = SessionFakeProvider()
    session = AgentSession(repo_path=repo_path, provider=provider)

    turn = session.run_turn(
        problem_statement="run verification",
        verification_commands=["python -c 'raise SystemExit(0)'"],
    )

    assert isinstance(turn, AgentSessionTurn)
    assert turn.index == 1
    assert turn.problem_statement == "run verification"
    assert turn.result.status == "completed"
    assert turn.review.verification_status == "passed"
    assert len(turn.tool_summaries) == 1
    assert turn.tool_summaries[0].action == "run_command"
    assert turn.tool_summaries[0].status == "succeeded"
    assert session.turns == [turn]
    assert provider.calls[0].problem_statement == "run verification"


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


def test_attempt_record_ignores_enveloped_passed_verification_after_patch() -> None:
    loop_result = AgentLoopResult(
        run_id="agent-6",
        status="completed",
        summary="verification passed",
        trace_path="data/traces/agent-6.jsonl",
        workspace_path=".worktrees/agent-6",
        steps=[
            patch_step(1, "succeeded"),
            tool_step(
                2,
                "run_command",
                Observation(
                    status="succeeded",
                    summary="Ran command",
                    payload={
                        "tool_name": "run_command",
                        "status": "succeeded",
                        "payload": {
                            "status": "passed",
                            "command": "python -m pytest -q",
                        },
                        "command": "python -m pytest -q",
                    },
                ),
            ),
        ],
    )

    attempts = build_attempt_records(loop_result)

    assert attempts == []


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


def test_review_summary_uses_enveloped_raw_verification_status() -> None:
    loop_result = AgentLoopResult(
        run_id="agent-7",
        status="completed",
        summary="verification passed",
        trace_path="data/traces/agent-7.jsonl",
        workspace_path=".worktrees/agent-7",
        steps=[
            tool_step(
                1,
                "run_command",
                Observation(
                    status="succeeded",
                    summary="Ran command",
                    payload={
                        "tool_name": "run_command",
                        "status": "succeeded",
                        "payload": {
                            "status": "passed",
                            "command": "python -m pytest -q",
                        },
                        "command": "python -m pytest -q",
                    },
                ),
            )
        ],
    )

    summary = build_review_summary(loop_result)

    assert summary.status == "verified"
    assert summary.verification_status == "passed"


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
