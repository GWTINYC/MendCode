from datetime import datetime
from pathlib import Path

from app.repo_map.models import RepoMap, RepoMapEntry

_EXCLUDED_DIRS = frozenset({".git", ".worktrees", "data", "__pycache__"})
_PYTHON_ENTRYPOINT_CANDIDATES = (
    "app/main.py",
    "src/main.py",
    "main.py",
)


def build_repo_map(
    root: Path,
    *,
    max_depth: int = 4,
    max_entries: int = 500,
) -> RepoMap:
    resolved_root = root.resolve()
    entries: list[RepoMapEntry] = []
    total_entries = 0
    truncated = False

    pending: list[tuple[Path, int]] = [(resolved_root, 0)]
    while pending:
        current, depth = pending.pop()
        if depth >= max_depth:
            continue
        try:
            children = sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name))
        except OSError:
            continue

        directories_to_visit: list[Path] = []
        for child in children:
            if child.is_dir() and child.name in _EXCLUDED_DIRS:
                continue
            entry_depth = depth + 1
            total_entries += 1
            if len(entries) < max_entries:
                entries.append(_entry_for(resolved_root, child, entry_depth))
            else:
                truncated = True
            if child.is_dir() and entry_depth < max_depth:
                directories_to_visit.append(child)
        pending.extend((directory, depth + 1) for directory in reversed(directories_to_visit))

    entry_paths = {entry.path for entry in entries}
    test_commands = _infer_test_commands(resolved_root)
    return RepoMap(
        root=str(resolved_root),
        generated_at=datetime.now().astimezone(),
        entries=entries,
        entry_points=_infer_entry_points(resolved_root, entry_paths),
        test_commands=test_commands,
        core_modules=_infer_core_modules(entry_paths),
        metadata={
            "max_depth": max_depth,
            "max_entries": max_entries,
            "total_entries": total_entries,
            "returned_entries": len(entries),
            "truncated": truncated,
            "excluded_dirs": sorted(_EXCLUDED_DIRS),
        },
    )


def _entry_for(root: Path, path: Path, depth: int) -> RepoMapEntry:
    entry_type = "directory" if path.is_dir() else "file"
    if path.is_symlink():
        entry_type = "symlink"
    size_bytes = None
    if path.is_file():
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = None
    return RepoMapEntry(
        path=path.resolve().relative_to(root).as_posix(),
        type=entry_type,
        size_bytes=size_bytes,
        depth=depth,
    )


def _infer_test_commands(root: Path) -> list[str]:
    for marker in ["pyproject.toml", "pytest.ini", "requirements.txt"]:
        if (root / marker).exists():
            return ["python -m pytest -q"]
    return []


def _infer_entry_points(root: Path, entry_paths: set[str]) -> list[str]:
    for candidate in _PYTHON_ENTRYPOINT_CANDIDATES:
        if candidate in entry_paths and (root / candidate).exists():
            return [candidate]
    return []


def _infer_core_modules(entry_paths: set[str]) -> list[str]:
    modules: list[str] = []
    for candidate in ["app", "src"]:
        if candidate in entry_paths:
            modules.append(candidate)
    return modules
