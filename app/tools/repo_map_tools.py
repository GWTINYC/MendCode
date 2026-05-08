from app.repo_map.builder import build_repo_map
from app.repo_map.models import RepoMap
from app.repo_map.store import RepoMapStore
from app.schemas.agent_action import Observation
from app.tools.arguments import RepoMapReadArgs, RepoMapRefreshArgs
from app.tools.observations import tool_observation
from app.tools.structured import ToolExecutionContext


def repo_map_refresh(args: RepoMapRefreshArgs, context: ToolExecutionContext) -> Observation:
    repo_map = build_repo_map(
        context.workspace_path,
        max_depth=args.max_depth,
        max_entries=args.max_entries,
    )
    store = RepoMapStore(context.settings.data_dir)
    store.save(repo_map)
    return tool_observation(
        tool_name="repo_map_refresh",
        status="succeeded",
        summary="Refreshed repository map",
        payload={
            **_summary_payload(repo_map, max_entries=0),
            "store_path": str(store.latest_path),
        },
    )


def repo_map_read(args: RepoMapReadArgs, context: ToolExecutionContext) -> Observation:
    store = RepoMapStore(context.settings.data_dir)
    repo_map = store.load_latest()
    if repo_map is None:
        return tool_observation(
            tool_name="repo_map_read",
            status="failed",
            summary="Repository map is not available",
            payload={"store_path": str(store.latest_path)},
            error_message="No repository map found. Run repo_map_refresh first.",
        )
    return tool_observation(
        tool_name="repo_map_read",
        status="succeeded",
        summary="Read repository map",
        payload={
            **_summary_payload(repo_map, max_entries=args.max_entries),
            "store_path": str(store.latest_path),
        },
    )


def _summary_payload(repo_map: RepoMap, *, max_entries: int) -> dict[str, object]:
    entries = [entry.model_dump(mode="json") for entry in repo_map.entries[:max_entries]]
    return {
        "root": repo_map.root,
        "generated_at": repo_map.model_dump(mode="json")["generated_at"],
        "entry_count": len(repo_map.entries),
        "entries": entries,
        "entry_points": repo_map.entry_points,
        "test_commands": repo_map.test_commands,
        "core_modules": repo_map.core_modules,
        "metadata": repo_map.metadata,
    }
