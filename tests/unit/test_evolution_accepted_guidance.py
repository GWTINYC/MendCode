import json
from pathlib import Path

from app.context.manager import ContextManager
from app.evolution.accepted import AcceptedGuidanceStore, EvolutionGuidanceRuntime
from app.evolution.models import EvolutionRuleCandidate, LessonCandidate
from app.memory.runtime import MemoryRuntime
from app.memory.store import MemoryStore
from app.tools.registry import default_tool_registry
from tests.unit.test_memory_tools import context_for


def test_review_queue_accept_persists_prompt_rule_candidate(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = context_for(tmp_path)
    assert context.memory_store is not None
    candidate = LessonCandidate(
        kind="prompt_rule_lesson",
        target_kind="prompt_rule",
        summary="Keep final-line answers concise.",
        evidence={
            "case_id": "file-last-line",
            "root_causes": ["answer_style_gap"],
            "source_report": "analysis/report.json",
        },
        source_trace_path="traces/run.jsonl",
        confidence=0.7,
    )
    MemoryRuntime(context.memory_store).enqueue_candidate(candidate)

    result = registry.get("review_queue_accept").execute(
        {"candidate_id": candidate.id},
        context,
    )

    assert result.status == "succeeded"
    assert result.payload["accepted_guidance"]["target_kind"] == "prompt_rule"
    store = AcceptedGuidanceStore(context.settings.data_dir / "evolution")
    prompt_rules = store.list_by_kind("prompt_rule")
    assert len(prompt_rules) == 1
    assert prompt_rules[0].candidate_id == candidate.id
    assert prompt_rules[0].source_report == "analysis/report.json"
    assert prompt_rules[0].source_trace == "traces/run.jsonl"


def test_review_queue_accept_persists_skill_candidate_as_skill_md(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = context_for(tmp_path)
    assert context.memory_store is not None
    candidate = LessonCandidate(
        kind="skill_lesson",
        target_kind="skill",
        summary="Refine the test-fix workflow.",
        evidence={"case_id": "patch-repair-test-fix"},
        source_trace_path="traces/run.jsonl",
        suggested_skill="test-fix",
        confidence=0.7,
    )
    MemoryRuntime(context.memory_store).enqueue_candidate(candidate)

    result = registry.get("review_queue_accept").execute(
        {"candidate_id": candidate.id},
        context,
    )

    assert result.status == "succeeded"
    skill_path = context.settings.data_dir / "skills" / "test-fix" / "SKILL.md"
    assert skill_path.exists()
    assert "Refine the test-fix workflow." in skill_path.read_text(encoding="utf-8")
    assert result.payload["accepted_guidance"]["skill_path"] == str(skill_path)


def test_review_queue_accept_persists_tool_schema_hint_candidate(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = context_for(tmp_path)
    assert context.memory_store is not None
    candidate = LessonCandidate(
        kind="tool_schema_hint",
        target_kind="tool_schema_hint",
        summary="Use repo_status for natural-language Git status questions.",
        evidence={"case_id": "git-status-natural-language"},
        confidence=0.7,
    )
    MemoryRuntime(context.memory_store).enqueue_candidate(candidate)

    result = registry.get("review_queue_accept").execute(
        {"candidate_id": candidate.id},
        context,
    )

    assert result.status == "succeeded"
    assert result.payload["accepted_guidance"]["target_kind"] == "tool_schema_hint"
    hints = AcceptedGuidanceStore(context.settings.data_dir / "evolution").list_by_kind(
        "tool_schema_hint"
    )
    assert hints[0].candidate_id == candidate.id


def test_review_queue_accept_persists_rule_candidate(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = context_for(tmp_path)
    assert context.memory_store is not None
    candidate = LessonCandidate(
        id="rule-candidate-1",
        kind="tool_policy_lesson",
        target_kind="rule",
        summary="Use git before answering git status.",
        rule_candidate=EvolutionRuleCandidate(
            candidate_id="rule-candidate-1",
            rule_type="tool_required",
            rule_text="查看 Git 状态前必须调用 repo_status 或 git 工具。",
            scope="git status",
            activation_hint="git status",
        ),
    )
    MemoryRuntime(context.memory_store).enqueue_candidate(candidate)

    result = registry.get("review_queue_accept").execute(
        {"candidate_id": candidate.id},
        context,
    )

    assert result.status == "succeeded"
    assert result.payload["rule"]["candidate_id"] == candidate.id
    assert (context.settings.data_dir / "evolution" / "rules.jsonl").exists()


def test_context_manager_recalls_accepted_prompt_rules_and_skills(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = AcceptedGuidanceStore(data_dir / "evolution", skills_root=data_dir / "skills")
    store.accept_candidate(
        LessonCandidate(
            kind="prompt_rule_lesson",
            target_kind="prompt_rule",
            summary="Keep final-line answers concise.",
            evidence={"root_causes": ["answer_style_gap"]},
        )
    )
    store.accept_candidate(
        LessonCandidate(
            kind="skill_lesson",
            target_kind="skill",
            summary="Run failing tests before editing and rerun after patch.",
            suggested_skill="test-fix",
            evidence={"case_id": "patch-repair-test-fix"},
        )
    )
    manager = ContextManager(
        memory_runtime=MemoryRuntime(MemoryStore(data_dir / "memory")),
        evolution_rule_runtime=EvolutionGuidanceRuntime(store),
    )

    bundle = manager.begin_turn(
        user_message="帮我修复测试失败，最后回答要简洁",
        repo_path=tmp_path,
    )

    payload = json.loads(bundle.provider_context)
    guidance = payload["evolution_guidance"]
    assert [item["target_kind"] for item in guidance] == ["skill", "prompt_rule"]
    assert "test-fix" in json.dumps(guidance, ensure_ascii=False)
    assert "Keep final-line answers concise." in json.dumps(guidance, ensure_ascii=False)


def test_context_manager_recalls_accepted_tool_schema_hints(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = AcceptedGuidanceStore(data_dir / "evolution", skills_root=data_dir / "skills")
    store.accept_candidate(
        LessonCandidate(
            kind="tool_schema_hint",
            target_kind="tool_schema_hint",
            summary="Use repo_status for natural-language Git status questions.",
            evidence={"case_id": "git-status-natural-language"},
        )
    )
    manager = ContextManager(
        memory_runtime=MemoryRuntime(MemoryStore(data_dir / "memory")),
        evolution_rule_runtime=EvolutionGuidanceRuntime(store),
    )

    bundle = manager.begin_turn(user_message="查看 git 状态", repo_path=tmp_path)

    guidance = json.loads(bundle.provider_context)["evolution_guidance"]
    assert guidance[0]["target_kind"] == "tool_schema_hint"
    assert "repo_status" in json.dumps(guidance, ensure_ascii=False)


def test_context_manager_does_not_recall_pending_skill_candidate(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    memory_store = MemoryStore(data_dir / "memory")
    MemoryRuntime(memory_store).enqueue_candidate(
        LessonCandidate(
            kind="skill_lesson",
            target_kind="skill",
            summary="Pending skills must not affect runtime.",
            suggested_skill="test-fix",
        )
    )
    manager = ContextManager(
        memory_runtime=MemoryRuntime(memory_store),
        evolution_rule_runtime=EvolutionGuidanceRuntime(
            AcceptedGuidanceStore(data_dir / "evolution", skills_root=data_dir / "skills")
        ),
    )

    bundle = manager.begin_turn(user_message="修复测试", repo_path=tmp_path)

    assert json.loads(bundle.provider_context)["evolution_guidance"] == []
