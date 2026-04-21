from pathlib import Path

from app.config.settings import Settings


def ensure_data_directories(settings: Settings) -> dict[str, Path]:
    paths = {
        "data_dir": settings.data_dir,
        "tasks_dir": settings.tasks_dir,
        "traces_dir": settings.traces_dir,
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths
