from pathlib import Path

import pytest

from app.evolution.models import EvolutionRuleCandidate
from app.evolution.rules import EvolutionRuleStore


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
