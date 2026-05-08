from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.evolution.models import LessonCandidate


class SkillSource(Protocol):
    candidate_id: str
    title: str
    content: str
    suggested_skill: str | None
    source_report: str | None
    source_trace: str | None
    accepted_at: datetime
    status: Literal["active", "disabled"]


class SkillRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    candidate_id: str = Field(min_length=1, max_length=120)
    source_report: str | None = Field(default=None, max_length=500)
    source_trace: str | None = Field(default=None, max_length=500)
    accepted_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    status: Literal["active", "disabled"] = "active"
    skill_path: str = Field(min_length=1, max_length=500)


class BuiltinSkillSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=500)
    activation_hint: str = Field(default="", max_length=300)
    source: Literal["built_in"] = "built_in"
    status: Literal["active"] = "active"


_BUILTIN_SKILLS: tuple[BuiltinSkillSummary, ...] = (
    BuiltinSkillSummary(
        name="test-fix",
        title="Test-Fix",
        summary="Run failing tests, inspect failure, patch, rerun focused test.",
        activation_hint="pytest failed test failing tests 修复 测试失败",
    ),
    BuiltinSkillSummary(
        name="review",
        title="Review",
        summary="Lead with findings, cite files, then note residual test risk.",
        activation_hint="review 审查 代码审查 风险 findings",
    ),
    BuiltinSkillSummary(
        name="debug",
        title="Debug",
        summary="Reproduce, isolate cause, make minimal fix, verify original symptom.",
        activation_hint="debug bug error exception failure 报错 调试",
    ),
    BuiltinSkillSummary(
        name="repo-map",
        title="Repo-Map",
        summary="Map structure, entry points, tests, and likely impact before edits.",
        activation_hint="repo map repository structure 项目结构 仓库结构 入口 测试命令",
    ),
)


def recall_builtin_skills(
    user_message: str,
    *,
    max_skills: int = 4,
    max_tokens: int = 400,
) -> list[BuiltinSkillSummary]:
    if max_skills <= 0 or max_tokens <= 0:
        return []
    scored = [
        (skill, _builtin_skill_score(skill, user_message))
        for skill in _BUILTIN_SKILLS
    ]
    ranked = sorted(
        [(skill, score) for skill, score in scored if score > 0],
        key=lambda item: (-item[1], item[0].name),
    )
    selected: list[BuiltinSkillSummary] = []
    for skill, _score in ranked:
        candidate = selected + [skill]
        if len(candidate) > max_skills:
            break
        if _skill_summaries_fit_budget(candidate, max_tokens=max_tokens):
            selected = candidate
            continue
        if selected:
            break
        compact = skill.model_copy(
            update={
                "summary": _compact_summary(skill.summary),
                "activation_hint": "",
            }
        )
        if _skill_summaries_fit_budget([compact], max_tokens=max_tokens):
            selected = [compact]
    return selected


def _builtin_skill_score(skill: BuiltinSkillSummary, user_message: str) -> int:
    text = user_message.casefold()
    score = 0
    for token in skill.activation_hint.casefold().split():
        if token and token in text:
            score += 4
    for token in skill.name.casefold().replace("-", " ").split():
        if token and token in text:
            score += 2
    return score


def _skill_summaries_fit_budget(
    summaries: list[BuiltinSkillSummary],
    *,
    max_tokens: int,
) -> bool:
    payload = {
        "evolution_rules": [],
        "evolution_guidance": [],
        "skill_summaries": [
            summary.model_dump(mode="json") for summary in summaries
        ],
    }
    return _estimate_tokens(payload) <= max_tokens


def _compact_summary(summary: str) -> str:
    first = summary.split(",", 1)[0].strip().rstrip(".")
    words = first.split()
    return " ".join(words[:4]).rstrip(".") + "."


def _estimate_tokens(value: object) -> int:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if not text:
        return 0
    return max(1, len(text) // 4)


class SkillStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def persist_candidate(self, candidate: LessonCandidate) -> SkillRecord:
        if candidate.target_kind != "skill":
            raise ValueError(f"candidate is not a skill candidate: {candidate.target_kind}")
        if not candidate.suggested_skill:
            raise ValueError("skill candidate must include suggested_skill")
        existing = self.record_for_candidate(candidate.id)
        if existing is not None:
            return existing
        source_report = candidate.evidence.get("source_report")
        return self._write(
            name=safe_skill_name(candidate.suggested_skill),
            candidate_id=candidate.id,
            title=candidate.suggested_skill,
            content=candidate.summary,
            source_report=str(source_report) if source_report else None,
            source_trace=candidate.source_trace_path,
            accepted_at=datetime.now().astimezone(),
            status="active",
        )

    def persist_guidance(self, guidance: SkillSource) -> SkillRecord:
        if not guidance.suggested_skill:
            raise ValueError("skill guidance must include suggested_skill")
        existing = self.record_for_candidate(guidance.candidate_id)
        if existing is not None:
            return existing
        return self._write(
            name=safe_skill_name(guidance.suggested_skill),
            candidate_id=guidance.candidate_id,
            title=guidance.suggested_skill or guidance.title,
            content=guidance.content,
            source_report=guidance.source_report,
            source_trace=guidance.source_trace,
            accepted_at=guidance.accepted_at,
            status=guidance.status,
        )

    def list_records(self) -> list[SkillRecord]:
        records: list[SkillRecord] = []
        if not self.root.exists():
            return records
        for path in sorted(self.root.glob("*/skill.json")):
            try:
                records.append(SkillRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValidationError):
                continue
        return records

    def record_for_candidate(self, candidate_id: str) -> SkillRecord | None:
        for record in self.list_records():
            if record.candidate_id == candidate_id:
                return record
        return None

    def _write(
        self,
        *,
        name: str,
        candidate_id: str,
        title: str,
        content: str,
        source_report: str | None,
        source_trace: str | None,
        accepted_at: datetime,
        status: Literal["active", "disabled"],
    ) -> SkillRecord:
        skill_dir = self.root / name
        skill_path = skill_dir / "SKILL.md"
        record = SkillRecord(
            name=name,
            candidate_id=candidate_id,
            source_report=source_report,
            source_trace=source_trace,
            accepted_at=accepted_at,
            status=status,
            skill_path=str(skill_path),
        )
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path.write_text(
            _skill_markdown(
                title=title,
                candidate_id=candidate_id,
                source_report=source_report,
                source_trace=source_trace,
                content=content,
            ),
            encoding="utf-8",
        )
        (skill_dir / "skill.json").write_text(
            json.dumps(
                record.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return record


def safe_skill_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "-", name.casefold()).strip("-")
    return normalized or "skill"


def _skill_markdown(
    *,
    title: str,
    candidate_id: str,
    source_report: str | None,
    source_trace: str | None,
    content: str,
) -> str:
    return (
        f"# {title}\n\n"
        f"## Source\n\n"
        f"- candidate_id: `{candidate_id}`\n"
        f"- source_report: `{source_report or ''}`\n"
        f"- source_trace: `{source_trace or ''}`\n\n"
        f"## Guidance\n\n"
        f"{content}\n"
    )
