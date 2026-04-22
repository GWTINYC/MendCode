import subprocess
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

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


def _fixed_flow_validation_summary(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Fixed-flow input invalid"

    error = errors[0]
    context_error = error.get("ctx", {}).get("error")
    if context_error is not None:
        message = str(context_error)
    else:
        message = str(error.get("msg", "fixed-flow input invalid"))
        prefix = "Value error, "
        if message.startswith(prefix):
            message = message[len(prefix) :]
    return f"Fixed-flow input invalid: {message}"


def _build_run_state(
    *,
    run_id: str,
    task: TaskSpec,
    trace_path: Path,
    workspace_path: Path | None,
    status: str,
    summary: str,
    verification: VerificationResult | None,
    selected_files: list[str],
    applied_patch: bool,
    tool_results: list[dict[str, object]],
) -> RunState:
    return RunState(
        run_id=run_id,
        task_id=task.task_id,
        task_type=task.task_type,
        status=status,
        current_step="summarize",
        summary=summary,
        trace_path=str(trace_path),
        workspace_path=str(workspace_path) if workspace_path is not None else None,
        selected_files=selected_files,
        applied_patch=applied_patch,
        tool_results=tool_results,
        verification=verification,
    )


def _has_fixed_flow_artifacts(entry_artifacts: dict[str, object]) -> bool:
    return bool(
        {
            "search_query",
            "target_path_glob",
            "read_target_path",
            "read_start_line",
            "read_end_line",
            "old_text",
            "new_text",
            "expected_verification_hint",
        }
        & set(entry_artifacts)
    )


def _finalize_run_state(
    *,
    recorder: TraceRecorder,
    run_id: str,
    task: TaskSpec,
    trace_path: Path,
    repo_path: Path,
    workspace_path: Path | None,
    status: str,
    summary: str,
    verification: VerificationResult | None,
    selected_files: list[str],
    applied_patch: bool,
    tool_results: list[dict[str, object]],
    cleanup_success_workspace: bool,
) -> RunState:
    cleanup = WorkspaceCleanupResult(
        workspace_path=str(workspace_path) if workspace_path is not None else None,
        cleanup_attempted=False,
        cleanup_succeeded=False,
        cleanup_reason="workspace preserved" if workspace_path is not None else "workspace not created",
    )
    if (
        status == "completed"
        and workspace_path is not None
        and cleanup_success_workspace
    ):
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
                "status": status,
                "summary": summary,
                "workspace_path": str(workspace_path) if workspace_path is not None else None,
            },
        )
    )
    return _build_run_state(
        run_id=run_id,
        task=task,
        trace_path=trace_path,
        workspace_path=workspace_path,
        status=status,
        summary=summary,
        verification=verification,
        selected_files=selected_files,
        applied_patch=applied_patch,
        tool_results=tool_results,
    )


def run_task_preview(task: TaskSpec, settings: Settings) -> RunState:
    recorder = TraceRecorder(settings.traces_dir)
    run_id = f"preview-{uuid4().hex[:12]}"
    repo_path = Path(task.repo_path)
    workspace_path: Path | None = None
    selected_files: list[str] = []
    applied_patch = False
    tool_results: list[dict[str, object]] = []

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
        return _build_run_state(
            run_id=run_id,
            task=task,
            trace_path=trace_path,
            workspace_path=None,
            status="failed",
            summary=summary,
            verification=None,
            selected_files=selected_files,
            applied_patch=applied_patch,
            tool_results=tool_results,
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

    if task.entry_artifacts and _has_fixed_flow_artifacts(task.entry_artifacts):
        try:
            artifacts = load_fixed_flow_artifacts(task.entry_artifacts)
        except ValidationError as exc:
            return _finalize_run_state(
                recorder=recorder,
                run_id=run_id,
                task=task,
                trace_path=trace_path,
                repo_path=repo_path,
                workspace_path=workspace_path,
                status="failed",
                summary=_fixed_flow_validation_summary(exc),
                verification=None,
                selected_files=selected_files,
                applied_patch=applied_patch,
                tool_results=tool_results,
                cleanup_success_workspace=settings.cleanup_success_workspace,
            )

        if artifacts.read_target_path is not None:
            selected_files = [artifacts.read_target_path]
        else:
            trace_path = _record_tool_started(recorder, run_id, "search_code", workspace_path)
            search_result = search_code(
                workspace_path=workspace_path,
                query=artifacts.search_query or "",
                glob=artifacts.target_path_glob,
                max_results=2,
            )
            tool_results.append(summarize_tool_result(search_result))
            trace_path = _record_tool_completed(recorder, run_id, search_result)
            if search_result.status != "passed":
                return _finalize_run_state(
                    recorder=recorder,
                    run_id=run_id,
                    task=task,
                    trace_path=trace_path,
                    repo_path=repo_path,
                    workspace_path=workspace_path,
                    status="failed",
                    summary=f"Fixed-flow failed: {search_result.summary}",
                    verification=None,
                    selected_files=selected_files,
                    applied_patch=applied_patch,
                    tool_results=tool_results,
                    cleanup_success_workspace=settings.cleanup_success_workspace,
                )

            matches = search_result.payload.get("matches", [])
            if len(matches) != 1:
                return _finalize_run_state(
                    recorder=recorder,
                    run_id=run_id,
                    task=task,
                    trace_path=trace_path,
                    repo_path=repo_path,
                    workspace_path=workspace_path,
                    status="failed",
                    summary=f"Fixed-flow failed: search_code returned {len(matches)} candidate files",
                    verification=None,
                    selected_files=[],
                    applied_patch=applied_patch,
                    tool_results=tool_results,
                    cleanup_success_workspace=settings.cleanup_success_workspace,
                )
            selected_files = [str(matches[0]["relative_path"])]

        trace_path = _record_tool_started(recorder, run_id, "read_file", workspace_path)
        read_result = read_file(
            workspace_path=workspace_path,
            relative_path=selected_files[0],
            start_line=artifacts.read_start_line,
            end_line=artifacts.read_end_line,
        )
        tool_results.append(summarize_tool_result(read_result))
        trace_path = _record_tool_completed(recorder, run_id, read_result)
        if read_result.status != "passed":
            return _finalize_run_state(
                recorder=recorder,
                run_id=run_id,
                task=task,
                trace_path=trace_path,
                repo_path=repo_path,
                workspace_path=workspace_path,
                status="failed",
                summary=f"Fixed-flow failed: {read_result.summary}",
                verification=None,
                selected_files=selected_files,
                applied_patch=applied_patch,
                tool_results=tool_results,
                cleanup_success_workspace=settings.cleanup_success_workspace,
            )
        if (
            (artifacts.read_start_line is not None or artifacts.read_end_line is not None)
            and artifacts.old_text not in str(read_result.payload.get("content", ""))
        ):
            return _finalize_run_state(
                recorder=recorder,
                run_id=run_id,
                task=task,
                trace_path=trace_path,
                repo_path=repo_path,
                workspace_path=workspace_path,
                status="failed",
                summary="Fixed-flow failed: inspected slice does not contain old_text",
                verification=None,
                selected_files=selected_files,
                applied_patch=applied_patch,
                tool_results=tool_results,
                cleanup_success_workspace=settings.cleanup_success_workspace,
            )

        trace_path = _record_tool_started(recorder, run_id, "apply_patch", workspace_path)
        patch_result = apply_patch(
            workspace_path=workspace_path,
            relative_path=selected_files[0],
            old_text=artifacts.old_text,
            new_text=artifacts.new_text,
        )
        tool_results.append(summarize_tool_result(patch_result))
        trace_path = _record_tool_completed(recorder, run_id, patch_result)
        if patch_result.status != "passed":
            return _finalize_run_state(
                recorder=recorder,
                run_id=run_id,
                task=task,
                trace_path=trace_path,
                repo_path=repo_path,
                workspace_path=workspace_path,
                status="failed",
                summary=f"Fixed-flow failed: {patch_result.summary}",
                verification=None,
                selected_files=selected_files,
                applied_patch=applied_patch,
                tool_results=tool_results,
                cleanup_success_workspace=settings.cleanup_success_workspace,
            )
        applied_patch = True

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

    return _finalize_run_state(
        recorder=recorder,
        run_id=run_id,
        task=task,
        trace_path=trace_path,
        repo_path=repo_path,
        workspace_path=workspace_path,
        status=run_status,
        summary=summary,
        verification=verification,
        selected_files=selected_files,
        applied_patch=applied_patch,
        tool_results=tool_results,
        cleanup_success_workspace=settings.cleanup_success_workspace,
    )
