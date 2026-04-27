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

_FINAL_RESPONSE_TOOL_NAME = "final_response"
_FINAL_RESPONSE_TOOL: dict[str, object] = {
    "type": "function",
    "function": {
        "name": _FINAL_RESPONSE_TOOL_NAME,
        "description": (
            "Return the final user-facing answer after the available observations "
            "already answer the request. Do not call this together with other tools."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["completed", "failed", "needs_user_confirmation"],
                    "description": "Final response status. Omit when observations are enough.",
                },
                "summary": {
                    "type": "string",
                    "description": "Concise final answer to show the user.",
                },
                "recommended_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional follow-up actions.",
                },
            },
            "required": ["summary"],
            "additionalProperties": False,
        },
    },
}


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
    ) -> str: ...

    @overload
    def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, object]],
        timeout_seconds: int,
    ) -> OpenAICompletion: ...


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
    ) -> str: ...

    @overload
    def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, object]],
        timeout_seconds: int,
    ) -> OpenAICompletion: ...

    def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, object]] | None = None,
        timeout_seconds: int,
    ) -> str | OpenAICompletion:
        request_kwargs: dict[str, object] = {
            "model": model,
            "messages": [message.model_dump(exclude_none=True) for message in messages],
            "timeout": timeout_seconds,
        }
        if tools is not None:
            request_kwargs["tools"] = tools
        response = self._client.chat.completions.create(**request_kwargs)
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


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def redact_secret(message: str, secret: str | None) -> str:
    if not secret:
        return message
    return message.replace(secret, "[REDACTED]")


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
        messages = build_provider_messages(step_input, secret_values=[self._api_key])
        try:
            tool_pool = self._tool_registry.tool_pool(
                permission_mode=step_input.permission_mode,
                allowed_tools=step_input.allowed_tools,
            )
            openai_tools = tool_pool.openai_tools()
            allowed_tool_names = set(tool_pool.names())
            openai_tools = [*openai_tools, _FINAL_RESPONSE_TOOL]
        except KeyError as exc:
            return ProviderResponse.failed(str(exc.args[0]))
        try:
            completion = self._client.complete(
                model=self._model,
                messages=messages,
                tools=openai_tools,
                timeout_seconds=self._timeout_seconds,
            )
        except Exception as exc:
            if _looks_like_unsupported_tools_error(exc):
                return ProviderResponse.failed(
                    "MendCode requires tool calls, but the configured provider "
                    f"rejected tools: {redact_secret(str(exc), self._api_key)}"
                )
            return ProviderResponse.failed(
                f"Provider request failed: {redact_secret(str(exc), self._api_key)}"
            )
        if completion.tool_calls:
            return _response_from_tool_calls(
                completion.tool_calls,
                tool_registry=self._tool_registry,
                allowed_tool_names=allowed_tool_names,
                text_final_status=_text_final_status(step_input),
            )
        return ProviderResponse.failed("Provider did not return a schema tool call")


def _looks_like_unsupported_tools_error(exc: Exception) -> bool:
    message = str(exc).lower()
    if "tool" not in message:
        return False
    unsupported_markers = (
        "unsupported parameter",
        "unknown parameter",
        "unrecognized request argument",
        "not support",
        "not supported",
        "does not support",
    )
    return any(marker in message for marker in unsupported_markers)


def _text_final_status(step_input: AgentProviderStepInput) -> str | None:
    if not step_input.observations:
        return None
    if all(record.observation.status == "succeeded" for record in step_input.observations):
        return "completed"
    return "failed"


def _parse_tool_call_arguments(tool_call: OpenAIToolCall) -> dict[str, object] | ProviderResponse:
    try:
        args = json.loads(tool_call.arguments or "{}")
    except json.JSONDecodeError:
        return ProviderResponse.failed("Provider returned invalid tool call arguments")
    if not isinstance(args, dict):
        return ProviderResponse.failed("Provider returned non-object tool call arguments")
    return args


def _response_from_final_response_tool_call(
    args: dict[str, object],
    *,
    text_final_status: str | None,
) -> ProviderResponse:
    payload = dict(args)
    payload["type"] = "final_response"
    if isinstance(payload.get("summary"), str):
        payload["summary"] = _strip_think_blocks(str(payload["summary"]))
    if payload.get("status") is None:
        payload["status"] = text_final_status or "completed"
    if payload.get("recommended_actions") is None:
        payload["recommended_actions"] = []
    try:
        parse_mendcode_action(payload)
    except ValidationError:
        return ProviderResponse.failed("Provider returned invalid final_response tool call")
    return ProviderResponse(status="succeeded", actions=[payload])


def _response_from_tool_calls(
    tool_calls: list[OpenAIToolCall],
    *,
    tool_registry: ToolRegistry,
    allowed_tool_names: set[str],
    text_final_status: str | None,
) -> ProviderResponse:
    parsed_calls: list[tuple[OpenAIToolCall, dict[str, object]]] = []
    for tool_call in tool_calls:
        parsed_args = _parse_tool_call_arguments(tool_call)
        if isinstance(parsed_args, ProviderResponse):
            return parsed_args
        parsed_calls.append((tool_call, parsed_args))

    final_response_calls = [
        (tool_call, args)
        for tool_call, args in parsed_calls
        if tool_call.name == _FINAL_RESPONSE_TOOL_NAME
    ]
    if final_response_calls:
        if len(parsed_calls) != 1:
            return ProviderResponse.failed("Provider returned mixed final_response and tool calls")
        _, args = final_response_calls[0]
        return _response_from_final_response_tool_call(
            args,
            text_final_status=text_final_status,
        )

    tool_invocations: list[ToolInvocation] = []
    for tool_call, args in parsed_calls:
        try:
            tool_registry.get(tool_call.name)
        except KeyError:
            return ProviderResponse.failed(f"Provider returned unknown tool call: {tool_call.name}")
        if tool_call.name not in allowed_tool_names:
            return ProviderResponse.failed("Provider returned disallowed tool call")
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


def _strip_think_blocks(text: str) -> str:
    return _THINK_BLOCK.sub("", text).strip()
