from pathlib import Path

from app.runtime.session_analysis.models import (
    ObservationEvent,
    SessionAnalysisReport,
    SessionTranscript,
    ToolCallEvent,
)


def test_session_transcript_defaults_are_stable(tmp_path: Path) -> None:
    transcript = SessionTranscript(
        session_id="conversation-1",
        source_path=tmp_path / "conversation.md",
        input_kind="conversation_markdown",
        user_messages=["查看 git 状态"],
    )

    assert transcript.assistant_messages == []
    assert transcript.tool_calls == []
    assert transcript.observations == []
    assert transcript.final_answer == ""


def test_tool_call_fingerprint_uses_tool_and_arguments() -> None:
    call = ToolCallEvent(
        tool_name="read_file",
        arguments={"path": "README.md", "tail": 1},
        call_index=2,
    )

    assert call.arguments_excerpt == '{"path":"README.md","tail":1}'
    assert len(call.arguments_fingerprint) == 16


def test_observation_visible_chars_counts_bounded_content() -> None:
    observation = ObservationEvent(
        tool_name="read_file",
        status="succeeded",
        content_excerpt="abc",
        stdout_excerpt="de",
    )

    assert observation.visible_chars == 5


def test_report_computed_observed_tools_are_unique(tmp_path: Path) -> None:
    report = SessionAnalysisReport(
        session_id="trace-1",
        source_path=tmp_path / "trace.jsonl",
        input_kind="jsonl_trace",
        user_messages=["列文件"],
        tool_calls=[
            ToolCallEvent(tool_name="list_dir", arguments={"path": "."}, call_index=1),
            ToolCallEvent(tool_name="list_dir", arguments={"path": "."}, call_index=2),
        ],
    )

    assert report.observed_tools == ["list_dir"]
