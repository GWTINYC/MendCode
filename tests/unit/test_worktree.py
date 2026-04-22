import subprocess
from pathlib import Path

from app.workspace.worktree import cleanup_worktree, prepare_worktree


def init_git_repo(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (repo_path / "README.md").write_text("demo\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return repo_path


def commit_file(repo_path: Path, name: str, content: str, message: str) -> str:
    (repo_path / name).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", name], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_prepare_worktree_honors_base_ref_and_is_detached(tmp_path):
    repo_path = init_git_repo(tmp_path)
    first_commit = commit_file(repo_path, "feature.txt", "first\n", "first")
    commit_file(repo_path, "feature.txt", "second\n", "second")
    workspace_root = tmp_path / ".worktrees"

    workspace_path = prepare_worktree(
        repo_path=repo_path,
        workspace_root=workspace_root,
        run_id="preview-123456789abc",
        base_ref=first_commit,
    )

    assert workspace_path == workspace_root / "preview-123456789abc"
    assert workspace_path.exists()

    head_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert head_commit.stdout.strip() == first_commit

    detached_head = subprocess.run(
        ["git", "symbolic-ref", "-q", "HEAD"],
        cwd=workspace_path,
        capture_output=True,
        text=True,
    )
    assert detached_head.returncode != 0
    assert (workspace_path / "README.md").exists()


def test_cleanup_worktree_removes_workspace_and_reports_success(tmp_path):
    repo_path = init_git_repo(tmp_path)
    workspace_root = tmp_path / ".worktrees"
    workspace_path = prepare_worktree(
        repo_path=repo_path,
        workspace_root=workspace_root,
        run_id="preview-123456789abc",
        base_ref=None,
    )

    cleanup = cleanup_worktree(repo_path=repo_path, workspace_path=workspace_path)

    assert cleanup.cleanup_attempted is True
    assert cleanup.cleanup_succeeded is True
    assert cleanup.workspace_path == str(workspace_path)
    assert not workspace_path.exists()


def test_cleanup_worktree_reports_failure_for_non_worktree_directory(tmp_path):
    repo_path = init_git_repo(tmp_path)
    workspace_path = tmp_path / ".worktrees" / "preview-123456789abc"
    workspace_path.mkdir(parents=True)

    cleanup = cleanup_worktree(repo_path=repo_path, workspace_path=workspace_path)

    assert cleanup.cleanup_attempted is True
    assert cleanup.cleanup_succeeded is False
    assert cleanup.cleanup_reason
