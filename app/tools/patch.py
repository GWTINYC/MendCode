from pathlib import Path

from app.tools.guard import resolve_workspace_file
from app.tools.schemas import ToolResult


def _reject_apply_patch(
    workspace_path: Path,
    relative_path: str,
    message: str,
) -> ToolResult:
    return ToolResult(
        tool_name="apply_patch",
        status="rejected",
        summary=f"Unable to patch {relative_path}",
        payload={"relative_path": relative_path},
        error_message=message,
        workspace_path=str(workspace_path),
    )


def _failed_apply_patch(
    workspace_path: Path,
    relative_path: str,
    message: str,
) -> ToolResult:
    return ToolResult(
        tool_name="apply_patch",
        status="failed",
        summary=f"Unable to patch {relative_path}",
        payload={"relative_path": relative_path},
        error_message=message,
        workspace_path=str(workspace_path),
    )


def apply_patch(
    workspace_path: Path,
    relative_path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
) -> ToolResult:
    if old_text == "":
        return _reject_apply_patch(workspace_path, relative_path, "old_text must not be empty")

    try:
        target = resolve_workspace_file(workspace_path, relative_path)
    except ValueError as exc:
        return _reject_apply_patch(workspace_path, relative_path, str(exc))

    try:
        content = target.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        return _failed_apply_patch(workspace_path, relative_path, str(exc))

    occurrences = content.count(old_text)
    if occurrences == 0:
        return _reject_apply_patch(workspace_path, relative_path, "target text not found")
    if occurrences > 1 and not replace_all:
        return _reject_apply_patch(
            workspace_path,
            relative_path,
            "target text matched multiple locations",
        )

    replacements_applied = occurrences if replace_all else 1
    updated_content = content.replace(old_text, new_text, replacements_applied)

    try:
        target.write_text(updated_content, encoding="utf-8")
    except OSError as exc:
        return _failed_apply_patch(workspace_path, relative_path, str(exc))

    return ToolResult(
        tool_name="apply_patch",
        status="passed",
        summary=f"Patched {relative_path}",
        payload={
            "relative_path": relative_path,
            "replacements_applied": replacements_applied,
            "replace_all": replace_all,
        },
        error_message=None,
        workspace_path=str(workspace_path),
    )
