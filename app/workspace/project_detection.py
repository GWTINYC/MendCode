import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ProjectDetection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    languages: list[str] = Field(default_factory=list)
    suggested_test: str | None = None


def detect_project(repo_path: Path) -> ProjectDetection:
    languages: list[str] = []
    if _has_python_marker(repo_path):
        languages.append("python")
    if (repo_path / "package.json").exists():
        languages.append("node")

    suggested_test = None
    if "python" in languages:
        suggested_test = "python -m pytest -q"
    elif "node" in languages and _package_has_test_script(repo_path / "package.json"):
        suggested_test = "npm test"

    return ProjectDetection(languages=languages, suggested_test=suggested_test)


def _has_python_marker(repo_path: Path) -> bool:
    return any(
        (repo_path / marker).exists()
        for marker in ["pyproject.toml", "requirements.txt", "setup.py"]
    )


def _package_has_test_script(package_json_path: Path) -> bool:
    try:
        payload = json.loads(package_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    scripts = payload.get("scripts")
    return isinstance(scripts, dict) and isinstance(scripts.get("test"), str)
