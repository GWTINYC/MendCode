from pathlib import Path

import pytest

import app.tools.memory_tools as memory_tools
from app.config.settings import Settings
from app.memory.models import MemoryRecord
from app.memory.store import MemoryStore
from app.tools.registry import default_tool_registry
from app.tools.structured import ToolExecutionContext


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        app_name="MendCode",
        app_version="0.0.0",
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        traces_dir=tmp_path / "data" / "traces",
        workspace_root=tmp_path / ".worktrees",
        verification_timeout_seconds=60,
        cleanup_success_workspace=False,
    )


def context_for(tmp_path: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        memory_store=MemoryStore(tmp_path / "data" / "memory"),
    )


def test_memory_write_and_search_roundtrip(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = context_for(tmp_path)

    write_result = registry.get("memory_write").execute(
        {
            "kind": "project_fact",
            "title": "pytest command",
            "content": "Use python -m pytest -q for full verification.",
            "tags": ["verification"],
        },
        context,
    )
    search_result = registry.get("memory_search").execute(
        {"query": "pytest", "kinds": ["project_fact"], "limit": 5},
        context,
    )

    assert write_result.status == "succeeded"
    assert search_result.payload["total_matches"] == 1
    assert search_result.payload["matches"][0]["title"] == "pytest command"


def test_memory_write_rejects_duplicate_record(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = context_for(tmp_path)
    payload = {
        "kind": "project_fact",
        "title": "pytest command",
        "content": "Use python -m pytest -q for full verification.",
        "tags": ["verification"],
    }

    first = registry.get("memory_write").execute(payload, context)
    second = registry.get("memory_write").execute(payload, context)

    assert first.status == "succeeded"
    assert second.status == "rejected"
    assert "duplicate" in (second.error_message or "")
    assert context.memory_store is not None
    assert len(context.memory_store.list_records()) == 1


def test_file_summary_refresh_and_read(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    registry = default_tool_registry()
    context = context_for(tmp_path)

    refresh = registry.get("file_summary_refresh").execute({"path": "app.py"}, context)
    read = registry.get("file_summary_read").execute({"path": "app.py"}, context)

    assert refresh.status == "succeeded"
    assert read.status == "succeeded"
    assert read.payload["path"] == "app.py"
    assert "run" in read.payload["symbols"]


def test_file_summary_read_rebuilds_stale_cached_summary(tmp_path: Path) -> None:
    file_path = tmp_path / "app.py"
    file_path.write_text("def old():\n    return 1\n", encoding="utf-8")
    registry = default_tool_registry()
    context = context_for(tmp_path)

    refresh = registry.get("file_summary_refresh").execute({"path": "app.py"}, context)
    file_path.write_text("def new():\n    return 2\n", encoding="utf-8")
    read = registry.get("file_summary_read").execute({"path": "app.py"}, context)

    assert refresh.status == "succeeded"
    assert read.status == "succeeded"
    assert read.payload["symbols"] == ["new"]
    assert "old" not in read.payload["summary"]


def test_file_summary_read_does_not_reuse_cache_for_different_path(
    tmp_path: Path,
) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    registry = default_tool_registry()
    context = context_for(tmp_path)

    refresh = registry.get("file_summary_refresh").execute({"path": "pkg/app.py"}, context)
    read = registry.get("file_summary_read").execute({"path": "app.py"}, context)

    assert refresh.status == "succeeded"
    assert read.status == "succeeded"
    assert read.payload["path"] == "app.py"


def test_trace_analyze_rejects_write_memory_in_read_only_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text("trace\n", encoding="utf-8")
    registry = default_tool_registry()
    context = context_for(tmp_path)
    monkeypatch.setattr(
        memory_tools,
        "analyze_trace",
        lambda _path: MemoryRecord(
            kind="failure_lesson",
            title="provider failure",
            content="Provider returned plain text.",
            source="test",
        ),
    )

    result = registry.get("trace_analyze").execute(
        {"trace_path": str(trace_path), "write_memory": True},
        context,
    )

    assert result.status == "rejected"
    assert "write_memory" in (result.error_message or "")
    assert context.memory_store is not None
    assert context.memory_store.list_records() == []


def test_trace_analyze_rejects_path_outside_trace_dir(tmp_path: Path) -> None:
    outside = tmp_path / "outside.jsonl"
    outside.write_text("{}", encoding="utf-8")
    registry = default_tool_registry()
    context = context_for(tmp_path)

    result = registry.get("trace_analyze").execute({"trace_path": str(outside)}, context)

    assert result.status == "rejected"
    assert "traces_dir" in (result.error_message or "")


def test_trace_analyze_returns_failed_observation_for_missing_trace(
    tmp_path: Path,
) -> None:
    registry = default_tool_registry()
    context = context_for(tmp_path)

    result = registry.get("trace_analyze").execute(
        {"trace_path": str(context.settings.traces_dir / "missing.jsonl")},
        context,
    )

    assert result.status == "failed"
    assert "missing.jsonl" in (result.error_message or "")
