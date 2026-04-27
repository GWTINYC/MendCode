import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.schemas.agent_action import Observation
from app.tools.arguments import (
    GitArgs,
    GlobFileSearchArgs,
    ListDirArgs,
    ReadFileArgs,
    RgArgs,
    SessionStatusArgs,
)
from app.tools.structured import ToolInvocation

REPEAT_GUARDED_TOOLS = frozenset(
    {
        "read_file",
        "list_dir",
        "glob_file_search",
        "rg",
        "search_code",
        "git",
        "repo_status",
        "show_diff",
        "detect_project",
        "session_status",
    }
)
_PATH_ARG_NAMES = {"path", "relative_path"}
_DEFAULTED_ARG_MODELS = {
    "read_file": ReadFileArgs,
    "list_dir": ListDirArgs,
    "glob_file_search": GlobFileSearchArgs,
    "rg": RgArgs,
    "search_code": RgArgs,
    "git": GitArgs,
    "session_status": SessionStatusArgs,
}


def tool_call_fingerprint(invocation: ToolInvocation, workspace_path: Path) -> str:
    workspace = workspace_path.resolve()
    args = _args_with_defaults(invocation)
    normalized_args = {
        key: _normalize_arg_value(key, value, workspace) for key, value in args.items()
    }
    payload = {
        "tool_name": invocation.name,
        "workspace_path": str(workspace),
        "args": normalized_args,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class _RepetitionRecord:
    count: int
    previous_step: int


class RepetitionTracker:
    def __init__(self, max_equivalent_calls: int = 2) -> None:
        self.max_equivalent_calls = max_equivalent_calls
        self._records: dict[str, _RepetitionRecord] = {}

    def rejection_for(
        self,
        invocation: ToolInvocation,
        workspace_path: Path,
        *,
        next_step_index: int,
    ) -> Observation | None:
        if invocation.name not in REPEAT_GUARDED_TOOLS:
            return None
        fingerprint = tool_call_fingerprint(invocation, workspace_path)
        record = self._records.get(fingerprint)
        repeat_count = (record.count if record is not None else 0) + 1
        if repeat_count <= self.max_equivalent_calls:
            return None
        return Observation(
            status="rejected",
            summary="Repeated equivalent tool call",
            payload={
                "tool_name": invocation.name,
                "repeat_count": repeat_count,
                "previous_step": record.previous_step if record is not None else None,
                "current_step": next_step_index,
                "suggestion": "Use the previous observation or call final_response.",
            },
            error_message="equivalent tool call repeated too many times",
        )

    def record(
        self,
        invocation: ToolInvocation,
        workspace_path: Path,
        *,
        step_index: int,
        observation: Observation,
    ) -> None:
        if invocation.name not in REPEAT_GUARDED_TOOLS:
            return
        if observation.status not in {"succeeded", "rejected"}:
            return
        fingerprint = tool_call_fingerprint(invocation, workspace_path)
        existing = self._records.get(fingerprint)
        count = 1 if existing is None else existing.count + 1
        self._records[fingerprint] = _RepetitionRecord(count=count, previous_step=step_index)


def _normalize_arg_value(key: str, value: Any, workspace: Path) -> Any:
    if key in _PATH_ARG_NAMES and isinstance(value, str):
        return _normalize_path_arg(value, workspace)
    return value


def _args_with_defaults(invocation: ToolInvocation) -> dict[str, Any]:
    args_model = _DEFAULTED_ARG_MODELS.get(invocation.name)
    if args_model is None:
        return dict(invocation.args)
    try:
        return args_model.model_validate(invocation.args).model_dump(mode="json")
    except ValueError:
        return dict(invocation.args)


def _normalize_path_arg(value: str, workspace: Path) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = workspace / path
    resolved = path.resolve()
    try:
        return resolved.relative_to(workspace).as_posix()
    except ValueError:
        return str(resolved)
