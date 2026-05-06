from __future__ import annotations

from typing import Any

from app.evolution.models import LessonCandidate
from app.evolution.rules import EvolutionRuleRuntime, EvolutionRuleStore
from app.evolution.runtime import EvolutionRuntime
from app.memory.runtime import MemoryRuntime
from app.memory.store import MemoryStore
from app.schemas.agent_action import Observation
from app.tools.arguments import (
    AnalysisReportIngestArgs,
    AnalysisReportListArgs,
    EvolutionRuleAcceptWithEditsArgs,
    EvolutionRuleActionArgs,
    EvolutionRuleListArgs,
    EvolutionRuleViewArgs,
)
from app.tools.observations import tool_observation
from app.tools.structured import ToolExecutionContext


def analysis_report_list(
    args: AnalysisReportListArgs,
    context: ToolExecutionContext,
) -> Observation:
    try:
        ingestion = _analysis_ingestion_runtime(context)
        reports = ingestion.list_reports()[: args.limit]
    except Exception as exc:
        return _rejected("analysis_report_list", "", exc)
    return tool_observation(
        tool_name="analysis_report_list",
        status="succeeded",
        summary=f"Found {len(reports)} analysis reports",
        payload={
            "total_reports": len(reports),
            "reports": [_compact_report(report) for report in reports],
        },
    )


def analysis_report_ingest(
    args: AnalysisReportIngestArgs,
    context: ToolExecutionContext,
) -> Observation:
    try:
        runtime = EvolutionRuntime(_memory_runtime(context))
        result = runtime.ingest_analysis_reports(
            _analysis_reports_dir(context),
            limit=args.limit,
        )
    except Exception as exc:
        return _rejected("analysis_report_ingest", "", exc)
    status = "succeeded" if not result.errors else "failed"
    return tool_observation(
        tool_name="analysis_report_ingest",
        status=status,
        summary=(
            f"Ingested {result.report_count} analysis reports, "
            f"enqueued {result.enqueued_count} candidates"
        ),
        payload={
            "report_count": result.report_count,
            "generated_count": result.generated_count,
            "enqueued_count": result.enqueued_count,
            "skipped_existing_count": result.skipped_existing_count,
            "candidate_ids": [candidate.id for candidate in result.candidates[:50]],
            "errors": result.errors[:20],
        },
        error_message="analysis report ingestion had errors" if result.errors else None,
    )


def evolution_rule_list(
    args: EvolutionRuleListArgs,
    context: ToolExecutionContext,
) -> Observation:
    try:
        runtime = _rule_runtime(context)
    except RuntimeError as exc:
        return _rejected("evolution_rule_list", "", exc)
    candidates = runtime.list_candidates(status=args.status, limit=args.limit)
    return tool_observation(
        tool_name="evolution_rule_list",
        status="succeeded",
        summary=f"Found {len(candidates)} evolution rule candidates",
        payload={
            "status": args.status,
            "total_candidates": len(candidates),
            "candidates": [_compact_candidate(candidate) for candidate in candidates],
        },
    )


def evolution_rule_view(
    args: EvolutionRuleViewArgs,
    context: ToolExecutionContext,
) -> Observation:
    try:
        runtime = _rule_runtime(context)
        candidate = runtime.candidate_for_id(args.candidate_id)
    except (KeyError, RuntimeError, ValueError) as exc:
        return _rejected("evolution_rule_view", args.candidate_id, exc)
    return tool_observation(
        tool_name="evolution_rule_view",
        status="succeeded",
        summary=f"Read evolution rule candidate {candidate.id}",
        payload={"candidate": _view_candidate(candidate)},
    )


def evolution_rule_accept(
    args: EvolutionRuleActionArgs,
    context: ToolExecutionContext,
) -> Observation:
    try:
        runtime = _rule_runtime(context)
        rule = runtime.accept(args.candidate_id)
    except (KeyError, RuntimeError, ValueError) as exc:
        return _rejected("evolution_rule_accept", args.candidate_id, exc)
    return _accepted("evolution_rule_accept", args.candidate_id, rule.model_dump(mode="json"))


def evolution_rule_reject(
    args: EvolutionRuleActionArgs,
    context: ToolExecutionContext,
) -> Observation:
    try:
        runtime = _rule_runtime(context)
        candidate = runtime.reject(args.candidate_id)
    except (KeyError, RuntimeError, ValueError) as exc:
        return _rejected("evolution_rule_reject", args.candidate_id, exc)
    return tool_observation(
        tool_name="evolution_rule_reject",
        status="succeeded",
        summary=f"Rejected evolution rule candidate {args.candidate_id}",
        payload={"candidate_id": candidate.id, "status": candidate.status},
    )


def evolution_rule_accept_with_edits(
    args: EvolutionRuleAcceptWithEditsArgs,
    context: ToolExecutionContext,
) -> Observation:
    try:
        runtime = _rule_runtime(context)
        rule = runtime.accept_with_edits(
            args.candidate_id,
            rule_text=args.rule_text,
            scope=args.scope,
            activation_hint=args.activation_hint,
        )
    except (KeyError, RuntimeError, ValueError) as exc:
        return _rejected("evolution_rule_accept_with_edits", args.candidate_id, exc)
    return _accepted(
        "evolution_rule_accept_with_edits",
        args.candidate_id,
        rule.model_dump(mode="json"),
    )


def _rule_runtime(context: ToolExecutionContext):
    rule_store = EvolutionRuleStore(context.settings.data_dir / "evolution")
    return EvolutionRuleRuntime(_memory_runtime(context).review_queue, rule_store)


def _memory_store(context: ToolExecutionContext) -> MemoryStore:
    if isinstance(context.memory_store, MemoryStore):
        return context.memory_store
    return MemoryStore(context.settings.data_dir / "memory")


def _memory_runtime(context: ToolExecutionContext) -> MemoryRuntime:
    return MemoryRuntime(_memory_store(context))


def _analysis_reports_dir(context: ToolExecutionContext):
    return context.settings.data_dir / "analysis-reports"


def _analysis_ingestion_runtime(context: ToolExecutionContext):
    from app.evolution.analysis_ingestion import AnalysisIngestionRuntime

    return AnalysisIngestionRuntime(
        _memory_runtime(context),
        reports_dir=_analysis_reports_dir(context),
    )


def _compact_report(report) -> dict[str, object]:
    return {
        "run_id": report.run_id,
        "case_id": report.case_id,
        "failure_reasons": report.failure_reasons[:20],
        "expected_tools": report.expected_tools[:20],
        "observed_tools": report.observed_tools[:20],
        "root_causes": report.root_causes[:20],
        "recommendations": [item[:300] for item in report.recommendations[:10]],
        "source_report": report.source_path,
    }


def _compact_candidate(candidate: LessonCandidate) -> dict[str, object]:
    rule = _rule(candidate)
    return {
        "id": candidate.id,
        "status": candidate.status,
        "summary": candidate.summary,
        "rule_type": rule.rule_type,
        "rule_text": rule.rule_text[:300],
        "scope": rule.scope,
        "activation_hint": rule.activation_hint,
    }


def _view_candidate(candidate: LessonCandidate) -> dict[str, object]:
    payload = _compact_candidate(candidate)
    rule = _rule(candidate)
    payload.update(
        {
            "source_report": rule.source_report,
            "source_trace": rule.source_trace,
            "root_cause": rule.root_cause,
            "evidence": _bounded_evidence(rule.evidence),
        }
    )
    return payload


def _rule(candidate: LessonCandidate):
    if candidate.rule_candidate is None:
        raise ValueError(f"lesson candidate is not a rule candidate: {candidate.id}")
    return candidate.rule_candidate


def _bounded_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    bounded: dict[str, Any] = {}
    for key, value in list(evidence.items())[:20]:
        bounded[key] = _bounded_value(value)
    return bounded


def _bounded_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:1000]
    if isinstance(value, list):
        return [_bounded_value(item) for item in value[:20]]
    if isinstance(value, dict):
        return {key: _bounded_value(item) for key, item in list(value.items())[:20]}
    return value


def _accepted(tool_name: str, candidate_id: str, rule: dict[str, object]) -> Observation:
    return tool_observation(
        tool_name=tool_name,
        status="succeeded",
        summary=f"Accepted evolution rule candidate {candidate_id}",
        payload={"candidate_id": candidate_id, "rule": rule},
    )


def _rejected(tool_name: str, candidate_id: str, exc: Exception) -> Observation:
    return tool_observation(
        tool_name=tool_name,
        status="rejected",
        summary="Unable to operate on evolution rule candidate",
        payload={"candidate_id": candidate_id},
        error_message=str(exc),
    )
