from pathlib import Path

from app.runtime.session_analysis.analyzer import analyze_transcript
from app.runtime.session_analysis.models import (
    ObservationEvent,
    SessionTranscript,
    ToolCallEvent,
)


def test_missing_list_dir_and_unsupported_claim_for_directory_question(tmp_path: Path) -> None:
    transcript = SessionTranscript(
        session_id="conversation",
        source_path=tmp_path / "conversation.md",
        input_kind="conversation_markdown",
        user_messages=["帮我查看当前文件夹里的文件"],
        final_answer="当前目录有 README.md 和 app 目录。",
    )

    report = analyze_transcript(transcript)

    assert _codes(report.missing_tools) == ["missing_directory_listing"]
    assert _codes(report.unsupported_claims) == ["unsupported_local_claim"]
    assert "prompt_rule" in _targets(report.recommendations)


def test_git_status_question_requires_git_or_shell(tmp_path: Path) -> None:
    transcript = SessionTranscript(
        session_id="trace",
        source_path=tmp_path / "trace.jsonl",
        input_kind="jsonl_trace",
        user_messages=["查看 git status"],
        final_answer="工作区干净。",
    )

    report = analyze_transcript(transcript)

    assert _codes(report.missing_tools) == ["missing_git_status"]
    assert report.confidence == "high"


def test_repeated_failed_tool_then_certain_answer_is_flagged(tmp_path: Path) -> None:
    transcript = SessionTranscript(
        session_id="trace",
        source_path=tmp_path / "trace.jsonl",
        input_kind="jsonl_trace",
        user_messages=["MendCode问题记录的最后一句是什么"],
        tool_calls=[
            ToolCallEvent(
                tool_name="read_file", arguments={"path": "MendCode_问题记录.md"}, call_index=1
            ),
            ToolCallEvent(
                tool_name="read_file", arguments={"path": "MendCode_问题记录.md"}, call_index=2
            ),
            ToolCallEvent(
                tool_name="read_file", arguments={"path": "MendCode_问题记录.md"}, call_index=3
            ),
        ],
        observations=[
            ObservationEvent(
                tool_name="read_file", status="failed", error_excerpt="file not found", call_index=1
            ),
            ObservationEvent(
                tool_name="read_file", status="failed", error_excerpt="file not found", call_index=2
            ),
            ObservationEvent(
                tool_name="read_file", status="failed", error_excerpt="file not found", call_index=3
            ),
        ],
        final_answer="最后一句是：已修复。",
    )

    report = analyze_transcript(transcript)

    assert _codes(report.repeated_tools) == ["repeated_tool_call"]
    assert _codes(report.failed_tools) == ["failed_tool_observation"]
    assert _codes(report.unsupported_claims) == ["unsupported_after_failed_tool"]
    assert "final_response_gate" in _targets(report.recommendations)


def test_oversized_final_answer_is_flagged(tmp_path: Path) -> None:
    transcript = SessionTranscript(
        session_id="conversation",
        source_path=tmp_path / "conversation.md",
        input_kind="conversation_markdown",
        user_messages=["某文档最后一句是什么"],
        tool_calls=[
            ToolCallEvent(tool_name="read_file", arguments={"path": "README.md"}, call_index=1)
        ],
        observations=[
            ObservationEvent(tool_name="read_file", status="succeeded", content_excerpt="ok")
        ],
        final_answer="x" * 3500,
    )

    report = analyze_transcript(transcript)

    assert _codes(report.oversized_outputs) == ["oversized_final_answer"]
    assert "context_compaction" in _targets(report.recommendations)


def test_dangerous_confirmation_observation_becomes_risk_event(tmp_path: Path) -> None:
    transcript = SessionTranscript(
        session_id="trace",
        source_path=tmp_path / "trace.jsonl",
        input_kind="jsonl_trace",
        user_messages=["删除所有文件"],
        observations=[
            ObservationEvent(
                tool_name="run_shell_command",
                status="needs_user_confirmation",
                risk_level="high",
                error_excerpt="confirmation required",
            )
        ],
    )

    report = analyze_transcript(transcript)

    assert _codes(report.risk_events) == ["permission_confirmation_required"]
    assert "permission_policy" in _targets(report.recommendations)


def _codes(findings) -> list[str]:
    return [finding.code for finding in findings]


def _targets(findings) -> list[str]:
    return [str(finding.evidence.get("target")) for finding in findings]
