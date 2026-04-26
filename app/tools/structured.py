import re
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.config.settings import Settings
from app.schemas.agent_action import Observation
from app.tools.observations import tool_observation

ToolInvocationSource = Literal["openai_tool_call", "json_action"]
AllowedTools = set[str] | frozenset[str] | list[str] | tuple[str, ...] | None
_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_TOOL_ALIASES: dict[str, tuple[str, ...]] = {
    "status": ("repo_status",),
    "project": ("detect_project",),
    "diff": ("show_diff",),
    "read": ("read_file",),
    "ls": ("list_dir",),
    "list": ("list_dir",),
    "glob": ("glob_file_search",),
    "grep": ("rg", "search_code"),
    "search": ("search_code",),
    "shell": ("run_shell_command",),
    "bash": ("run_shell_command",),
    "patch": ("apply_patch",),
}


def validate_tool_name(name: str) -> str:
    if not _TOOL_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "tool name must contain only letters, digits, underscores, "
            "and dashes, and be 1-64 characters long",
        )
    return name


class ToolRisk(StrEnum):
    READ_ONLY = "read_only"
    WRITE_WORKTREE = "write_worktree"
    SHELL_RESTRICTED = "shell_restricted"
    DANGEROUS = "dangerous"


class ToolInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    source: ToolInvocationSource
    group_id: str | None = None

    @model_validator(mode="after")
    def validate_name(self) -> "ToolInvocation":
        validate_tool_name(self.name)
        return self


class ToolExecutionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    workspace_path: Path
    settings: Settings
    verification_commands: list[str] = Field(default_factory=list)


ToolExecutor = Callable[[BaseModel, ToolExecutionContext], Observation]


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    name: str
    description: str
    args_model: type[BaseModel]
    risk_level: ToolRisk
    executor: ToolExecutor

    @model_validator(mode="after")
    def validate_spec(self) -> "ToolSpec":
        validate_tool_name(self.name)
        if not self.description.strip():
            raise ValueError("tool description must not be empty")
        return self

    def execute(self, args: dict[str, Any], context: ToolExecutionContext) -> Observation:
        try:
            parsed_args = self.args_model.model_validate(args)
        except ValidationError as exc:
            return tool_observation(
                tool_name=self.name,
                status="rejected",
                summary="Invalid tool arguments",
                payload={"args": args},
                error_message=str(exc),
            )
        return self.executor(parsed_args, context)

    def to_openai_tool(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec] | None = None) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"duplicate tool name: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def _normalize_allowed_tools(self, allowed_tools: AllowedTools = None) -> set[str] | None:
        if allowed_tools is None:
            return None
        normalized: set[str] = set()
        for raw_name in allowed_tools:
            validate_tool_name(raw_name)
            expanded_names = _TOOL_ALIASES.get(raw_name, (raw_name,))
            for name in expanded_names:
                if name not in self._specs:
                    raise KeyError(f"unknown allowed tool: {raw_name}")
                normalized.add(name)
        return normalized

    def names(self, allowed_tools: AllowedTools = None) -> list[str]:
        normalized = self._normalize_allowed_tools(allowed_tools)
        if normalized is None:
            return sorted(self._specs)
        return sorted(normalized)

    def openai_tools(self, allowed_tools: AllowedTools = None) -> list[dict[str, object]]:
        return [
            self._specs[name].to_openai_tool()
            for name in self.names(allowed_tools=allowed_tools)
        ]
