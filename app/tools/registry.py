from app.schemas.agent_action import Observation
from app.tools.arguments import (
    GlobFileSearchArgs,
    ListDirArgs,
    ReadFileArgs,
    RgArgs,
)
from app.tools.read_only import (
    glob_file_search,
    list_dir,
    read_file,
    search_code,
)
from app.tools.schemas import ToolResult
from app.tools.structured import ToolExecutionContext, ToolRegistry, ToolRisk, ToolSpec


def tool_result_to_observation(result: ToolResult) -> Observation:
    status = "succeeded" if result.status == "passed" else result.status
    return Observation(
        status=status,
        summary=result.summary,
        payload=result.payload,
        error_message=result.error_message,
    )


def _execute_read_file(args: ReadFileArgs, context: ToolExecutionContext) -> Observation:
    return tool_result_to_observation(
        read_file(
            context.workspace_path,
            args.path,
            start_line=args.start_line,
            end_line=args.end_line,
            max_chars=args.max_chars,
        )
    )


def _execute_list_dir(args: ListDirArgs, context: ToolExecutionContext) -> Observation:
    return tool_result_to_observation(
        list_dir(
            context.workspace_path,
            args.path,
            max_entries=args.max_entries,
        )
    )


def _execute_glob_file_search(
    args: GlobFileSearchArgs,
    context: ToolExecutionContext,
) -> Observation:
    return tool_result_to_observation(
        glob_file_search(
            context.workspace_path,
            args.pattern,
            max_results=args.max_results,
        )
    )


def _execute_rg(args: RgArgs, context: ToolExecutionContext) -> Observation:
    return tool_result_to_observation(
        search_code(
            context.workspace_path,
            args.query,
            glob=args.glob,
            max_results=args.max_results,
        )
    )


def default_tool_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            ToolSpec(
                name="glob_file_search",
                description="Find repo files using a relative glob pattern.",
                args_model=GlobFileSearchArgs,
                risk_level=ToolRisk.READ_ONLY,
                executor=_execute_glob_file_search,
            ),
            ToolSpec(
                name="list_dir",
                description="List entries in a repo-relative directory.",
                args_model=ListDirArgs,
                risk_level=ToolRisk.READ_ONLY,
                executor=_execute_list_dir,
            ),
            ToolSpec(
                name="read_file",
                description="Read text content from a repo-relative file.",
                args_model=ReadFileArgs,
                risk_level=ToolRisk.READ_ONLY,
                executor=_execute_read_file,
            ),
            ToolSpec(
                name="rg",
                description="Search repo text using ripgrep.",
                args_model=RgArgs,
                risk_level=ToolRisk.READ_ONLY,
                executor=_execute_rg,
            ),
        ]
    )
