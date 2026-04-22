from pathlib import Path

from app.tools.patch import apply_patch


def test_apply_patch_replaces_single_match(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    target = workspace_path / "notes.txt"
    target.write_text("alpha\nbeta\n", encoding="utf-8")

    result = apply_patch(
        workspace_path=workspace_path,
        relative_path="notes.txt",
        old_text="beta",
        new_text="gamma",
    )

    assert result.status == "passed"
    assert result.payload == {
        "relative_path": "notes.txt",
        "replacements_applied": 1,
        "replace_all": False,
    }
    assert target.read_text(encoding="utf-8") == "alpha\ngamma\n"


def test_apply_patch_rejects_empty_old_text(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "notes.txt").write_text("alpha\nbeta\n", encoding="utf-8")

    result = apply_patch(
        workspace_path=workspace_path,
        relative_path="notes.txt",
        old_text="",
        new_text="gamma",
    )

    assert result.status == "rejected"
    assert result.error_message == "old_text must not be empty"


def test_apply_patch_rejects_missing_target_text(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    target = workspace_path / "notes.txt"
    target.write_text("alpha\nbeta\n", encoding="utf-8")

    result = apply_patch(
        workspace_path=workspace_path,
        relative_path="notes.txt",
        old_text="delta",
        new_text="gamma",
    )

    assert result.status == "rejected"
    assert result.error_message == "target text not found"
    assert target.read_text(encoding="utf-8") == "alpha\nbeta\n"


def test_apply_patch_rejects_ambiguous_match_without_replace_all(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    target = workspace_path / "notes.txt"
    target.write_text("beta\nbeta\n", encoding="utf-8")

    result = apply_patch(
        workspace_path=workspace_path,
        relative_path="notes.txt",
        old_text="beta",
        new_text="gamma",
    )

    assert result.status == "rejected"
    assert result.error_message == "target text matched multiple locations"
    assert target.read_text(encoding="utf-8") == "beta\nbeta\n"


def test_apply_patch_replaces_all_matches_when_requested(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    target = workspace_path / "notes.txt"
    target.write_text("beta\nbeta\n", encoding="utf-8")

    result = apply_patch(
        workspace_path=workspace_path,
        relative_path="notes.txt",
        old_text="beta",
        new_text="gamma",
        replace_all=True,
    )

    assert result.status == "passed"
    assert result.payload == {
        "relative_path": "notes.txt",
        "replacements_applied": 2,
        "replace_all": True,
    }
    assert target.read_text(encoding="utf-8") == "gamma\ngamma\n"
