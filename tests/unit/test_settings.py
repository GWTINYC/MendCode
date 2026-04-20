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


def test_ensure_data_directories_creates_missing_directories(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    settings = get_settings()

    created = ensure_data_directories(settings)

    assert created == {
        "data_dir": tmp_path / "data",
        "tasks_dir": tmp_path / "data" / "tasks",
        "traces_dir": tmp_path / "data" / "traces",
    }
    assert all(path.exists() for path in created.values())
