import json
from datetime import UTC, datetime

from app.schemas.trace import TraceEvent
from app.tracing.recorder import TraceRecorder


def test_trace_event_serializes_expected_fields():
    event = TraceEvent(
        run_id="run-001",
        event_type="task.show",
        message="Previewed task",
        timestamp=datetime(2026, 4, 20, tzinfo=UTC),
        payload={"task_id": "demo-ci-001"},
    )

    assert event.run_id == "run-001"
    assert event.payload["task_id"] == "demo-ci-001"


def test_trace_recorder_writes_jsonl_file(tmp_path):
    recorder = TraceRecorder(base_dir=tmp_path)
    event = TraceEvent(
        run_id="run-001",
        event_type="task.show",
        message="Previewed task",
        payload={"task_id": "demo-ci-001"},
    )

    output_path = recorder.record(event)

    lines = output_path.read_text(encoding="utf-8").strip().splitlines()
    assert output_path.name == "run-001.jsonl"
    assert len(lines) == 1
    assert json.loads(lines[0])["event_type"] == "task.show"
