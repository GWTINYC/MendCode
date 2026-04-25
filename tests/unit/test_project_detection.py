import json
from pathlib import Path

from app.workspace.project_detection import detect_project


def test_detect_project_suggests_pytest_for_python_markers(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")

    result = detect_project(tmp_path)

    assert result.languages == ["python"]
    assert result.suggested_test == "python -m pytest -q"


def test_detect_project_suggests_npm_test_for_package_test_script(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}}),
        encoding="utf-8",
    )

    result = detect_project(tmp_path)

    assert result.languages == ["node"]
    assert result.suggested_test == "npm test"


def test_detect_project_returns_no_suggestion_without_markers(tmp_path: Path) -> None:
    result = detect_project(tmp_path)

    assert result.languages == []
    assert result.suggested_test is None
