import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.evolution.models import EvolutionRuleCandidate, LessonCandidate
from app.memory.runtime import MemoryRuntime

_DETERMINISTIC_CREATED_AT = datetime.fromtimestamp(0, tz=timezone.utc)
_MAX_EVIDENCE_ITEMS = 20
_MAX_EVIDENCE_TEXT = 400


class AnalysisReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str = Field(default="", max_length=160)
    case_id: str = Field(min_length=1, max_length=240)
    failure_reasons: list[str] = Field(default_factory=list)
    expected_tools: list[str] = Field(default_factory=list)
    observed_tools: list[str] = Field(default_factory=list)
    root_causes: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    source_path: str = Field(min_length=1, max_length=500)
    source_trace: str | None = Field(default=None, max_length=500)


class AnalysisIngestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_count: int = 0
    generated_count: int = 0
    enqueued_count: int = 0
    skipped_existing_count: int = 0
    candidates: list[LessonCandidate] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)


def load_analysis_report(path: Path, *, reports_dir: Path) -> AnalysisReport:
    resolved_path = path.resolve()
    resolved_dir = reports_dir.resolve()
    try:
        resolved_path.relative_to(resolved_dir)
    except ValueError as exc:
        raise ValueError("analysis report path must stay inside reports_dir") from exc
    payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("analysis report must be a JSON object")
    payload.setdefault("source_path", str(resolved_path))
    return AnalysisReport.model_validate(payload)


def build_candidates_from_analysis_report(report: AnalysisReport) -> list[LessonCandidate]:
    candidates: list[LessonCandidate] = []
    for root_cause in _dedupe(report.root_causes or ["unknown"]):
        rule_candidate = _rule_candidate_for_root_cause(report, root_cause)
        if rule_candidate is not None:
            candidates.append(rule_candidate)
        review_candidate = _review_candidate_for_root_cause(report, root_cause)
        if review_candidate is not None:
            candidates.append(review_candidate)
    candidates.append(_memory_candidate_for_report(report))
    return candidates


class AnalysisIngestionRuntime:
    def __init__(self, memory_runtime: MemoryRuntime, *, reports_dir: Path) -> None:
        self.memory_runtime = memory_runtime
        self.reports_dir = reports_dir

    def list_reports(self) -> list[AnalysisReport]:
        if not self.reports_dir.exists():
            return []
        reports: list[AnalysisReport] = []
        for path in sorted(self.reports_dir.glob("*.json")):
            reports.append(load_analysis_report(path, reports_dir=self.reports_dir))
        return reports

    def ingest_reports(self, *, limit: int | None = None) -> AnalysisIngestionResult:
        result = AnalysisIngestionResult()
        existing_ids = {candidate.id for candidate in self.memory_runtime.list_candidates()}
        paths = sorted(self.reports_dir.glob("*.json")) if self.reports_dir.exists() else []
        if limit is not None:
            paths = paths[:limit]
        for path in paths:
            try:
                report = load_analysis_report(path, reports_dir=self.reports_dir)
                candidates = build_candidates_from_analysis_report(report)
            except Exception as exc:
                result.errors.append(
                    {"path": str(path), "type": type(exc).__name__, "message": str(exc)}
                )
                continue
            result.report_count += 1
            result.generated_count += len(candidates)
            for candidate in candidates:
                result.candidates.append(candidate)
                if candidate.id in existing_ids:
                    result.skipped_existing_count += 1
                    continue
                self.memory_runtime.enqueue_candidate(candidate)
                existing_ids.add(candidate.id)
                result.enqueued_count += 1
        return result


def _rule_candidate_for_root_cause(
    report: AnalysisReport,
    root_cause: str,
) -> LessonCandidate | None:
    if root_cause == "tool_selection_gap":
        tools = ", ".join(report.expected_tools) or "the expected local tool"
        return _rule_lesson_candidate(
            report,
            root_cause=root_cause,
            rule_type="tool_required",
            rule_text=(
                f"When a user asks about case `{report.case_id}`, use the expected "
                f"tool(s) before answering: {tools}."
            ),
            scope=report.case_id,
            activation_hint=" ".join(report.expected_tools + [report.case_id]),
        )
    if root_cause == "answer_style_gap":
        return _rule_lesson_candidate(
            report,
            root_cause=root_cause,
            rule_type="answer_style",
            rule_text=(
                "回答文件末句、目录状态或单点事实时保持简洁，只返回用户需要的结论，"
                "不要把完整工具输出复制到聊天流。"
            ),
            scope=report.case_id,
            activation_hint="last line final sentence concise answer 简洁",
        )
    if root_cause == "permission_policy_gap":
        return _rule_lesson_candidate(
            report,
            root_cause=root_cause,
            rule_type="observation_required",
            rule_text=(
                "High-risk shell, install, network, git mutate, and destructive operations "
                "must produce a permission observation before the final response."
            ),
            scope=report.case_id,
            activation_hint="permission dangerous shell install network git reset",
        )
    if root_cause == "tui_visibility_gap":
        return _rule_lesson_candidate(
            report,
            root_cause=root_cause,
            rule_type="answer_style",
            rule_text=(
                "Keep trace paths and raw payload details in logs or detail views, "
                "not visible chat."
            ),
            scope=report.case_id,
            activation_hint="trace path visible chat output",
        )
    if root_cause == "unknown":
        return None
    if root_cause in {"verification_recovered", "test_fix_gap"}:
        return None
    return _rule_lesson_candidate(
        report,
        root_cause=root_cause,
        rule_type="tool_schema_hint",
        rule_text=(
            f"Review tool descriptions and prompt rules for benchmark case `{report.case_id}`."
        ),
        scope=report.case_id,
        activation_hint=root_cause,
    )


def _review_candidate_for_root_cause(
    report: AnalysisReport,
    root_cause: str,
) -> LessonCandidate | None:
    if root_cause == "tool_selection_gap":
        tools = ", ".join(report.expected_tools) or "expected local tools"
        return _typed_review_candidate(
            report,
            root_cause=root_cause,
            target_kind="tool_schema_hint",
            kind="tool_schema_hint",
            summary=(
                f"Tool schema hint candidate: {report.case_id} should steer "
                f"the model toward {tools}."
            ),
            confidence=0.7,
        )
    if root_cause == "answer_style_gap":
        return _typed_review_candidate(
            report,
            root_cause=root_cause,
            target_kind="prompt_rule",
            kind="prompt_rule_lesson",
            summary=(
                f"Prompt rule candidate: {report.case_id} should keep answers "
                "concise and observation-grounded."
            ),
            confidence=0.69,
        )
    if root_cause in {"verification_recovered", "test_fix_gap"} or _looks_like_test_fix(report):
        return _typed_review_candidate(
            report,
            root_cause=root_cause,
            target_kind="skill",
            kind="skill_lesson",
            summary=(
                f"Skill candidate: {report.case_id} should refine the test-fix workflow."
            ),
            suggested_skill="test-fix",
            confidence=0.66,
        )
    return None


def _rule_lesson_candidate(
    report: AnalysisReport,
    *,
    root_cause: str,
    rule_type: str,
    rule_text: str,
    scope: str,
    activation_hint: str,
) -> LessonCandidate:
    candidate_id = _candidate_id(
        {
            "target": "rule",
            "case_id": report.case_id,
            "root_cause": root_cause,
            "rule_type": rule_type,
            "rule_text": rule_text,
        }
    )
    rule = EvolutionRuleCandidate(
        candidate_id=candidate_id,
        rule_type=rule_type,  # type: ignore[arg-type]
        rule_text=rule_text,
        scope=scope,
        activation_hint=activation_hint,
        source_report=report.source_path,
        source_trace=report.source_trace,
        evidence=_evidence(report),
        root_cause=root_cause,
        created_at=_DETERMINISTIC_CREATED_AT,
        updated_at=_DETERMINISTIC_CREATED_AT,
    )
    return LessonCandidate(
        id=candidate_id,
        kind="tool_policy_lesson" if rule_type == "tool_required" else "failure_lesson",
        summary=f"Benchmark failure rule candidate: {report.case_id} ({root_cause})",
        evidence=_evidence(report),
        source_trace_path=report.source_trace,
        confidence=0.72,
        target_kind="rule",
        rule_candidate=rule,
        created_at=_DETERMINISTIC_CREATED_AT,
        updated_at=_DETERMINISTIC_CREATED_AT,
    )


def _typed_review_candidate(
    report: AnalysisReport,
    *,
    root_cause: str,
    target_kind: str,
    kind: str,
    summary: str,
    confidence: float,
    suggested_skill: str | None = None,
) -> LessonCandidate:
    candidate_id = _candidate_id(
        {
            "target": target_kind,
            "kind": kind,
            "case_id": report.case_id,
            "root_cause": root_cause,
            "suggested_skill": suggested_skill,
            "recommendations": report.recommendations,
        }
    )
    return LessonCandidate(
        id=candidate_id,
        kind=kind,  # type: ignore[arg-type]
        summary=summary,
        evidence=_evidence(report),
        source_trace_path=report.source_trace,
        suggested_memory_kind="trace_insight",
        suggested_skill=suggested_skill,
        confidence=confidence,
        target_kind=target_kind,  # type: ignore[arg-type]
        created_at=_DETERMINISTIC_CREATED_AT,
        updated_at=_DETERMINISTIC_CREATED_AT,
    )


def _memory_candidate_for_report(report: AnalysisReport) -> LessonCandidate:
    root_cause = ", ".join(report.root_causes) or "unknown"
    candidate_id = _candidate_id(
        {
            "target": "memory",
            "case_id": report.case_id,
            "failure_reasons": report.failure_reasons,
            "root_causes": report.root_causes,
        }
    )
    return LessonCandidate(
        id=candidate_id,
        kind="failure_lesson",
        summary=f"Benchmark failure lesson: {report.case_id} ({root_cause})",
        evidence=_evidence(report),
        source_trace_path=report.source_trace,
        suggested_memory_kind="failure_lesson",
        confidence=0.68,
        created_at=_DETERMINISTIC_CREATED_AT,
        updated_at=_DETERMINISTIC_CREATED_AT,
    )


def _looks_like_test_fix(report: AnalysisReport) -> bool:
    haystack = " ".join(
        [report.case_id, *report.failure_reasons, *report.recommendations]
    ).casefold()
    return any(
        token in haystack
        for token in ["test-fix", "test_fix", "pytest", "verification"]
    )


def _candidate_id(payload: dict[str, object]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()[:32]
    return f"analysis-{digest}"


def _evidence(report: AnalysisReport) -> dict[str, object]:
    return {
        "run_id": _bounded_text(report.run_id),
        "case_id": report.case_id,
        "failure_reasons": _bounded_list(report.failure_reasons),
        "expected_tools": _bounded_list(report.expected_tools),
        "observed_tools": _bounded_list(report.observed_tools),
        "root_causes": _bounded_list(report.root_causes),
        "recommendations": _bounded_list(report.recommendations),
        "source_report": report.source_path,
    }


def _dedupe(values: list[str]) -> list[str]:
    return [value for value in dict.fromkeys(value.strip() for value in values) if value]


def _bounded_list(values: list[str]) -> list[str]:
    return [_bounded_text(value) for value in values[:_MAX_EVIDENCE_ITEMS]]


def _bounded_text(value: str) -> str:
    text = value.strip()
    if len(text) <= _MAX_EVIDENCE_TEXT:
        return text
    return f"{text[:_MAX_EVIDENCE_TEXT]}..."
