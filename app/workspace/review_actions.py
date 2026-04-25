import subprocess
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.workspace.worktree import cleanup_worktree

ReviewActionStatus = Literal["succeeded", "failed", "rejected"]


class ReviewActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    status: ReviewActionStatus
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_error_message(self) -> "ReviewActionResult":
        if self.status == "succeeded" and self.error_message is not None:
            raise ValueError("succeeded review actions require error_message=None")
        if self.status in {"failed", "rejected"} and self.error_message is None:
            raise ValueError("failed and rejected review actions require error_message")
        return self


def _run_git(
    args: list[str],
    *,
    cwd: Path,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )


def _failed(action: str, summary: str, message: str) -> ReviewActionResult:
    return ReviewActionResult(
        action=action,
        status="failed",
        summary=summary,
        payload={},
        error_message=message,
    )


def _rejected(
    action: str,
    summary: str,
    message: str,
    payload: dict[str, Any],
) -> ReviewActionResult:
    return ReviewActionResult(
        action=action,
        status="rejected",
        summary=summary,
        payload=payload,
        error_message=message,
    )


def _changed_files_from_diff_stat(diff_stat: str) -> list[str]:
    files: list[str] = []
    for line in diff_stat.splitlines():
        stripped = line.strip()
        if not stripped or "|" not in stripped:
            continue
        files.append(stripped.split("|", 1)[0].strip())
    return files


def _worktree_diff(workspace_path: Path) -> tuple[ReviewActionResult | None, str, str, list[str]]:
    stat_result = _run_git(["diff", "--stat", "HEAD"], cwd=workspace_path)
    if stat_result.returncode != 0:
        return (
            _failed(
                "view_diff",
                "Unable to read worktree diff",
                stat_result.stderr.strip() or "git diff --stat failed",
            ),
            "",
            "",
            [],
        )

    diff_result = _run_git(["diff", "--binary", "HEAD"], cwd=workspace_path)
    if diff_result.returncode != 0:
        return (
            _failed(
                "view_diff",
                "Unable to read worktree diff",
                diff_result.stderr.strip() or "git diff failed",
            ),
            "",
            "",
            [],
        )

    diff_stat = stat_result.stdout
    changed_files = _changed_files_from_diff_stat(diff_stat)
    return None, diff_stat, diff_result.stdout, changed_files


def view_worktree_diff(*, workspace_path: Path) -> ReviewActionResult:
    try:
        error, diff_stat, diff, changed_files = _worktree_diff(workspace_path)
    except OSError as exc:
        return _failed("view_diff", "Unable to read worktree diff", str(exc))
    if error is not None:
        return error
    return ReviewActionResult(
        action="view_diff",
        status="succeeded",
        summary="Read worktree diff",
        payload={
            "workspace_path": str(workspace_path),
            "changed_files": changed_files,
            "diff_stat": diff_stat,
            "diff": diff,
        },
    )


def view_trace(*, trace_path: Path, max_chars: int = 12000) -> ReviewActionResult:
    if max_chars < 0:
        return _rejected(
            "view_trace",
            "Unable to read trace",
            "max_chars must be greater than or equal to 0",
            {"trace_path": str(trace_path), "max_chars": max_chars},
        )
    if not trace_path.exists():
        return _failed(
            "view_trace",
            "Unable to read trace",
            "trace file does not exist",
        )
    if trace_path.is_dir():
        return _failed("view_trace", "Unable to read trace", "trace path points to a directory")

    try:
        content = trace_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        return _failed("view_trace", "Unable to read trace", str(exc))

    truncated = len(content) > max_chars
    return ReviewActionResult(
        action="view_trace",
        status="succeeded",
        summary="Read trace",
        payload={
            "trace_path": str(trace_path),
            "content": content[:max_chars],
            "truncated": truncated,
        },
    )


def discard_worktree(*, repo_path: Path, workspace_path: Path) -> ReviewActionResult:
    cleanup = cleanup_worktree(repo_path=repo_path, workspace_path=workspace_path)
    if not cleanup.cleanup_succeeded:
        return _failed("discard", "Unable to discard worktree", cleanup.cleanup_reason)
    return ReviewActionResult(
        action="discard",
        status="succeeded",
        summary="Discarded worktree",
        payload=cleanup.model_dump(mode="json"),
    )


def apply_worktree_changes(*, repo_path: Path, workspace_path: Path) -> ReviewActionResult:
    try:
        status_result = _run_git(["status", "--short"], cwd=repo_path)
    except OSError as exc:
        return _failed("apply", "Unable to inspect main workspace", str(exc))
    if status_result.returncode != 0:
        return _failed(
            "apply",
            "Unable to inspect main workspace",
            status_result.stderr.strip() or "git status failed",
        )

    dirty_files = [line for line in status_result.stdout.splitlines() if line.strip()]
    if dirty_files:
        return _rejected(
            "apply",
            "Main workspace is not clean",
            "main workspace has uncommitted changes",
            {"dirty_files": dirty_files},
        )

    try:
        error, diff_stat, diff, changed_files = _worktree_diff(workspace_path)
    except OSError as exc:
        return _failed("apply", "Unable to read worktree diff", str(exc))
    if error is not None:
        return _failed("apply", error.summary, error.error_message or "git diff failed")
    if not diff.strip():
        return _rejected("apply", "No worktree changes to apply", "worktree diff is empty", {})

    check_result = _run_git(
        ["apply", "--check", "--whitespace=nowarn"],
        cwd=repo_path,
        input_text=diff,
    )
    if check_result.returncode != 0:
        error_message = (
            check_result.stderr.strip()
            or check_result.stdout.strip()
            or "git apply --check failed"
        )
        return _rejected(
            "apply",
            "Worktree changes cannot be applied cleanly",
            error_message,
            {"changed_files": changed_files, "diff_stat": diff_stat},
        )

    apply_result = _run_git(["apply", "--whitespace=nowarn"], cwd=repo_path, input_text=diff)
    if apply_result.returncode != 0:
        return _failed(
            "apply",
            "Unable to apply worktree changes",
            apply_result.stderr.strip() or apply_result.stdout.strip() or "git apply failed",
        )

    return ReviewActionResult(
        action="apply",
        status="succeeded",
        summary="Applied worktree changes to main workspace",
        payload={"changed_files": changed_files, "diff_stat": diff_stat},
    )
