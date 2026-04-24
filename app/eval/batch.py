from pathlib import Path
from uuid import uuid4

from app.config.settings import Settings
from app.orchestrator.runner import run_task_preview
from app.schemas.eval import BatchEvalResult, BatchEvalSummary
from app.schemas.task import load_task_spec


def _result_from_state(task_file: Path, state) -> BatchEvalResult:
    return BatchEvalResult(
        task_id=state.task_id,
        task_type=state.task_type,
        task_file=str(task_file),
        status=state.status,
        current_step=state.current_step,
        summary=state.summary,
        passed_count=state.verification.passed_count if state.verification else 0,
        failed_count=state.verification.failed_count if state.verification else 0,
        applied_patch=state.applied_patch,
        tool_results=state.tool_results,
        trace_path=state.trace_path,
        workspace_path=state.workspace_path,
    )


def _render_summary_markdown(summary: BatchEvalSummary) -> str:
    lines = [
        "# Batch Eval",
        "",
        f"- run_id: {summary.run_id}",
        f"- task_count: {summary.task_count}",
        f"- completed_count: {summary.completed_count}",
        f"- failed_count: {summary.failed_count}",
        f"- summary_json_path: {summary.summary_json_path}",
        f"- summary_md_path: {summary.summary_md_path}",
        "",
        "## Results",
        "",
    ]
    for result in summary.results:
        lines.append(f"- {result.task_id}: {result.status} - {result.summary}")
    lines.append("")
    return "\n".join(lines)


def run_batch_eval(task_paths: list[Path], settings: Settings) -> BatchEvalSummary:
    run_id = f"eval-{uuid4().hex[:12]}"
    output_dir = settings.evals_dir / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[BatchEvalResult] = []
    for task_path in task_paths:
        task = load_task_spec(task_path)
        state = run_task_preview(task, settings)
        results.append(_result_from_state(task_path, state))

    completed_count = sum(1 for result in results if result.status == "completed")
    failed_count = sum(1 for result in results if result.status == "failed")
    summary_json_path = output_dir / "summary.json"
    summary_md_path = output_dir / "summary.md"

    summary = BatchEvalSummary(
        run_id=run_id,
        task_count=len(results),
        completed_count=completed_count,
        failed_count=failed_count,
        output_dir=str(output_dir),
        summary_json_path=str(summary_json_path),
        summary_md_path=str(summary_md_path),
        results=results,
    )

    summary_json_path.write_text(
        summary.model_dump_json(indent=2),
        encoding="utf-8",
    )
    summary_md_path.write_text(_render_summary_markdown(summary), encoding="utf-8")
    return summary
