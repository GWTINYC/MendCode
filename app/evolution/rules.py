from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from app.evolution.models import EvolutionRule, EvolutionRuleCandidate

EDITABLE_RULE_FIELDS = {"rule_text", "scope", "activation_hint"}


class EvolutionRuleStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "rules.jsonl"

    def list_rules(self) -> list[EvolutionRule]:
        rules: list[EvolutionRule] = []
        for line in self._raw_lines():
            if not line.strip():
                continue
            try:
                rules.append(EvolutionRule.model_validate_json(line))
            except ValidationError:
                continue
        return rules

    def accept_candidate(
        self,
        candidate: EvolutionRuleCandidate,
        *,
        edits: dict[str, str] | None = None,
    ) -> EvolutionRule:
        existing = self.rule_for_candidate(candidate.candidate_id)
        if existing is not None:
            return existing
        payload = candidate.model_dump()
        if edits:
            immutable = sorted(set(edits) - EDITABLE_RULE_FIELDS)
            if immutable:
                raise ValueError(f"immutable rule fields cannot be edited: {', '.join(immutable)}")
            payload.update(edits)
        now = datetime.now().astimezone()
        rule = EvolutionRule(
            rule_id=_rule_id(candidate.candidate_id),
            candidate_id=candidate.candidate_id,
            rule_type=payload["rule_type"],
            rule_text=payload["rule_text"],
            scope=payload.get("scope") or "",
            activation_hint=payload.get("activation_hint") or "",
            evidence_ref=f"rule_candidate:{candidate.candidate_id}",
            source_report=payload.get("source_report"),
            source_trace=payload.get("source_trace"),
            created_at=now,
            updated_at=now,
            status="active",
        )
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(rule.model_dump_json())
            handle.write("\n")
        return rule

    def rule_for_candidate(self, candidate_id: str) -> EvolutionRule | None:
        for rule in self.list_rules():
            if rule.candidate_id == candidate_id:
                return rule
        return None

    def _raw_lines(self) -> list[str]:
        if not self.path.exists():
            return []
        return self.path.read_text(encoding="utf-8").splitlines()


def _rule_id(candidate_id: str) -> str:
    digest = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:16]
    return f"rule-{digest}"
