import subprocess
from pathlib import Path

from app.tools.guard import resolve_workspace_file
from app.tools.schemas import ToolResult


def _reject_read_file(relative_path: str, workspace_path: Path, message: str) -> ToolResult:
    return ToolResult(
        tool_name="read_file",
        status="rejected",
        summary=f"Unable to read {relative_path}",
        payload={"relative_path": relative_path},
        error_message=message,
        workspace_path=str(workspace_path),
    )


def read_file(
    workspace_path: Path,
    relative_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    max_chars: int | None = None,
) -> ToolResult:
    if start_line is not None and start_line <= 0:
        return _reject_read_file(relative_path, workspace_path, "start_line must be greater than 0")
    if end_line is not None and end_line <= 0:
        return _reject_read_file(relative_path, workspace_path, "end_line must be greater than 0")
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
