from os import getenv
from pathlib import Path

from pydantic import BaseModel

from app import APP_NAME, __version__

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    app_name: str
    app_version: str
    project_root: Path
    data_dir: Path
    tasks_dir: Path
    traces_dir: Path


def get_settings() -> Settings:
    root = Path(getenv("MENDCODE_PROJECT_ROOT", Path.cwd())).resolve()
    data_dir = root / "data"
    return Settings(
        app_name=APP_NAME,
        app_version=__version__,
        project_root=root,
        data_dir=data_dir,
        tasks_dir=data_dir / "tasks",
        traces_dir=data_dir / "traces",
    )
