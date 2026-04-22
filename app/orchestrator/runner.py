import subprocess
from pathlib import Path
from uuid import uuid4

from app.config.settings import Settings
from app.orchestrator.fixed_flow import load_fixed_flow_artifacts, summarize_tool_result
from app.schemas.run_state import RunState
from app.schemas.task import TaskSpec
from app.schemas.trace import TraceEvent
from app.schemas.verification import VerificationCommandResult, VerificationResult
from app.tools.patch import apply_patch
from app.tools.read_only import read_file, search_code
from app.tools.schemas import ToolResult
from app.tracing.recorder import TraceRecorder
from app.workspace.command_policy import CommandPolicy
from app.workspace.executor import execute_verification_command
from app.workspace.worktree import WorkspaceCleanupResult, cleanup_worktree, prepare_worktree


def _record_tool_started(recorder: TraceRecorder, run_id: str, tool_name: str, workspace_path: Path) -> Path:
    return recorder.record(
        TraceEvent(
            run_id=run_id,
            event_type="run.tool.started",
            message=f"Started tool {tool_name}",
            payload={"tool_name": tool_name, "workspace_path": str(workspace_path)},
        )
    )


def _record_tool_completed(recorder: TraceRecorder, run_id: str, result: ToolResult) -> Path:
    return recorder.record(
        TraceEvent(
            run_id=run_id,
            event_type="run.tool.completed",
            message=f"Completed tool {result.tool_name}",
            payload=summarize_tool_result(result) | {"workspace_path": result.workspace_path},
        )
    )


def run_task_preview(task: TaskSpec, settings: Settings) -> RunState:
    recorder = TraceRecorder(settings.traces_dir)
    run_id = f"preview-{uuid4().hex[:12]}"
    repo_path = Path(task.repo_path)
    workspace_path: Path | None = None

    try:
        workspace_path = prepare_worktree(
            repo_path=repo_path,
            workspace_root=settings.workspace_root,
            run_id=run_id,
            base_ref=task.base_ref,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        trace_path = recorder.record(
            TraceEvent(
                run_id=run_id,
                event_type="run.started",
                message="Started task preview run",
                payload={
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "status": "running",
                    "summary": "Task preview started",
                    "workspace_path": None,
                },
            )
        )
        failure_detail = str(exc)
        if isinstance(exc, subprocess.CalledProcessError):
            failure_detail = exc.stderr or exc.stdout or str(exc)
        summary = f"Workspace setup failed: {failure_detail.strip()}"
        trace_path = recorder.record(
            TraceEvent(
                run_id=run_id,
                event_type="run.workspace.cleanup",
                message="Recorded workspace cleanup decision",
                payload={
                    "workspace_path": None,
                    "cleanup_attempted": False,
                    "cleanup_succeeded": False,
                    "cleanup_reason": "workspace not created",
                },
            )
        )
        trace_path = recorder.record(
            TraceEvent(
                run_id=run_id,
                event_type="run.completed",
                message="Completed task preview run",
                payload={
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "status": "failed",
                    "summary": summary,
                    "workspace_path": None,
                },
            )
        )
        return RunState(
            run_id=run_id,
            task_id=task.task_id,
            task_type=task.task_type,
            status="failed",
            current_step="summarize",
            summary=summary,
            trace_path=str(trace_path),
            workspace_path=None,
            verification=None,
        )

    trace_path = recorder.record(
        TraceEvent(
            run_id=run_id,
            event_type="run.started",
            message="Started task preview run",
            payload={
                "task_id": task.task_id,
                "task_type": task.task_type,
                "status": "running",
                "summary": "Task preview started",
                "workspace_path": str(workspace_path),
            },
        )
    )
    trace_path = recorder.record(
        TraceEvent(
            run_id=run_id,
            event_type="run.verification.started",
            message="Started verification commands",
            payload={
                "task_id": task.task_id,
                "task_type": task.task_type,
                "command_count": len(task.verification_commands),
                "status": "running",
                "workspace_path": str(workspace_path),
            },
        )
    )

    command_results: list[VerificationCommandResult] = []
    policy = CommandPolicy(
        allowed_commands=task.verification_commands,
        allowed_root=workspace_path,
        timeout_seconds=settings.verification_timeout_seconds,
    )

    if not task.verification_commands:
        command_results.append(
            VerificationCommandResult(
                command="<none>",
                exit_code=-1,
                status="failed",
                duration_ms=0,
                stdout_excerpt="",
                stderr_excerpt="no verification commands provided",
                timed_out=False,
                rejected=False,
                cwd=str(workspace_path),
            )
        )
    else:
        for command in task.verification_commands:
            command_result = execute_verification_command(
                command=command,
                cwd=workspace_path,
                policy=policy,
            )
            command_results.append(command_result)

            trace_path = recorder.record(
                TraceEvent(
                    run_id=run_id,
                    event_type="run.verification.command.completed",
                    message="Completed verification command",
                    payload={
                        "task_id": task.task_id,
                        "task_type": task.task_type,
                        "command": command_result.command,
                        "exit_code": command_result.exit_code,
                        "status": command_result.status,
                        "duration_ms": command_result.duration_ms,
                        "stdout_excerpt": command_result.stdout_excerpt,
                        "stderr_excerpt": command_result.stderr_excerpt,
                        "timed_out": command_result.timed_out,
                        "rejected": command_result.rejected,
                        "cwd": command_result.cwd,
                    },
                )
            )

    failed_count = sum(1 for result in command_results if result.status != "passed")
    passed_count = len(command_results) - failed_count
    verification = VerificationResult(
        status="passed" if failed_count == 0 else "failed",
        command_results=command_results,
        passed_count=passed_count,
        failed_count=failed_count,
    )

    run_status = "completed" if verification.status == "passed" else "failed"
    if not task.verification_commands:
        summary = "Verification failed: no verification commands provided"
    elif verification.status == "passed":
        summary = (
            "Verification passed: "
            f"{verification.passed_count}/{len(command_results)} commands succeeded"
        )
    else:
        summary = (
            "Verification failed: "
            f"{verification.failed_count} of {len(command_results)} commands failed"
        )

    cleanup = WorkspaceCleanupResult(
        workspace_path=str(workspace_path),
        cleanup_attempted=False,
        cleanup_succeeded=False,
        cleanup_reason="workspace preserved",
    )
    if run_status == "completed" and settings.cleanup_success_workspace:
        cleanup = cleanup_worktree(repo_path=repo_path, workspace_path=workspace_path)
        if not cleanup.cleanup_succeeded:
            summary = f"{summary}; workspace cleanup failed: {cleanup.cleanup_reason}"

    trace_path = recorder.record(
        TraceEvent(
            run_id=run_id,
            event_type="run.workspace.cleanup",
            message="Recorded workspace cleanup decision",
            payload=cleanup.model_dump(mode="json"),
        )
    )
    trace_path = recorder.record(
        TraceEvent(
            run_id=run_id,
            event_type="run.completed",
            message="Completed task preview run",
            payload={
                "task_id": task.task_id,
                "task_type": task.task_type,
                "status": run_status,
                "summary": summary,
                "workspace_path": str(workspace_path),
            },
        )
    )

    return RunState(
        run_id=run_id,
        task_id=task.task_id,
        task_type=task.task_type,
        status=run_status,
        current_step="summarize",
        summary=summary,
        trace_path=str(trace_path),
        workspace_path=str(workspace_path),
        verification=verification,
    )
