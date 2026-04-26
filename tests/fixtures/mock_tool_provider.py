from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from app.agent.provider import AgentProviderStepInput, ProviderResponse
from app.schemas.agent_action import FinalResponseStatus
from app.tools.structured import ToolInvocation

StepAssertion = Callable[[AgentProviderStepInput], None]


@dataclass(frozen=True)
class ScriptedToolStep:
    response: ProviderResponse
    expected_allowed_tools: set[str] | None = None
    expected_observation_count: int | None = None
    assertions: tuple[StepAssertion, ...] = field(default_factory=tuple)


class MockToolProvider:
    def __init__(self, steps: list[ScriptedToolStep]) -> None:
        self.steps = steps
        self.calls: list[AgentProviderStepInput] = []

    def next_action(self, step_input: AgentProviderStepInput) -> ProviderResponse:
        self.calls.append(step_input)
        index = len(self.calls) - 1
        if index >= len(self.steps):
            raise AssertionError(f"provider called more than scripted steps: {len(self.calls)}")

        step = self.steps[index]
        if step.expected_allowed_tools is not None:
            assert step_input.allowed_tools == step.expected_allowed_tools
        if step.expected_observation_count is not None:
            assert len(step_input.observations) == step.expected_observation_count
        for assertion in step.assertions:
            assertion(step_input)
        return step.response


def tool_call_step(
    *invocations: ToolInvocation,
    expected_allowed_tools: set[str] | None = None,
    expected_observation_count: int | None = None,
    assertions: tuple[StepAssertion, ...] = (),
) -> ScriptedToolStep:
    return ScriptedToolStep(
        response=ProviderResponse(status="succeeded", tool_invocations=list(invocations)),
        expected_allowed_tools=expected_allowed_tools,
        expected_observation_count=expected_observation_count,
        assertions=assertions,
    )


def final_response_step(
    summary: str,
    *,
    status: FinalResponseStatus = "completed",
    expected_observation_count: int | None = None,
    assertions: tuple[StepAssertion, ...] = (),
) -> ScriptedToolStep:
    return ScriptedToolStep(
        response=ProviderResponse(
            status="succeeded",
            actions=[
                {
                    "type": "final_response",
                    "status": status,
                    "summary": summary,
                }
            ],
        ),
        expected_observation_count=expected_observation_count,
        assertions=assertions,
    )


def native_tool(
    name: str,
    args: dict[str, object] | None = None,
    *,
    call_id: str = "call_1",
) -> ToolInvocation:
    return ToolInvocation(
        id=call_id,
        name=name,
        args=args or {},
        source="openai_tool_call",
    )


def assert_last_observation(
    *,
    tool_name: str,
    status: Literal["succeeded", "failed", "rejected"] = "succeeded",
) -> StepAssertion:
    def _assert(step_input: AgentProviderStepInput) -> None:
        assert step_input.observations
        record = step_input.observations[-1]
        assert record.tool_invocation is not None
        assert record.tool_invocation.name == tool_name
        assert record.observation.status == status
        assert record.observation.payload["tool_name"] == tool_name
        assert record.observation.payload["status"] == status

    return _assert


def assert_payload_contains(key: str, expected: object) -> StepAssertion:
    def _assert(step_input: AgentProviderStepInput) -> None:
        payload = step_input.observations[-1].observation.payload
        assert payload.get(key) == expected or payload.get("payload", {}).get(key) == expected

    return _assert
