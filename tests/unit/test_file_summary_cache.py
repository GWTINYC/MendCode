from pathlib import Path

import pytest

from app.memory.file_summary import build_file_summary, summary_record_for_file


def test_build_file_summary_extracts_stable_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = repo / "app.py"
    path.write_text("def run():\n    return 1\n\nclass Worker:\n    pass\n", encoding="utf-8")

    summary = build_file_summary(repo, "app.py")

    assert summary.path == "app.py"
    assert summary.line_count == 5
    assert "def run" in summary.summary
    assert "class Worker" in summary.summary
    assert summary.symbols == ["run", "Worker"]


def test_summary_record_for_file_creates_file_summary_memory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Demo\n\nHello MendCode.\n", encoding="utf-8")

    record = summary_record_for_file(repo, "README.md")

    assert record.kind == "file_summary"
    assert record.title == "File summary: README.md"
    assert record.metadata["path"] == "README.md"
    assert record.metadata["content_sha256"]


def test_build_file_summary_accepts_relative_repo_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    monkeypatch.chdir(repo)

    summary = build_file_summary(Path("."), "app.py")

    assert summary.path == "app.py"
    assert summary.symbols == ["run"]


def test_build_file_summary_rejects_path_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("def outside():\n    return 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="inside repo"):
        build_file_summary(repo, "../outside.py")
