from pathlib import Path

from app.repo_map.models import RepoMap


class RepoMapStore:
    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "repo-map"
        self.latest_path = self.root / "latest.json"

    def save(self, repo_map: RepoMap) -> RepoMap:
        self.root.mkdir(parents=True, exist_ok=True)
        self.latest_path.write_text(
            repo_map.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return repo_map

    def load_latest(self) -> RepoMap | None:
        if not self.latest_path.exists():
            return None
        return RepoMap.model_validate_json(self.latest_path.read_text(encoding="utf-8"))
