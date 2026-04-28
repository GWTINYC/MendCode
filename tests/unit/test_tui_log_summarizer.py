import json

from app.agent.loop import AgentLoopResult, AgentStep
from app.agent.session import AgentSessionTurn, ReviewSummary, ToolCallSummary
from app.schemas.agent_action import FinalResponseAction, Observation, ToolCallAction
from app.tui.log_summarizer import compact_agent_loop_result, compact_agent_session_turn


def test_compact_agent_loop_result_keeps_tool_summary_without_full_file_content() -> None:
    full_content = "x" * 5000
    result = AgentLoopResult(
        run_id="agent-log-test",
        status="completed",
        summary="Read README.md",
        trace_path="/tmp/trace.jsonl",
        workspace_path="/tmp/worktree",
        steps=[
            AgentStep(
                index=1,
                action=ToolCallAction(
                    type="tool_call",
                    action="read_file",
                    reason="inspect README",
                    args={"path": "README.md"},
                ),
                observation=Observation(
                    status="succeeded",
                    summary="Read README.md",
                    payload={
                        "relative_path": "README.md",
                        "content": full_content,
                        "truncated": False,
                    },
                ),
            ),
            AgentStep(
                index=2,
                action=FinalResponseAction(
                    type="final_response",
                    status="completed",
                    summary="README.md inspected",
                ),
                observation=Observation(
                    status="succeeded",
                    summary="Recorded final response",
                    payload={},
                ),
            ),
        ],
    )

    compact = compact_agent_loop_result(result)
    compact_json = json.dumps(compact, ensure_ascii=False, sort_keys=True)
    full_json = result.model_dump_json()

    assert compact["run_id"] == "agent-log-test"
    assert compact["step_count"] == 2
    assert compact["trace_path"] == "/tmp/trace.jsonl"
    assert compact["steps"][0]["action"] == "read_file"
    assert compact["steps"][0]["payload"]["relative_path"] == "README.md"
    assert compact["steps"][0]["payload"]["content_truncated"] is True
    assert full_content not in compact_json
    assert len(compact_json) < len(full_json) / 3


def test_compact_agent_loop_result_samples_large_directory_entries() -> None:
    entries = [
        {"name": f"file_{index}.txt", "relative_path": f"file_{index}.txt"}
        for index in range(80)
    ]
    result = AgentLoopResult(
        run_id="agent-log-test",
        status="completed",
        summary="Listed .",
        trace_path="/tmp/trace.jsonl",
        steps=[
            AgentStep(
                index=1,
                action=ToolCallAction(
                    type="tool_call",
                    action="list_dir",
                    reason="inspect directory",
                    args={"path": "."},
                ),
                observation=Observation(
                    status="succeeded",
                    summary="Listed .",
                    payload={
                        "relative_path": ".",
                        "entries": entries,
                        "total_entries": len(entries),
                        "truncated": False,
                    },
                ),
            )
        ],
    )

    compact = compact_agent_loop_result(result)
    payload = compact["steps"][0]["payload"]

    assert payload["total_entries"] == 80
    assert payload["entries_count"] == 80
    assert len(payload["entries_sample"]) < len(entries)
    assert payload["entries_truncated"] is True
    assert payload["entries_sample"][0]["relative_path"] == "file_0.txt"


def test_compact_agent_loop_result_summarizes_memory_matches() -> None:
    result = AgentLoopResult(
        run_id="agent-memory",
        status="completed",
        summary="done",
        trace_path="/tmp/trace.jsonl",
        steps=[
            AgentStep(
                index=1,
                action=ToolCallAction(
                    type="tool_call",
                    action="memory_search",
                    reason="recall",
                    args={"query": "pytest"},
                ),
                observation=Observation(
                    status="succeeded",
                    summary="Found 1 memory records",
                    payload={
                        "total_matches": 1,
                        "matches": [
                            {
                                "id": "m1",
                                "title": "pytest command",
                                "content_excerpt": "Use python -m pytest -q.",
                            }
                        ],
                    },
                ),
            )
        ],
    )

    compact = compact_agent_loop_result(result)

    assert compact["steps"][0]["args"]["query"] == "pytest"
    assert compact["steps"][0]["payload"]["total_matches"] == 1
    assert compact["steps"][0]["payload"]["matches_count"] == 1


def test_compact_agent_loop_result_keeps_session_status_tool_surface() -> None:
    result = AgentLoopResult(
        run_id="agent-status",
        status="completed",
        summary="done",
        trace_path="/tmp/trace.jsonl",
        steps=[
            AgentStep(
                index=1,
                action=ToolCallAction(
                    type="tool_call",
                    action="session_status",
                    reason="inspect tools",
                    args={"include_tools": True, "include_recent_steps": False},
                ),
                observation=Observation(
                    status="succeeded",
                    summary="Read session status",
                    payload={
                        "available_tools": ["read_file", "session_status", "tool_search"],
                        "allowed_tools": [
                            "read_file",
                            "session_status",
                            "tool_search",
                            "write_file",
                        ],
                        "denied_tools": ["write_file"],
                    },
                ),
            )
        ],
    )

    compact = compact_agent_loop_result(result)
    step = compact["steps"][0]

    assert step["args"]["include_tools"] is True
    assert step["args"]["include_recent_steps"] is False
    assert step["payload"]["available_tools"] == [
        "read_file",
        "session_status",
        "tool_search",
    ]
    assert step["payload"]["allowed_tools_count"] == 4
    assert step["payload"]["denied_tools"] == ["write_file"]


def test_compact_agent_loop_result_keeps_runtime_summaries() -> None:
    result = AgentLoopResult(
        run_id="agent-context",
        status="completed",
        summary="done",
        trace_path="/tmp/trace.jsonl",
        context_summary={
            "metrics": {
                "context_chars": 100,
                "memory_recall_hits": 1,
                "observation_count": 2,
                "read_file_count": 1,
                "repeated_read_file_count": 0,
            },
            "memory_recall_hits": 1,
            "warnings": [],
        },
        evolution_summary={
            "generated_candidates": [],
            "generated_candidate_count": 0,
            "signals": [],
            "skipped_reason": "no evolution signals",
        },
        steps=[],
    )

    compact = compact_agent_loop_result(result)

    assert compact["context_summary"]["metrics"]["memory_recall_hits"] == 1
    assert compact["evolution_summary"]["generated_candidate_count"] == 0


def test_compact_agent_session_turn_does_not_embed_full_nested_result() -> None:
    full_content = "readme\n" * 1000
    result = AgentLoopResult(
        run_id="agent-turn-test",
        status="completed",
        summary="Read README.md",
        trace_path="/tmp/trace.jsonl",
        workspace_path="/tmp/worktree",
        steps=[
            AgentStep(
                index=1,
                action=ToolCallAction(
                    type="tool_call",
                    action="read_file",
                    reason="inspect README",
                    args={"path": "README.md"},
                ),
                observation=Observation(
                    status="succeeded",
                    summary="Read README.md",
                    payload={"relative_path": "README.md", "content": full_content},
                ),
            )
        ],
    )
    turn = AgentSessionTurn(
        index=1,
        problem_statement="read README",
        result=result,
        review=ReviewSummary(
            status="verified",
            workspace_path="/tmp/worktree",
            trace_path="/tmp/trace.jsonl",
            verification_status="passed",
            summary="Read README.md",
        ),
        tool_summaries=[
            ToolCallSummary(
                index=1,
                action="read_file",
                status="succeeded",
                summary="Read README.md",
            )
        ],
    )

    compact_json = json.dumps(compact_agent_session_turn(turn), ensure_ascii=False)

    assert full_content not in compact_json
    assert "tool_summaries" in compact_json
    assert "trace.jsonl" in compact_json
