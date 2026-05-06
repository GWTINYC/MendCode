import json
from pathlib import Path

from app.runtime.story_runner import (
    append_progress_entry,
    load_story_plan,
    mark_story_passed,
    pick_next_story,
)


def write_plan(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "branch_name": "feature/context-compaction-v2",
                "progress_path": "tasks/context-v2/progress.md",
                "stories": [
                    {
                        "id": "MC-002",
                        "title": "Lower priority",
                        "priority": 20,
                        "passes": False,
                        "acceptance_criteria": ["second story works"],
                        "verification_commands": ["pytest tests/unit/test_second.py -q"],
                    },
                    {
                        "id": "MC-001",
                        "title": "Add tokenizer-aware context budget",
                        "priority": 10,
                        "passes": False,
                        "acceptance_criteria": ["budget uses model window"],
                        "verification_commands": ["pytest tests/unit/test_context_manager.py -q"],
                    },
                    {
                        "id": "MC-000",
                        "title": "Already complete",
                        "priority": 1,
                        "passes": True,
                        "acceptance_criteria": ["done"],
                        "verification_commands": ["pytest -q"],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_pick_next_story_uses_lowest_priority_unpassed_story(tmp_path: Path) -> None:
    plan_path = tmp_path / "tasks" / "context-v2" / "plan.json"
    write_plan(plan_path)

    plan = load_story_plan(plan_path)
    story = pick_next_story(plan)

    assert story is not None
    assert story.id == "MC-001"
    assert story.title == "Add tokenizer-aware context budget"
    assert story.acceptance_criteria == ["budget uses model window"]
    assert story.verification_commands == ["pytest tests/unit/test_context_manager.py -q"]


def test_mark_story_passed_updates_plan_file(tmp_path: Path) -> None:
    plan_path = tmp_path / "tasks" / "context-v2" / "plan.json"
    write_plan(plan_path)

    updated = mark_story_passed(plan_path, "MC-001")

    assert updated.id == "MC-001"
    assert updated.passes is True
    reloaded = load_story_plan(plan_path)
    assert reloaded.story_by_id("MC-001").passes is True
    assert reloaded.story_by_id("MC-002").passes is False


def test_append_progress_entry_writes_compact_markdown(tmp_path: Path) -> None:
    plan_path = tmp_path / "tasks" / "context-v2" / "plan.json"
    write_plan(plan_path)
    plan = load_story_plan(plan_path)

    progress_path = append_progress_entry(
        plan_path=plan_path,
        plan=plan,
        story_id="MC-001",
        status="passed",
        summary="Implemented tokenizer-aware budget.",
        verification=["pytest tests/unit/test_context_manager.py -q"],
        trace_path="data/traces/run-123.jsonl",
        commit="abc1234",
        learnings=["Keep provider context compact."],
    )

    assert progress_path == tmp_path / "tasks" / "context-v2" / "progress.md"
    content = progress_path.read_text(encoding="utf-8")
    assert "## MC-001 - passed" in content
    assert "Implemented tokenizer-aware budget." in content
    assert "`pytest tests/unit/test_context_manager.py -q`" in content
    assert "trace: data/traces/run-123.jsonl" in content
    assert "commit: abc1234" in content
    assert "Keep provider context compact." in content
