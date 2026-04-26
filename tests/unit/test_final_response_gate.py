from app.agent.loop import AgentStep, _HandledAction
from app.runtime.final_response_gate import apply_final_response_gate
from app.schemas.agent_action import FinalResponseAction, Observation, ToolCallAction


def tool_step(
    *,
    index: int,
    action: str,
    status: str = "succeeded",
    summary: str = "ok",
) -> AgentStep:
    error_message = "error" if status in {"failed", "rejected"} else None
    return AgentStep(
        index=index,
        action=ToolCallAction(
            type="tool_call",
            action=action,
            reason="test",
            args={},
        ),
        observation=Observation(
            status=status,
            summary=summary,
            payload={},
            error_message=error_message,
        ),
    )


def handled_final(
    *,
    index: int,
    status: str = "completed",
    summary: str = "done",
) -> _HandledAction:
    action = FinalResponseAction(
        type="final_response",
        status=status,
        summary=summary,
    )
    return _HandledAction(
        stop=True,
        status=status,
        summary=summary,
        step=AgentStep(
            index=index,
            action=action,
            observation=Observation(
                status="succeeded",
                summary="Recorded agent action",
                payload={},
            ),
        ),
    )


def test_gate_blocks_completed_final_after_failed_observation() -> None:
    status, summary = apply_final_response_gate(
        steps=[
            tool_step(index=1, action="read_file", status="rejected", summary="missing"),
        ],
        handled=handled_final(index=2),
    )

    assert status == "failed"
    assert summary == "Agent loop ended with failed observations"


def test_gate_requires_successful_verification_after_patch() -> None:
    status, summary = apply_final_response_gate(
        steps=[
            tool_step(index=1, action="apply_patch"),
        ],
        handled=handled_final(index=2),
    )

    assert status == "failed"
    assert summary == "Agent loop ended with failed observations"


def test_gate_allows_completed_final_after_patch_and_successful_verification() -> None:
    status, summary = apply_final_response_gate(
        steps=[
            tool_step(index=1, action="apply_patch"),
            tool_step(index=2, action="run_command"),
        ],
        handled=handled_final(index=3),
    )

    assert status == "completed"
    assert summary == "done"
