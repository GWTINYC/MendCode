from pathlib import Path

from pydantic import ValidationError

from app.memory.file_summary import build_file_summary, summary_record_for_file
from app.memory.models import MemoryKind, MemoryRecord
from app.memory.store import MemoryStore
from app.runtime.trace_analyzer import analyze_trace
from app.schemas.agent_action import Observation
from app.tools.arguments import (
    FileSummaryReadArgs,
    FileSummaryRefreshArgs,
    MemorySearchArgs,
    MemoryWriteArgs,
    TraceAnalyzeArgs,
)
from app.tools.observations import tool_observation
from app.tools.structured import ToolExecutionContext

_VALID_MEMORY_KINDS = frozenset(
    {
        "project_fact",
        "task_state",
        "file_summary",
        "failure_lesson",
        "trace_insight",
    }
)


def memory_search(args: MemorySearchArgs, context: ToolExecutionContext) -> Observation:
    invalid_kinds = sorted(set(args.kinds) - _VALID_MEMORY_KINDS)
    if invalid_kinds:
        return tool_observation(
            tool_name="memory_search",
            status="rejected",
            summary="Invalid memory kinds",
            payload={"invalid_kinds": invalid_kinds},
            error_message=f"invalid memory kinds: {', '.join(invalid_kinds)}",
        )
    store = _memory_store(context)
    kinds: set[MemoryKind] | None = set(args.kinds) if args.kinds else None  # type: ignore[assignment]
    results = store.search(
        query=args.query,
        kinds=kinds,
        tags=set(args.tags) if args.tags else None,
        limit=args.limit,
    )
    matches = [
        {
            "id": result.record.id,
            "kind": result.record.kind,
            "title": result.record.title,
            "content_excerpt": result.record.content[:1200],
            "tags": result.record.tags,
            "score": result.score,
        }
        for result in results
    ]
    return tool_observation(
        tool_name="memory_search",
        status="succeeded",
        summary=f"Found {len(matches)} memory records",
        payload={"total_matches": len(matches), "matches": matches},
    )


def memory_write(args: MemoryWriteArgs, context: ToolExecutionContext) -> Observation:
    store = _memory_store(context)
    duplicate = _duplicate_memory_record(
        store,
        kind=args.kind,
        title=args.title,
        content=args.content,
    )
    if duplicate is not None:
        return tool_observation(
            tool_name="memory_write",
            status="rejected",
            summary="Duplicate memory record",
            payload={"existing_id": duplicate.id, "kind": duplicate.kind, "title": duplicate.title},
            error_message="duplicate memory record already exists",
        )
    try:
        record = MemoryRecord(
            kind=args.kind,  # type: ignore[arg-type]
            title=args.title,
            content=args.content,
            source=args.source,
            tags=args.tags,
            metadata=args.metadata,
        )
    except ValidationError as exc:
        return tool_observation(
            tool_name="memory_write",
            status="rejected",
            summary="Invalid memory record",
            payload=args.model_dump(mode="json"),
            error_message=str(exc),
        )
    written = store.append(record)
    return tool_observation(
        tool_name="memory_write",
        status="succeeded",
        summary="Wrote memory record",
        payload={"id": written.id, "kind": written.kind, "title": written.title},
    )


def file_summary_refresh(
    args: FileSummaryRefreshArgs,
    context: ToolExecutionContext,
) -> Observation:
    store = _memory_store(context)
    try:
        record = store.append(summary_record_for_file(context.workspace_path, args.path))
    except (OSError, ValueError) as exc:
        return tool_observation(
            tool_name="file_summary_refresh",
            status="failed",
            summary=f"Unable to refresh file summary for {args.path}",
            payload={"path": args.path},
            error_message=str(exc),
        )
    return tool_observation(
        tool_name="file_summary_refresh",
        status="succeeded",
        summary=f"Refreshed file summary for {args.path}",
        payload={"id": record.id, **record.metadata},
    )


def file_summary_read(args: FileSummaryReadArgs, context: ToolExecutionContext) -> Observation:
    store = _memory_store(context)
    try:
        current_summary = build_file_summary(context.workspace_path, args.path)
    except (OSError, ValueError) as exc:
        return tool_observation(
            tool_name="file_summary_read",
            status="failed",
            summary=f"Unable to read file summary for {args.path}",
            payload={"path": args.path},
            error_message=str(exc),
        )
    results = [
        record
        for record in store.list_records()
        if record.kind == "file_summary" and record.metadata.get("path") == current_summary.path
    ]
    if results:
        record = results[-1]
        if record.metadata.get("content_sha256") == current_summary.content_sha256:
            return tool_observation(
                tool_name="file_summary_read",
                status="succeeded",
                summary=f"Read cached file summary for {args.path}",
                payload={**record.metadata, "summary": record.content},
            )
    return tool_observation(
        tool_name="file_summary_read",
        status="succeeded",
        summary=f"Built file summary for {args.path}",
        payload=current_summary.model_dump(mode="json"),
    )


def trace_analyze(args: TraceAnalyzeArgs, context: ToolExecutionContext) -> Observation:
    if args.write_memory:
        return tool_observation(
            tool_name="trace_analyze",
            status="rejected",
            summary="trace_analyze is read-only",
            payload={"trace_path": args.trace_path, "write_memory": args.write_memory},
            error_message="write_memory is not allowed on read-only trace_analyze",
        )
    store = _memory_store(context)
    trace_path = Path(args.trace_path)
    if not trace_path.is_absolute():
        trace_path = context.settings.traces_dir / trace_path
    try:
        resolved_trace_path = trace_path.resolve()
        resolved_traces_dir = context.settings.traces_dir.resolve()
        resolved_trace_path.relative_to(resolved_traces_dir)
    except ValueError:
        return tool_observation(
            tool_name="trace_analyze",
            status="rejected",
            summary="trace_analyze path must stay inside traces_dir",
            payload={"trace_path": args.trace_path},
            error_message="trace_path must stay inside settings.traces_dir",
        )
    try:
        insight = analyze_trace(resolved_trace_path)
    except OSError as exc:
        return tool_observation(
            tool_name="trace_analyze",
            status="failed",
            summary="Unable to analyze trace",
            payload={"trace_path": args.trace_path},
            error_message=str(exc),
        )
    memory_id = None
    if args.write_memory and insight is not None:
        memory_id = store.append(insight).id
    return tool_observation(
        tool_name="trace_analyze",
        status="succeeded" if insight else "rejected",
        summary="Analyzed trace" if insight else "No trace insight found",
        payload={
            "memory_id": memory_id,
            "insight": insight.model_dump(mode="json") if insight else None,
        },
        error_message=None if insight else "no trace insight found",
    )


def _memory_store(context: ToolExecutionContext) -> MemoryStore:
    if isinstance(context.memory_store, MemoryStore):
        return context.memory_store
    return MemoryStore(context.settings.data_dir / "memory")


def _duplicate_memory_record(
    store: MemoryStore,
    *,
    kind: str,
    title: str,
    content: str,
) -> MemoryRecord | None:
    normalized_title = " ".join(title.casefold().split())
    normalized_content = " ".join(content.casefold().split())
    for record in store.list_records():
        if record.kind != kind:
            continue
        if " ".join(record.title.casefold().split()) != normalized_title:
            continue
        if " ".join(record.content.casefold().split()) != normalized_content:
            continue
        return record
    return None
