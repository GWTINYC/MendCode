import pytest

from app.agent.provider import (
    AgentObservationRecord,
    AgentProviderInput,
    AgentProviderStepInput,
    ProviderResponse,
    ScriptedAgentProvider,
)
from app.schemas.agent_action import Observation, ToolCallAction
from app.tools.structured import ToolInvocation


def test_scripted_provider_builds_initial_fix_actions() -> None:
    provider = ScriptedAgentProvider()

    response = provider.plan_actions(
        AgentProviderInput(
            problem_statement="pytest failed",
            verification_commands=["python -m pytest -q"],
        )
    )

    assert response == ProviderResponse(
        status="succeeded",
        actions=[
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
            {
                "type": "tool_call",
                "action": "run_command",
                "reason": "run requested verification command",
                "args": {"command": "python -m pytest -q"},
            },
            {
                "type": "final_response",
                "status": "completed",
                "summary": "Agent loop completed requested verification commands",
            },
        ],
    )


def test_scripted_provider_returns_initial_actions_one_step_at_a_time() -> None:
    provider = ScriptedAgentProvider()

    first = provider.next_action(
        AgentProviderStepInput(
            problem_statement="fix tests",
            verification_commands=["python -m pytest -q"],
            step_index=1,
            remaining_steps=4,
            observations=[],
        )
    )
    second = provider.next_action(
        AgentProviderStepInput(
            problem_statement="fix tests",
            verification_commands=["python -m pytest -q"],
            step_index=2,
            remaining_steps=3,
            observations=[],
        )
    )
    third = provider.next_action(
        AgentProviderStepInput(
            problem_statement="fix tests",
            verification_commands=["python -m pytest -q"],
            step_index=3,
            remaining_steps=2,
            observations=[],
        )
    )

    assert first.status == "succeeded"
    assert first.action is not None
    assert first.action["type"] == "tool_call"
    assert first.action["action"] == "repo_status"
    assert second.action is not None
    assert second.action["action"] == "detect_project"
    assert third.action is not None
    assert third.action["action"] == "run_command"
    assert third.action["args"] == {"command": "python -m pytest -q"}


def test_scripted_provider_returns_final_response_after_scripted_steps() -> None:
    provider = ScriptedAgentProvider()

    response = provider.next_action(
        AgentProviderStepInput(
            problem_statement="fix tests",
            verification_commands=["python -m pytest -q"],
            step_index=4,
            remaining_steps=1,
            observations=[
                AgentObservationRecord(
                    action=ToolCallAction(
                        type="tool_call",
                        action="run_command",
                        reason="run verification",
                        args={"command": "python -m pytest -q"},
                    ),
                    observation=Observation(
                        status="failed",
                        summary="Ran command: python -m pytest -q",
                        payload={"status": "failed"},
                        error_message="tests failed",
                    ),
                )
            ],
        )
    )

    assert response.status == "succeeded"
    assert response.action is not None
    assert response.action["type"] == "final_response"
    assert response.action["status"] == "completed"


def test_provider_response_failed_factory_includes_observation() -> None:
    response = ProviderResponse.failed("provider timed out")

    assert response.status == "failed"
    assert response.actions == []
    assert response.observation.status == "failed"
    assert response.observation.summary == "Provider failed"
    assert response.observation.error_message == "provider timed out"


def test_provider_response_rejects_success_without_actions_or_tool_invocations() -> None:
    with pytest.raises(ValueError, match="require either actions or tool invocations"):
        ProviderResponse(status="succeeded")


def test_provider_response_rejects_failed_without_observation() -> None:
    try:
        ProviderResponse(status="failed")
    except ValueError as exc:
        assert "failed provider responses require observation" in str(exc)
    else:
        raise AssertionError("ProviderResponse accepted failed status without observation")


def test_scripted_provider_rejects_missing_verification_commands() -> None:
    provider = ScriptedAgentProvider()

    response = provider.plan_actions(
        AgentProviderInput(
            problem_statement="pytest failed",
            verification_commands=[],
        )
    )

    assert response.status == "failed"
    assert response.observation.status == "failed"
    assert response.observation.error_message == "at least one verification command is required"


def test_scripted_provider_can_include_patch_proposal_and_review_actions() -> None:
    provider = ScriptedAgentProvider()
    patch = """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1 +1 @@
-return a - b
+return a + b
"""

    response = provider.plan_actions(
        AgentProviderInput(
            problem_statement="fix add",
            verification_commands=["python check.py"],
            patch_proposal={
                "reason": "add should add operands",
                "files_to_modify": ["calculator.py"],
                "patch": patch,
            },
        )
    )

    assert response.status == "succeeded"
    actions = response.actions
    assert actions[3] == {
        "type": "patch_proposal",
        "reason": "add should add operands",
        "files_to_modify": ["calculator.py"],
        "patch": patch,
    }
    assert actions[4] == {
        "type": "tool_call",
        "action": "run_command",
        "reason": "verify patch proposal",
        "args": {"command": "python check.py"},
    }
    assert actions[5] == {
        "type": "tool_call",
        "action": "show_diff",
        "reason": "summarize worktree changes",
        "args": {},
    }


def test_scripted_provider_builds_failure_location_actions() -> None:
    provider = ScriptedAgentProvider()

    response = provider.plan_failure_location_actions(
        failed_node="tests/test_calculator.py::test_add",
        file_path="tests/test_calculator.py",
        test_name="test_add",
    )

    assert response.status == "succeeded"
    assert response.actions == [
        {
            "type": "tool_call",
            "action": "read_file",
            "reason": "inspect failing test file",
            "args": {"relative_path": "tests/test_calculator.py", "max_chars": 12000},
        },
        {
            "type": "tool_call",
            "action": "search_code",
            "reason": "locate implementation related to failing test",
            "args": {"query": "test_add", "glob": "*.py", "max_results": 20},
        },
        {
            "type": "final_response",
            "status": "completed",
            "summary": "Failure location context collected",
        },
    ]


def test_scripted_provider_rejects_failure_location_without_file_path() -> None:
    provider = ScriptedAgentProvider()

    response = provider.plan_failure_location_actions(
        failed_node=None,
        file_path=None,
        test_name=None,
    )

    assert response.status == "failed"
    assert response.observation.error_message == "failure insight did not include a file path"


def test_provider_response_accepts_native_tool_invocations() -> None:
    response = ProviderResponse(
        status="succeeded",
        tool_invocations=[
            ToolInvocation(
                id="call_1",
                name="read_file",
                args={"path": "README.md"},
                source="openai_tool_call",
            )
        ],
    )

    assert response.tool_invocations[0].name == "read_file"
    assert response.actions == []


def test_agent_observation_record_accepts_tool_invocation() -> None:
    tool_invocation = ToolInvocation(
        id="call_1",
        name="read_file",
        args={"path": "README.md"},
        source="openai_tool_call",
    )
    observation = Observation(
        status="succeeded",
        summary="read README.md",
        payload={"path": "README.md"},
    )

    record = AgentObservationRecord(
        tool_invocation=tool_invocation,
        observation=observation,
    )

    assert record.tool_invocation == tool_invocation
    assert record.observation == observation


def test_provider_response_rejects_actions_and_tool_invocations_together() -> None:
    with pytest.raises(ValueError, match="must not mix actions and tool invocations"):
        ProviderResponse(
            status="succeeded",
            actions=[{"type": "final_response", "status": "completed", "summary": "done"}],
            tool_invocations=[
                ToolInvocation(
                    id="call_1",
                    name="read_file",
                    args={"path": "README.md"},
                    source="openai_tool_call",
                )
            ],
        )
