import json
from pathlib import Path

from app.agent.provider import AgentObservationRecord
from app.context.manager import ContextManager
from app.context.models import ContextBudget
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
