from pathlib import Path

from app.config.settings import get_settings
from app.core.paths import ensure_data_directories


def test_settings_default_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))

    settings = get_settings()

    assert settings.project_root == tmp_path
    assert settings.data_dir == tmp_path / "data"
    assert settings.tasks_dir == tmp_path / "data" / "tasks"
    assert settings.traces_dir == tmp_path / "data" / "traces"
    assert settings.evals_dir == tmp_path / "data" / "evals"


def test_settings_uses_default_project_root_when_env_unset(monkeypatch):
    monkeypatch.delenv("MENDCODE_PROJECT_ROOT", raising=False)

    settings = get_settings()

    assert settings.project_root == Path.cwd().resolve()
    assert settings.data_dir == Path.cwd().resolve() / "data"


def test_ensure_data_directories_creates_missing_directories(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    settings = get_settings()

    created = ensure_data_directories(settings)

    assert created == {
        "data_dir": tmp_path / "data",
        "tasks_dir": tmp_path / "data" / "tasks",
        "traces_dir": tmp_path / "data" / "traces",
        "evals_dir": tmp_path / "data" / "evals",
        "workspace_root": tmp_path / ".worktrees",
    }
    assert all(path.exists() for path in created.values())


def test_settings_exposes_workspace_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))

    settings = get_settings()

    assert settings.workspace_root == tmp_path / ".worktrees"
    assert settings.verification_timeout_seconds == 60
    assert settings.cleanup_success_workspace is False


def test_ensure_data_directories_creates_workspace_root(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    settings = get_settings()

    created = ensure_data_directories(settings)

    assert created["workspace_root"] == tmp_path / ".worktrees"
    assert created["workspace_root"].exists()
