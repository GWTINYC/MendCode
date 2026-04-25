from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from app.agent.loop import AgentLoopInput, run_agent_loop
from app.config.settings import get_settings
from app.core.paths import ensure_data_directories
from app.orchestrator.failure_parser import extract_failure_insight
from app.schemas.verification import VerificationCommandResult

app = typer.Typer(help="MendCode CLI")
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
    table.add_row("traces_dir", str(settings.traces_dir))
    table.add_row("workspace_root", str(settings.workspace_root))
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
    actions: list[dict[str, object]] = [
        {
            "type": "tool_call",
            "action": "repo_status",
            "reason": "inspect repository state before attempting a fix",
            "args": {},
        },
        {
            "type": "tool_call",
            "action": "detect_project",
            "reason": "detect project type and likely verification commands",
            "args": {},
        },
    ]
    actions.extend(
        {
            "type": "tool_call",
            "action": "run_command",
            "reason": "run requested verification command",
            "args": {"command": command},
        }
        for command in test_commands
    )
    actions.append(
        {
            "type": "final_response",
            "status": "completed",
            "summary": "Agent loop completed requested verification commands",
        }
    )

    loop_input = AgentLoopInput(
        repo_path=repo.resolve(),
        problem_statement=problem_statement,
        actions=actions,
        step_budget=max_attempts + 3,
        use_worktree=True,
    )

    try:
        result = run_agent_loop(loop_input, settings)
    except OSError as exc:
        typer.echo(f"Agent fix failed while writing trace output: {exc}")
        raise typer.Exit(code=1)

    command_results = [
        VerificationCommandResult.model_validate(step.observation.payload)
        for step in result.steps
        if step.action.type == "tool_call"
        and getattr(step.action, "action", None) == "run_command"
        and "command" in step.observation.payload
    ]
    insight = extract_failure_insight(command_results)

    table = Table(title="Agent Fix")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("run_id", result.run_id)
    table.add_row("problem_statement", problem_statement)
    table.add_row("status", result.status)
    table.add_row("summary", result.summary)
    table.add_row("max_attempts", str(max_attempts))
    table.add_row("repo_path", str(repo.resolve()))
    table.add_row("workspace_path", result.workspace_path or "")
    table.add_row("trace_path", result.trace_path or "")
    if insight is not None:
        table.add_row("failed_node", insight.failed_node or "")
        table.add_row("file_path", insight.file_path or "")
        table.add_row("test_name", insight.test_name or "")
        table.add_row("error_summary", insight.error_summary)
    console.print(table)


if __name__ == "__main__":
    app()
