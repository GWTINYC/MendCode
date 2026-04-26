import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_gitignore_covers_runtime_artifacts() -> None:
    contents = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert ".env" in contents
    assert ".worktrees/" in contents
    assert "data/" in contents
    assert ".pytest_cache/" in contents
    assert ".ruff_cache/" in contents
    assert "__pycache__/" in contents
    assert "*.py[cod]" in contents


def test_env_file_is_ignored_but_example_is_trackable() -> None:
    ignored_env = subprocess.run(
        ["git", "check-ignore", ".env"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    ignored_example = subprocess.run(
        ["git", "check-ignore", ".env.example"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert ignored_env.returncode == 0
    assert ignored_example.returncode != 0


def test_repo_does_not_track_python_bytecode() -> None:
    tracked_files = subprocess.run(
        ["git", "ls-files", "*__pycache__*", "*.pyc"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert tracked_files == []
