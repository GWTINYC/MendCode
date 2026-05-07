from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.evolution.models import LessonCandidate

AcceptedGuidanceKind = Literal["prompt_rule", "tool_schema_hint", "skill"]


class AcceptedGuidance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guidance_id: str
    candidate_id: str
    target_kind: AcceptedGuidanceKind
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=1200)
    activation_hint: str = Field(default="", max_length=600)
    suggested_skill: str | None = Field(default=None, max_length=120)
    source_report: str | None = Field(default=None, max_length=500)
    source_trace: str | None = Field(default=None, max_length=500)
    evidence_ref: str | None = Field(default=None, max_length=240)
    accepted_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    status: Literal["active", "disabled"] = "active"
    skill_path: str | None = Field(default=None, max_length=500)


class AcceptedGuidanceRecall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guidance: list[AcceptedGuidance] = Field(default_factory=list)
    total_active_guidance: int = 0
    truncated: bool = False


class AcceptedGuidanceStore:
    def __init__(self, root: Path, *, skills_root: Path | None = None) -> None:
        self.root = root
        self.skills_root = skills_root or root.parent / "skills"

    def accept_candidate(self, candidate: LessonCandidate) -> AcceptedGuidance:
        if candidate.target_kind not in {"prompt_rule", "tool_schema_hint", "skill"}:
            raise ValueError(
                f"candidate target cannot be accepted as guidance: {candidate.target_kind}"
            )
        existing = self.guidance_for_candidate(candidate.id, candidate.target_kind)
        if existing is not None:
            return existing
        guidance = _guidance_from_candidate(candidate, skills_root=self.skills_root)
        self._append(guidance)
        if guidance.target_kind == "skill":
            self._write_skill(guidance)
        return guidance

    def list_by_kind(self, kind: AcceptedGuidanceKind | None = None) -> list[AcceptedGuidance]:
        kinds = [kind] if kind is not None else ["prompt_rule", "tool_schema_hint", "skill"]
        guidance: list[AcceptedGuidance] = []
        for target_kind in kinds:
            path = self._path(target_kind)
            lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    guidance.append(AcceptedGuidance.model_validate_json(line))
                except ValidationError:
                    continue
        return guidance

    def guidance_for_candidate(
        self,
        candidate_id: str,
        kind: AcceptedGuidanceKind,
    ) -> AcceptedGuidance | None:
        for guidance in self.list_by_kind(kind):
            if guidance.candidate_id == candidate_id:
                return guidance
        return None

    def _append(self, guidance: AcceptedGuidance) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(guidance.target_kind)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(guidance.model_dump_json())
            handle.write("\n")

    def _path(self, kind: AcceptedGuidanceKind) -> Path:
        if kind == "prompt_rule":
            return self.root / "prompt_rules.jsonl"
        if kind == "tool_schema_hint":
            return self.root / "tool_schema_hints.jsonl"
        return self.root / "skills.jsonl"

    def _write_skill(self, guidance: AcceptedGuidance) -> None:
        if not guidance.suggested_skill:
            return
        skill_path = Path(guidance.skill_path or "")
        if not skill_path:
            return
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text(_skill_markdown(guidance), encoding="utf-8")


class EvolutionGuidanceRuntime:
    def __init__(self, store: AcceptedGuidanceStore) -> None:
        self.store = store

    def recall_for_turn(
        self,
        user_message: str,
        *,
        max_rules: int = 3,
        max_chars: int = 1200,
    ) -> AcceptedGuidanceRecall:
        active = [item for item in self.store.list_by_kind() if item.status == "active"]
        scored = [(item, _guidance_score(item, user_message)) for item in active]
        relevant = [(item, score) for item, score in scored if score > 0]
        ranked = sorted(
            relevant,
            key=lambda item: (0 if item[0].target_kind == "skill" else 1, -item[1]),
        )
        selected: list[AcceptedGuidance] = []
        total_chars = 0
        for item, _score in ranked:
            if len(selected) >= max_rules:
                break
            item_chars = len(item.model_dump_json())
            if selected and total_chars + item_chars > max_chars:
                break
            selected.append(item)
            total_chars += item_chars
        return AcceptedGuidanceRecall(
            guidance=selected,
            total_active_guidance=len(active),
            truncated=len(selected) < len(relevant),
        )


def _guidance_from_candidate(
    candidate: LessonCandidate,
    *,
    skills_root: Path,
) -> AcceptedGuidance:
    target_kind = candidate.target_kind
    if target_kind not in {"prompt_rule", "tool_schema_hint", "skill"}:
        raise ValueError(f"unsupported guidance candidate: {target_kind}")
    suggested_skill = candidate.suggested_skill if target_kind == "skill" else None
    skill_path = None
    if suggested_skill:
        skill_path = str(skills_root / _safe_skill_name(suggested_skill) / "SKILL.md")
    return AcceptedGuidance(
        guidance_id=_guidance_id(candidate.id, target_kind),
        candidate_id=candidate.id,
        target_kind=target_kind,  # type: ignore[arg-type]
        title=candidate.summary,
        content=candidate.summary,
        activation_hint=_activation_hint(candidate),
        suggested_skill=suggested_skill,
        source_report=_source_report(candidate),
        source_trace=candidate.source_trace_path,
        evidence_ref=f"lesson_candidate:{candidate.id}",
        skill_path=skill_path,
    )


def _source_report(candidate: LessonCandidate) -> str | None:
    value = candidate.evidence.get("source_report")
    return str(value) if value else None


def _activation_hint(candidate: LessonCandidate) -> str:
    pieces = [
        str(candidate.evidence.get("case_id") or ""),
        " ".join(str(item) for item in candidate.evidence.get("root_causes", []) if item),
        candidate.suggested_skill or "",
        candidate.summary,
    ]
    return " ".join(piece for piece in pieces if piece).strip()[:600]


def _guidance_id(candidate_id: str, target_kind: str) -> str:
    digest = hashlib.sha256(f"{target_kind}:{candidate_id}".encode("utf-8")).hexdigest()[:16]
    return f"{target_kind}-{digest}"


def _safe_skill_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "-", name.casefold()).strip("-")
    return normalized or "skill"


def _guidance_score(guidance: AcceptedGuidance, user_message: str) -> int:
    text = user_message.casefold()
    score = 0
    for weight, field in [
        (5, guidance.suggested_skill or ""),
        (4, guidance.activation_hint),
        (2, guidance.title),
        (1, guidance.content),
    ]:
        for token in _tokens(field):
            if token in text:
                score += weight
    if guidance.target_kind == "skill" and any(
        term in text for term in ["修复", "测试", "debug", "review", "repo", "map"]
    ):
        score += 3
    if guidance.target_kind == "prompt_rule" and any(
        term in text for term in ["简洁", "最后", "回答", "不要"]
    ):
        score += 3
    return score


def _tokens(value: str) -> set[str]:
    return {token for token in value.casefold().replace(",", " ").split() if len(token) >= 2}


def _skill_markdown(guidance: AcceptedGuidance) -> str:
    return (
        f"# {guidance.suggested_skill or guidance.title}\n\n"
        f"## Source\n\n"
        f"- candidate_id: `{guidance.candidate_id}`\n"
        f"- source_report: `{guidance.source_report or ''}`\n"
        f"- source_trace: `{guidance.source_trace or ''}`\n\n"
        f"## Guidance\n\n"
        f"{guidance.content}\n"
    )
