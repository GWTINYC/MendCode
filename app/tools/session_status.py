from app.schemas.agent_action import Observation
from app.tools.arguments import SessionStatusArgs
from app.tools.observations import tool_observation
from app.tools.structured import ToolExecutionContext


def session_status(args: SessionStatusArgs, context: ToolExecutionContext) -> Observation:
    payload: dict[str, object] = {
        "repo_path": str(context.settings.project_root),
        "workspace_path": str(context.workspace_path),
        "permission_mode": context.permission_mode,
        "verification_commands": context.verification_commands,
        "pending_confirmation": context.pending_confirmation,
        "trace_path": context.trace_path,
        "run_id": context.run_id,
    }
    if args.include_tools:
        payload["allowed_tools"] = sorted(context.allowed_tools or [])
        payload["available_tools"] = sorted(context.available_tools or [])
        payload["denied_tools"] = sorted(context.denied_tools)
    if args.include_recent_steps:
        payload["recent_steps"] = context.recent_steps[-10:]
    return tool_observation(
        tool_name="session_status",
        status="succeeded",
        summary="Read session status",
        payload=payload,
    )
