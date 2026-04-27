import subprocess
from pathlib import Path
from unittest.mock import patch

from app.tools.read_only import glob_file_search, list_dir, read_file, search_code


def test_read_file_returns_full_content(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    target = workspace_path / "notes.txt"
    target.write_text("alpha\nbeta\n", encoding="utf-8")

    result = read_file(workspace_path=workspace_path, relative_path="notes.txt")

    assert result.status == "passed"
    assert result.model_dump() == {
        "tool_name": "read_file",
        "status": "passed",
        "summary": "Read notes.txt",
        "payload": {
            "relative_path": "notes.txt",
            "start_line": 1,
            "end_line": 2,
            "total_lines": 2,
            "content": "alpha\nbeta\n",
            "truncated": False,
        },
        "error_message": None,
        "workspace_path": str(workspace_path),
    }


def test_read_file_returns_requested_line_range(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    target = workspace_path / "notes.txt"
    target.write_text("a\nb\nc\nd\n", encoding="utf-8")

    result = read_file(
        workspace_path=workspace_path,
        relative_path="notes.txt",
        start_line=2,
        end_line=3,
    )

    assert result.status == "passed"
    assert result.payload == {
        "relative_path": "notes.txt",
        "start_line": 2,
        "end_line": 3,
        "total_lines": 4,
        "content": "b\nc\n",
        "truncated": False,
    }


def test_read_file_returns_tail_lines(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    target = workspace_path / "notes.txt"
    target.write_text("a\nb\nc\nd\n", encoding="utf-8")

    result = read_file(
        workspace_path=workspace_path,
        relative_path="notes.txt",
        tail_lines=2,
    )

    assert result.status == "passed"
    assert result.payload == {
        "relative_path": "notes.txt",
        "start_line": 3,
        "end_line": 4,
        "total_lines": 4,
        "content": "c\nd\n",
        "truncated": False,
    }


def test_read_file_rejects_tail_lines_with_explicit_range(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "notes.txt").write_text("a\nb\n", encoding="utf-8")

    result = read_file(
        workspace_path=workspace_path,
        relative_path="notes.txt",
        start_line=1,
        tail_lines=1,
    )

    assert result.status == "rejected"
    assert result.error_message == "tail_lines cannot be combined with start_line or end_line"


def test_read_file_returns_empty_file_as_passed(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "empty.txt").write_text("", encoding="utf-8")

    result = read_file(workspace_path=workspace_path, relative_path="empty.txt")

    assert result.status == "passed"
    assert result.payload == {
        "relative_path": "empty.txt",
        "start_line": 0,
        "end_line": 0,
        "total_lines": 0,
        "content": "",
        "truncated": False,
    }


def test_read_file_truncates_large_content(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    target = workspace_path / "notes.txt"
    target.write_text("abcdef", encoding="utf-8")

    result = read_file(
        workspace_path=workspace_path,
        relative_path="notes.txt",
        max_chars=3,
    )

    assert result.status == "passed"
    assert result.payload["content"] == "abc"
    assert result.payload["truncated"] is True


def test_search_code_falls_back_when_rg_binary_is_unavailable(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "app.py").write_text("alpha\nbeta alpha\n", encoding="utf-8")

    with patch("app.tools.read_only.subprocess.run", side_effect=FileNotFoundError("rg")):
        result = search_code(workspace_path=workspace_path, query="alpha", glob="*.py")

    assert result.status == "passed"
    assert result.payload["total_matches"] == 2
    assert result.payload["matches"] == [
        {"relative_path": "app.py", "line_number": 1, "line_text": "alpha"},
        {"relative_path": "app.py", "line_number": 2, "line_text": "beta alpha"},
    ]


def test_read_file_rejects_missing_path(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()

    result = read_file(workspace_path=workspace_path, relative_path="missing.txt")

    assert result.status == "rejected"
    assert result.error_message == "path does not exist"


def test_read_file_rejects_non_positive_start_line(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "notes.txt").write_text("alpha\nbeta\n", encoding="utf-8")

    result = read_file(
        workspace_path=workspace_path,
        relative_path="notes.txt",
        start_line=0,
    )

    assert result.status == "rejected"
    assert result.error_message == "start_line must be greater than 0"


def test_read_file_rejects_non_positive_end_line(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "notes.txt").write_text("alpha\nbeta\n", encoding="utf-8")

    result = read_file(
        workspace_path=workspace_path,
        relative_path="notes.txt",
        end_line=0,
    )

    assert result.status == "rejected"
    assert result.error_message == "end_line must be greater than 0"


def test_read_file_rejects_start_line_after_end_line(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "notes.txt").write_text("alpha\nbeta\n", encoding="utf-8")

    result = read_file(
        workspace_path=workspace_path,
        relative_path="notes.txt",
        start_line=3,
        end_line=2,
    )

    assert result.status == "rejected"
    assert result.error_message == "start_line cannot be greater than end_line"


def test_read_file_rejects_negative_max_chars(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "notes.txt").write_text("alpha\nbeta\n", encoding="utf-8")

    result = read_file(
        workspace_path=workspace_path,
        relative_path="notes.txt",
        max_chars=-1,
    )

    assert result.status == "rejected"
    assert result.error_message == "max_chars must be greater than or equal to 0"


def test_read_file_rejects_start_line_beyond_file_length(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "notes.txt").write_text("alpha\nbeta\n", encoding="utf-8")

    result = read_file(
        workspace_path=workspace_path,
        relative_path="notes.txt",
        start_line=3,
    )

    assert result.status == "rejected"
    assert result.error_message == "start_line exceeds file length"


def test_read_file_rejects_end_line_beyond_file_length(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "notes.txt").write_text("alpha\nbeta\n", encoding="utf-8")

    result = read_file(
        workspace_path=workspace_path,
        relative_path="notes.txt",
        end_line=3,
    )

    assert result.status == "rejected"
    assert result.error_message == "end_line exceeds file length"


def test_list_dir_returns_sorted_directory_entries(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "b.txt").write_text("beta\n", encoding="utf-8")
    (workspace_path / "src").mkdir()
    (workspace_path / "src" / "a.py").write_text("alpha\n", encoding="utf-8")

    result = list_dir(workspace_path=workspace_path, relative_path=".")

    assert result.status == "passed"
    assert result.payload == {
        "relative_path": ".",
        "total_entries": 2,
        "truncated": False,
        "entries": [
            {"relative_path": "b.txt", "name": "b.txt", "type": "file", "size_bytes": 5},
            {"relative_path": "src", "name": "src", "type": "directory", "size_bytes": None},
        ],
    }


def test_list_dir_rejects_path_escape(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()

    result = list_dir(workspace_path=workspace_path, relative_path="../outside")

    assert result.status == "rejected"
    assert result.error_message == "path escapes workspace root"


def test_glob_file_search_returns_matching_files(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "src").mkdir()
    (workspace_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (workspace_path / "src" / "notes.md").write_text("# notes\n", encoding="utf-8")

    result = glob_file_search(workspace_path=workspace_path, pattern="**/*.py")

    assert result.status == "passed"
    assert result.payload == {
        "pattern": "**/*.py",
        "total_matches": 1,
        "truncated": False,
        "matches": [
            {"relative_path": "src/app.py", "type": "file", "size_bytes": 12},
        ],
    }


def test_glob_file_search_rejects_absolute_patterns(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()

    result = glob_file_search(workspace_path=workspace_path, pattern="/tmp/*.py")

    assert result.status == "rejected"
    assert result.error_message == "pattern must be relative"


def test_search_code_returns_matches(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "src.py").write_text("alpha\nbeta alpha\n", encoding="utf-8")

    result = search_code(workspace_path=workspace_path, query="alpha")

    assert result.status == "passed"
    assert result.model_dump() == {
        "tool_name": "search_code",
        "status": "passed",
        "summary": "Searched for alpha",
        "payload": {
            "query": "alpha",
            "glob": None,
            "total_matches": 2,
            "matches": [
                {"relative_path": "src.py", "line_number": 1, "line_text": "alpha"},
                {"relative_path": "src.py", "line_number": 2, "line_text": "beta alpha"},
            ],
        },
        "error_message": None,
        "workspace_path": str(workspace_path),
    }


def test_search_code_rejects_empty_query(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()

    result = search_code(workspace_path=workspace_path, query="")

    assert result.status == "rejected"
    assert result.error_message == "query must not be empty"


def test_search_code_rejects_empty_query_preserves_glob(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()

    result = search_code(workspace_path=workspace_path, query="", glob="*.py")

    assert result.status == "rejected"
    assert result.payload == {
        "query": "",
        "glob": "*.py",
        "total_matches": 0,
        "matches": [],
    }
    assert result.error_message == "query must not be empty"


def test_search_code_treats_query_as_literal_string(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "src.py").write_text("arr[0] = 1\n", encoding="utf-8")

    result = search_code(workspace_path=workspace_path, query="arr[0]")

    assert result.status == "passed"
    assert result.payload == {
        "query": "arr[0]",
        "glob": None,
        "total_matches": 1,
        "matches": [{"relative_path": "src.py", "line_number": 1, "line_text": "arr[0] = 1"}],
    }


def test_search_code_applies_glob_filter(tmp_path: Path, monkeypatch) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    calls: list[tuple[list[str], Path]] = []

    def fake_run(command, cwd, capture_output, text, check):
        calls.append((command, cwd))
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="src.py:1:alpha\n",
            stderr="",
        )

    monkeypatch.setattr("app.tools.read_only.subprocess.run", fake_run)

    result = search_code(workspace_path=workspace_path, query="alpha", glob="*.py")

    assert result.status == "passed"
    assert calls == [
        (
            ["rg", "--fixed-strings", "--line-number", "--no-heading", "--glob", "*.py", "alpha"],
            workspace_path,
        )
    ]
    assert result.payload == {
        "query": "alpha",
        "glob": "*.py",
        "total_matches": 1,
        "matches": [{"relative_path": "src.py", "line_number": 1, "line_text": "alpha"}],
    }


def test_search_code_limits_results(tmp_path: Path, monkeypatch) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()

    def fake_run(command, cwd, capture_output, text, check):
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="src.py:1:alpha\nsrc.py:2:alpha\nsrc.py:3:alpha\n",
            stderr="",
        )

    monkeypatch.setattr("app.tools.read_only.subprocess.run", fake_run)

    result = search_code(workspace_path=workspace_path, query="alpha", max_results=2)

    assert result.status == "passed"
    assert result.payload["total_matches"] == 3
    assert result.payload["matches"] == [
        {"relative_path": "src.py", "line_number": 1, "line_text": "alpha"},
        {"relative_path": "src.py", "line_number": 2, "line_text": "alpha"},
    ]


def test_search_code_rejects_negative_max_results(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()

    result = search_code(workspace_path=workspace_path, query="alpha", max_results=-1)

    assert result.status == "rejected"
    assert result.payload == {
        "query": "alpha",
        "glob": None,
        "total_matches": 0,
        "matches": [],
    }
    assert result.error_message == "max_results must be greater than or equal to 0"


def test_search_code_returns_no_matches_as_passed(tmp_path: Path, monkeypatch) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()

    def fake_run(command, cwd, capture_output, text, check):
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr("app.tools.read_only.subprocess.run", fake_run)

    result = search_code(workspace_path=workspace_path, query="alpha")

    assert result.status == "passed"
    assert result.payload == {
        "query": "alpha",
        "glob": None,
        "total_matches": 0,
        "matches": [],
    }
