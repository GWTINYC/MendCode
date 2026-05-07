import json
from pathlib import Path

from app.evolution.analysis_ingestion import (
    AnalysisIngestionRuntime,
    build_candidates_from_analysis_report,
    load_analysis_report,
)
from app.evolution.runtime import EvolutionRuntime
from app.memory.runtime import MemoryRuntime
from app.memory.store import MemoryStore


def _write_report(
    path: Path,
    *,
    case_id: str = "git-status-natural-language",
    root_causes: list[str] | None = None,
    failure_reasons: list[str] | None = None,
) -> Path:
    payload = {
        "run_id": "run-1",
        "case_id": case_id,
        "failure_reasons": failure_reasons or ["missing_expected_tools"],
        "expected_tools": ["git"],
        "observed_tools": [],
        "root_causes": root_causes or ["tool_selection_gap"],
        "recommendations": ["review tool schema and prompt rules for expected tools"],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_analysis_report_rejects_path_outside_reports_dir(tmp_path: Path) -> None:
    report_dir = tmp_path / "analysis-reports"
    outside = tmp_path / "other" / "report.json"
    outside.parent.mkdir()
    _write_report(outside)

    try:
        load_analysis_report(outside, reports_dir=report_dir)
    except ValueError as exc:
        assert "analysis report path must stay inside reports_dir" in str(exc)
    else:
        raise AssertionError("expected path boundary rejection")


def test_build_candidates_maps_tool_selection_gap_to_rule_and_memory(
    tmp_path: Path,
) -> None:
    report_dir = tmp_path / "analysis-reports"
    report_dir.mkdir()
    report = load_analysis_report(
        _write_report(report_dir / "run-1-case.json"),
        reports_dir=report_dir,
    )

    candidates = build_candidates_from_analysis_report(report)

    assert [candidate.target_kind for candidate in candidates] == [
        "rule",
        "tool_schema_hint",
        "memory",
    ]
    rule_candidate = candidates[0]
    assert rule_candidate.rule_candidate is not None
    assert rule_candidate.rule_candidate.rule_type == "tool_required"
    assert "git" in rule_candidate.rule_candidate.rule_text
    assert rule_candidate.rule_candidate.source_report == str(report.source_path)
    assert rule_candidate.evidence["case_id"] == "git-status-natural-language"
    assert "recommendations" in rule_candidate.evidence
    memory_candidate = candidates[1]
    assert memory_candidate.target_kind == "tool_schema_hint"
    assert memory_candidate.kind == "tool_schema_hint"
    assert memory_candidate.suggested_skill is None
    memory_candidate = candidates[2]
    assert memory_candidate.kind == "failure_lesson"
    assert memory_candidate.suggested_memory_kind == "failure_lesson"


def test_build_candidates_maps_answer_style_gap_to_answer_style_rule(
    tmp_path: Path,
) -> None:
    report_dir = tmp_path / "analysis-reports"
    report_dir.mkdir()
    report = load_analysis_report(
        _write_report(
            report_dir / "run-1-last-line.json",
            case_id="file-last-line",
            root_causes=["answer_style_gap"],
            failure_reasons=["answer_too_verbose"],
        ),
        reports_dir=report_dir,
    )

    candidates = build_candidates_from_analysis_report(report)

    assert len(candidates) == 3
    assert candidates[0].rule_candidate is not None
    assert candidates[0].rule_candidate.rule_type == "answer_style"
    assert "简洁" in candidates[0].rule_candidate.rule_text
    assert candidates[1].target_kind == "prompt_rule"
    assert candidates[1].kind == "prompt_rule_lesson"
    assert "answer_style_gap" in candidates[1].evidence["root_causes"]
    assert candidates[2].target_kind == "memory"


def test_build_candidates_maps_test_fix_failure_to_skill_candidate(
    tmp_path: Path,
) -> None:
    report_dir = tmp_path / "analysis-reports"
    report_dir.mkdir()
    report = load_analysis_report(
        _write_report(
            report_dir / "run-1-test-fix.json",
            case_id="patch-repair-test-fix",
            root_causes=["verification_recovered"],
            failure_reasons=["test_failed_then_passed"],
        ),
        reports_dir=report_dir,
    )

    candidates = build_candidates_from_analysis_report(report)

    assert [candidate.target_kind for candidate in candidates] == ["skill", "memory"]
    skill_candidate = candidates[0]
    assert skill_candidate.kind == "skill_lesson"
    assert skill_candidate.suggested_skill == "test-fix"
    assert skill_candidate.evidence["case_id"] == "patch-repair-test-fix"


def test_analysis_ingestion_runtime_enqueues_reports_once(tmp_path: Path) -> None:
    reports_dir = tmp_path / "analysis-reports"
    reports_dir.mkdir()
    _write_report(reports_dir / "run-1-case.json")
    memory_runtime = MemoryRuntime(MemoryStore(tmp_path / "memory"))
    runtime = AnalysisIngestionRuntime(memory_runtime, reports_dir=reports_dir)

    first = runtime.ingest_reports()
    second = runtime.ingest_reports()

    assert first.report_count == 1
    assert first.generated_count == 3
    assert first.enqueued_count == 3
    assert second.generated_count == 3
    assert second.enqueued_count == 0
    assert len(memory_runtime.list_candidates()) == 3


def test_evolution_runtime_ingests_analysis_reports(tmp_path: Path) -> None:
    reports_dir = tmp_path / "analysis-reports"
    reports_dir.mkdir()
    _write_report(reports_dir / "run-1-case.json")
    memory_runtime = MemoryRuntime(MemoryStore(tmp_path / "memory"))
    runtime = EvolutionRuntime(memory_runtime)

    result = runtime.ingest_analysis_reports(reports_dir)

    assert result.report_count == 1
    assert result.enqueued_count == 3
    assert {candidate.target_kind for candidate in memory_runtime.list_candidates()} == {
        "memory",
        "rule",
        "tool_schema_hint",
    }
