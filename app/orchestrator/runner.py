import subprocess
import time
from pathlib import Path
from uuid import uuid4

from app.schemas.run_state import RunState
from app.schemas.task import TaskSpec
from app.schemas.trace import TraceEvent
from app.schemas.verification import VerificationCommandResult, VerificationResult
from app.tracing.recorder import TraceRecorder

_OUTPUT_EXCERPT_LIMIT = 2000


def _trim_output(value: str) -> str:
    if len(value) <= _OUTPUT_EXCERPT_LIMIT:
        return value
    return value[:_OUTPUT_EXCERPT_LIMIT]


def run_task_preview(task: TaskSpec, traces_dir: Path) -> RunState:
    recorder = TraceRecorder(traces_dir)
    run_id = f"preview-{uuid4().hex[:12]}"

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
            },
        )
    )

    command_results: list[VerificationCommandResult] = []

    if not task.verification_commands:
        command_results.append(
            VerificationCommandResult(
                command="<none>",
                exit_code=-1,
                status="failed",
                duration_ms=0,
                stdout_excerpt="",
                stderr_excerpt="no verification commands provided",
            )
        )
    else:
        for command in task.verification_commands:
            started_at = time.perf_counter()
            try:
                completed_process = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=task.repo_path,
                )
                exit_code = completed_process.returncode
                stdout_excerpt = _trim_output(completed_process.stdout)
                stderr_excerpt = _trim_output(completed_process.stderr)
            except OSError as exc:
                exit_code = -1
                stdout_excerpt = ""
                stderr_excerpt = str(exc)

            duration_ms = int((time.perf_counter() - started_at) * 1000)
            status = "passed" if exit_code == 0 else "failed"
            command_result = VerificationCommandResult(
                command=command,
                exit_code=exit_code,
                status=status,
                duration_ms=duration_ms,
                stdout_excerpt=stdout_excerpt,
                stderr_excerpt=stderr_excerpt,
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
                    },
                )
            )

    failed_count = sum(1 for result in command_results if result.status == "failed")
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
        summary = f"Verification passed: {passed_count}/{len(command_results)} commands succeeded"
    else:
        summary = f"Verification failed: {failed_count} of {len(command_results)} commands failed"

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
        verification=verification,
    )
