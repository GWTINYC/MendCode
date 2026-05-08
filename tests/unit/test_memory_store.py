from pathlib import Path

from app.memory.models import MemoryRecord, infer_memory_layer
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


def test_memory_record_defaults_layer_from_kind() -> None:
    assert MemoryRecord(
        kind="task_state",
        title="current task",
        content="Inspect repo map.",
        source="test",
    ).layer == "short"
    assert MemoryRecord(
        kind="file_summary",
        title="README summary",
        content="README.md summary.",
        source="test",
    ).layer == "medium"
    assert MemoryRecord(
        kind="project_fact",
        title="pytest command",
        content="Use python -m pytest -q.",
        source="test",
    ).layer == "long"
    assert infer_memory_layer("failure_lesson") == "long"


def test_memory_store_search_filters_by_layer(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.append(
        MemoryRecord(
            kind="task_state",
            title="pytest task",
            content="Run pytest after editing.",
            source="test",
        )
    )
    store.append(
        MemoryRecord(
            kind="file_summary",
            title="pytest helper summary",
            content="helpers.py wraps pytest commands.",
            source="test",
        )
    )
    store.append(
        MemoryRecord(
            kind="project_fact",
            title="pytest command",
            content="Use python -m pytest -q.",
            source="test",
        )
    )

    short_results = store.search(query="pytest", layers={"short"})
    medium_results = store.search(query="pytest", layers={"medium"})
    long_results = store.search(query="pytest", layers={"long"})

    assert [result.record.kind for result in short_results] == ["task_state"]
    assert [result.record.kind for result in medium_results] == ["file_summary"]
    assert [result.record.kind for result in long_results] == ["project_fact"]


def test_memory_store_loads_legacy_rows_without_layer(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.root.mkdir(parents=True)
    store.path.write_text(
        (
            '{"id":"legacy-1","kind":"file_summary","title":"README",'
            '"content":"summary","source":"legacy","tags":[],"metadata":{}}\n'
        ),
        encoding="utf-8",
    )

    records = store.list_records()
    results = store.search(query="README", layers={"medium"})

    assert records[0].layer == "medium"
    assert results[0].record.id == "legacy-1"


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
