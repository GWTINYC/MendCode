from os import getenv
from pathlib import Path

from pydantic import BaseModel, model_validator

from app import APP_NAME, __version__

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    app_name: str
    app_version: str
    project_root: Path
    data_dir: Path
    tasks_dir: Path
    traces_dir: Path
    evals_dir: Path | None = None
    workspace_root: Path
    verification_timeout_seconds: int
    cleanup_success_workspace: bool

    @model_validator(mode="after")
    def default_evals_dir(self) -> "Settings":
        if self.evals_dir is None:
            self.evals_dir = self.data_dir / "evals"
        return self


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
        evals_dir=data_dir / "evals",
        workspace_root=root / ".worktrees",
        verification_timeout_seconds=60,
        cleanup_success_workspace=False,
    )
