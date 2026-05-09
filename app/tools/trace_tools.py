from pathlib import Path

from app.runtime.session_store import SessionNotFoundError, SessionStore
from app.schemas.agent_action import Observation
from app.tools.arguments import TraceSummaryReadArgs
from app.tools.observations import tool_observation
from app.tools.structured import ToolExecutionContext


def trace_summary_read(args: TraceSummaryReadArgs, context: ToolExecutionContext) -> Observation:
    store = SessionStore(data_dir=context.settings.data_dir)
    trace_path = (
        Path(context.trace_path)
        if context.trace_path and args.session_id is None
        else None
    )
    try:
        summary = store.read_trace_summary(
            args.session_id,
            trace_path=trace_path,
            max_tool_events=args.max_tool_events,
            max_excerpt_chars=args.max_excerpt_chars,
        )
    except SessionNotFoundError as exc:
        return tool_observation(
            tool_name="trace_summary_read",
            status="failed",
            summary="Unable to read trace summary",
            payload={"session_id": args.session_id},
            error_message=str(exc),
        )
    except (OSError, ValueError) as exc:
        return tool_observation(
            tool_name="trace_summary_read",
            status="failed",
            summary="Unable to read trace summary",
            payload={"session_id": args.session_id},
            error_message=str(exc),
        )
    return tool_observation(
        tool_name="trace_summary_read",
        status="succeeded",
        summary=f"Read {len(summary.tool_events)} recent trace tool events",
        payload={
            "event_count": summary.event_count,
            "tool_names": summary.tool_names,
            "failed_tools": summary.failed_tools,
            "tool_events": summary.tool_events,
            "truncated": summary.truncated,
        },
        truncated=summary.truncated,
    )
