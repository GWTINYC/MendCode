import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class WorkspaceCleanupResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    cleanup_attempted: bool
    cleanup_succeeded: bool
    cleanup_reason: str


def prepare_worktree(
    repo_path: Path,
    workspace_root: Path,
    run_id: str,
    base_ref: str | None,
) -> Path:
    workspace_root.mkdir(parents=True, exist_ok=True)
    workspace_path = workspace_root / run_id
    ref = base_ref or "HEAD"

    subprocess.run(
        ["git", "-C", str(repo_path), "worktree", "add", "--detach", str(workspace_path), ref],
        check=True,
        capture_output=True,
        text=True,
    )

    return workspace_path


def cleanup_worktree(repo_path: Path, workspace_path: Path) -> WorkspaceCleanupResult:
    try:
        subprocess.run(
            ["git", "-C", str(repo_path), "worktree", "remove", "--force", str(workspace_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        return WorkspaceCleanupResult(
            workspace_path=str(workspace_path),
            cleanup_attempted=True,
            cleanup_succeeded=False,
            cleanup_reason=exc.stderr.strip() or exc.stdout.strip() or str(exc),
        )

    return WorkspaceCleanupResult(
        workspace_path=str(workspace_path),
        cleanup_attempted=True,
        cleanup_succeeded=True,
        cleanup_reason="workspace removed",
    )
