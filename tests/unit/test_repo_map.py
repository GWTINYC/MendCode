from datetime import UTC, datetime
from pathlib import Path

from app.repo_map.models import RepoMap, RepoMapEntry
from app.repo_map.store import RepoMapStore


def test_repo_map_model_has_stable_json_shape() -> None:
    generated_at = datetime(2026, 5, 7, 12, 0, tzinfo=UTC)
    repo_map = RepoMap(
        root="/repo",
        generated_at=generated_at,
        entries=[
            RepoMapEntry(
                path="app/main.py",
                type="file",
                size_bytes=120,
                depth=2,
            )
        ],
        entry_points=["app/main.py"],
        test_commands=["python -m pytest -q"],
        core_modules=["app"],
    )

    assert repo_map.model_dump(mode="json") == {
        "root": "/repo",
        "generated_at": "2026-05-07T12:00:00Z",
        "entries": [
            {
                "path": "app/main.py",
                "type": "file",
                "size_bytes": 120,
                "depth": 2,
                "summary": "",
            }
        ],
        "entry_points": ["app/main.py"],
        "test_commands": ["python -m pytest -q"],
        "core_modules": ["app"],
        "metadata": {},
    }


def test_repo_map_store_saves_and_reads_latest_json(tmp_path: Path) -> None:
    generated_at = datetime(2026, 5, 7, 12, 0, tzinfo=UTC)
    repo_map = RepoMap(
        root=str(tmp_path / "repo"),
        generated_at=generated_at,
        entries=[
            RepoMapEntry(path="README.md", type="file", size_bytes=42, depth=1),
        ],
        entry_points=["README.md"],
        test_commands=[],
        core_modules=[],
    )
    store = RepoMapStore(tmp_path / "data")

    saved = store.save(repo_map)
    loaded = store.load_latest()

    assert saved == repo_map
    assert loaded == repo_map
    assert store.latest_path == tmp_path / "data" / "repo-map" / "latest.json"
    assert store.latest_path.exists()


def test_repo_map_store_returns_none_when_latest_is_missing(tmp_path: Path) -> None:
    store = RepoMapStore(tmp_path / "data")

    assert store.load_latest() is None
