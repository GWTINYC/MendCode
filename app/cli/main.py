import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from app.agent.loop import AgentLoopInput, AgentStep, run_agent_loop
from app.agent.provider import ScriptedAgentProvider
from app.agent.provider_factory import ProviderConfigurationError, build_agent_provider
from app.agent.session import AgentSession, AgentSessionTurn
from app.config.settings import get_settings
from app.core.paths import ensure_data_directories
from app.orchestrator.failure_parser import FailureInsight, extract_failure_insight
from app.runtime.benchmark import load_manifest, load_report, validate_report_coverage
from app.runtime.session_analysis import (
    analyze_transcript,
    parse_session_file,
    write_analysis_report,
)
from app.runtime.story_runner import (
    Story,
    StoryStatus,
    append_progress_entry,
    load_story_plan,
    mark_story_passed,
    pick_next_story,
)
from app.schemas.verification import VerificationCommandResult
from app.workspace.review_actions import (
    ReviewActionResult,
    apply_worktree_changes,
    discard_worktree,
    view_trace,
    view_worktree_diff,
)

app = typer.Typer(help="MendCode CLI", invoke_without_command=True)
story_app = typer.Typer(help="Ralph-style story plan utilities")
benchmark_app = typer.Typer(help="Benchmark manifest and report utilities")
trace_app = typer.Typer(help="Trace and conversation analysis utilities")
app.add_typer(story_app, name="story")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(trace_app, name="trace")
console = Console()


def _git_value(repo_path: Path, args: list[str], fallback: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return fallback
    if completed.returncode != 0:
        return fallback
    return completed.stdout.strip() or fallback


def _render_tui_header(repo_path: Path) -> None:
    status_lines = _git_value(repo_path, ["status", "--short"], "").splitlines()
    branch = _git_value(repo_path, ["branch", "--show-current"], "unknown")
    status = f"dirty, {len(status_lines)} modified" if status_lines else "clean"
    console.print("MendCode")
    console.print(f"repo: {repo_path}")
    console.print(f"branch: {branch}")
    console.print(f"status: {status}")
    console.print("mode: guided")


def _render_turn(turn: AgentSessionTurn) -> None:
    tools = Table(title="Tool Summary")
    tools.add_column("Step")
    tools.add_column("Action")
    tools.add_column("Status")
    tools.add_column("Summary")
    for item in turn.tool_summaries:
        tools.add_row(str(item.index), item.action, item.status, item.summary)
    console.print(tools)

    review = Table(title="Review")
    review.add_column("Field")
    review.add_column("Value")
    review.add_row("status", turn.review.status)
    review.add_row("summary", turn.result.summary)
    review.add_row("verification_status", turn.review.verification_status)
    review.add_row("workspace_path", turn.review.workspace_path or "")
    review.add_row("trace_path", turn.review.trace_path or "")
    review.add_row("changed_files", ", ".join(turn.review.changed_files))
    review.add_row("recommended_actions", ", ".join(turn.review.recommended_actions))
    console.print(review)


def _available_review_actions(turn: AgentSessionTurn) -> list[str]:
    actions = set(turn.review.recommended_actions)
    if turn.review.workspace_path is None:
        actions.difference_update({"view_diff", "apply", "discard"})
    if turn.review.trace_path is None:
        actions.discard("view_trace")
    ordered = ["view_diff", "view_trace", "apply", "discard"]
    return [action for action in ordered if action in actions]


def _render_review_actions(actions: list[str]) -> None:
    if not actions:
        return
    table = Table(title="Review Actions")
    table.add_column("Action")
    table.add_column("Description")
    descriptions = {
        "view_diff": "Show the worktree diff",
        "view_trace": "Show the JSONL trace excerpt",
        "apply": "Apply verified worktree changes to the main workspace",
        "discard": "Remove the worktree without applying changes",
    }
    for action in actions:
        table.add_row(action, descriptions[action])
    console.print(table)


def _prompt_review_action() -> str:
    try:
        return typer.prompt("Review action", default="", show_default=False).strip()
    except (EOFError, typer.Abort):
        return ""


def _render_review_action_result(result: ReviewActionResult) -> None:
    table = Table(title="Review Action Result")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("action", result.action)
    table.add_row("status", result.status)
    table.add_row("summary", result.summary)
    if result.error_message is not None:
        table.add_row("error", result.error_message)
    changed_files = result.payload.get("changed_files")
    if isinstance(changed_files, list):
        table.add_row("changed_files", ", ".join(str(item) for item in changed_files))
    console.print(table)

    if result.action == "view_diff" and result.status == "succeeded":
        diff_stat = str(result.payload.get("diff_stat", ""))
        diff = str(result.payload.get("diff", ""))
        if diff_stat:
            console.print(diff_stat)
        if diff:
            console.print(diff)
    if result.action == "view_trace" and result.status == "succeeded":
        content = str(result.payload.get("content", ""))
        if content:
            console.print(content)
        if result.payload.get("truncated") is True:
            console.print("[trace truncated]")


def _render_story(story: Story) -> None:
    table = Table(title="Story")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("id", story.id)
    table.add_row("title", story.title)
    table.add_row("priority", str(story.priority))
    table.add_row("passes", str(story.passes).lower())
    table.add_row("acceptance_criteria", "\n".join(story.acceptance_criteria))
    table.add_row("verification_commands", "\n".join(story.verification_commands))
    console.print(table)


def _render_benchmark_manifest(manifest_path: Path) -> None:
    manifest = load_manifest(manifest_path)
    table = Table(title="Benchmark Manifest")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("name", manifest.name)
    table.add_row("case_count", str(manifest.case_count))
    missing = manifest.missing_target_categories()
    table.add_row("missing_target_categories", ", ".join(missing) if missing else "none")
    for category, count in manifest.category_counts().items():
        table.add_row(category, str(count))
    console.print(table)


def _render_benchmark_coverage(manifest_path: Path, result_path: Path) -> None:
    manifest = load_manifest(manifest_path)
    report = load_report(result_path)
    coverage = validate_report_coverage(manifest, report)
    table = Table(title="Benchmark Coverage")
    table.add_column("Field")
    table.add_column("Value")
    for key, value in coverage.items():
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value) if value else "none"
        elif isinstance(value, bool):
            rendered = str(value).lower()
        else:
            rendered = str(value)
        table.add_row(key, rendered)
    console.print(table)


def _execute_review_action(
    *,
    action: str,
    repo_path: Path,
    turn: AgentSessionTurn,
) -> ReviewActionResult:
    workspace_path = Path(turn.review.workspace_path) if turn.review.workspace_path else None
    trace_path = Path(turn.review.trace_path) if turn.review.trace_path else None

    if action == "view_diff":
        if workspace_path is None:
            return ReviewActionResult(
                action="view_diff",
                status="failed",
                summary="Unable to read worktree diff",
                error_message="workspace path is unavailable",
            )
        return view_worktree_diff(workspace_path=workspace_path)
    if action == "view_trace":
        if trace_path is None:
            return ReviewActionResult(
                action="view_trace",
                status="failed",
                summary="Unable to read trace",
                error_message="trace path is unavailable",
            )
        return view_trace(trace_path=trace_path)
    if action == "apply":
        if workspace_path is None:
            return ReviewActionResult(
                action="apply",
                status="failed",
                summary="Unable to apply worktree changes",
                error_message="workspace path is unavailable",
            )
        return apply_worktree_changes(repo_path=repo_path, workspace_path=workspace_path)
    if action == "discard":
        if workspace_path is None:
            return ReviewActionResult(
                action="discard",
                status="failed",
                summary="Unable to discard worktree",
                error_message="workspace path is unavailable",
            )
        return discard_worktree(repo_path=repo_path, workspace_path=workspace_path)
    return ReviewActionResult(
        action=action,
        status="rejected",
        summary="Action not available",
        error_message=f"Action not available: {action}",
    )


def _run_review_actions(*, repo_path: Path, turn: AgentSessionTurn) -> None:
    available_actions = _available_review_actions(turn)
    if not available_actions:
        return

    while True:
        _render_review_actions(available_actions)
        selected_action = _prompt_review_action()
        if not selected_action:
            return
        if selected_action not in available_actions:
            console.print(f"Action not available: {selected_action}")
            return

        result = _execute_review_action(
            action=selected_action,
            repo_path=repo_path,
            turn=turn,
        )
        _render_review_action_result(result)
        if selected_action in {"apply", "discard"}:
            return


def _verification_payload_from_observation_payload(
    payload: dict[str, object],
) -> dict[str, object]:
    raw_payload = payload.get("payload")
    if isinstance(raw_payload, dict) and "command" in raw_payload:
        return raw_payload
    return payload


def _verification_command_result_from_step(step: AgentStep) -> VerificationCommandResult | None:
    if step.action.type != "tool_call" or getattr(step.action, "action", None) != "run_command":
        return None
    payload = _verification_payload_from_observation_payload(step.observation.payload)
    if "command" not in payload:
        return None
    return VerificationCommandResult.model_validate(payload)


def _command_results_from_steps(turn: AgentSessionTurn) -> list[VerificationCommandResult]:
    return [
        command_result
        for step in turn.result.steps
        if (command_result := _verification_command_result_from_step(step)) is not None
    ]


def _run_location_summary(
    *,
    turn: AgentSessionTurn,
    insight: FailureInsight | None,
    problem_statement: str,
    settings,
):
    if insight is None or turn.result.workspace_path is None:
        return None
    location_response = ScriptedAgentProvider().plan_failure_location_actions(
        failed_node=insight.failed_node,
        file_path=insight.file_path,
        test_name=insight.test_name,
    )
    if location_response.status != "succeeded":
        return None
    return run_agent_loop(
        AgentLoopInput(
            repo_path=Path(turn.result.workspace_path),
            problem_statement=problem_statement,
            actions=location_response.actions,
            step_budget=len(location_response.actions),
            use_worktree=False,
        ),
        settings,
    )


def _render_failure_insight(
    insight: FailureInsight | None,
    location_result,
) -> None:
    if insight is None and location_result is None:
        return
    table = Table(title="Failure Insight")
    table.add_column("Field")
    table.add_column("Value")
    if insight is not None:
        table.add_row("failed_node", insight.failed_node or "")
        table.add_row("file_path", insight.file_path or "")
        table.add_row("test_name", insight.test_name or "")
        table.add_row("error_summary", insight.error_summary)
    if location_result is not None:
        table.add_row("location_status", location_result.status)
        table.add_row(
            "location_steps",
            ", ".join(
                f"{getattr(step.action, 'action', step.action.type)}:{step.observation.status}"
                for step in location_result.steps
                if step.action.type == "tool_call"
            ),
        )
    console.print(table)


def _is_interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _run_textual_app(*, repo_path: Path, settings) -> None:
    from app.tui.app import MendCodeTextualApp

    MendCodeTextualApp(repo_path=repo_path, settings=settings).run()


def _run_single_turn_fallback(*, repo_path: Path, settings) -> None:
    _render_tui_header(repo_path)
    problem_statement = typer.prompt("Type your task")
    verification_command = typer.prompt("Verification command")
    if not verification_command.strip():
        table = Table(title="MendCode")
        table.add_column("Field")
        table.add_column("Value")
        table.add_row("status", "failed")
        table.add_row("error", "Verification command is required")
        console.print(table)
        raise typer.Exit(code=1)

    try:
        provider = build_agent_provider(settings)
    except ProviderConfigurationError as exc:
        table = Table(title="Provider Configuration")
        table.add_column("Field")
        table.add_column("Value")
        table.add_row("status", "failed")
        table.add_row("error", str(exc))
        console.print(table)
        raise typer.Exit(code=1)

    session = AgentSession(repo_path=repo_path, provider=provider, settings=settings)
    turn = session.run_turn(
        problem_statement=problem_statement,
        verification_commands=[verification_command],
    )
    _render_turn(turn)
    _run_review_actions(repo_path=repo_path, turn=turn)
    insight = extract_failure_insight(_command_results_from_steps(turn))
    location_result = _run_location_summary(
        turn=turn,
        insight=insight,
        problem_statement=problem_statement,
        settings=settings,
    )
    _render_failure_insight(insight, location_result)


@app.callback()
def tui_entry(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return

    settings = get_settings()
    ensure_data_directories(settings)
    repo_path = Path.cwd().resolve()
    if _is_interactive_terminal():
        _run_textual_app(repo_path=repo_path, settings=settings)
        return

    _run_single_turn_fallback(repo_path=repo_path, settings=settings)


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


@story_app.command("status")
def story_status(plan: Path) -> None:
    story_plan = load_story_plan(plan)
    table = Table(title="Story Plan")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("branch_name", story_plan.branch_name)
    table.add_row("stories", str(len(story_plan.stories)))
    table.add_row("completed", str(story_plan.completed_count))
    table.add_row("remaining", str(story_plan.remaining_count))
    table.add_row("progress_path", story_plan.progress_path)
    console.print(table)


@benchmark_app.command("status")
def benchmark_status(manifest: Path) -> None:
    _render_benchmark_manifest(manifest)


@benchmark_app.command("check")
def benchmark_check(manifest: Path, result: Path) -> None:
    _render_benchmark_coverage(manifest, result)


@trace_app.command("analyze-session")
def trace_analyze_session(
    path: Path,
    output_dir: Path = typer.Option(Path("data/analysis-reports"), "--output-dir"),
    output_format: str = typer.Option("both", "--format"),
    llm: bool = typer.Option(False, "--llm"),
) -> None:
    if llm:
        console.print("--llm is reserved for a later evidence-grounded summary layer")
        raise typer.Exit(code=1)
    transcript = parse_session_file(path)
    report = analyze_transcript(transcript)
    written = write_analysis_report(report, output_dir, output_format=output_format)
    console.print("Analysis reports written")
    for item in written:
        console.print(str(item))


@story_app.command("next")
def story_next(plan: Path) -> None:
    story_plan = load_story_plan(plan)
    story = pick_next_story(story_plan)
    if story is None:
        console.print("No pending stories.")
        return
    _render_story(story)


@story_app.command("mark-passed")
def story_mark_passed(plan: Path, story_id: str) -> None:
    story = mark_story_passed(plan, story_id)
    console.print(f"Marked story passed: {story.id}")


@story_app.command("append-progress")
def story_append_progress(
    plan: Path,
    story_id: str,
    status: StoryStatus = typer.Option("planned", "--status"),
    summary: str = typer.Option(..., "--summary"),
    verification: list[str] = typer.Option([], "--verification"),
    trace: str | None = typer.Option(None, "--trace"),
    commit: str | None = typer.Option(None, "--commit"),
    learning: list[str] = typer.Option([], "--learning"),
) -> None:
    story_plan = load_story_plan(plan)
    progress_path = append_progress_entry(
        plan_path=plan,
        plan=story_plan,
        story_id=story_id,
        status=status,
        summary=summary,
        verification=verification,
        trace_path=trace,
        commit=commit,
        learnings=learning,
    )
    console.print(f"Progress appended: {progress_path}")


@app.command("fix")
def fix_problem(
    problem_statement: str,
    test_commands: list[str] = typer.Option(
        [],
        "--test",
        "-t",
        help="Verification command to run. Can be supplied multiple times.",
    ),
    repo: Path = typer.Option(Path("."), "--repo", help="Repository path to fix."),
    max_attempts: int = typer.Option(3, "--max-attempts", min=1),
) -> None:
    settings = get_settings()
    ensure_data_directories(settings)

    if not test_commands:
        table = Table(title="Agent Fix")
        table.add_column("Field")
        table.add_column("Value")
        table.add_row("problem_statement", problem_statement)
        table.add_row("status", "failed")
        table.add_row("summary", "Provider failed")
        table.add_row("error", "at least one verification command is required")
        console.print(table)
        raise typer.Exit(code=1)

    try:
        provider = build_agent_provider(settings)
    except ProviderConfigurationError as exc:
        table = Table(title="Provider Configuration")
        table.add_column("Field")
        table.add_column("Value")
        table.add_row("status", "failed")
        table.add_row("error", str(exc))
        console.print(table)
        raise typer.Exit(code=1)

    loop_input = AgentLoopInput(
        repo_path=repo.resolve(),
        problem_statement=problem_statement,
        provider=provider,
        verification_commands=test_commands,
        step_budget=max_attempts + 3,
        use_worktree=True,
    )

    try:
        result = run_agent_loop(loop_input, settings)
    except OSError as exc:
        typer.echo(f"Agent fix failed while writing trace output: {exc}")
        raise typer.Exit(code=1)

    command_results = [
        command_result
        for step in result.steps
        if (command_result := _verification_command_result_from_step(step)) is not None
    ]
    insight = extract_failure_insight(command_results)
    location_result = None
    if insight is not None and result.workspace_path is not None:
        location_provider = ScriptedAgentProvider()
        location_response = location_provider.plan_failure_location_actions(
            failed_node=insight.failed_node,
            file_path=insight.file_path,
            test_name=insight.test_name,
        )
        if location_response.status == "succeeded":
            location_result = run_agent_loop(
                AgentLoopInput(
                    repo_path=Path(result.workspace_path),
                    problem_statement=problem_statement,
                    actions=location_response.actions,
                    step_budget=len(location_response.actions),
                    use_worktree=False,
                ),
                settings,
            )

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
    if location_result is not None:
        table.add_row("location_status", location_result.status)
        table.add_row(
            "location_steps",
            ", ".join(
                f"{getattr(step.action, 'action', step.action.type)}:{step.observation.status}"
                for step in location_result.steps
                if step.action.type == "tool_call"
            ),
        )
    console.print(table)


if __name__ == "__main__":
    app()
