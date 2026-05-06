from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StoryStatus = Literal["planned", "running", "passed", "failed", "blocked"]


class Story(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    priority: int = Field(ge=0)
    passes: bool = False
    acceptance_criteria: list[str] = Field(default_factory=list)
    verification_commands: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class StoryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_name: str = Field(min_length=1)
    progress_path: str = "progress.md"
    stories: list[Story] = Field(default_factory=list)

    def story_by_id(self, story_id: str) -> Story:
        for story in self.stories:
            if story.id == story_id:
                return story
        raise KeyError(f"unknown story id: {story_id}")

    @property
    def completed_count(self) -> int:
        return sum(1 for story in self.stories if story.passes)

    @property
    def remaining_count(self) -> int:
        return sum(1 for story in self.stories if not story.passes)


def load_story_plan(path: Path) -> StoryPlan:
    data = json.loads(path.read_text(encoding="utf-8"))
    return StoryPlan.model_validate(data)


def save_story_plan(path: Path, plan: StoryPlan) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        plan.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def pick_next_story(plan: StoryPlan) -> Story | None:
    candidates = [story for story in plan.stories if not story.passes]
    if not candidates:
        return None
    return sorted(candidates, key=lambda story: (story.priority, story.id))[0]


def mark_story_passed(path: Path, story_id: str) -> Story:
    plan = load_story_plan(path)
    story = plan.story_by_id(story_id)
    updated_story = story.model_copy(update={"passes": True})
    updated_stories = [
        updated_story if item.id == story_id else item
        for item in plan.stories
    ]
    save_story_plan(path, plan.model_copy(update={"stories": updated_stories}))
    return updated_story


def append_progress_entry(
    *,
    plan_path: Path,
    plan: StoryPlan,
    story_id: str,
    status: StoryStatus,
    summary: str,
    verification: list[str] | None = None,
    trace_path: str | None = None,
    commit: str | None = None,
    learnings: list[str] | None = None,
) -> Path:
    story = plan.story_by_id(story_id)
    progress_path = _resolve_progress_path(plan_path, plan.progress_path)
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"## {story.id} - {status}",
        "",
        f"- title: {story.title}",
        f"- run_at: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- summary: {summary}",
    ]
    if commit:
        lines.append(f"- commit: {commit}")
    if trace_path:
        lines.append(f"- trace: {trace_path}")
    if verification:
        lines.append("- verification:")
        lines.extend(f"  - `{command}`" for command in verification)
    if learnings:
        lines.append("- learnings:")
        lines.extend(f"  - {learning}" for learning in learnings)
    lines.append("")
    with progress_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return progress_path


def _resolve_progress_path(plan_path: Path, progress_path: str) -> Path:
    candidate = Path(progress_path)
    if candidate.is_absolute():
        return candidate
    plan_root = plan_path.parent
    if candidate.parts and candidate.parts[0] == "tasks":
        for parent in plan_path.parents:
            if parent.name == "tasks":
                return parent.parent / candidate
    return plan_root / candidate
