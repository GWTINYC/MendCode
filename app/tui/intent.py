from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from app.agent.openai_compatible import (
    OpenAIChatCompletionsClient,
    OpenAICompatibleClient,
)
from app.agent.prompt_context import ChatMessage
from app.agent.provider_factory import ProviderConfigurationError
from app.config.settings import Settings

IntentKind = Literal["chat", "fix"]

FIX_INTENT_TERMS = (
    "fix",
    "repair",
    "resolve",
    "make tests pass",
    "failed",
    "failing",
    "bug",
    "error",
    "修复",
    "解决",
    "改一下",
    "修改",
    "失败",
    "报错",
)


@dataclass(frozen=True)
class IntentContext:
    repo_path: Path
    verification_command: str | None = None


@dataclass(frozen=True)
class IntentDecision:
    kind: IntentKind
    source: str = "rule"


class IntentRouter(Protocol):
    def route(self, message: str, context: IntentContext) -> IntentDecision:
        ...


class RuleBasedIntentRouter:
    def route(self, message: str, context: IntentContext) -> IntentDecision:
        if looks_like_fix_request(message):
            return IntentDecision(kind="fix", source="rule")
        return IntentDecision(kind="chat", source="rule")


class OpenAICompatibleIntentRouter:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        timeout_seconds: int,
        client: OpenAICompatibleClient,
    ) -> None:
        self._rule_router = RuleBasedIntentRouter()
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client = client

    def route(self, message: str, context: IntentContext) -> IntentDecision:
        rule_decision = self._rule_router.route(message, context)
        if rule_decision.kind == "fix":
            return rule_decision

        try:
            content = self._client.complete(
                model=self._model,
                messages=_build_intent_messages(message=message, context=context),
                timeout_seconds=self._timeout_seconds,
            )
        except Exception:
            return IntentDecision(kind="chat", source="model_fallback")

        normalized = content.strip().lower()
        if normalized.startswith("fix"):
            return IntentDecision(kind="fix", source="model")
        return IntentDecision(kind="chat", source="model")


def looks_like_fix_request(message: str) -> bool:
    normalized = message.strip().lower()
    return any(term in normalized for term in FIX_INTENT_TERMS)


def _build_intent_messages(*, message: str, context: IntentContext) -> list[ChatMessage]:
    verification = context.verification_command or "not set"
    return [
        ChatMessage(
            role="system",
            content=(
                "Classify the user's message for MendCode. Return exactly one word: "
                "fix or chat. Return fix only when the user wants code changes, "
                "debugging, tests fixed, or command-driven repair. Return chat for "
                "questions, explanations, thanks, or general discussion.\n"
                f"repo_path: {context.repo_path}\n"
                f"verification_command: {verification}"
            ),
        ),
        ChatMessage(role="user", content=message),
    ]


def build_intent_router(settings: Settings) -> IntentRouter:
    if settings.provider == "scripted":
        return RuleBasedIntentRouter()
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
        return OpenAICompatibleIntentRouter(
            model=settings.provider_model,
            api_key=settings.provider_api_key,
            timeout_seconds=settings.provider_timeout_seconds,
            client=OpenAIChatCompletionsClient(
                api_key=settings.provider_api_key,
                base_url=settings.provider_base_url,
            ),
        )
    raise ProviderConfigurationError(f"unsupported provider: {settings.provider}")
