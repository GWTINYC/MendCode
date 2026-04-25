from pathlib import Path

from app.agent.openai_compatible import ChatMessage
from app.config.settings import Settings
from app.tui.chat import (
    ChatContext,
    OpenAICompatibleChatResponder,
    ScriptedChatResponder,
    build_chat_responder,
)


class FakeClient:
    def __init__(self, response: str) -> None:
        self.response = response
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
        return self.response


def make_settings(tmp_path: Path, provider: str = "scripted") -> Settings:
    return Settings(
        app_name="MendCode",
        app_version="0.0.0",
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        traces_dir=tmp_path / "data" / "traces",
        workspace_root=tmp_path / ".worktrees",
        verification_timeout_seconds=60,
        cleanup_success_workspace=False,
        provider=provider,  # type: ignore[arg-type]
        provider_model="test-model" if provider != "scripted" else None,
        provider_base_url="https://example.test/v1" if provider != "scripted" else None,
        provider_api_key="secret-key" if provider != "scripted" else None,
        provider_timeout_seconds=12,
    )


def test_scripted_chat_responder_answers_without_tools(tmp_path: Path) -> None:
    responder = ScriptedChatResponder()

    response = responder.respond(
        "what can you do?",
        ChatContext(repo_path=tmp_path, verification_command=None, history=[]),
    )

    assert "MendCode" in response.content
    assert "/fix" in response.content


def test_openai_compatible_chat_responder_sends_conversation_prompt(tmp_path: Path) -> None:
    client = FakeClient("I can answer and help with code tasks.")
    responder = OpenAICompatibleChatResponder(
        model="test-model",
        api_key="secret-key",
        timeout_seconds=12,
        client=client,
    )

    response = responder.respond(
        "hello",
        ChatContext(
            repo_path=tmp_path,
            verification_command="python -m pytest -q",
            history=[ChatMessage(role="assistant", content="previous answer")],
        ),
    )

    assert response.content == "I can answer and help with code tasks."
    assert client.calls[0]["model"] == "test-model"
    assert client.calls[0]["timeout_seconds"] == 12
    messages = client.calls[0]["messages"]
    assert isinstance(messages, list)
    assert "general conversation" in messages[0].content
    assert "python -m pytest -q" in messages[0].content
    assert messages[-1] == ChatMessage(role="user", content="hello")


def test_build_chat_responder_uses_scripted_responder_for_scripted_provider(tmp_path: Path) -> None:
    responder = build_chat_responder(make_settings(tmp_path))

    assert isinstance(responder, ScriptedChatResponder)
