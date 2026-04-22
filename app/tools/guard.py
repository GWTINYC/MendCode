from pathlib import Path


def resolve_workspace_path(workspace_path: Path, relative_path: str) -> Path:
    workspace_root = workspace_path.resolve()
    candidate = (workspace_root / relative_path).resolve()

    try:
        candidate.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("path escapes workspace root") from exc

    return candidate


def resolve_workspace_file(workspace_path: Path, relative_path: str) -> Path:
    candidate = resolve_workspace_path(workspace_path, relative_path)

    if not candidate.exists():
        raise ValueError("path does not exist")
    if candidate.is_dir():
        raise ValueError("path points to a directory")

    return candidate
