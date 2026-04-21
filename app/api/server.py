from datetime import UTC, datetime

from fastapi import FastAPI

from app import __version__
from app.config.settings import get_settings
from app.core.paths import ensure_data_directories

app = FastAPI(
    title="MendCode API",
    version=__version__,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    settings = get_settings()
    ensure_data_directories(settings)
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "status": "ok",
        "timestamp": datetime.now(UTC).isoformat(),
        "project_root": str(settings.project_root),
        "tasks_dir": str(settings.tasks_dir),
        "traces_dir": str(settings.traces_dir),
    }
