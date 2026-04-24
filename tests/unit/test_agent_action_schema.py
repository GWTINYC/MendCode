import pytest
from pydantic import ValidationError

from app.schemas.agent_action import (
    Observation,
    ToolCallAction,
    build_invalid_action_observation,
    parse_mendcode_action,
)
from app.schemas.trace import TraceEvent


def test_parse_tool_call_action_accepts_known_tool():
    action = parse_mendcode_action(
        {
            "type": "tool_call",
            "action": "search_code",
            "reason": "test_add failed, locate the add implementation",
            "args": {"query": "def add", "glob": "*.py"},
        }
    )

    assert isinstance(action, ToolCallAction)
    assert action.action == "search_code"
    assert action.reason == "test_add failed, locate the add implementation"
    assert action.args == {"query": "def add", "glob": "*.py"}


def test_parse_tool_call_action_rejects_unknown_tool():
    with pytest.raises(ValidationError):
        parse_mendcode_action(
            {
                "type": "tool_call",
                "action": "delete_repo",
                "reason": "unsupported destructive operation",
                "args": {},
            }
        )


def test_build_invalid_action_observation_keeps_error_context():
    observation = build_invalid_action_observation(
        payload={"type": "tool_call", "action": "delete_repo"},
        error_message="Input should be 'repo_status'",
    )

    assert observation.status == "rejected"
    assert observation.summary == "Invalid MendCode action"
    assert observation.error_message == "Input should be 'repo_status'"
    assert observation.payload == {"type": "tool_call", "action": "delete_repo"}


def test_observation_requires_error_message_for_failed_or_rejected_status():
    with pytest.raises(ValidationError):
        Observation(
            status="failed",
            summary="Tool failed",
            payload={},
        )


def test_observation_rejects_error_message_for_succeeded_status():
    with pytest.raises(ValidationError):
        Observation(
            status="succeeded",
            summary="Tool succeeded",
            payload={},
            error_message="should not be set",
        )


def test_observation_accepts_succeeded_status_without_error_message():
    observation = Observation(
        status="succeeded",
        summary="Read file",
        payload={"path": "tests/test_calculator.py"},
    )

    assert observation.status == "succeeded"
    assert observation.error_message is None


def test_action_and_observation_can_be_embedded_in_trace_payload():
    action = parse_mendcode_action(
        {
            "type": "tool_call",
            "action": "read_file",
            "reason": "inspect the failing test",
            "args": {"path": "tests/test_calculator.py"},
        }
    )
    observation = Observation(
        status="succeeded",
        summary="Read failing test",
        payload={"path": "tests/test_calculator.py"},
    )

    event = TraceEvent(
        run_id="agent-run-001",
        event_type="agent.action.completed",
        message="Completed agent action",
        payload={
            "action": action.model_dump(mode="json"),
            "observation": observation.model_dump(mode="json"),
        },
    )

    dumped = event.model_dump(mode="json")
    assert dumped["payload"]["action"]["action"] == "read_file"
    assert dumped["payload"]["observation"]["status"] == "succeeded"
