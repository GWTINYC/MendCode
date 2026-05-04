import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agent.provider import AgentObservationRecord
from app.context.compaction import compact_observation_record
from app.context.manager import ContextManager
from app.context.models import ContextBudget, ContextMetrics
from app.memory.models import MemoryRecord
from app.memory.runtime import MemoryRuntime
from app.memory.store import MemoryStore
from app.schemas.agent_action import Observation, ToolCallAction
from app.tools.structured import ToolInvocation


def _memory_runtime(tmp_path: Path) -> MemoryRuntime:
    return MemoryRuntime(MemoryStore(tmp_path / "memory"))


def test_context_manager_builds_provider_context_with_memory_recall(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.append(
        MemoryRecord(
            kind="project_fact",
            title="pytest command",
            content="Use python -m pytest -q for verification.",
            source="test",
            tags=["pytest"],
        )
    )
    manager = ContextManager(
        memory_runtime=MemoryRuntime(store),
        base_context='{"session":"demo"}',
        budget=ContextBudget(max_memory_items=3),
    )

    bundle = manager.begin_turn(
        user_message="之前记录的 pytest 命令是什么",
        repo_path=tmp_path,
    )

    payload = json.loads(bundle.provider_context)
    assert payload["base_context"] == {"session": "demo"}
    assert payload["memory_recall"][0]["title"] == "pytest command"
    assert bundle.metrics.memory_recall_hits == 1
    assert bundle.metrics.context_chars == len(bundle.provider_context)


def test_context_manager_records_read_file_repetition(tmp_path: Path) -> None:
    manager = ContextManager(memory_runtime=_memory_runtime(tmp_path))
    manager.begin_turn(user_message="read twice", repo_path=tmp_path)

    for index in range(2):
        manager.record_observation(
            AgentObservationRecord(
                action=ToolCallAction(
                    type="tool_call",
                    action="read_file",
                    reason="inspect",
                    args={"path": "README.md"},
                ),
                tool_invocation=ToolInvocation(
                    id=f"call_{index}",
                    name="read_file",
                    args={"path": "README.md"},
                    source="openai_tool_call",
                ),
                observation=Observation(
                    status="succeeded",
                    summary="Read README.md",
                    payload={"relative_path": "README.md", "content": "demo"},
                ),
            )
        )

    bundle = manager.build_provider_context()

    assert bundle.metrics.observation_count == 2
    assert bundle.metrics.read_file_count == 2
    assert bundle.metrics.repeated_read_file_count == 1
    assert json.loads(bundle.provider_context)["context_metrics"][
        "repeated_read_file_count"
    ] == 1


def test_context_models_reject_scalar_coercion() -> None:
    with pytest.raises(ValidationError):
        ContextBudget(max_memory_items="3")

    with pytest.raises(ValidationError):
        ContextMetrics(read_file_count="2")


def test_context_budget_exposes_compaction_limits() -> None:
    budget = ContextBudget(
        max_memory_items=3,
        max_context_chars=5000,
        max_memory_chars=900,
        max_observation_chars=1200,
        max_file_summary_chars=800,
        max_observation_items=4,
    )

    assert budget.max_context_chars == 5000
    assert budget.max_memory_chars == 900
    assert budget.max_observation_chars == 1200
    assert budget.max_file_summary_chars == 800
    assert budget.max_observation_items == 4


def test_context_metrics_exposes_compaction_counters() -> None:
    metrics = ContextMetrics(
        context_chars=100,
        raw_context_chars=300,
        compacted_context_chars=100,
        compacted_item_count=2,
        file_summary_hit_count=1,
        observation_chars_saved=200,
    )

    assert metrics.raw_context_chars == 300
    assert metrics.compacted_context_chars == 100
    assert metrics.compacted_item_count == 2
    assert metrics.file_summary_hit_count == 1
    assert metrics.observation_chars_saved == 200


def test_context_manager_normalizes_simple_repeated_read_file_paths(
    tmp_path: Path,
) -> None:
    manager = ContextManager(memory_runtime=_memory_runtime(tmp_path))
    manager.begin_turn(user_message="read equivalent paths", repo_path=tmp_path)

    for index, path in enumerate(("README.md", "./README.md")):
        manager.record_observation(
            AgentObservationRecord(
                action=ToolCallAction(
                    type="tool_call",
                    action="read_file",
                    reason="inspect",
                    args={"path": path},
                ),
                tool_invocation=ToolInvocation(
                    id=f"call_{index}",
                    name="read_file",
                    args={"path": path},
                    source="openai_tool_call",
                ),
                observation=Observation(
                    status="succeeded",
                    summary=f"Read {path}",
                    payload={"relative_path": path, "content": "demo"},
                ),
            )
        )

    bundle = manager.build_provider_context()

    assert bundle.metrics.read_file_count == 2
    assert bundle.metrics.repeated_read_file_count == 1


def test_compact_observation_record_truncates_read_file_content() -> None:
    record = AgentObservationRecord(
        action=ToolCallAction(
            type="tool_call",
            action="read_file",
            reason="inspect",
            args={"path": "README.md"},
        ),
        tool_invocation=ToolInvocation(
            id="call_read",
            name="read_file",
            args={"path": "README.md"},
            source="openai_tool_call",
        ),
        observation=Observation(
            status="succeeded",
            summary="Read README.md",
            payload={
                "relative_path": "README.md",
                "content": "x" * 5000,
                "truncated": False,
            },
        ),
    )

    item = compact_observation_record(record, max_chars=300)

    assert item.kind == "observation"
    assert item.title == "read_file: succeeded"
    assert item.metadata["tool_name"] == "read_file"
    assert item.metadata["relative_path"] == "README.md"
    assert item.metadata["content_length"] == 5000
    assert item.metadata["content_truncated"] is True
    assert len(item.content or "") <= 320
    assert "x" * 1000 not in item.model_dump_json()


def test_compact_observation_record_samples_search_matches() -> None:
    matches = [
        {
            "relative_path": f"file_{index}.py",
            "line_number": index,
            "line": "def target(): pass",
        }
        for index in range(40)
    ]
    record = AgentObservationRecord(
        action=ToolCallAction(
            type="tool_call",
            action="rg",
            reason="search",
            args={"pattern": "target"},
        ),
        observation=Observation(
            status="succeeded",
            summary="Found matches",
            payload={"pattern": "target", "matches": matches, "total_matches": 40},
        ),
    )

    item = compact_observation_record(record, max_chars=500, max_collection_items=5)

    assert item.metadata["tool_name"] == "rg"
    assert item.metadata["matches_count"] == 40
    assert item.metadata["matches_truncated"] is True
    assert len(item.metadata["matches_sample"]) == 5


def test_compact_observation_record_metadata_is_json_safe_and_bounded() -> None:
    record = AgentObservationRecord(
        action=ToolCallAction(
            type="tool_call",
            action="run_shell_command",
            reason="inspect",
            args={"command": "x" * 500},
        ),
        observation=Observation(
            status="succeeded",
            summary="Ran command",
            payload={
                "command": "x" * 500,
                "pattern": Path("not-json-safe"),
            },
        ),
    )

    item = compact_observation_record(record, max_chars=120)
    dumped = item.model_dump_json()

    assert len(item.metadata["command"]) <= 120
    assert item.metadata["pattern"] == "not-json-safe"
    assert "x" * 200 not in dumped


def test_compact_observation_record_uses_hard_excerpt_limit() -> None:
    record = AgentObservationRecord(
        action=ToolCallAction(
            type="tool_call",
            action="read_file",
            reason="inspect",
            args={"path": "README.md"},
        ),
        observation=Observation(
            status="succeeded",
            summary="Read README.md",
            payload={"relative_path": "README.md", "content": "x" * 5000},
        ),
    )

    item = compact_observation_record(record, max_chars=80)

    assert item.content is not None
    assert len(item.content) <= 80


def test_merge_context_metrics_preserves_compaction_counters() -> None:
    from app.context.metrics import merge_context_metrics

    merged = merge_context_metrics(
        ContextMetrics(
            raw_context_chars=300,
            compacted_context_chars=100,
            compacted_item_count=2,
            file_summary_hit_count=1,
            observation_chars_saved=200,
        ),
        ContextMetrics(
            raw_context_chars=30,
            compacted_context_chars=10,
            compacted_item_count=3,
            file_summary_hit_count=4,
            observation_chars_saved=20,
        ),
    )

    assert merged.raw_context_chars == 330
    assert merged.compacted_context_chars == 110
    assert merged.compacted_item_count == 5
    assert merged.file_summary_hit_count == 5
    assert merged.observation_chars_saved == 220


def test_context_manager_provider_context_uses_compact_observation_items(
    tmp_path: Path,
) -> None:
    manager = ContextManager(
        memory_runtime=_memory_runtime(tmp_path),
        budget=ContextBudget(max_observation_chars=600, max_item_excerpt_chars=200),
    )
    manager.begin_turn(user_message="read large file", repo_path=tmp_path)
    manager.record_observation(
        AgentObservationRecord(
            action=ToolCallAction(
                type="tool_call",
                action="read_file",
                reason="inspect",
                args={"path": "README.md"},
            ),
            observation=Observation(
                status="succeeded",
                summary="Read README.md",
                payload={"relative_path": "README.md", "content": "x" * 5000},
            ),
        )
    )

    payload = json.loads(manager.build_provider_context().provider_context)

    assert "observations" in payload
    assert payload["observations"][0]["metadata"]["content_length"] == 5000
    assert "x" * 1000 not in json.dumps(payload, ensure_ascii=False)
    assert payload["context_metrics"]["compacted_item_count"] >= 1
    assert payload["context_metrics"]["observation_chars_saved"] > 0


def test_context_manager_limits_memory_recall_chars(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.append(
        MemoryRecord(
            kind="project_fact",
            title="long pytest note",
            content="pytest " + ("x" * 5000),
            source="test",
            tags=["pytest"],
        )
    )
    manager = ContextManager(
        memory_runtime=MemoryRuntime(store),
        budget=ContextBudget(max_memory_items=3, max_memory_chars=200),
    )

    payload = json.loads(
        manager.begin_turn(user_message="pytest", repo_path=tmp_path).provider_context
    )

    assert payload["memory_recall"][0]["title"] == "long pytest note"
    assert len(payload["memory_recall"][0]["content_excerpt"]) <= 200
    assert "x" * 1000 not in json.dumps(payload, ensure_ascii=False)


def test_context_manager_adds_file_summary_for_repeated_read_file(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "README.md").write_text(
        "MendCode\n\n" + "\n".join(f"line {index}" for index in range(200)),
        encoding="utf-8",
    )
    manager = ContextManager(
        memory_runtime=MemoryRuntime(MemoryStore(tmp_path / "memory")),
        budget=ContextBudget(max_file_summary_chars=400),
    )
    manager.begin_turn(user_message="read repeatedly", repo_path=repo_path)

    for path in ("README.md", "./README.md"):
        manager.record_observation(
            AgentObservationRecord(
                action=ToolCallAction(
                    type="tool_call",
                    action="read_file",
                    reason="inspect",
                    args={"path": path},
                ),
                observation=Observation(
                    status="succeeded",
                    summary=f"Read {path}",
                    payload={
                        "relative_path": path,
                        "content": "large content " * 500,
                    },
                ),
            )
        )

    payload = json.loads(manager.build_provider_context().provider_context)

    assert payload["context_metrics"]["file_summary_hit_count"] == 1
    summaries = [
        item
        for item in payload["file_summaries"]
        if item["metadata"]["path"] == "README.md"
    ]
    assert summaries
    assert len(summaries[0]["content"]) <= 400
    assert "large content " * 100 not in json.dumps(payload, ensure_ascii=False)


def test_context_manager_warns_when_repeated_read_file_summary_fails(
    tmp_path: Path,
) -> None:
    manager = ContextManager(
        memory_runtime=_memory_runtime(tmp_path),
        budget=ContextBudget(max_file_summary_chars=400),
    )
    manager.begin_turn(user_message="read missing repeatedly", repo_path=tmp_path)

    for _ in range(2):
        manager.record_observation(
            AgentObservationRecord(
                action=ToolCallAction(
                    type="tool_call",
                    action="read_file",
                    reason="inspect",
                    args={"path": "missing.md"},
                ),
                observation=Observation(
                    status="succeeded",
                    summary="Read missing.md",
                    payload={"relative_path": "missing.md", "content": "demo"},
                ),
            )
        )

    bundle = manager.build_provider_context()

    assert bundle.metrics.file_summary_hit_count == 0
    assert any(warning.code == "file_summary_failed" for warning in bundle.warnings)
