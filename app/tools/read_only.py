import subprocess
from collections import deque
from pathlib import Path

from app.tools.guard import resolve_workspace_file, resolve_workspace_path
from app.tools.schemas import ToolResult


def _relative_posix(workspace_path: Path, path: Path) -> str:
    relative = path.resolve().relative_to(workspace_path.resolve())
    return relative.as_posix() or "."


def _reject_read_file(relative_path: str, workspace_path: Path, message: str) -> ToolResult:
    return ToolResult(
        tool_name="read_file",
        status="rejected",
        summary=f"Unable to read {relative_path}",
        payload={"relative_path": relative_path},
        error_message=message,
        workspace_path=str(workspace_path),
    )


def _join_lines_with_limit(
    lines: list[str] | deque[str],
    max_chars: int | None,
) -> tuple[str, bool]:
    if max_chars is None:
        return "".join(lines), False

    content_parts: list[str] = []
    content_length = 0
    truncated = False
    for line in lines:
        if truncated:
            break

        remaining = max_chars - content_length
        if remaining <= 0:
            truncated = True
            break

        if len(line) <= remaining:
            content_parts.append(line)
            content_length += len(line)
            continue

        content_parts.append(line[:remaining])
        truncated = True

    return "".join(content_parts), truncated


def read_file(
    workspace_path: Path,
    relative_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    tail_lines: int | None = None,
    max_chars: int | None = None,
) -> ToolResult:
    if start_line is not None and start_line <= 0:
        return _reject_read_file(relative_path, workspace_path, "start_line must be greater than 0")
    if end_line is not None and end_line <= 0:
        return _reject_read_file(relative_path, workspace_path, "end_line must be greater than 0")
    if tail_lines is not None and tail_lines <= 0:
        return _reject_read_file(relative_path, workspace_path, "tail_lines must be greater than 0")
    if tail_lines is not None and (start_line is not None or end_line is not None):
        return _reject_read_file(
            relative_path,
            workspace_path,
            "tail_lines cannot be combined with start_line or end_line",
        )
    if start_line is not None and end_line is not None and start_line > end_line:
        return _reject_read_file(
            relative_path,
            workspace_path,
            "start_line cannot be greater than end_line",
        )
    if max_chars is not None and max_chars < 0:
        return _reject_read_file(
            relative_path,
            workspace_path,
            "max_chars must be greater than or equal to 0",
        )

    try:
        target = resolve_workspace_file(workspace_path, relative_path)
    except ValueError as exc:
        return _reject_read_file(relative_path, workspace_path, str(exc))

    if tail_lines is not None:
        tail: deque[str] = deque(maxlen=tail_lines)
        total_lines = 0
        try:
            with target.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    total_lines = line_number
                    tail.append(line)
        except (UnicodeDecodeError, OSError) as exc:
            return ToolResult(
                tool_name="read_file",
                status="failed",
                summary=f"Unable to read {relative_path}",
                payload={"relative_path": relative_path},
                error_message=str(exc),
                workspace_path=str(workspace_path),
            )

        content, truncated = _join_lines_with_limit(tail, max_chars)
        line_count = len(tail)
        start = total_lines - line_count + 1 if line_count else 0
        end = total_lines if line_count else 0

        return ToolResult(
            tool_name="read_file",
            status="passed",
            summary=f"Read {relative_path}",
            payload={
                "relative_path": relative_path,
                "start_line": start,
                "end_line": end,
                "total_lines": total_lines,
                "content": content,
                "truncated": truncated,
            },
            error_message=None,
            workspace_path=str(workspace_path),
        )

    start = 1 if start_line is None else start_line
    requested_end = end_line
    content_parts: list[str] = []
    content_length = 0
    total_lines = 0
    truncated = False

    try:
        with target.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                total_lines = line_number
                if line_number < start:
                    continue

                if requested_end is not None and line_number > requested_end:
                    continue

                if truncated:
                    continue

                if max_chars is None:
                    content_parts.append(line)
                    continue

                remaining = max_chars - content_length
                if remaining <= 0:
                    truncated = True
                    continue

                if len(line) <= remaining:
                    content_parts.append(line)
                    content_length += len(line)
                    continue

                content_parts.append(line[:remaining])
                content_length += remaining
                truncated = True
    except (UnicodeDecodeError, OSError) as exc:
        return ToolResult(
            tool_name="read_file",
            status="failed",
            summary=f"Unable to read {relative_path}",
            payload={"relative_path": relative_path},
            error_message=str(exc),
            workspace_path=str(workspace_path),
        )

    content = "".join(content_parts)
    end = total_lines if requested_end is None else requested_end

    if total_lines == 0 and start_line is None and requested_end is None:
        return ToolResult(
            tool_name="read_file",
            status="passed",
            summary=f"Read {relative_path}",
            payload={
                "relative_path": relative_path,
                "start_line": 0,
                "end_line": 0,
                "total_lines": 0,
                "content": content,
                "truncated": truncated,
            },
            error_message=None,
            workspace_path=str(workspace_path),
        )

    if start > total_lines:
        return _reject_read_file(relative_path, workspace_path, "start_line exceeds file length")
    if requested_end is not None and requested_end > total_lines:
        return _reject_read_file(relative_path, workspace_path, "end_line exceeds file length")

    return ToolResult(
        tool_name="read_file",
        status="passed",
        summary=f"Read {relative_path}",
        payload={
            "relative_path": relative_path,
            "start_line": start,
            "end_line": end,
            "total_lines": total_lines,
            "content": content,
            "truncated": truncated,
        },
        error_message=None,
        workspace_path=str(workspace_path),
    )


def _reject_list_dir(relative_path: str, workspace_path: Path, message: str) -> ToolResult:
    return ToolResult(
        tool_name="list_dir",
        status="rejected",
        summary=f"Unable to list {relative_path}",
        payload={"relative_path": relative_path, "total_entries": 0, "entries": []},
        error_message=message,
        workspace_path=str(workspace_path),
    )


def list_dir(
    workspace_path: Path,
    relative_path: str = ".",
    max_entries: int | None = None,
) -> ToolResult:
    if max_entries is not None and max_entries < 0:
        return _reject_list_dir(
            relative_path,
            workspace_path,
            "max_entries must be greater than or equal to 0",
        )

    try:
        target = resolve_workspace_path(workspace_path, relative_path)
    except ValueError as exc:
        return _reject_list_dir(relative_path, workspace_path, str(exc))

    if not target.exists():
        return _reject_list_dir(relative_path, workspace_path, "path does not exist")
    if not target.is_dir():
        return _reject_list_dir(relative_path, workspace_path, "path is not a directory")

    entries = []
    for child in sorted(target.iterdir(), key=lambda item: item.name):
        entry_type = "directory" if child.is_dir() else "file"
        if child.is_symlink():
            entry_type = "symlink"
        entries.append(
            {
                "relative_path": _relative_posix(workspace_path, child),
                "name": child.name,
                "type": entry_type,
                "size_bytes": child.stat().st_size if child.is_file() else None,
            }
        )

    total_entries = len(entries)
    truncated = False
    if max_entries is not None and len(entries) > max_entries:
        entries = entries[:max_entries]
        truncated = True

    return ToolResult(
        tool_name="list_dir",
        status="passed",
        summary=f"Listed {relative_path}",
        payload={
            "relative_path": relative_path,
            "total_entries": total_entries,
            "truncated": truncated,
            "entries": entries,
        },
        error_message=None,
        workspace_path=str(workspace_path),
    )


def _reject_glob_file_search(workspace_path: Path, pattern: str, message: str) -> ToolResult:
    return ToolResult(
        tool_name="glob_file_search",
        status="rejected",
        summary="Unable to search files",
        payload={"pattern": pattern, "total_matches": 0, "matches": []},
        error_message=message,
        workspace_path=str(workspace_path),
    )


def glob_file_search(
    workspace_path: Path,
    pattern: str,
    max_results: int | None = None,
) -> ToolResult:
    stripped = pattern.strip()
    if not stripped:
        return _reject_glob_file_search(workspace_path, pattern, "pattern must not be empty")
    if Path(stripped).is_absolute():
        return _reject_glob_file_search(workspace_path, pattern, "pattern must be relative")
    if ".." in Path(stripped).parts:
        return _reject_glob_file_search(workspace_path, pattern, "pattern escapes workspace root")
    if max_results is not None and max_results < 0:
        return _reject_glob_file_search(
            workspace_path,
            pattern,
            "max_results must be greater than or equal to 0",
        )

    matches = []
    try:
        candidates = sorted(workspace_path.glob(stripped), key=lambda item: item.as_posix())
    except ValueError as exc:
        return _reject_glob_file_search(workspace_path, pattern, str(exc))

    for candidate in candidates:
        if not candidate.exists():
            continue
        entry_type = "directory" if candidate.is_dir() else "file"
        if candidate.is_symlink():
            entry_type = "symlink"
        matches.append(
            {
                "relative_path": _relative_posix(workspace_path, candidate),
                "type": entry_type,
                "size_bytes": candidate.stat().st_size if candidate.is_file() else None,
            }
        )

    total_matches = len(matches)
    truncated = False
    if max_results is not None and len(matches) > max_results:
        matches = matches[:max_results]
        truncated = True

    return ToolResult(
        tool_name="glob_file_search",
        status="passed",
        summary=f"Searched files with {pattern}",
        payload={
            "pattern": pattern,
            "total_matches": total_matches,
            "truncated": truncated,
            "matches": matches,
        },
        error_message=None,
        workspace_path=str(workspace_path),
    )


def _reject_search_code(
    workspace_path: Path,
    query: str,
    glob: str | None,
    message: str,
) -> ToolResult:
    return ToolResult(
        tool_name="search_code",
        status="rejected",
        summary="Unable to search code",
        payload={"query": query, "glob": glob, "total_matches": 0, "matches": []},
        error_message=message,
        workspace_path=str(workspace_path),
    )


def _failed_search_code(
    workspace_path: Path,
    query: str,
    glob: str | None,
    message: str,
) -> ToolResult:
    return ToolResult(
        tool_name="search_code",
        status="failed",
        summary="Unable to search code",
        payload={"query": query, "glob": glob, "total_matches": 0, "matches": []},
        error_message=message,
        workspace_path=str(workspace_path),
    )


def _fallback_search_code(
    workspace_path: Path,
    query: str,
    glob: str | None,
    max_results: int | None,
) -> ToolResult:
    matches: list[dict[str, object]] = []
    total_matches = 0
    workspace_root = workspace_path.resolve()

    for candidate in sorted(workspace_path.rglob("*"), key=lambda item: item.as_posix()):
        if not candidate.is_file():
            continue

        try:
            relative = candidate.resolve().relative_to(workspace_root)
        except ValueError:
            continue
        if any(part in {".git", ".worktrees"} for part in relative.parts):
            continue
        if glob is not None and not relative.match(glob):
            continue

        try:
            with candidate.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    line_text = line.rstrip("\n")
                    if query not in line_text:
                        continue

                    total_matches += 1
                    if max_results is None or len(matches) < max_results:
                        matches.append(
                            {
                                "relative_path": relative.as_posix(),
                                "line_number": line_number,
                                "line_text": line_text,
                            }
                        )
        except (OSError, UnicodeDecodeError):
            continue

    return ToolResult(
        tool_name="search_code",
        status="passed",
        summary=f"Searched for {query}",
        payload={
            "query": query,
            "glob": glob,
            "total_matches": total_matches,
            "matches": matches,
        },
        error_message=None,
        workspace_path=str(workspace_path),
    )


def search_code(
    workspace_path: Path,
    query: str,
    glob: str | None = None,
    max_results: int | None = None,
) -> ToolResult:
    if not query.strip():
        return _reject_search_code(workspace_path, query, glob, "query must not be empty")
    if max_results is not None and max_results < 0:
        return _reject_search_code(
            workspace_path,
            query,
            glob,
            "max_results must be greater than or equal to 0",
        )

    command = ["rg", "--fixed-strings", "--line-number", "--no-heading"]
    if glob is not None:
        command.extend(["--glob", glob])
    command.append(query)

    try:
        completed = subprocess.run(
            command,
            cwd=workspace_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return _fallback_search_code(workspace_path, query, glob, max_results)
    except OSError as exc:
        return _failed_search_code(workspace_path, query, glob, str(exc))

    if completed.returncode not in {0, 1}:
        return _failed_search_code(
            workspace_path,
            query,
            glob,
            f"rg exited with code {completed.returncode}",
        )

    matches: list[dict[str, object]] = []
    for line in completed.stdout.splitlines():
        relative_path, line_number_text, line_text = line.split(":", 2)
        matches.append(
            {
                "relative_path": relative_path,
                "line_number": int(line_number_text),
                "line_text": line_text,
            }
        )

    total_matches = len(matches)
    if max_results is not None:
        matches = matches[:max_results]

    return ToolResult(
        tool_name="search_code",
        status="passed",
        summary=f"Searched for {query}",
        payload={
            "query": query,
            "glob": glob,
            "total_matches": total_matches,
            "matches": matches,
        },
        error_message=None,
        workspace_path=str(workspace_path),
    )
