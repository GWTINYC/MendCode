from app.agent.prompt_context import PromptContextLimits, build_provider_messages
from app.agent.provider import AgentObservationRecord, AgentProviderStepInput
from app.schemas.agent_action import Observation, ToolCallAction


def test_provider_messages_include_repair_contract_and_allowed_tools() -> None:
    messages = build_provider_messages(
        AgentProviderStepInput(
            problem_statement="fix failing tests",
            verification_commands=["python -m pytest -q"],
            step_index=1,
            remaining_steps=6,
            observations=[],
        )
    )

    assert messages[0].role == "system"
    assert "Return exactly one JSON object and no prose" in messages[0].content
    assert "patch_proposal" in messages[0].content
    assert "show_diff" in messages[0].content
    assert "Never claim completed after a failed verification" in messages[0].content
    assert messages[1].role == "user"
    assert "fix failing tests" in messages[1].content
    assert "python -m pytest -q" in messages[1].content


def test_provider_messages_summarize_failed_run_command() -> None:
    action = ToolCallAction(
        type="tool_call",
        action="run_command",
        reason="run tests",
        args={"command": "python -m pytest -q"},
    )
    observation = Observation(
        status="failed",
        summary="Ran command: python -m pytest -q",
        payload={
            "command": "python -m pytest -q",
            "status": "failed",
            "stderr_excerpt": "AssertionError: assert -1 == 5",
        },
        error_message="AssertionError: assert -1 == 5",
    )

    messages = build_provider_messages(
        AgentProviderStepInput(
            problem_statement="fix failing tests",
            verification_commands=["python -m pytest -q"],
            step_index=2,
            remaining_steps=5,
            observations=[AgentObservationRecord(action=action, observation=observation)],
        )
    )

    assert "run_command" in messages[1].content
    assert "AssertionError: assert -1 == 5" in messages[1].content


def test_provider_messages_truncate_large_read_file_content() -> None:
    action = ToolCallAction(
        type="tool_call",
        action="read_file",
        reason="read file",
        args={"relative_path": "tests/test_calculator.py"},
    )
    observation = Observation(
        status="succeeded",
        summary="Read tests/test_calculator.py",
        payload={
            "relative_path": "tests/test_calculator.py",
            "content": "x" * 200,
            "truncated": False,
        },
    )

    messages = build_provider_messages(
        AgentProviderStepInput(
            problem_statement="fix failing tests",
            verification_commands=["python -m pytest -q"],
            step_index=3,
            remaining_steps=4,
            observations=[AgentObservationRecord(action=action, observation=observation)],
        ),
        limits=PromptContextLimits(max_text_chars=40, max_observations=5),
    )

    assert "x" * 40 in messages[1].content
    assert "x" * 80 not in messages[1].content


def test_provider_messages_redact_secrets() -> None:
    observation = Observation(
        status="failed",
        summary="Provider failed",
        payload={"stderr_excerpt": "token secret-key leaked"},
        error_message="secret-key",
    )

    messages = build_provider_messages(
        AgentProviderStepInput(
            problem_statement="secret-key should not leak",
            verification_commands=["python -m pytest -q"],
            step_index=1,
            remaining_steps=4,
            observations=[AgentObservationRecord(action=None, observation=observation)],
        ),
        secret_values=["secret-key"],
    )

    combined = "\n".join(message.content for message in messages)
    assert "secret-key" not in combined
    assert "[REDACTED]" in combined
