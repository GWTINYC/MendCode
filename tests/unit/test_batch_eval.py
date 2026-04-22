import json
from pathlib import Path

from app.config.settings import Settings
from app.eval.batch import run_batch_eval
from app.schemas.run_state import RunState


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_name="MendCode",
        app_version="0.1.0",
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        tasks_dir=tmp_path / "data" / "tasks",
        traces_dir=tmp_path / "data" / "traces",
        workspace_root=tmp_path / ".worktrees",
        verification_timeout_seconds=60,
        cleanup_success_workspace=False,
    )


def write_task_file(path: Path, task_id: str) -> Path:
    task_file = path / f"{task_id}.json"
    task_file.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "task_type": "ci_fix",
                "title": task_id,
                "repo_path": "/tmp/repo",
                "entry_artifacts": {},
                "verification_commands": [],
                "allowed_tools": [],
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )
    return task_file


def test_run_batch_eval_writes_summary_files(monkeypatch, tmp_path):
    settings = build_settings(tmp_path)
    task_file_one = write_task_file(tmp_path, "task-1")
    task_file_two = write_task_file(tmp_path, "task-2")

    def fake_run_task_preview(task, settings):
        status = "completed" if task.task_id == "task-1" else "failed"
        return RunState(
            run_id=f"preview-{task.task_id}",
            task_id=task.task_id,
            task_type=task.task_type,
            status=status,
            current_step="summarize",
            summary=f"{task.task_id} {status}",
            trace_path=str(tmp_path / f"{task.task_id}.jsonl"),
            workspace_path=None,
            selected_files=[],
            applied_patch=False,
            tool_results=[],
            verification=None,
        )

    monkeypatch.setattr("app.eval.batch.run_task_preview", fake_run_task_preview)

    result = run_batch_eval([task_file_one, task_file_two], settings)

    assert result.task_count == 2
    assert result.completed_count == 1
    assert result.failed_count == 1
    assert Path(result.summary_json_path).exists()
    assert Path(result.summary_md_path).exists()
