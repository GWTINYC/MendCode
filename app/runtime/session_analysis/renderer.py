from __future__ import annotations

from pathlib import Path

from app.runtime.session_analysis.models import AnalysisFinding, SessionAnalysisReport, compact_text

VALID_OUTPUT_FORMATS = {"json", "md", "both"}


def render_report_json(report: SessionAnalysisReport) -> str:
    return report.model_dump_json(indent=2)


def render_report_markdown(report: SessionAnalysisReport) -> str:
    lines = [
        "# MendCode Session Analysis",
        "",
        "## Summary",
        f"- session_id: `{report.session_id}`",
        f"- input_kind: `{report.input_kind}`",
        f"- source_path: `{report.source_path}`",
        f"- confidence: `{report.confidence}`",
        f"- observed_tools: {_inline_list(report.observed_tools)}",
        "",
        "## User Request",
        _bullet_text(report.user_messages),
        "",
        "## Expected Tool Chain",
        _finding_list(report.expected_tools),
        "",
        "## Actual Tool Chain",
        _actual_tool_chain(report),
        "",
        "## Missing / Repeated / Failed Tools",
        _finding_list(report.missing_tools + report.repeated_tools + report.failed_tools),
        "",
        "## Observation Grounding",
        _finding_list(report.unsupported_claims),
        "",
        "## Context Waste",
        _finding_list(report.oversized_outputs),
        "",
        "## Permission And Risk Events",
        _finding_list(report.risk_events),
        "",
        "## Root Causes",
        _finding_list(report.root_causes),
        "",
        "## Recommendations",
        _finding_list(report.recommendations),
        "",
        "## Final Answer Excerpt",
        compact_text(report.final_answer_excerpt, max_chars=1200) or "none",
        "",
    ]
    return "\n".join(lines)


def write_analysis_report(
    report: SessionAnalysisReport,
    output_dir: Path,
    output_format: str = "both",
) -> list[Path]:
    if output_format not in VALID_OUTPUT_FORMATS:
        raise ValueError("output_format must be one of: both, json, md")
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if output_format in {"json", "both"}:
        path = output_dir / f"{report.session_id}.json"
        path.write_text(render_report_json(report), encoding="utf-8")
        written.append(path)
    if output_format in {"md", "both"}:
        path = output_dir / f"{report.session_id}.md"
        path.write_text(render_report_markdown(report), encoding="utf-8")
        written.append(path)
    return written


def _finding_list(findings: list[AnalysisFinding]) -> str:
    if not findings:
        return "- none"
    lines: list[str] = []
    for finding in findings:
        lines.append(f"- `{finding.code}` ({finding.severity}): {finding.summary}")
        if finding.evidence:
            rendered = ", ".join(
                f"{key}={compact_text(value, max_chars=200)!r}"
                for key, value in finding.evidence.items()
            )
            lines.append(f"  evidence: {rendered}")
    return "\n".join(lines)


def _actual_tool_chain(report: SessionAnalysisReport) -> str:
    if not report.tool_calls and not report.observations:
        return "- none"
    lines: list[str] = []
    for call in report.tool_calls:
        lines.append(f"- call #{call.call_index}: `{call.tool_name}` status={call.status}")
    for observation in report.observations:
        visible_chars = observation.visible_chars
        lines.append(
            f"- observation: `{observation.tool_name}` "
            f"status={observation.status} visible_chars={visible_chars}"
        )
    return "\n".join(lines)


def _bullet_text(items: list[str]) -> str:
    if not items:
        return "- none"
    return "\n".join(f"- {compact_text(item, max_chars=500)}" for item in items)


def _inline_list(items: list[str]) -> str:
    return ", ".join(f"`{item}`" for item in items) if items else "none"
