from dataclasses import dataclass
from pathlib import Path

from app.tui.commands import KNOWN_COMMANDS

_MAX_COMPLETIONS = 8
_IGNORED_PATH_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".worktrees",
    "__pycache__",
    "data",
    "mendcode.egg-info",
}

_COMMAND_DESCRIPTIONS = {
    "help": "显示可用命令",
    "status": "查看仓库、权限和会话状态",
    "test": "设置验证命令",
    "fix": "准备一次修复任务",
    "diff": "查看最近修复的 diff",
    "trace": "查看最近 trace 摘要",
    "tools": "展开最近工具调用详情",
    "apply": "应用最近验证通过的改动",
    "discard": "丢弃最近 worktree",
    "sessions": "列出本地会话",
    "resume": "恢复历史会话上下文",
    "exit": "退出 TUI",
}

_DOLLAR_ITEMS = {
    "$repo": "当前仓库路径和项目上下文",
    "$status": "仓库状态、权限和运行状态",
    "$diff": "最近一次 diff 或待审查改动",
    "$memory": "已召回的项目记忆和经验",
    "$tools": "当前模型可用工具列表",
    "$last_turn": "最近一轮对话和工具结果",
}


@dataclass(frozen=True)
class CompletionItem:
    label: str
    insert_text: str
    description: str
    replace_start: int
    replace_end: int


@dataclass(frozen=True)
class CompletionState:
    trigger: str
    query: str
    selected_index: int
    items: list[CompletionItem]


def build_completion_state(
    *,
    repo_path: Path,
    text: str,
    cursor_position: int | None = None,
    selected_index: int = 0,
) -> CompletionState | None:
    cursor = len(text) if cursor_position is None else cursor_position
    trigger_info = _active_trigger(text, cursor)
    if trigger_info is None:
        return None
    trigger, replace_start, query = trigger_info
    replace_end = cursor
    items = _items_for_trigger(
        repo_path=repo_path,
        trigger=trigger,
        query=query,
        replace_start=replace_start,
        replace_end=replace_end,
    )
    if not items:
        return None
    selected = min(max(selected_index, 0), len(items) - 1)
    return CompletionState(
        trigger=trigger,
        query=query,
        selected_index=selected,
        items=items,
    )


def insert_completion(
    text: str,
    cursor_position: int,
    item: CompletionItem,
) -> tuple[str, int]:
    replacement = item.insert_text
    if not replacement.endswith(" "):
        replacement += " "
    updated = text[: item.replace_start] + replacement + text[item.replace_end :]
    return updated, item.replace_start + len(replacement)


def _active_trigger(text: str, cursor: int) -> tuple[str, int, str] | None:
    prefix = text[:cursor]
    last_trigger = -1
    trigger = ""
    for candidate in "@/":
        index = prefix.rfind(candidate)
        if index > last_trigger:
            last_trigger = index
            trigger = candidate
    dollar_index = prefix.rfind("$")
    if dollar_index > last_trigger:
        last_trigger = dollar_index
        trigger = "$"
    if last_trigger < 0:
        return None
    if last_trigger > 0 and not prefix[last_trigger - 1].isspace():
        return None
    query = prefix[last_trigger + 1 :]
    if any(char.isspace() for char in query):
        return None
    return trigger, last_trigger, query


def _items_for_trigger(
    *,
    repo_path: Path,
    trigger: str,
    query: str,
    replace_start: int,
    replace_end: int,
) -> list[CompletionItem]:
    normalized_query = query.casefold()
    if trigger == "/":
        return _command_items(normalized_query, replace_start, replace_end)
    if trigger == "$":
        return _dollar_items(normalized_query, replace_start, replace_end)
    return _file_items(repo_path, normalized_query, replace_start, replace_end)


def _command_items(
    query: str,
    replace_start: int,
    replace_end: int,
) -> list[CompletionItem]:
    items = []
    commands = sorted(KNOWN_COMMANDS, key=lambda command: _match_rank(command, query))
    for command in commands:
        label = f"/{command}"
        if query and query not in command.casefold():
            continue
        items.append(
            CompletionItem(
                label=label,
                insert_text=label,
                description=_COMMAND_DESCRIPTIONS.get(command, "TUI 命令"),
                replace_start=replace_start,
                replace_end=replace_end,
            )
        )
    return items[:_MAX_COMPLETIONS]


def _dollar_items(
    query: str,
    replace_start: int,
    replace_end: int,
) -> list[CompletionItem]:
    items = []
    labels = sorted(_DOLLAR_ITEMS, key=lambda label: _match_rank(label[1:], query))
    for label in labels:
        description = _DOLLAR_ITEMS[label]
        name = label[1:].casefold()
        if query and query not in name:
            continue
        items.append(
            CompletionItem(
                label=label,
                insert_text=label,
                description=description,
                replace_start=replace_start,
                replace_end=replace_end,
            )
        )
    return items[:_MAX_COMPLETIONS]


def _file_items(
    repo_path: Path,
    query: str,
    replace_start: int,
    replace_end: int,
) -> list[CompletionItem]:
    items = []
    if not repo_path.exists():
        return items
    for path in sorted(repo_path.rglob("*")):
        if len(items) >= _MAX_COMPLETIONS:
            break
        if not path.is_file() or _is_ignored_path(path, repo_path):
            continue
        relative = path.relative_to(repo_path).as_posix()
        if query and query not in relative.casefold():
            continue
        label = f"@{relative}"
        items.append(
            CompletionItem(
                label=label,
                insert_text=label,
                description="文件路径",
                replace_start=replace_start,
                replace_end=replace_end,
            )
        )
    return items


def _match_rank(value: str, query: str) -> tuple[int, str]:
    normalized = value.casefold()
    if not query:
        return (1, normalized)
    if normalized.startswith(query):
        return (0, normalized)
    return (1, normalized)


def _is_ignored_path(path: Path, repo_path: Path) -> bool:
    try:
        parts = path.relative_to(repo_path).parts
    except ValueError:
        return True
    return any(part in _IGNORED_PATH_PARTS for part in parts)
