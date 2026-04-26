from app.agent.prompt_context import PromptContextLimits, build_provider_messages
from app.agent.provider import AgentObservationRecord, AgentProviderStepInput
from app.schemas.agent_action import Observation, ToolCallAction
from app.tools.structured import ToolInvocation


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
    assert "list_dir" in messages[0].content
    assert "glob_file_search" in messages[0].content
    assert "apply_patch" in messages[0].content
    assert "git" in messages[0].content
    assert "rg" in messages[0].content
    assert "run_shell_command" in messages[0].content
    assert "run_command only for declared verification commands" in messages[0].content
    assert '"type": "final_response"' in messages[0].content
    assert "Do not use action_type" in messages[0].content
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


def test_provider_messages_include_openai_tool_result_messages() -> None:
    messages = build_provider_messages(
        AgentProviderStepInput(
            problem_statement="inspect",
            verification_commands=[],
            step_index=2,
            remaining_steps=4,
            observations=[
                AgentObservationRecord(
                    tool_invocation=ToolInvocation(
                        id="call_1",
                        name="read_file",
                        args={"path": "README.md"},
                        source="openai_tool_call",
                        group_id="provider-1",
                    ),
                    observation=Observation(
                        status="succeeded",
                        summary="Read README.md",
                        payload={"relative_path": "README.md", "content": "hello"},
                    ),
                )
            ],
        )
    )

    assert messages[-2].role == "assistant"
    assert messages[-2].tool_calls[0].id == "call_1"
    assert messages[-1].role == "tool"
    assert messages[-1].tool_call_id == "call_1"
    assert "Read README.md" in messages[-1].content


def test_provider_messages_group_same_openai_tool_call_batch() -> None:
    messages = build_provider_messages(
        AgentProviderStepInput(
            problem_statement="inspect",
            verification_commands=[],
            step_index=2,
            remaining_steps=4,
            observations=[
                AgentObservationRecord(
                    tool_invocation=ToolInvocation(
                        id="call_1",
                        name="read_file",
                        args={"path": "README.md"},
                        source="openai_tool_call",
                        group_id="provider-1",
                    ),
                    observation=Observation(
                        status="succeeded",
                        summary="Read README.md",
                        payload={"relative_path": "README.md", "content": "hello"},
                    ),
                ),
                AgentObservationRecord(
                    tool_invocation=ToolInvocation(
                        id="call_2",
                        name="list_dir",
                        args={"path": "tests"},
                        source="openai_tool_call",
                        group_id="provider-1",
                    ),
                    observation=Observation(
                        status="succeeded",
                        summary="Listed tests",
                        payload={"relative_path": "tests", "entries": [{"name": "unit"}]},
                    ),
                ),
            ],
        )
    )

    assert messages[-3].role == "assistant"
    assert [tool_call.id for tool_call in messages[-3].tool_calls] == [
        "call_1",
        "call_2",
    ]
    assert [message.role for message in messages[-2:]] == ["tool", "tool"]
    assert [message.tool_call_id for message in messages[-2:]] == ["call_1", "call_2"]
    assert "Read README.md" in messages[-2].content
    assert "Listed tests" in messages[-1].content


def test_provider_messages_skip_tool_result_messages_without_tool_call_id() -> None:
    messages = build_provider_messages(
        AgentProviderStepInput(
            problem_statement="inspect",
            verification_commands=[],
            step_index=2,
            remaining_steps=4,
            observations=[
                AgentObservationRecord(
                    tool_invocation=ToolInvocation(
                        id=None,
                        name="read_file",
                        args={"path": "README.md"},
                        source="openai_tool_call",
                        group_id="provider-1",
                    ),
                    observation=Observation(
                        status="succeeded",
                        summary="Read README.md",
                        payload={"relative_path": "README.md", "content": "hello"},
                    ),
                )
            ],
        )
    )

    assert [message.role for message in messages] == ["system", "user"]


def test_provider_messages_redact_and_truncate_openai_tool_result_content() -> None:
    messages = build_provider_messages(
        AgentProviderStepInput(
            problem_statement="inspect",
            verification_commands=[],
            step_index=2,
            remaining_steps=4,
            observations=[
                AgentObservationRecord(
                    tool_invocation=ToolInvocation(
                        id="call_1",
                        name="read_file",
                        args={"path": "secret.txt"},
                        source="openai_tool_call",
                        group_id="provider-1",
                    ),
                    observation=Observation(
                        status="succeeded",
                        summary="Read secret-token file",
                        payload={
                            "relative_path": "secret.txt",
                            "content": "secret-token " + ("x" * 200),
                        },
                    ),
                )
            ],
        ),
        limits=PromptContextLimits(max_text_chars=40, max_observations=5),
        secret_values=["secret-token"],
    )

    assert messages[-1].role == "tool"
    assert "secret-token" not in messages[-1].content
    assert "[REDACTED]" in messages[-1].content
    assert "...[truncated]" in messages[-1].content
    assert "x" * 80 not in messages[-1].content


def test_provider_messages_dump_openai_tool_message_shapes() -> None:
    messages = build_provider_messages(
        AgentProviderStepInput(
            problem_statement="inspect",
            verification_commands=[],
            step_index=2,
            remaining_steps=4,
            observations=[
                AgentObservationRecord(
                    tool_invocation=ToolInvocation(
                        id="call_1",
                        name="read_file",
                        args={"path": "README.md"},
                        source="openai_tool_call",
                        group_id="provider-1",
                    ),
                    observation=Observation(
                        status="succeeded",
                        summary="Read README.md",
                        payload={"relative_path": "README.md", "content": "hello"},
                    ),
                )
            ],
        )
    )

    assert messages[-2].model_dump(exclude_none=True) == {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path": "README.md"}',
                },
            }
        ],
    }
    assert messages[-1].model_dump(exclude_none=True) == {
        "role": "tool",
        "content": (
            '{"action": null, "action_type": null, "error_message": null, '
            '"payload": {"content": "hello", "relative_path": "README.md"}, '
            '"status": "succeeded", "summary": "Read README.md", "tool_name": null}'
        ),
        "tool_call_id": "call_1",
    }
