from pathlib import Path

from app.runtime.tool_repetition import RepetitionTracker, tool_call_fingerprint
from app.schemas.agent_action import Observation
from app.tools.structured import ToolInvocation


def invocation(name: str, args: dict[str, object]) -> ToolInvocation:
    return ToolInvocation(id="call", name=name, args=args, source="openai_tool_call")


def test_read_file_fingerprint_normalizes_path_and_args(tmp_path: Path) -> None:
    workspace = tmp_path.resolve()
    left = tool_call_fingerprint(
        invocation("read_file", {"path": "./README.md"}),
        workspace,
    )
    right = tool_call_fingerprint(
        invocation("read_file", {"max_chars": 12000, "path": "README.md"}),
        workspace,
    )
    assert left == right


def test_list_dir_fingerprint_normalizes_default_path(tmp_path: Path) -> None:
    workspace = tmp_path.resolve()

    left = tool_call_fingerprint(invocation("list_dir", {}), workspace)
    right = tool_call_fingerprint(invocation("list_dir", {"path": "."}), workspace)

    assert left == right


def test_search_fingerprint_normalizes_default_limit(tmp_path: Path) -> None:
    workspace = tmp_path.resolve()

    left = tool_call_fingerprint(invocation("rg", {"query": "needle"}), workspace)
    right = tool_call_fingerprint(
        invocation("rg", {"query": "needle", "max_results": 50}),
        workspace,
    )

    assert left == right


def test_repetition_tracker_rejects_third_equivalent_call(tmp_path: Path) -> None:
    tracker = RepetitionTracker(max_equivalent_calls=2)
    call = invocation("read_file", {"path": "README.md"})
    assert tracker.rejection_for(call, tmp_path, next_step_index=1) is None
    tracker.record(
        call,
        tmp_path,
        step_index=1,
        observation=Observation(status="succeeded", summary="Read", payload={}),
    )
    assert tracker.rejection_for(call, tmp_path, next_step_index=2) is None
    tracker.record(
        call,
        tmp_path,
        step_index=2,
        observation=Observation(status="succeeded", summary="Read", payload={}),
    )
    rejected = tracker.rejection_for(call, tmp_path, next_step_index=3)
    assert rejected is not None
    assert rejected.status == "rejected"
    assert rejected.payload["repeat_count"] == 3
    assert rejected.payload["previous_step"] == 2


def test_repetition_tracker_allows_different_line_ranges(tmp_path: Path) -> None:
    tracker = RepetitionTracker(max_equivalent_calls=2)
    first = invocation("read_file", {"path": "README.md", "start_line": 1, "end_line": 5})
    second = invocation(
        "read_file",
        {"path": "README.md", "start_line": 6, "end_line": 10},
    )
    tracker.record(
        first,
        tmp_path,
        step_index=1,
        observation=Observation(status="succeeded", summary="Read", payload={}),
    )
    assert tracker.rejection_for(second, tmp_path, next_step_index=2) is None
