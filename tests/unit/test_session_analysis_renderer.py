import json
from pathlib import Path

from app.runtime.session_analysis.analyzer import analyze_transcript
from app.runtime.session_analysis.models import SessionTranscript
from app.runtime.session_analysis.renderer import (
    render_report_json,
    render_report_markdown,
    write_analysis_report,
)


def test_render_report_json_contains_structured_fields(tmp_path: Path) -> None:
    report = analyze_transcript(
        SessionTranscript(
            session_id="session-1",
            source_path=tmp_path / "session.md",
            input_kind="conversation_markdown",
            user_messages=["查看 git status"],
            final_answer="工作区干净。",
        )
    )

    payload = json.loads(render_report_json(report))

    assert payload["session_id"] == "session-1"
    assert payload["missing_tools"][0]["code"] == "missing_git_status"
    assert payload["observed_tools"] == []


def test_render_report_markdown_is_bounded_and_readable(tmp_path: Path) -> None:
    report = analyze_transcript(
        SessionTranscript(
            session_id="session-1",
            source_path=tmp_path / "session.md",
            input_kind="conversation_markdown",
            user_messages=["某文档最后一句是什么"],
            final_answer="x" * 4000,
        )
    )

    markdown = render_report_markdown(report)

    assert "# MendCode Session Analysis" in markdown
    assert "## Missing / Repeated / Failed Tools" in markdown
    assert "oversized_final_answer" in markdown
    assert len(markdown) < 12000


def test_write_analysis_report_respects_format(tmp_path: Path) -> None:
    report = analyze_transcript(
        SessionTranscript(
            session_id="session-1",
            source_path=tmp_path / "session.md",
            input_kind="conversation_markdown",
            user_messages=["列文件"],
        )
    )

    written = write_analysis_report(report, tmp_path / "reports", output_format="json")

    assert written == [tmp_path / "reports" / "session-1.json"]
    assert written[0].exists()
    assert not (tmp_path / "reports" / "session-1.md").exists()


def test_write_analysis_report_rejects_unknown_format(tmp_path: Path) -> None:
    report = analyze_transcript(
        SessionTranscript(
            session_id="session-1",
            source_path=tmp_path / "session.md",
            input_kind="conversation_markdown",
        )
    )

    try:
        write_analysis_report(report, tmp_path / "reports", output_format="xml")
    except ValueError as exc:
        assert "output_format must be one of" in str(exc)
    else:
        raise AssertionError("expected ValueError")
