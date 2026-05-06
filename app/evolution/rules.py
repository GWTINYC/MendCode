from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.evolution.models import EvolutionRule, EvolutionRuleCandidate, LessonCandidate
from app.memory.review_queue import MemoryReviewQueue

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


class EvolutionRuleRecall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[EvolutionRule] = Field(default_factory=list)
    context_block: str = ""
    total_active_rules: int = 0
    truncated: bool = False


class EvolutionRuleRuntime:
    def __init__(
        self,
        review_queue: MemoryReviewQueue | None,
        rule_store: EvolutionRuleStore,
    ) -> None:
        self.review_queue = review_queue
        self.rule_store = rule_store

    def accept(self, candidate_id: str) -> EvolutionRule:
        candidate = self._rule_lesson(candidate_id)
        rule_candidate = candidate.rule_candidate
        if rule_candidate is None:
            raise ValueError(f"review candidate is not a rule candidate: {candidate_id}")
        rule = self.rule_store.accept_candidate(rule_candidate)
        self._update_status(candidate.id, "accepted")
        return rule

    def accept_with_edits(
        self,
        candidate_id: str,
        *,
        rule_text: str,
        scope: str,
        activation_hint: str,
    ) -> EvolutionRule:
        candidate = self._rule_lesson(candidate_id)
        rule_candidate = candidate.rule_candidate
        if rule_candidate is None:
            raise ValueError(f"review candidate is not a rule candidate: {candidate_id}")
        rule = self.rule_store.accept_candidate(
            rule_candidate,
            edits={
                "rule_text": rule_text,
                "scope": scope,
                "activation_hint": activation_hint,
            },
        )
        self._update_status(candidate.id, "accepted")
        return rule

    def reject(self, candidate_id: str) -> LessonCandidate:
        candidate = self._rule_lesson(candidate_id)
        return self._update_status(candidate.id, "rejected")

    def list_candidates(self, *, status: str = "pending", limit: int = 20) -> list[LessonCandidate]:
        if self.review_queue is None:
            return []
        candidates = [
            candidate
            for candidate in self.review_queue.list_candidates()
            if candidate.target_kind == "rule" and candidate.rule_candidate is not None
        ]
        if status != "all":
            candidates = [candidate for candidate in candidates if candidate.status == status]
        return candidates[:limit]

    def candidate_for_id(self, candidate_id: str) -> LessonCandidate:
        return self._rule_lesson(candidate_id)

    def recall_for_turn(
        self,
        user_message: str,
        *,
        max_rules: int = 3,
        max_chars: int = 1200,
    ) -> EvolutionRuleRecall:
        active_rules = [rule for rule in self.rule_store.list_rules() if rule.status == "active"]
        scored_rules = [
            (rule, _rule_score(rule, user_message))
            for rule in active_rules
        ]
        ranked = sorted(scored_rules, key=lambda item: item[1], reverse=True)
        relevant = [(rule, score) for rule, score in ranked if score > 0]
        selected: list[EvolutionRule] = []
        lines = ["Accepted Evolution Rules:"]
        total_chars = len(lines[0])
        for rule, _score in relevant:
            if len(selected) >= max_rules:
                break
            line = f"- [{rule.rule_type}] {rule.rule_text}"
            if selected and total_chars + len(line) > max_chars:
                break
            selected.append(rule)
            lines.append(line)
            total_chars += len(line)
        return EvolutionRuleRecall(
            rules=selected,
            context_block="\n".join(lines) if selected else "",
            total_active_rules=len(active_rules),
            truncated=len(selected) < len(relevant),
        )

    def _rule_lesson(self, candidate_id: str) -> LessonCandidate:
        if self.review_queue is None:
            raise KeyError(f"unknown rule candidate: {candidate_id}")
        for candidate in self.review_queue.list_candidates():
            if candidate.id != candidate_id:
                continue
            if candidate.target_kind != "rule" or candidate.rule_candidate is None:
                raise ValueError(f"review candidate is not a rule candidate: {candidate_id}")
            if candidate.status == "accepted":
                raise ValueError(f"cannot modify accepted rule candidate: {candidate_id}")
            if candidate.status == "rejected":
                raise ValueError(f"cannot modify rejected rule candidate: {candidate_id}")
            return candidate
        raise KeyError(f"unknown rule candidate: {candidate_id}")

    def _update_status(self, candidate_id: str, status: str) -> LessonCandidate:
        if self.review_queue is None:
            raise KeyError(f"unknown rule candidate: {candidate_id}")
        if status not in {"accepted", "rejected"}:
            raise ValueError(f"unsupported rule candidate status: {status}")
        return self.review_queue.update_status(candidate_id, status)


def _rule_id(candidate_id: str) -> str:
    digest = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:16]
    return f"rule-{digest}"


def _rule_score(rule: EvolutionRule, user_message: str) -> int:
    text = user_message.casefold()
    score = 0
    for weight, field in [
        (5, rule.scope),
        (4, rule.activation_hint),
        (2, rule.rule_text),
    ]:
        for token in _tokens(field):
            if token in text:
                score += weight
    if rule.rule_type == "tool_required" and any(
        term in text for term in ["git", "文件", "目录", "status"]
    ):
        score += 2
    if rule.rule_type == "observation_required" and any(
        term in text for term in ["文件", "目录", "git", "状态"]
    ):
        score += 2
    return score


def _tokens(value: str) -> set[str]:
    return {token for token in value.casefold().replace(",", " ").split() if len(token) >= 2}
