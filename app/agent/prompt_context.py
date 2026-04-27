import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent.provider import AgentObservationRecord, AgentProviderStepInput
from app.tools.registry import default_tool_registry
from app.tools.structured import ToolInvocation


class ChatToolFunction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: str


class ChatToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str = "function"
    function: ChatToolFunction


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    content: str | None = None
    tool_calls: list[ChatToolCall] | None = None
    tool_call_id: str | None = None


class PromptContextLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_text_chars: int = Field(default=2000, ge=1)
    max_observations: int = Field(default=12, ge=1)
    max_search_matches: int = Field(default=8, ge=0)


def _redact_text(value: str, secret_values: list[str]) -> str:
    redacted = value
    for secret in secret_values:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _trim_text(value: object, *, limits: PromptContextLimits, secret_values: list[str]) -> str:
    text = _redact_text(str(value), secret_values)
    if len(text) <= limits.max_text_chars:
        return text
    return text[: limits.max_text_chars] + "...[truncated]"


def _selected_payload(
    payload: dict[str, Any],
    *,
    limits: PromptContextLimits,
    secret_values: list[str],
) -> dict[str, object]:
    selected: dict[str, object] = {}
    for key in [
        "command",
        "status",
        "exit_code",
        "relative_path",
        "file_path",
        "failed_node",
        "test_name",
        "stderr_excerpt",
        "stdout_excerpt",
        "error_summary",
        "diff_stat",
        "content",
        "truncated",
        "pattern",
        "total_entries",
        "total_matches",
    ]:
        if key in payload:
            selected[key] = _trim_text(
                payload[key],
                limits=limits,
                secret_values=secret_values,
            )
    entries = payload.get("entries")
    if isinstance(entries, list):
        entry_limit = (
            len(entries) if payload.get("truncated") is False else limits.max_search_matches
        )
        selected["entries"] = [
            {
                str(entry_key): _trim_text(
                    entry_value,
                    limits=limits,
                    secret_values=secret_values,
                )
                for entry_key, entry_value in entry.items()
            }
            for entry in entries[:entry_limit]
            if isinstance(entry, dict)
        ]
        selected["entries_truncated"] = len(entries) > entry_limit
    matches = payload.get("matches")
    if isinstance(matches, list):
        selected["matches"] = [
            {
                str(match_key): _trim_text(
                    match_value,
                    limits=limits,
                    secret_values=secret_values,
                )
                for match_key, match_value in match.items()
            }
            for match in matches[: limits.max_search_matches]
            if isinstance(match, dict)
        ]
        selected["matches_truncated"] = len(matches) > limits.max_search_matches
    return selected


def summarize_observation_record(
    record: AgentObservationRecord,
    *,
    limits: PromptContextLimits,
    secret_values: list[str],
    include_action: bool = True,
) -> dict[str, object]:
    action = record.action
    action_payload: dict[str, object] | None = None
    if action is not None:
        action_payload = action.model_dump(mode="json")
    observation = record.observation
    tool_invocation_name = (
        record.tool_invocation.name if record.tool_invocation is not None else None
    )
    summary: dict[str, object] = {
        "tool_name": (
            getattr(action, "action", None) if action is not None else tool_invocation_name
        ),
        "status": observation.status,
        "summary": _trim_text(
            observation.summary,
            limits=limits,
            secret_values=secret_values,
        ),
        "error_message": (
            _trim_text(
                observation.error_message,
                limits=limits,
                secret_values=secret_values,
            )
            if observation.error_message is not None
            else None
        ),
        "payload": _selected_payload(
            observation.payload,
            limits=limits,
            secret_values=secret_values,
        ),
    }
    if include_action:
        summary["action_type"] = action.type if action is not None else None
        summary["action"] = action_payload
    return summary


def _without_none_values(payload: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in payload.items() if value is not None}


def _is_native_tool_result_record(record: AgentObservationRecord) -> bool:
    invocation = record.tool_invocation
    return (
        invocation is not None
        and invocation.id is not None
        and invocation.source == "openai_tool_call"
    )


def _tool_result_content(
    record: AgentObservationRecord,
    *,
    limits: PromptContextLimits,
    secret_values: list[str],
) -> str:
    return json.dumps(
        _without_none_values(
            summarize_observation_record(
                record,
                limits=limits,
                secret_values=secret_values,
                include_action=False,
            )
        ),
        ensure_ascii=False,
        sort_keys=True,
    )


def _tool_call_message(invocation: ToolInvocation) -> ChatToolCall:
    if invocation.id is None:
        raise ValueError("tool invocation id is required")
    return ChatToolCall(
        id=invocation.id,
        function=ChatToolFunction(
            name=invocation.name,
            arguments=json.dumps(invocation.args, ensure_ascii=False, sort_keys=True),
        ),
    )


def _native_tool_result_messages(
    records: list[AgentObservationRecord],
    *,
    limits: PromptContextLimits,
    secret_values: list[str],
) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    current_group_id: str | None = None
    current_records: list[AgentObservationRecord] = []

    def flush_group() -> None:
        if not current_records:
            return
        messages.append(
            ChatMessage(
                role="assistant",
                tool_calls=[
                    _tool_call_message(record.tool_invocation)
                    for record in current_records
                    if record.tool_invocation is not None
                ],
            )
        )
        for record in current_records:
            invocation = record.tool_invocation
            if invocation is None or invocation.id is None:
                continue
            messages.append(
                ChatMessage(
                    role="tool",
                    tool_call_id=invocation.id,
                    content=_tool_result_content(
                        record,
                        limits=limits,
                        secret_values=secret_values,
                    ),
                )
            )

    for record in records:
        invocation = record.tool_invocation
        if invocation is None or invocation.id is None or invocation.source != "openai_tool_call":
            flush_group()
            current_group_id = None
            current_records = []
            continue
        group_id = invocation.group_id or invocation.id
        if current_records and group_id != current_group_id:
            flush_group()
            current_records = []
        current_group_id = group_id
        current_records.append(record)

    flush_group()
    return messages


def _system_prompt(allowed_tools: set[str] | None = None) -> str:
    registry = default_tool_registry()
    tool_names = registry.names(allowed_tools=allowed_tools)
    scoped_prompt = allowed_tools is not None
    text = (
        "You are MendCode's action planner. Use native tool calls when tools are available. "
        "Return JSON only when no native tool call is needed, such as final_response or "
        "a patch_proposal fallback. The JSON object must be a valid MendCodeAction.\n"
        "Allowed action types: assistant_message, tool_call, patch_proposal, "
        "user_confirmation_request, final_response.\n"
        f"Allowed native tools in this turn: {', '.join(tool_names)}.\n"
    )
    if not scoped_prompt:
        json_tool_actions = [*tool_names, "apply_patch_to_worktree"]
        text += "Allowed JSON tool actions: " + ", ".join(dict.fromkeys(json_tool_actions)) + ".\n"
    text += (
        "Use the discriminator field named type. Do not use action_type. Examples: "
        '{"type": "tool_call", "action": "repo_status", "reason": "inspect", "args": {}}; '
        '{"type": "final_response", "status": "completed", "summary": "verified", '
        '"recommended_actions": []}.\n'
        "Prefer structured tools over raw shell: use read_file for file content, "
        "list_dir for directory inspection, glob_file_search for path discovery, rg or "
        "search_code for text search, git for repository inspection, write_file or "
        "edit_file for workspace edits, todo_write for short task tracking, and "
        "tool_search when tool capabilities are unclear."
    )
    if "read_file" in tool_names:
        text += (
            " For questions about the final line, last sentence, or end of a file, "
            "call read_file with tail_lines instead of guessing line numbers."
        )
    if "apply_patch" in tool_names:
        text += " Use apply_patch for unified diffs."
    if "run_shell_command" in tool_names:
        text += " Use run_shell_command only when no structured tool fits."
    if "run_command" in tool_names:
        text += (
            " Use run_command only for declared verification commands from verification_commands."
        )
    text += (
        "\n"
        "When list_dir returns truncated=false, the listed entries are complete; do not "
        "repeat list_dir for the same path with a larger max_entries. When the "
        "observations answer the user, return a final_response JSON instead of making "
        "more tool calls.\n"
    )
    if not scoped_prompt or {"run_command", "apply_patch"}.intersection(tool_names):
        text += (
            "Repair workflow: inspect repo status and project type if unknown; run or inspect "
            "verification failure; read failing test files; search candidate implementation; "
            "propose a unified diff patch with patch_proposal; rerun verification; show_diff; "
            "then return final_response.\n"
        )
    text += (
        'Never claim completed after a failed verification. Use "status": "failed" when '
        "the repair is not verified or the step budget is low."
    )
    return text


def build_provider_messages(
    step_input: AgentProviderStepInput,
    *,
    limits: PromptContextLimits | None = None,
    secret_values: list[str] | None = None,
) -> list[ChatMessage]:
    context_limits = limits or PromptContextLimits()
    secrets = secret_values or []
    recent_records = step_input.observations[-context_limits.max_observations :]
    user_context_records = [
        record for record in recent_records if not _is_native_tool_result_record(record)
    ]
    observations = [
        summarize_observation_record(
            record,
            limits=context_limits,
            secret_values=secrets,
        )
        for record in user_context_records
    ]
    user_context = {
        "problem_statement": _trim_text(
            step_input.problem_statement,
            limits=context_limits,
            secret_values=secrets,
        ),
        "verification_commands": [
            _trim_text(command, limits=context_limits, secret_values=secrets)
            for command in step_input.verification_commands
        ],
        "step_index": step_input.step_index,
        "remaining_steps": step_input.remaining_steps,
        "observations": observations,
    }
    messages = [
        ChatMessage(role="system", content=_system_prompt(step_input.allowed_tools)),
        ChatMessage(
            role="user",
            content=json.dumps(user_context, ensure_ascii=False, sort_keys=True),
        ),
    ]
    messages.extend(
        _native_tool_result_messages(
            recent_records,
            limits=context_limits,
            secret_values=secrets,
        )
    )
    return messages
