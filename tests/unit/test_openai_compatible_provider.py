from app.agent.openai_compatible import (
    ChatMessage,
    OpenAICompatibleAgentProvider,
    extract_action_json,
    redact_secret,
)
from app.agent.provider import AgentProviderStepInput


class FakeClient:
    def __init__(self, response: str | None = None, exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc
        self.calls: list[dict[str, object]] = []

    def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        timeout_seconds: int,
    ) -> str:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.exc is not None:
            raise self.exc
        return self.response or ""


def step_input() -> AgentProviderStepInput:
    return AgentProviderStepInput(
        problem_statement="inspect repo",
        verification_commands=["python -m pytest -q"],
        step_index=1,
        remaining_steps=4,
        observations=[],
    )


def test_extract_action_json_accepts_plain_object() -> None:
    text = '{"type":"tool_call","action":"repo_status","reason":"inspect","args":{}}'

    assert extract_action_json(text) == {
        "type": "tool_call",
        "action": "repo_status",
        "reason": "inspect",
        "args": {},
    }


def test_extract_action_json_accepts_single_json_fence() -> None:
    text = '```json\n{"type":"final_response","status":"completed","summary":"done"}\n```'

    assert extract_action_json(text) == {
        "type": "final_response",
        "status": "completed",
        "summary": "done",
    }


def test_openai_compatible_provider_returns_action_from_fake_client() -> None:
    client = FakeClient(
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

    assert response.status == "succeeded"
    assert response.action == {
        "type": "tool_call",
        "action": "repo_status",
        "reason": "inspect",
        "args": {},
    }
    assert client.calls[0]["model"] == "test-model"
    assert client.calls[0]["timeout_seconds"] == 12


def test_openai_compatible_provider_uses_repair_contract_prompt() -> None:
    client = FakeClient(
        '{"type":"tool_call","action":"repo_status","reason":"inspect","args":{}}'
    )
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


def test_openai_compatible_provider_rejects_empty_response() -> None:
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
    assert response.observation.error_message == "Provider returned empty response"


def test_openai_compatible_provider_rejects_invalid_json() -> None:
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
    assert response.observation.error_message == "Provider returned invalid JSON action"


def test_openai_compatible_provider_rejects_invalid_action_schema() -> None:
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
    assert response.observation.error_message == "Provider returned invalid MendCode action"


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
