import json
from pathlib import Path

from app.config.settings import Settings
from app.evolution.models import EvolutionRuleCandidate, LessonCandidate
from app.memory.runtime import MemoryRuntime
from app.memory.store import MemoryStore
from app.tools.registry import default_tool_registry
from app.tools.structured import ToolExecutionContext


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        app_name="MendCode",
        app_version="0.0.0",
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        traces_dir=tmp_path / "data" / "traces",
        workspace_root=tmp_path / ".worktrees",
        verification_timeout_seconds=60,
        cleanup_success_workspace=False,
    )


def _context(tmp_path: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_path=tmp_path,
        settings=_settings(tmp_path),
        memory_store=MemoryStore(tmp_path / "data" / "memory"),
    )


def _seed_rule_candidate(context: ToolExecutionContext, candidate_id: str = "rule-1") -> None:
    assert context.memory_store is not None
    MemoryRuntime(context.memory_store).enqueue_candidate(
        LessonCandidate(
            id=candidate_id,
            kind="tool_policy_lesson",
            summary="Git status must use a tool.",
            target_kind="rule",
            rule_candidate=EvolutionRuleCandidate(
                candidate_id=candidate_id,
                rule_type="tool_required",
                rule_text="查看 Git 状态前必须调用 git 工具。",
                scope="git status",
                activation_hint="git status",
                evidence={"missing_tools": ["git"]},
                root_cause="tool_selection_gap",
            ),
        )
    )


def _write_analysis_report(context: ToolExecutionContext) -> None:
    report_dir = context.settings.data_dir / "analysis-reports"
    report_dir.mkdir(parents=True)
    (report_dir / "run-1-git-status.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "case_id": "git-status-natural-language",
                "failure_reasons": ["missing_expected_tools"],
                "expected_tools": ["git"],
                "observed_tools": [],
                "root_causes": ["tool_selection_gap"],
                "recommendations": [
                    "review tool schema and prompt rules for expected tools",
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_evolution_rule_list_returns_compact_pending_candidates(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = _context(tmp_path)
    _seed_rule_candidate(context)

    result = registry.get("evolution_rule_list").execute({"status": "pending"}, context)

    assert result.status == "succeeded"
    assert result.payload["total_candidates"] == 1
    candidate = result.payload["candidates"][0]
    assert candidate["id"] == "rule-1"
    assert candidate["rule_type"] == "tool_required"
    assert "evidence" not in candidate


def test_evolution_rule_view_returns_bounded_evidence(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = _context(tmp_path)
    _seed_rule_candidate(context)

    result = registry.get("evolution_rule_view").execute({"candidate_id": "rule-1"}, context)

    assert result.status == "succeeded"
    assert result.payload["candidate"]["id"] == "rule-1"
    assert result.payload["candidate"]["evidence"]["missing_tools"] == ["git"]


def test_evolution_rule_accept_writes_rule(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = _context(tmp_path)
    _seed_rule_candidate(context)

    result = registry.get("evolution_rule_accept").execute({"candidate_id": "rule-1"}, context)

    assert result.status == "succeeded"
    assert result.payload["rule"]["candidate_id"] == "rule-1"
    assert (tmp_path / "data" / "evolution" / "rules.jsonl").exists()


def test_evolution_rule_accept_with_edits_preserves_evidence(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = _context(tmp_path)
    _seed_rule_candidate(context)

    result = registry.get("evolution_rule_accept_with_edits").execute(
        {
            "candidate_id": "rule-1",
            "rule_text": "回答 Git 状态前必须调用 git 工具。",
            "scope": "git status",
            "activation_hint": "git status",
        },
        context,
    )

    assert result.status == "succeeded"
    assert result.payload["rule"]["rule_text"] == "回答 Git 状态前必须调用 git 工具。"


def test_evolution_rule_reject_does_not_write_rule(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = _context(tmp_path)
    _seed_rule_candidate(context)

    result = registry.get("evolution_rule_reject").execute({"candidate_id": "rule-1"}, context)

    assert result.status == "succeeded"
    assert not (tmp_path / "data" / "evolution" / "rules.jsonl").exists()


def test_analysis_report_list_returns_compact_reports(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = _context(tmp_path)
    _write_analysis_report(context)

    result = registry.get("analysis_report_list").execute({}, context)

    assert result.status == "succeeded"
    assert result.payload["total_reports"] == 1
    report = result.payload["reports"][0]
    assert report["case_id"] == "git-status-natural-language"
    assert report["root_causes"] == ["tool_selection_gap"]
    assert "raw" not in report


def test_analysis_report_ingest_enqueues_review_candidates(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = _context(tmp_path)
    _write_analysis_report(context)

    result = registry.get("analysis_report_ingest").execute({}, context)

    assert result.status == "succeeded"
    assert result.payload["report_count"] == 1
    assert result.payload["enqueued_count"] == 3
    assert result.payload["candidate_ids"]
    assert MemoryRuntime(context.memory_store).list_candidates()[0].id.startswith("analysis-")
