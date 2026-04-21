from pathlib import Path
from uuid import uuid4

from app.schemas.run_state import RunState
from app.schemas.task import TaskSpec
from app.schemas.trace import TraceEvent
from app.tracing.recorder import TraceRecorder


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
            event_type="run.completed",
            message="Completed task preview run",
            payload={
                "task_id": task.task_id,
                "task_type": task.task_type,
                "status": "completed",
                "summary": "Task preview completed",
            },
        )
    )

    return RunState(
        run_id=run_id,
        task_id=task.task_id,
        task_type=task.task_type,
        status="completed",
        current_step="summarize",
        summary="Task preview completed",
        trace_path=str(trace_path),
    )
