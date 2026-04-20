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

    serialized = event.model_dump(mode="json")

    assert serialized["run_id"] == "run-001"
    assert serialized["event_type"] == "task.show"
    assert serialized["message"] == "Previewed task"
    assert serialized["payload"]["task_id"] == "demo-ci-001"
    assert isinstance(serialized["timestamp"], str)
    assert serialized["timestamp"].startswith("2026-04-20T00:00:00")


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
