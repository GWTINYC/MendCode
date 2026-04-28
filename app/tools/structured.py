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
    "write": ("write_file",),
    "edit": ("edit_file",),
    "todo": ("todo_write",),
    "tools": ("tool_search",),
    "memory": (
        "memory_search",
        "memory_write",
        "file_summary_read",
        "file_summary_refresh",
        "trace_analyze",
    ),
    "fs_read": ("read_file", "list_dir", "glob_file_search", "rg", "search_code"),
    "fs_write": ("apply_patch", "write_file", "edit_file"),
    "git_read": ("repo_status", "git", "show_diff"),
    "runtime": ("run_shell_command", "run_command"),
    "planning": ("todo_write",),
    "introspection": ("tool_search", "session_status"),
    "process": (
        "process_start",
        "process_poll",
        "process_write",
        "process_stop",
        "process_list",
    ),
    "lsp_tools": ("lsp",),
    "read_only_agent": (
        "fs_read",
        "git_read",
        "introspection",
        "lsp_tools",
    ),
    "coding_agent": (
        "fs_read",
        "fs_write",
        "git_read",
        "runtime",
        "planning",
        "introspection",
        "lsp_tools",
        "memory",
    ),
    "full_coding_agent": ("coding_agent", "process"),
    "repair_agent": ("coding_agent",),
    "simple_chat_tool_agent": (
        "fs_read",
        "git_read",
        "introspection",
    ),
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
    available_tools: set[str] | None = None
    permission_mode: str | None = None
    allowed_tools: set[str] | None = None
    denied_tools: set[str] = Field(default_factory=set)
    run_id: str | None = None
    trace_path: str | None = None
    recent_steps: list[dict[str, object]] = Field(default_factory=list)
    pending_confirmation: dict[str, object] | None = None
    process_registry: Any | None = None
    lsp_client: Any | None = None
    memory_store: Any | None = None


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


_MODE_RANK = {
    "read-only": 1,
    "safe": 1,
    "workspace-write": 2,
    "guided": 2,
    "danger-full-access": 3,
    "full": 3,
}
_RISK_REQUIRED_RANK = {
    ToolRisk.READ_ONLY: 1,
    ToolRisk.WRITE_WORKTREE: 2,
    ToolRisk.SHELL_RESTRICTED: 2,
    ToolRisk.DANGEROUS: 3,
}
_SIMPLE_MODE_TOOLS = frozenset(
    {
        "repo_status",
        "detect_project",
        "show_diff",
        "glob_file_search",
        "list_dir",
        "read_file",
        "rg",
        "search_code",
        "git",
        "tool_search",
        "session_status",
    }
)
_DEFAULT_EXCLUDED_TOOLS = frozenset(
    {
        "memory_write",
        "file_summary_refresh",
    }
)


class ToolPool:
    def __init__(
        self,
        *,
        specs: list[ToolSpec],
        permission_mode: str,
        simple_mode: bool,
        excluded_tools: list[str],
    ) -> None:
        self._specs = {spec.name: spec for spec in specs}
        self.permission_mode = permission_mode
        self.simple_mode = simple_mode
        self.excluded_tools = sorted(set(excluded_tools))

    def names(self) -> list[str]:
        return sorted(self._specs)

    def get(self, name: str) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise KeyError(f"unknown pooled tool: {name}") from exc

    def openai_tools(self) -> list[dict[str, object]]:
        return [self._specs[name].to_openai_tool() for name in self.names()]

    def manifest(self) -> dict[str, object]:
        return {
            "permission_mode": self.permission_mode,
            "simple_mode": self.simple_mode,
            "tools": self.names(),
            "excluded_tools": self.excluded_tools,
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

        def expand_tool_name(raw_name: str, seen: set[str]) -> None:
            validate_tool_name(raw_name)
            if raw_name in seen:
                return
            seen.add(raw_name)
            expanded_names = _TOOL_ALIASES.get(raw_name)
            if expanded_names is not None:
                for expanded_name in expanded_names:
                    expand_tool_name(expanded_name, seen)
                return
            if raw_name not in self._specs:
                raise KeyError(f"unknown allowed tool: {raw_name}")
            normalized.add(raw_name)

        for raw_name in allowed_tools:
            expand_tool_name(raw_name, set())
        return normalized

    def names(self, allowed_tools: AllowedTools = None) -> list[str]:
        normalized = self._normalize_allowed_tools(allowed_tools)
        if normalized is None:
            return sorted(self._specs)
        return sorted(normalized)

    def tool_pool(
        self,
        *,
        permission_mode: str,
        allowed_tools: AllowedTools = None,
        denied_tools: AllowedTools = None,
        simple_mode: bool = False,
    ) -> ToolPool:
        mode_rank = _MODE_RANK.get(permission_mode, 1)
        allowed_names = self._normalize_allowed_tools(allowed_tools)
        denied_names = self._normalize_allowed_tools(denied_tools) or set()

        included: list[ToolSpec] = []
        excluded: list[str] = []
        for name in sorted(self._specs):
            spec = self._specs[name]
            include = True
            if allowed_names is None and name in _DEFAULT_EXCLUDED_TOOLS:
                include = False
            if allowed_names is not None and name not in allowed_names:
                include = False
            if name in denied_names:
                include = False
            if simple_mode and name not in _SIMPLE_MODE_TOOLS:
                include = False
            if _RISK_REQUIRED_RANK[spec.risk_level] > mode_rank:
                include = False

            if include:
                included.append(spec)
            else:
                excluded.append(name)

        return ToolPool(
            specs=included,
            permission_mode=permission_mode,
            simple_mode=simple_mode,
            excluded_tools=excluded,
        )

    def openai_tools(self, allowed_tools: AllowedTools = None) -> list[dict[str, object]]:
        return [
            self._specs[name].to_openai_tool()
            for name in self.names(allowed_tools=allowed_tools)
        ]
