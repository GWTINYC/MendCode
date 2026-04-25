from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.agent.openai_compatible import (
    OpenAIChatCompletionsClient,
    OpenAICompatibleClient,
    redact_secret,
)
from app.agent.prompt_context import ChatMessage
from app.agent.provider_factory import ProviderConfigurationError
from app.config.settings import Settings


@dataclass(frozen=True)
class ChatContext:
    repo_path: Path
    verification_command: str | None
    history: list[ChatMessage]
    last_turn_status: str | None = None


@dataclass(frozen=True)
class ChatResponse:
    content: str


class ChatResponder(Protocol):
    def respond(self, message: str, context: ChatContext) -> ChatResponse:
        ...


class ScriptedChatResponder:
    def respond(self, message: str, context: ChatContext) -> ChatResponse:
        verification = context.verification_command or "not set"
        return ChatResponse(
            content=(
                "I am MendCode, a local code-agent chat shell. I can discuss the repo "
                "and answer questions here. To run tools for a repair, set "
                f"`/test <command>` and use `/fix <problem>`. Current verification command: "
                f"{verification}."
            )
        )


class OpenAICompatibleChatResponder:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        timeout_seconds: int,
        client: OpenAICompatibleClient,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._client = client

    def respond(self, message: str, context: ChatContext) -> ChatResponse:
        messages = _build_chat_messages(message=message, context=context)
        try:
            content = self._client.complete(
                model=self._model,
                messages=messages,
                timeout_seconds=self._timeout_seconds,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Provider request failed: {redact_secret(str(exc), self._api_key)}"
            ) from exc
        if not content.strip():
            raise RuntimeError("Provider returned empty chat response")
        return ChatResponse(content=content.strip())


def _build_chat_messages(*, message: str, context: ChatContext) -> list[ChatMessage]:
    verification = context.verification_command or "not set"
    last_turn_status = context.last_turn_status or "none"
    system_prompt = (
        "You are MendCode, a terminal code-agent workbench with general conversation "
        "and tool-calling workflows. In this chat mode, answer normally and concisely. "
        "Do not claim you ran tools, edited files, or verified code unless the supplied "
        "conversation context says so. If the user wants code changes or command execution, "
        "explain that they can use /test <command> and /fix <problem> to start the tool "
        "workflow.\n"
        f"repo_path: {context.repo_path}\n"
        f"verification_command: {verification}\n"
        f"last_turn_status: {last_turn_status}"
    )
    return [
        ChatMessage(role="system", content=system_prompt),
        *context.history[-12:],
        ChatMessage(role="user", content=message),
    ]


def build_chat_responder(settings: Settings) -> ChatResponder:
    if settings.provider == "scripted":
        return ScriptedChatResponder()
    if settings.provider in {"openai-compatible", "minimax"}:
        if (
            not settings.provider_model
            or not settings.provider_base_url
            or not settings.provider_api_key
        ):
            raise ProviderConfigurationError(
                "openai-compatible provider requires MENDCODE_MODEL, "
                "MENDCODE_BASE_URL, and MENDCODE_API_KEY"
            )
        return OpenAICompatibleChatResponder(
            model=settings.provider_model,
            api_key=settings.provider_api_key,
            timeout_seconds=settings.provider_timeout_seconds,
            client=OpenAIChatCompletionsClient(
                api_key=settings.provider_api_key,
                base_url=settings.provider_base_url,
            ),
        )
    raise ProviderConfigurationError(f"unsupported provider: {settings.provider}")
