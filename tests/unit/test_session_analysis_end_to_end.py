import json
from pathlib import Path

from app.runtime.session_analysis import (
    analyze_transcript,
    parse_session_file,
    render_report_markdown,
)


def test_markdown_directory_question_without_tool_is_diagnosed(tmp_path: Path) -> None:
    path = tmp_path / "directory.md"
    path.write_text(
        "## User\n帮我查看当前文件夹里的文件\n## Assistant\n当前目录包含 README.md。\n",
        encoding="utf-8",
    )

    report = analyze_transcript(parse_session_file(path))

    assert [finding.code for finding in report.missing_tools] == [
        "missing_directory_listing"
    ]
    assert [finding.code for finding in report.unsupported_claims] == [
        "unsupported_local_claim"
    ]


def test_jsonl_repeated_failed_read_then_fabricated_answer_is_diagnosed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "failed-read.jsonl"
    events = [
        {
            "run_id": "run",
            "event_type": "agent.user_message",
            "message": "user",
            "payload": {"message": "问题记录最后一句是什么"},
        },
        {
            "run_id": "run",
            "event_type": "agent.tool_call",
            "message": "tool",
            "payload": {
                "tool_name": "read_file",
                "arguments": {"path": "MendCode_问题记录.md"},
            },
        },
        {
            "run_id": "run",
            "event_type": "agent.tool_call",
            "message": "tool",
            "payload": {
                "tool_name": "read_file",
                "arguments": {"path": "MendCode_问题记录.md"},
            },
        },
        {
            "run_id": "run",
            "event_type": "agent.tool_observation",
            "message": "obs",
            "payload": {
                "observation": {
                    "tool_name": "read_file",
                    "status": "failed",
                    "error_message": "not found",
                }
            },
        },
        {
            "run_id": "run",
            "event_type": "agent.final_response",
            "message": "final",
            "payload": {"content": "最后一句是：已修复。"},
        },
    ]
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events),
        encoding="utf-8",
    )

    report = analyze_transcript(parse_session_file(path))
    markdown = render_report_markdown(report)

    assert "repeated_tool_call" in markdown
    assert "failed_tool_observation" in markdown
    assert "unsupported_after_failed_tool" in markdown
