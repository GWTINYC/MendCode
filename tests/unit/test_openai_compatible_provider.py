from app.agent.openai_compatible import (
    ChatMessage,
    OpenAIChatCompletionsClient,
    OpenAICompatibleAgentProvider,
    OpenAICompletion,
    OpenAIToolCall,
    redact_secret,
)
from app.agent.provider import AgentObservationRecord, AgentProviderStepInput
from app.schemas.agent_action import Observation, ToolCallAction
from app.tools.registry import default_tool_registry


class FakeClient:
    def __init__(self, response: object | None = None, exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc
        self.calls: list[dict[str, object]] = []

    def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, object]],
        timeout_seconds: int,
    ) -> OpenAICompletion:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.exc is not None:
            raise self.exc
        if isinstance(self.response, OpenAICompletion):
            return self.response
        return OpenAICompletion(content=str(self.response or ""), tool_calls=[])


class ToolsUnsupportedClient:
    def __init__(self, fallback_response: str) -> None:
        self.fallback_response = fallback_response
        self.calls: list[dict[str, object]] = []

    def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        timeout_seconds: int,
        tools: list[dict[str, object]] | None = None,
    ) -> OpenAICompletion | str:
        call: dict[str, object] = {
            "model": model,
            "messages": messages,
            "timeout_seconds": timeout_seconds,
        }
        if tools is not None:
            call["tools"] = tools
        self.calls.append(call)
        if tools is not None:
            raise RuntimeError("Unsupported parameter: tools")
        return self.fallback_response


class FakeSDKFunction:
    def __init__(self, *, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class FakeSDKToolCall:
    def __init__(self, *, id: str, name: str, arguments: str) -> None:
        self.id = id
        self.function = FakeSDKFunction(name=name, arguments=arguments)


class FakeSDKMessage:
    def __init__(self, *, content: str | None, tool_calls: list[FakeSDKToolCall]) -> None:
        self.content = content
        self.tool_calls = tool_calls


class FakeSDKChoice:
    def __init__(self, message: FakeSDKMessage) -> None:
        self.message = message


class FakeSDKResponse:
    def __init__(self, message: FakeSDKMessage) -> None:
        self.choices = [FakeSDKChoice(message)]


class FakeSDKCompletions:
    def __init__(self, response: FakeSDKResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> FakeSDKResponse:
        self.calls.append(kwargs)
        return self.response


class FakeSDKChat:
    def __init__(self, completions: FakeSDKCompletions) -> None:
        self.completions = completions


class FakeSDKClient:
    def __init__(self, response: FakeSDKResponse) -> None:
        self.completions = FakeSDKCompletions(response)
        self.chat = FakeSDKChat(self.completions)


def step_input() -> AgentProviderStepInput:
    return AgentProviderStepInput(
        problem_statement="inspect repo",
        verification_commands=["python -m pytest -q"],
        step_index=1,
        remaining_steps=4,
        observations=[],
    )


def test_openai_compatible_provider_returns_native_invocation_from_fake_client() -> None:
    client = FakeClient(
        OpenAICompletion(
            tool_calls=[
                OpenAIToolCall(
                    id="call-1",
                    name="list_dir",
                    arguments='{"path":"."}',
                )
            ]
        )
    )
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=client,
    )

    response = provider.next_action(step_input())

    assert response.status == "succeeded"
    assert response.tool_invocations[0].name == "list_dir"
    assert response.tool_invocations[0].args == {"path": "."}
    assert client.calls[0]["model"] == "test-model"
    assert client.calls[0]["timeout_seconds"] == 12


def test_openai_compatible_provider_sends_registered_tools_to_client() -> None:
    client = FakeClient('{"type":"tool_call","action":"repo_status","reason":"inspect","args":{}}')
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=client,
    )

    provider.next_action(step_input())

    assert [tool["function"]["name"] for tool in client.calls[0]["tools"]] == [
        *[tool["function"]["name"] for tool in default_tool_registry().openai_tools()],
        "final_response",
    ]


def test_openai_compatible_provider_sends_only_allowed_tools() -> None:
    client = FakeClient(
        OpenAICompletion(
            tool_calls=[
                OpenAIToolCall(
                    id="call-1",
                    name="list_dir",
                    arguments='{"path":"."}',
                )
            ]
        )
    )
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=client,
    )

    response = provider.next_action(
        step_input().model_copy(update={"allowed_tools": {"read_file", "list_dir"}})
    )

    assert response.status == "succeeded"
    assert [tool["function"]["name"] for tool in client.calls[0]["tools"]] == [
        "list_dir",
        "read_file",
        "final_response",
    ]


def test_openai_compatible_provider_always_exposes_final_response_tool() -> None:
    client = FakeClient(
        OpenAICompletion(
            tool_calls=[
                OpenAIToolCall(
                    id="call-final",
                    name="final_response",
                    arguments='{"summary":"最后一句是：不再记录纯讨论、一次性环境噪声、旧路线细枝末节。"}',
                )
            ]
        )
    )
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=client,
    )

    response = provider.next_action(
        step_input().model_copy(update={"allowed_tools": {"read_file", "glob_file_search"}})
    )

    sent_tool_names = [tool["function"]["name"] for tool in client.calls[0]["tools"]]
    assert sent_tool_names == ["glob_file_search", "read_file", "final_response"]
    assert response.status == "succeeded"
    assert response.action == {
        "type": "final_response",
        "status": "completed",
        "summary": "最后一句是：不再记录纯讨论、一次性环境噪声、旧路线细枝末节。",
        "recommended_actions": [],
    }


def test_openai_compatible_provider_strips_think_blocks_from_final_response_tool() -> None:
    action = ToolCallAction(
        type="tool_call",
        action="read_file",
        reason="read document",
        args={"path": "README.md"},
    )
    observation = Observation(
        status="succeeded",
        summary="Read README.md",
        payload={"relative_path": "README.md", "content": "# Demo\n\nHello MendCode.\n"},
    )
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=FakeClient(
            OpenAICompletion(
                tool_calls=[
                    OpenAIToolCall(
                        id="call-final",
                        name="final_response",
                        arguments=(
                            '{"summary":"<think>Need to explain briefly.</think>\\n\\n'
                            'README.md 写了：Hello MendCode."}'
                        ),
                    )
                ]
            )
        ),
    )

    response = provider.next_action(
        AgentProviderStepInput(
            problem_statement="帮我读取 README.md，告诉我里面写了什么",
            verification_commands=[],
            step_index=2,
            remaining_steps=10,
            observations=[AgentObservationRecord(action=action, observation=observation)],
            allowed_tools={"read_file"},
        )
    )

    assert response.status == "succeeded"
    assert response.action is not None
    assert response.action["summary"] == "README.md 写了：Hello MendCode."


def test_openai_compatible_provider_rejects_mixed_final_response_and_tool_call() -> None:
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=FakeClient(
            OpenAICompletion(
                tool_calls=[
                    OpenAIToolCall(
                        id="call-final",
                        name="final_response",
                        arguments='{"summary":"done"}',
                    ),
                    OpenAIToolCall(
                        id="call-read",
                        name="read_file",
                        arguments='{"path":"README.md"}',
                    ),
                ]
            )
        ),
    )

    response = provider.next_action(
        step_input().model_copy(
            update={
                "observations": [
                    AgentObservationRecord(
                        action=ToolCallAction(
                            type="tool_call",
                            action="list_dir",
                            reason="inspect",
                            args={"path": "."},
                        ),
                        observation=Observation(
                            status="succeeded",
                            summary="Listed .",
                            payload={"entries": []},
                        ),
                    )
                ]
            }
        )
    )

    assert response.status == "failed"
    assert response.observation is not None
    assert (
        response.observation.error_message
        == "Provider returned mixed final_response and tool calls"
    )


def test_openai_compatible_provider_rejects_tool_call_outside_allowed_tools() -> None:
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=FakeClient(
            OpenAICompletion(
                tool_calls=[
                    OpenAIToolCall(
                        id="call-1",
                        name="apply_patch",
                        arguments='{"patch":"diff --git a/x b/x"}',
                    )
                ]
            )
        ),
    )

    response = provider.next_action(
        step_input().model_copy(update={"allowed_tools": {"read_file", "list_dir"}})
    )

    assert response.status == "failed"
    assert response.observation is not None
    assert response.observation.error_message == "Provider returned disallowed tool call"


def test_openai_compatible_provider_fails_when_tools_are_unsupported() -> None:
    client = ToolsUnsupportedClient(
        '{"type":"tool_call","action":"repo_status","reason":"inspect","args":{}}'
    )
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=client,
    )

    response = provider.next_action(step_input())

    assert response.status == "failed"
    assert response.observation is not None
    assert "MendCode requires tool calls" in response.observation.error_message
    assert len(client.calls) == 1


def test_openai_compatible_provider_returns_native_tool_invocation() -> None:
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=FakeClient(
            OpenAICompletion(
                tool_calls=[
                    OpenAIToolCall(
                        id="call-1",
                        name="read_file",
                        arguments='{"path":"README.md"}',
                    )
                ]
            )
        ),
    )

    response = provider.next_action(step_input())

    assert response.status == "succeeded"
    assert response.actions == []
    assert len(response.tool_invocations) == 1
    invocation = response.tool_invocations[0]
    assert invocation.id == "call-1"
    assert invocation.name == "read_file"
    assert invocation.args == {"path": "README.md"}
    assert invocation.source == "openai_tool_call"


def test_openai_compatible_provider_rejects_invalid_tool_call_arguments_json() -> None:
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=FakeClient(
            OpenAICompletion(
                tool_calls=[OpenAIToolCall(id="call-1", name="read_file", arguments="{not json")]
            )
        ),
    )

    response = provider.next_action(step_input())

    assert response.status == "failed"
    assert response.observation is not None
    assert response.observation.error_message == "Provider returned invalid tool call arguments"


def test_openai_compatible_provider_rejects_non_object_tool_call_arguments() -> None:
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=FakeClient(
            OpenAICompletion(
                tool_calls=[
                    OpenAIToolCall(
                        id="call-1",
                        name="read_file",
                        arguments='["README.md"]',
                    )
                ]
            )
        ),
    )

    response = provider.next_action(step_input())

    assert response.status == "failed"
    assert response.observation is not None
    assert response.observation.error_message == "Provider returned non-object tool call arguments"


def test_openai_compatible_provider_rejects_unknown_tool_call_name() -> None:
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=FakeClient(
            OpenAICompletion(
                tool_calls=[OpenAIToolCall(id="call-1", name="delete_repo", arguments="{}")]
            )
        ),
    )

    response = provider.next_action(step_input())

    assert response.status == "failed"
    assert response.observation is not None
    assert response.observation.error_message == "Provider returned unknown tool call: delete_repo"


def test_openai_chat_completions_client_returns_text_when_no_tools_requested() -> None:
    sdk_client = FakeSDKClient(FakeSDKResponse(FakeSDKMessage(content="hello", tool_calls=[])))
    client = OpenAIChatCompletionsClient.__new__(OpenAIChatCompletionsClient)
    client._client = sdk_client

    response = client.complete(
        model="test-model",
        messages=[ChatMessage(role="user", content="hello")],
        timeout_seconds=12,
    )

    assert response == "hello"
    assert "tools" not in sdk_client.completions.calls[0]


def test_openai_chat_completions_client_parses_sdk_tool_calls() -> None:
    sdk_client = FakeSDKClient(
        FakeSDKResponse(
            FakeSDKMessage(
                content=None,
                tool_calls=[
                    FakeSDKToolCall(
                        id="call-1",
                        name="read_file",
                        arguments='{"path":"README.md"}',
                    )
                ],
            )
        )
    )
    client = OpenAIChatCompletionsClient.__new__(OpenAIChatCompletionsClient)
    client._client = sdk_client

    response = client.complete(
        model="test-model",
        messages=[ChatMessage(role="user", content="hello")],
        tools=default_tool_registry().openai_tools(),
        timeout_seconds=12,
    )

    assert response == OpenAICompletion(
        content="",
        tool_calls=[
            OpenAIToolCall(
                id="call-1",
                name="read_file",
                arguments='{"path":"README.md"}',
            )
        ],
    )
    assert sdk_client.completions.calls[0]["tools"] == default_tool_registry().openai_tools()


def test_openai_compatible_provider_uses_repair_contract_prompt() -> None:
    client = FakeClient('{"type":"tool_call","action":"repo_status","reason":"inspect","args":{}}')
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=client,
    )

    provider.next_action(step_input())

    messages = client.calls[0]["messages"]
    assert isinstance(messages, list)
    assert "Never claim completed after a failed verification" in messages[0].content
    assert "secret-key" not in "\n".join(message.content for message in messages)


def test_openai_compatible_provider_rejects_plain_text_without_tool_call() -> None:
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=FakeClient("not json"),
    )

    response = provider.next_action(step_input())

    assert response.status == "failed"
    assert response.observation is not None
    assert (
        response.observation.error_message
        == "Provider returned message content instead of a schema tool call"
    )


def test_openai_compatible_provider_rejects_empty_response_without_tool_call() -> None:
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=FakeClient(""),
    )

    response = provider.next_action(step_input())

    assert response.status == "failed"
    assert response.observation is not None
    assert (
        response.observation.error_message
        == "Provider returned message content instead of a schema tool call"
    )


def test_openai_compatible_provider_rejects_text_after_tool_observation() -> None:
    action = ToolCallAction(
        type="tool_call",
        action="read_file",
        reason="read document",
        args={"path": "MendCode_开发方案.md"},
    )
    observation = Observation(
        status="succeeded",
        summary="Read MendCode_开发方案.md",
        payload={"relative_path": "MendCode_开发方案.md", "content": "本文档是当前开发执行方案。"},
    )
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=FakeClient("第一句话是：本文档是当前开发执行方案。"),
    )

    response = provider.next_action(
        AgentProviderStepInput(
            problem_statement="mendcode开发方案的第一句话是什么",
            verification_commands=[],
            step_index=2,
            remaining_steps=4,
            observations=[AgentObservationRecord(action=action, observation=observation)],
        )
    )

    assert response.status == "failed"
    assert response.observation is not None
    assert (
        response.observation.error_message
        == "Provider returned message content instead of a schema tool call"
    )


def test_openai_compatible_provider_rejects_think_block_text_after_tool_observation() -> None:
    action = ToolCallAction(
        type="tool_call",
        action="read_file",
        reason="read document",
        args={"path": "README.md"},
    )
    observation = Observation(
        status="succeeded",
        summary="Read README.md",
        payload={"relative_path": "README.md", "content": "# Demo\n\nHello MendCode.\n"},
    )
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=FakeClient("<think>Need to answer.</think>\n\nREADME.md 写了：Hello MendCode."),
    )

    response = provider.next_action(
        AgentProviderStepInput(
            problem_statement="帮我读取 README.md，告诉我里面写了什么",
            verification_commands=[],
            step_index=2,
            remaining_steps=4,
            observations=[AgentObservationRecord(action=action, observation=observation)],
        )
    )

    assert response.status == "failed"
    assert response.observation is not None
    assert (
        response.observation.error_message
        == "Provider returned message content instead of a schema tool call"
    )


def test_openai_compatible_provider_rejects_json_action_without_tool_call() -> None:
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=FakeClient('{"type":"tool_call","action":"delete_repo"}'),
    )

    response = provider.next_action(step_input())

    assert response.status == "failed"
    assert response.observation is not None
    assert (
        response.observation.error_message
        == "Provider returned message content instead of a schema tool call"
    )


def test_openai_compatible_provider_redacts_api_key_from_client_errors() -> None:
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=FakeClient(exc=RuntimeError("bad secret-key failure")),
    )

    response = provider.next_action(step_input())

    assert response.status == "failed"
    assert response.observation is not None
    assert response.observation.error_message == "Provider request failed: bad [REDACTED] failure"


def test_redact_secret_replaces_secret_value() -> None:
    assert redact_secret("token secret-key leaked", "secret-key") == "token [REDACTED] leaked"
