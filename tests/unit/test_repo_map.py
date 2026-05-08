from datetime import UTC, datetime
from pathlib import Path

from app.repo_map.builder import build_repo_map
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


def test_repo_map_builder_identifies_python_project_summary(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (repo / "app" / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (repo / "tests" / "test_main.py").write_text(
        "def test_main():\n    assert True\n",
        encoding="utf-8",
    )

    repo_map = build_repo_map(repo)

    paths = {entry.path for entry in repo_map.entries}
    assert repo_map.root == str(repo)
    assert {"README.md", "pyproject.toml", "app", "app/main.py", "tests/test_main.py"} <= paths
    assert repo_map.entry_points == ["app/main.py"]
    assert repo_map.test_commands == ["python -m pytest -q"]
    assert repo_map.core_modules == ["app"]


def test_repo_map_builder_skips_runtime_data_and_cache_dirs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for ignored in [".git", ".worktrees", "data", "__pycache__"]:
        ignored_path = repo / ignored
        ignored_path.mkdir()
        (ignored_path / "ignored.py").write_text("ignored\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")

    repo_map = build_repo_map(repo)

    paths = {entry.path for entry in repo_map.entries}
    assert "src/module.py" in paths
    assert not any(path.startswith(".git") for path in paths)
    assert not any(path.startswith(".worktrees") for path in paths)
    assert not any(path.startswith("data") for path in paths)
    assert not any("__pycache__" in path for path in paths)


def test_repo_map_builder_limits_depth_and_entries(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "a" / "b" / "c").mkdir(parents=True)
    (repo / "a" / "b" / "c" / "deep.py").write_text("deep\n", encoding="utf-8")
    for index in range(5):
        (repo / f"file_{index}.py").write_text("x\n", encoding="utf-8")

    repo_map = build_repo_map(repo, max_depth=1, max_entries=3)

    assert len(repo_map.entries) == 3
    assert repo_map.metadata["truncated"] is True
    assert repo_map.metadata["max_depth"] == 1
    assert all(entry.depth <= 1 for entry in repo_map.entries)
    assert "a/b/c/deep.py" not in {entry.path for entry in repo_map.entries}


def test_repo_map_builder_handles_non_python_project(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text('{"scripts":{"test":"echo ok"}}\n', encoding="utf-8")

    repo_map = build_repo_map(repo)

    assert repo_map.entries
    assert repo_map.test_commands == []
    assert repo_map.core_modules == []
