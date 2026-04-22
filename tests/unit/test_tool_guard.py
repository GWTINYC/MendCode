from pathlib import Path

from app.tools.guard import resolve_workspace_file


def test_resolve_workspace_file_returns_file_path_inside_workspace(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    file_path = workspace_root / "notes.txt"
    file_path.write_text("hello\n", encoding="utf-8")

    result = resolve_workspace_file(workspace_root, "notes.txt")

    assert result == file_path


def test_resolve_workspace_file_rejects_parent_escape(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    try:
        resolve_workspace_file(workspace_root, "../escape.txt")
    except ValueError as exc:
        assert str(exc) == "path escapes workspace root"
    else:
        raise AssertionError("expected ValueError")


def test_resolve_workspace_file_rejects_missing_path(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    try:
        resolve_workspace_file(workspace_root, "missing.txt")
    except ValueError as exc:
        assert str(exc) == "path does not exist"
    else:
        raise AssertionError("expected ValueError")


def test_resolve_workspace_file_rejects_directory_path(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "notes").mkdir()

    try:
        resolve_workspace_file(workspace_root, "notes")
    except ValueError as exc:
        assert str(exc) == "path points to a directory"
    else:
        raise AssertionError("expected ValueError")
