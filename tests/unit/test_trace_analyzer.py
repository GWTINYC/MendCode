import json
from pathlib import Path

from app.runtime.trace_analyzer import analyze_trace


def write_trace(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )


def test_analyze_trace_creates_failure_lesson_for_provider_failure(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    write_trace(
        trace,
        [
            {
                "event_type": "agent.step",
                "message": "Handled action",
                "payload": {
                    "action": {"type": "final_response", "status": "failed"},
                    "observation": {
                        "status": "failed",
                        "summary": "Provider failed",
                        "error_message": "Provider returned plain text without tool call",
                    },
                },
            }
        ],
    )

    lesson = analyze_trace(trace)

    assert lesson is not None
    assert lesson.kind == "failure_lesson"
    assert "Provider failed" in lesson.title
    assert lesson.metadata["category"] == "provider_protocol"


def test_analyze_trace_returns_none_for_successful_trace(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    write_trace(
        trace,
        [
            {
                "event_type": "agent.run.completed",
                "message": "completed",
                "payload": {"status": "completed", "summary": "ok"},
            }
        ],
    )

    assert analyze_trace(trace) is None


def test_analyze_trace_categorizes_hyphenated_tool_call_failure(
    tmp_path: Path,
) -> None:
    trace = tmp_path / "trace.jsonl"
    write_trace(
        trace,
        [
            {
                "event_type": "agent.step",
                "message": "Handled action",
                "payload": {
                    "observation": {
                        "status": "failed",
                        "summary": "Malformed tool-call response",
                        "error_message": "tool-call arguments were invalid",
                    },
                },
            }
        ],
    )

    lesson = analyze_trace(trace)

    assert lesson is not None
    assert lesson.metadata["category"] == "provider_protocol"


def test_analyze_trace_categorizes_repeated_tool_call_as_repetition(
    tmp_path: Path,
) -> None:
    trace = tmp_path / "trace.jsonl"
    write_trace(
        trace,
        [
            {
                "event_type": "agent.step",
                "message": "Handled action",
                "payload": {
                    "observation": {
                        "status": "rejected",
                        "summary": "Repeated equivalent tool call",
                        "error_message": "equivalent tool call repeated too many times",
                    },
                },
            }
        ],
    )

    lesson = analyze_trace(trace)

    assert lesson is not None
    assert lesson.metadata["category"] == "tool_repetition"


def test_analyze_trace_ignores_recovered_failures_when_run_completed(
    tmp_path: Path,
) -> None:
    trace = tmp_path / "trace.jsonl"
    write_trace(
        trace,
        [
            {
                "event_type": "agent.step",
                "message": "Handled action",
                "payload": {
                    "observation": {
                        "status": "failed",
                        "summary": "Transient tool failure",
                        "error_message": "first attempt failed",
                    },
                },
            },
            {
                "event_type": "agent.run.completed",
                "message": "completed",
                "payload": {"status": "completed", "summary": "Recovered"},
            },
        ],
    )

    assert analyze_trace(trace) is None
