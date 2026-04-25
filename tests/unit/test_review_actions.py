import subprocess
from pathlib import Path

from app.workspace.review_actions import (
    apply_worktree_changes,
    discard_worktree,
    view_trace,
    view_worktree_diff,
)
from app.workspace.worktree import prepare_worktree


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
    (repo_path / "calculator.py").write_text(
        "def add(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "calculator.py"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add calculator"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return repo_path


def prepare_changed_worktree(repo_path: Path, tmp_path: Path) -> Path:
    workspace_path = prepare_worktree(
        repo_path=repo_path,
        workspace_root=tmp_path / ".worktrees",
        run_id="agent-review",
        base_ref=None,
    )
    (workspace_path / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n",
        encoding="utf-8",
    )
    return workspace_path


def test_apply_worktree_changes_applies_clean_diff_to_main_workspace(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    workspace_path = prepare_changed_worktree(repo_path, tmp_path)

    result = apply_worktree_changes(repo_path=repo_path, workspace_path=workspace_path)

    assert result.status == "succeeded"
    assert result.action == "apply"
    assert result.payload["changed_files"] == ["calculator.py"]
    assert (repo_path / "calculator.py").read_text(encoding="utf-8") == (
        "def add(a, b):\n    return a + b\n"
    )


def test_apply_worktree_changes_rejects_dirty_main_workspace(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    workspace_path = prepare_changed_worktree(repo_path, tmp_path)
    (repo_path / "local.txt").write_text("local change\n", encoding="utf-8")

    result = apply_worktree_changes(repo_path=repo_path, workspace_path=workspace_path)

    assert result.status == "rejected"
    assert "main workspace has uncommitted changes" in result.error_message
    assert (repo_path / "calculator.py").read_text(encoding="utf-8") == (
        "def add(a, b):\n    return a - b\n"
    )
    assert workspace_path.exists()


def test_discard_worktree_removes_registered_worktree(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    workspace_path = prepare_changed_worktree(repo_path, tmp_path)

    result = discard_worktree(repo_path=repo_path, workspace_path=workspace_path)

    assert result.status == "succeeded"
    assert result.action == "discard"
    assert not workspace_path.exists()


def test_view_worktree_diff_returns_stat_and_full_diff(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    workspace_path = prepare_changed_worktree(repo_path, tmp_path)

    result = view_worktree_diff(workspace_path=workspace_path)

    assert result.status == "succeeded"
    assert result.payload["changed_files"] == ["calculator.py"]
    assert "calculator.py" in result.payload["diff_stat"]
    assert "-    return a - b" in result.payload["diff"]
    assert "+    return a + b" in result.payload["diff"]


def test_view_trace_truncates_long_trace_content(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text("x" * 50, encoding="utf-8")

    result = view_trace(trace_path=trace_path, max_chars=12)

    assert result.status == "succeeded"
    assert result.payload["content"] == "x" * 12
    assert result.payload["truncated"] is True


def test_view_trace_fails_when_trace_path_is_missing(tmp_path: Path) -> None:
    result = view_trace(trace_path=tmp_path / "missing.jsonl")

    assert result.status == "failed"
    assert "trace file does not exist" in result.error_message
