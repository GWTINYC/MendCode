import json
from pathlib import Path
from uuid import uuid4

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from app.config.settings import get_settings
from app.core.paths import ensure_data_directories
from app.eval.batch import run_batch_eval
from app.orchestrator.failure_parser import extract_failure_insight
from app.orchestrator.runner import run_task_preview
from app.schemas.task import TaskSpec, load_task_spec
from app.schemas.trace import TraceEvent
from app.tracing.recorder import TraceRecorder

app = typer.Typer(help="MendCode CLI")
eval_app = typer.Typer(help="Batch evaluation commands")
task_app = typer.Typer(help="Task file utilities")
app.add_typer(eval_app, name="eval")
app.add_typer(task_app, name="task")
console = Console()


@app.command()
def version() -> None:
    settings = get_settings()
    console.print(f"{settings.app_name} {settings.app_version}")


@app.command()
def health() -> None:
    settings = get_settings()
    ensure_data_directories(settings)

    table = Table(title="MendCode Health")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("app", settings.app_name)
    table.add_row("version", settings.app_version)
    table.add_row("status", "ok")
    table.add_row("project_root", str(settings.project_root))
    table.add_row("tasks_dir", str(settings.tasks_dir))
    table.add_row("traces_dir", str(settings.traces_dir))
    console.print(table)


@app.command("fix")
def fix_problem(
    problem_statement: str,
    test_commands: list[str] = typer.Option(
        ...,
        "--test",
        "-t",
        help="Verification command to run. Can be supplied multiple times.",
    ),
    repo: Path = typer.Option(Path("."), "--repo", help="Repository path to fix."),
    max_attempts: int = typer.Option(3, "--max-attempts", min=1),
) -> None:
    settings = get_settings()
    ensure_data_directories(settings)
    task = TaskSpec(
        task_id=f"agent-fix-{uuid4().hex[:12]}",
        task_type="ci_fix",
        title="Agent fix",
        repo_path=str(repo.resolve()),
        problem_statement=problem_statement,
        verification_commands=test_commands,
        max_attempts=max_attempts,
        allowed_tools=["run_command", "read_file", "search_code", "apply_patch"],
        metadata={"source": "cli.fix"},
    )

    try:
        state = run_task_preview(task, settings)
    except OSError as exc:
        typer.echo(f"Agent fix failed while writing trace output: {exc}")
        raise typer.Exit(code=1)

    insight = None
    if state.verification is not None:
        insight = extract_failure_insight(state.verification.command_results)

    table = Table(title="Agent Fix")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("run_id", state.run_id)
    table.add_row("problem_statement", problem_statement)
    table.add_row("status", state.status)
    table.add_row("summary", state.summary)
    table.add_row("max_attempts", str(max_attempts))
    table.add_row("workspace_path", state.workspace_path or "")
    table.add_row("trace_path", state.trace_path)
    if insight is not None:
        table.add_row("failed_node", insight.failed_node or "")
        table.add_row("file_path", insight.file_path or "")
        table.add_row("test_name", insight.test_name or "")
        table.add_row("error_summary", insight.error_summary)
    console.print(table)


def _load_task_spec_or_exit(file_path: Path):
    if not file_path.exists():
        typer.echo(f"Task file not found: {file_path}")
        raise typer.Exit(code=1)

    try:
        return load_task_spec(file_path)
    except OSError as exc:
        typer.echo(f"Task file could not be read: {exc}")
        raise typer.Exit(code=1)
    except json.JSONDecodeError as exc:
        typer.echo(f"Task file is not valid JSON: {exc.msg}")
        raise typer.Exit(code=1)
    except ValidationError as exc:
        message = exc.errors()[0]["msg"] if exc.errors() else "unknown validation error"
        typer.echo(f"Task file failed schema validation: {message}")
        raise typer.Exit(code=1)


@task_app.command("validate")
def validate_task(file_path: Path) -> None:
    task = _load_task_spec_or_exit(file_path)
    console.print(f"Task file is valid: {task.task_id} ({task.task_type})")


@task_app.command("show")
def show_task(file_path: Path) -> None:
    task = _load_task_spec_or_exit(file_path)
    settings = get_settings()
    ensure_data_directories(settings)
    recorder = TraceRecorder(settings.traces_dir)
    run_id = f"preview-{uuid4().hex[:12]}"
    trace_path = recorder.record(
        TraceEvent(
            run_id=run_id,
            event_type="task.show",
            message="Previewed task file",
            payload={
                "task_id": task.task_id,
                "task_type": task.task_type,
                "title": task.title,
            },
        )
    )

    table = Table(title="Task Preview")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("task_id", task.task_id)
    table.add_row("task_type", task.task_type)
    table.add_row("title", task.title)
    table.add_row("repo_path", task.repo_path)
    table.add_row("trace_path", str(trace_path))
    console.print(table)


@task_app.command("run")
def run_task(file_path: Path) -> None:
    task = _load_task_spec_or_exit(file_path)
    settings = get_settings()
    ensure_data_directories(settings)

    try:
        state = run_task_preview(task, settings)
    except OSError as exc:
        typer.echo(f"Task run failed while writing trace output: {exc}")
        raise typer.Exit(code=1)

    table = Table(title="Task Run")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("run_id", state.run_id)
    table.add_row("task_id", state.task_id)
    table.add_row("task_type", state.task_type)
    table.add_row("status", state.status)
    table.add_row("current_step", state.current_step)
    table.add_row("summary", state.summary)
    passed_count = state.verification.passed_count if state.verification else 0
    failed_count = state.verification.failed_count if state.verification else 0
    table.add_row("passed_count", str(passed_count))
    table.add_row("failed_count", str(failed_count))
    table.add_row("selected_files", ", ".join(state.selected_files))
    table.add_row("applied_patch", "yes" if state.applied_patch else "no")
    table.add_row("workspace_path", state.workspace_path or "")
    table.add_row("trace_path", state.trace_path)
    console.print(table)

    if state.verification and state.verification.failed_count > 0:
        first_non_passed = next(
            (item for item in state.verification.command_results if item.status != "passed"),
            None,
        )
        if first_non_passed is not None:
            console.print(
                f"First non-passed command: {first_non_passed.status}: "
                f"{first_non_passed.command} "
                f"(exit {first_non_passed.exit_code})"
            )


@eval_app.command("run")
def run_batch_eval_command(task_files: list[Path] = typer.Argument([])) -> None:
    if not task_files:
        typer.echo("At least one task file path is required.")
        raise typer.Exit(code=1)

    settings = get_settings()
    ensure_data_directories(settings)
    summary = run_batch_eval(task_files, settings)

    table = Table(title="Batch Eval")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("run_id", summary.run_id)
    table.add_row("task_count", str(summary.task_count))
    table.add_row("completed_count", str(summary.completed_count))
    table.add_row("failed_count", str(summary.failed_count))
    table.add_row("summary_json_path", summary.summary_json_path)
    table.add_row("summary_md_path", summary.summary_md_path)
    console.print(table)


if __name__ == "__main__":
    app()
