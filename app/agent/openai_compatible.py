import json
import re
from typing import Protocol, overload

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from app.agent.prompt_context import ChatMessage, build_provider_messages
from app.agent.provider import AgentProviderStepInput, ProviderResponse
from app.schemas.agent_action import parse_mendcode_action
from app.tools.registry import default_tool_registry
from app.tools.structured import ToolInvocation, ToolRegistry


class OpenAIToolCall(BaseModel):
    id: str | None = None
    name: str
    arguments: str = ""


class OpenAICompletion(BaseModel):
    content: str = ""
    tool_calls: list[OpenAIToolCall] = Field(default_factory=list)


class OpenAICompatibleClient(Protocol):
    @overload
    def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        timeout_seconds: int,
    ) -> str:
        ...

    @overload
    def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, object]],
        timeout_seconds: int,
    ) -> OpenAICompletion:
        ...


class OpenAIChatCompletionsClient:
    def __init__(self, *, api_key: str, base_url: str) -> None:
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    @overload
    def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        timeout_seconds: int,
    ) -> str:
        ...

    @overload
    def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, object]],
        timeout_seconds: int,
    ) -> OpenAICompletion:
        ...

    def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, object]] | None = None,
        timeout_seconds: int,
    ) -> str | OpenAICompletion:
        response = self._client.chat.completions.create(
            model=model,
            messages=[message.model_dump(exclude_none=True) for message in messages],
            tools=tools,
            timeout=timeout_seconds,
        )
        message = response.choices[0].message
        if tools is None:
            return message.content or ""
        return OpenAICompletion(
            content=message.content or "",
            tool_calls=[
                OpenAIToolCall(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    arguments=tool_call.function.arguments or "",
                )
                for tool_call in message.tool_calls or []
            ],
        )


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
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = _extract_first_json_object(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("action JSON must be an object")
    return parsed


def _extract_first_json_object(text: str) -> object:
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return parsed
    raise ValueError("no JSON object found")


class OpenAICompatibleAgentProvider:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        timeout_seconds: int,
        client: OpenAICompatibleClient | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._tool_registry = tool_registry or default_tool_registry()
        self._client = client or OpenAIChatCompletionsClient(
            api_key=api_key,
            base_url=base_url,
        )

    def next_action(self, step_input: AgentProviderStepInput) -> ProviderResponse:
        try:
            completion = self._client.complete(
                model=self._model,
                messages=build_provider_messages(step_input, secret_values=[self._api_key]),
                tools=self._tool_registry.openai_tools(),
                timeout_seconds=self._timeout_seconds,
            )
        except Exception as exc:
            return ProviderResponse.failed(
                f"Provider request failed: {redact_secret(str(exc), self._api_key)}"
            )
        if completion.tool_calls:
            tool_invocations: list[ToolInvocation] = []
            for tool_call in completion.tool_calls:
                try:
                    args = json.loads(tool_call.arguments or "{}")
                except json.JSONDecodeError:
                    return ProviderResponse.failed(
                        "Provider returned invalid tool call arguments"
                    )
                if not isinstance(args, dict):
                    return ProviderResponse.failed(
                        "Provider returned non-object tool call arguments"
                    )
                try:
                    self._tool_registry.get(tool_call.name)
                except KeyError:
                    return ProviderResponse.failed("Provider returned unknown tool call")
                try:
                    tool_invocations.append(
                        ToolInvocation(
                            id=tool_call.id,
                            name=tool_call.name,
                            args=args,
                            source="openai_tool_call",
                        )
                    )
                except ValidationError:
                    return ProviderResponse.failed("Provider returned invalid tool call")
            return ProviderResponse(status="succeeded", tool_invocations=tool_invocations)
        content = completion.content
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
