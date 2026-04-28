from pathlib import Path

from app.memory.models import MemoryRecord
from app.memory.store import MemoryStore


def test_memory_store_appends_and_searches_records(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    record = MemoryRecord(
        kind="project_fact",
        title="pytest command",
        content="Use python -m pytest -q for full verification.",
        source="test",
        tags=["verification", "pytest"],
    )

    written = store.append(record)
    results = store.search(query="pytest", kinds={"project_fact"}, limit=5)

    assert written.id
    assert len(results) == 1
    assert results[0].record.title == "pytest command"
    assert results[0].score > 0
    assert (tmp_path / "memory" / "memories.jsonl").exists()


def test_memory_store_filters_by_kind_and_tag(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.append(
        MemoryRecord(
            kind="project_fact",
            title="tool registry",
            content="ToolRegistry owns tool schema and risk.",
            source="test",
            tags=["tools"],
        )
    )
    store.append(
        MemoryRecord(
            kind="failure_lesson",
            title="provider plain text",
            content="Provider must return final_response after tool observations.",
            source="test",
            tags=["provider"],
        )
    )

    results = store.search(query="provider", kinds={"failure_lesson"}, tags={"provider"})

    assert [result.record.kind for result in results] == ["failure_lesson"]
    assert results[0].record.title == "provider plain text"


def test_memory_store_update_rewrites_matching_record(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    original = store.append(
        MemoryRecord(
            kind="task_state",
            title="current task",
            content="Implement memory store.",
            source="test",
            tags=["task"],
        )
    )

    updated = store.update(
        original.id,
        content="Implement memory store and tools.",
        tags=["task", "tools"],
    )
    records = store.list_records()

    assert updated.content == "Implement memory store and tools."
    assert records[0].tags == ["task", "tools"]
    assert len(records) == 1


def test_memory_store_update_preserves_unreadable_jsonl_lines(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    original = store.append(
        MemoryRecord(
            kind="task_state",
            title="current task",
            content="Implement memory store.",
            source="test",
            tags=["task"],
        )
    )
    raw_future_record = (
        '{"kind":"future_kind","title":"future","content":"future",'
        '"source":"test","required_by_future_schema":true}'
    )
    with store.path.open("a", encoding="utf-8") as handle:
        handle.write(raw_future_record)
        handle.write("\n")

    store.update(original.id, content="Updated task.")

    lines = store.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert raw_future_record in lines
    assert store.list_records()[0].content == "Updated task."
