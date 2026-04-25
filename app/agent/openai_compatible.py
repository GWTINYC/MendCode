import json
import re
from typing import Protocol

from openai import OpenAI
from pydantic import ValidationError

from app.agent.prompt_context import ChatMessage, build_provider_messages
from app.agent.provider import AgentProviderStepInput, ProviderResponse
from app.schemas.agent_action import parse_mendcode_action


class OpenAICompatibleClient(Protocol):
    def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        timeout_seconds: int,
    ) -> str:
        ...


class OpenAIChatCompletionsClient:
    def __init__(self, *, api_key: str, base_url: str) -> None:
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        timeout_seconds: int,
    ) -> str:
        response = self._client.chat.completions.create(
            model=model,
            messages=[message.model_dump() for message in messages],
            timeout=timeout_seconds,
        )
        content = response.choices[0].message.content
        return content or ""


_JSON_FENCE = re.compile(r"^```(?:json)?\s*(?P<body>.*?)\s*```$", re.DOTALL)


def redact_secret(message: str, secret: str | None) -> str:
    if not secret:
        return message
    return message.replace(secret, "[REDACTED]")


def extract_action_json(text: str) -> dict[str, object]:
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty response")
    fence_match = _JSON_FENCE.match(stripped)
    if fence_match is not None:
        stripped = fence_match.group("body").strip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("action JSON must be an object")
    return parsed


class OpenAICompatibleAgentProvider:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        timeout_seconds: int,
        client: OpenAICompatibleClient | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._client = client or OpenAIChatCompletionsClient(
            api_key=api_key,
            base_url=base_url,
        )

    def next_action(self, step_input: AgentProviderStepInput) -> ProviderResponse:
        try:
            content = self._client.complete(
                model=self._model,
                messages=build_provider_messages(step_input, secret_values=[self._api_key]),
                timeout_seconds=self._timeout_seconds,
            )
        except Exception as exc:
            return ProviderResponse.failed(
                f"Provider request failed: {redact_secret(str(exc), self._api_key)}"
            )
        if not content.strip():
            return ProviderResponse.failed("Provider returned empty response")
        try:
            payload = extract_action_json(content)
        except (json.JSONDecodeError, ValueError):
            return ProviderResponse.failed("Provider returned invalid JSON action")
        try:
            parse_mendcode_action(payload)
        except ValidationError:
            return ProviderResponse.failed("Provider returned invalid MendCode action")
        return ProviderResponse(status="succeeded", actions=[payload])
