import json
from datetime import UTC, datetime

import pytest

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
    assert serialized["timestamp"].endswith(("Z", "+00:00"))


@pytest.mark.parametrize(
    "run_id",
    [
        "",
        "../escape",
        "bad/name",
        r"bad\name",
        " bad",
        ".bad",
        "bad.",
        "con",
        "con.txt",
        "com2",
        "lpt2",
    ],
)
def test_trace_event_rejects_unsafe_run_id(run_id):
    with pytest.raises(ValueError):
        TraceEvent(
            run_id=run_id,
            event_type="task.show",
            message="Previewed task",
        )


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
    parsed = TraceEvent.model_validate(json.loads(lines[0]))
    assert parsed.run_id == "run-001"
    assert parsed.event_type == "task.show"
    assert parsed.message == "Previewed task"
    assert parsed.payload["task_id"] == "demo-ci-001"
