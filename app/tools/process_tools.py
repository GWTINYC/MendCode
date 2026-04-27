from __future__ import annotations

from pathlib import Path
from typing import Any

from app.runtime.process_registry import ProcessRegistry, ProcessSnapshot
from app.schemas.agent_action import Observation
from app.tools.arguments import (
    EmptyToolArgs,
    ProcessPollArgs,
    ProcessStartArgs,
    ProcessStopArgs,
    ProcessWriteArgs,
)
from app.tools.observations import tool_observation
from app.tools.structured import ToolExecutionContext
from app.workspace.shell_policy import ShellPolicy

_FALLBACK_REGISTRIES: dict[Path, ProcessRegistry] = {}


def process_start(args: ProcessStartArgs, context: ToolExecutionContext) -> Observation:
    if args.pty:
        return tool_observation(
            tool_name="process_start",
            status="rejected",
            summary="Unable to start process",
            payload={"command": args.command, "pty": args.pty},
            error_message="pty processes are not supported",
        )
    if not args.background:
        return tool_observation(
            tool_name="process_start",
            status="rejected",
            summary="Unable to start process",
            payload={"command": args.command, "background": args.background},
            error_message="process_start only supports background processes",
        )
    cwd = _resolve_workspace_cwd(args.cwd, context.workspace_path)
    if cwd is None:
        return tool_observation(
            tool_name="process_start",
            status="rejected",
            summary="Unable to start process",
            payload={"command": args.command, "cwd": args.cwd},
            error_message="cwd escapes workspace root",
        )
    if not cwd.exists() or not cwd.is_dir():
        return tool_observation(
            tool_name="process_start",
            status="rejected",
            summary="Unable to start process",
            payload={"command": args.command, "cwd": str(cwd)},
            error_message="cwd must exist and be a directory",
        )

    decision = ShellPolicy(
        allowed_root=context.workspace_path,
        timeout_seconds=context.settings.verification_timeout_seconds,
    ).evaluate(args.command, cwd=cwd)
    if not decision.allowed:
        return tool_observation(
            tool_name="process_start",
            status="rejected",
            summary="Process start rejected by shell policy",
            payload={
                "command": args.command,
                "cwd": str(cwd),
                "risk_level": decision.risk_level,
                "reason": decision.reason,
            },
            error_message=decision.reason,
        )

    snapshot = _registry(context).start(
        command=args.command,
        cwd=cwd,
        name=args.name,
        pty=args.pty,
    )
    payload = _snapshot_payload(snapshot)
    return tool_observation(
        tool_name="process_start",
        status="succeeded",
        summary=f"Started process {snapshot.process_id}",
        payload=payload,
        stdout_excerpt=snapshot.stdout_excerpt,
        stderr_excerpt=snapshot.stderr_excerpt,
    )


def process_poll(args: ProcessPollArgs, context: ToolExecutionContext) -> Observation:
    snapshot = _registry(context).poll(
        args.process_id,
        offset=args.offset,
        stdout_offset=args.stdout_offset,
        stderr_offset=args.stderr_offset,
        max_chars=args.max_chars,
    )
    return _snapshot_observation("process_poll", snapshot, f"Polled process {args.process_id}")


def process_write(args: ProcessWriteArgs, context: ToolExecutionContext) -> Observation:
    snapshot = _registry(context).write(args.process_id, args.input)
    return _snapshot_observation("process_write", snapshot, f"Wrote process {args.process_id}")


def process_stop(args: ProcessStopArgs, context: ToolExecutionContext) -> Observation:
    snapshot = _registry(context).stop(args.process_id, signal=args.signal)
    return _snapshot_observation("process_stop", snapshot, f"Stopped process {args.process_id}")


def process_list(args: EmptyToolArgs, context: ToolExecutionContext) -> Observation:
    del args
    snapshots = [_snapshot_payload(snapshot) for snapshot in _registry(context).list()]
    return tool_observation(
        tool_name="process_list",
        status="succeeded",
        summary=f"Listed {len(snapshots)} processes",
        payload={"processes": snapshots},
    )


def _registry(context: ToolExecutionContext) -> Any:
    if context.process_registry is not None:
        return context.process_registry
    log_dir = context.settings.data_dir / "processes"
    resolved_log_dir = log_dir.resolve()
    registry = _FALLBACK_REGISTRIES.get(resolved_log_dir)
    if registry is None:
        registry = ProcessRegistry(log_dir=resolved_log_dir)
        _FALLBACK_REGISTRIES[resolved_log_dir] = registry
    return registry


def _resolve_workspace_cwd(raw_cwd: str, workspace_path: Path) -> Path | None:
    candidate = Path(raw_cwd)
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (workspace_path / candidate).resolve()
    )
    try:
        resolved.relative_to(workspace_path.resolve())
    except ValueError:
        return None
    return resolved


def _snapshot_observation(
    tool_name: str,
    snapshot: ProcessSnapshot,
    summary: str,
) -> Observation:
    observation_status = "succeeded"
    if snapshot.status == "missing":
        observation_status = "failed"
    elif snapshot.error_message is not None:
        observation_status = "failed"
    return tool_observation(
        tool_name=tool_name,
        status=observation_status,
        summary=summary,
        payload=_snapshot_payload(snapshot),
        error_message=snapshot.error_message,
        stdout_excerpt=snapshot.stdout_excerpt,
        stderr_excerpt=snapshot.stderr_excerpt,
    )


def _snapshot_payload(snapshot: ProcessSnapshot) -> dict[str, object]:
    return {"snapshot": snapshot.model_dump(mode="json"), **snapshot.model_dump(mode="json")}
