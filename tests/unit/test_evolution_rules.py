from pathlib import Path

import pytest

from app.evolution.models import EvolutionRuleCandidate, LessonCandidate
from app.evolution.rules import EvolutionRuleRuntime, EvolutionRuleStore
from app.memory.runtime import MemoryRuntime
from app.memory.store import MemoryStore


def _candidate(candidate_id: str = "rule-1") -> EvolutionRuleCandidate:
    return EvolutionRuleCandidate(
        candidate_id=candidate_id,
        rule_type="observation_required",
        rule_text="Do not state local repository facts without a successful observation.",
        scope="local facts",
        activation_hint="git status, directory listing, file content",
        source_report="data/analysis-reports/session.json",
        source_trace="data/traces/session.jsonl",
        evidence={"unsupported_claim": "unsupported_local_claim"},
        root_cause="tool_selection_gap",
    )


def test_rule_candidate_defaults_are_pending() -> None:
    candidate = _candidate()

    assert candidate.status == "pending"
    assert candidate.rule_type == "observation_required"


def test_rule_store_accepts_candidate_and_persists_rule(tmp_path: Path) -> None:
    store = EvolutionRuleStore(tmp_path / "data" / "evolution")

    accepted = store.accept_candidate(_candidate())
    reloaded = EvolutionRuleStore(tmp_path / "data" / "evolution").list_rules()

    assert accepted.candidate_id == "rule-1"
    assert accepted.rule_type == "observation_required"
    assert accepted.status == "active"
    assert reloaded == [accepted]


def test_rule_store_accept_with_edits_only_changes_allowed_fields(tmp_path: Path) -> None:
    store = EvolutionRuleStore(tmp_path / "data" / "evolution")

    accepted = store.accept_candidate(
        _candidate(),
        edits={
            "rule_text": "Answer Git status only after calling git.",
            "scope": "git status",
            "activation_hint": "git status",
        },
    )

    assert accepted.rule_text == "Answer Git status only after calling git."
    assert accepted.scope == "git status"
    assert accepted.activation_hint == "git status"
    assert accepted.source_report == "data/analysis-reports/session.json"
    assert accepted.source_trace == "data/traces/session.jsonl"


def test_rule_store_rejects_immutable_edits(tmp_path: Path) -> None:
    store = EvolutionRuleStore(tmp_path / "data" / "evolution")

    with pytest.raises(ValueError, match="immutable"):
        store.accept_candidate(_candidate(), edits={"source_trace": "changed.jsonl"})


def test_rule_store_is_idempotent_for_same_candidate(tmp_path: Path) -> None:
    store = EvolutionRuleStore(tmp_path / "data" / "evolution")

    first = store.accept_candidate(_candidate())
    second = store.accept_candidate(_candidate())

    assert second.rule_id == first.rule_id
    assert store.list_rules() == [first]


def test_rule_runtime_accepts_rule_candidate_and_updates_queue(tmp_path: Path) -> None:
    memory = MemoryRuntime(MemoryStore(tmp_path / "data" / "memory"))
    runtime = EvolutionRuleRuntime(
        memory.review_queue,
        EvolutionRuleStore(tmp_path / "data" / "evolution"),
    )
    lesson = LessonCandidate(
        id="candidate-1",
        kind="tool_policy_lesson",
        summary="Git status needs git tool",
        target_kind="rule",
        rule_candidate=_candidate("candidate-1"),
    )
    memory.enqueue_candidate(lesson)

    accepted = runtime.accept("candidate-1")
    listed = memory.list_candidates()

    assert accepted.candidate_id == "candidate-1"
    assert listed[0].status == "accepted"


def test_rule_runtime_accept_with_edits_preserves_evidence(tmp_path: Path) -> None:
    memory = MemoryRuntime(MemoryStore(tmp_path / "data" / "memory"))
    runtime = EvolutionRuleRuntime(
        memory.review_queue,
        EvolutionRuleStore(tmp_path / "data" / "evolution"),
    )
    lesson = LessonCandidate(
        id="candidate-1",
        kind="tool_policy_lesson",
        summary="Git status needs git tool",
        target_kind="rule",
        rule_candidate=_candidate("candidate-1"),
    )
    memory.enqueue_candidate(lesson)

    accepted = runtime.accept_with_edits(
        "candidate-1",
        rule_text="回答 Git 状态前必须调用 git 工具。",
        scope="git status",
        activation_hint="git status",
    )

    assert accepted.rule_text == "回答 Git 状态前必须调用 git 工具。"
    assert accepted.source_trace == "data/traces/session.jsonl"


def test_rule_runtime_rejects_rule_candidate_without_writing_rule(tmp_path: Path) -> None:
    memory = MemoryRuntime(MemoryStore(tmp_path / "data" / "memory"))
    rule_store = EvolutionRuleStore(tmp_path / "data" / "evolution")
    runtime = EvolutionRuleRuntime(memory.review_queue, rule_store)
    lesson = LessonCandidate(
        id="candidate-1",
        kind="tool_policy_lesson",
        summary="Git status needs git tool",
        target_kind="rule",
        rule_candidate=_candidate("candidate-1"),
    )
    memory.enqueue_candidate(lesson)

    rejected = runtime.reject("candidate-1")

    assert rejected.status == "rejected"
    assert rule_store.list_rules() == []


def test_rule_runtime_recalls_relevant_top_three_rules(tmp_path: Path) -> None:
    store = EvolutionRuleStore(tmp_path / "data" / "evolution")
    hints = ["git status", "last sentence", "directory listing", "pytest"]
    for index, hint in enumerate(hints, start=1):
        store.accept_candidate(
            EvolutionRuleCandidate(
                candidate_id=f"rule-{index}",
                rule_type="tool_required",
                rule_text=f"Rule for {hint}",
                scope=hint,
                activation_hint=hint,
            )
        )
    runtime = EvolutionRuleRuntime(None, store)

    recalled = runtime.recall_for_turn("请查看 git status", max_rules=3, max_chars=500)

    assert len(recalled.rules) <= 3
    assert recalled.rules[0].scope == "git status"
    assert "Rule for git status" in recalled.context_block
