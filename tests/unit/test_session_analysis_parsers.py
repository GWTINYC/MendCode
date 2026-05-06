import json
from pathlib import Path

from app.runtime.session_analysis.parsers import parse_session_file


def test_parse_markdown_conversation_extracts_messages(tmp_path: Path) -> None:
    path = tmp_path / "2026-04-27_160326-323e138850fe.md"
    path.write_text(
        "\n".join(
            [
                "# Conversation",
                "## User",
                "MendCode问题记录的最后一句是什么",
                "## Assistant",
                "我需要查看文件。",
                "## Assistant",
                "这是最终回答。",
            ]
        ),
        encoding="utf-8",
    )

    transcript = parse_session_file(path)

    assert transcript.session_id == "2026-04-27_160326-323e138850fe"
    assert transcript.input_kind == "conversation_markdown"
    assert transcript.user_messages == ["MendCode问题记录的最后一句是什么"]
    assert transcript.final_answer == "这是最终回答。"


def test_parse_markdown_conversation_extracts_visible_tool_block(tmp_path: Path) -> None:
    path = tmp_path / "session.md"
    path.write_text(
        "\n".join(
            [
                "## User",
                "查看 git 状态",
                "## Tool",
                "tool: git",
                "status: failed",
                "stderr: fatal error",
                "## Assistant",
                "当前仓库是干净的。",
            ]
        ),
        encoding="utf-8",
    )

    transcript = parse_session_file(path)

    assert transcript.tool_calls[0].tool_name == "git"
    assert transcript.observations[0].status == "failed"
    assert "fatal error" in transcript.observations[0].stderr_excerpt


def test_parse_real_markdown_conversation_log_extracts_you_and_agent_messages(
    tmp_path: Path,
) -> None:
    path = tmp_path / "2026-05-06_120000-run.md"
    path.write_text(
        "\n".join(
            [
                "# MendCode Conversation",
                "",
                "repo: /home/wxh/MendCode",
                "started_at: 2026-05-06T12:00:00",
                "run_id: run",
                "",
                "## Message 1 - You",
                "",
                "timestamp: 2026-05-06T12:00:01",
                "",
                "```",
                "查看 git status",
                "```",
                "",
                "## Message 2 - Agent",
                "",
                "timestamp: 2026-05-06T12:00:02",
                "",
                "```",
                "工作区干净。",
                "```",
            ]
        ),
        encoding="utf-8",
    )

    transcript = parse_session_file(path)

    assert transcript.user_messages == ["查看 git status"]
    assert transcript.assistant_messages == ["工作区干净。"]
    assert transcript.final_answer == "工作区干净。"


def test_parse_jsonl_trace_extracts_tool_and_final_response(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    events = [
        {
            "run_id": "run-1",
            "event_type": "agent.user_message",
            "message": "user",
            "payload": {"message": "列一下当前目录"},
        },
        {
            "run_id": "run-1",
            "event_type": "agent.tool_call",
            "message": "tool",
            "payload": {"tool_name": "list_dir", "arguments": {"path": "."}},
        },
        {
            "run_id": "run-1",
            "event_type": "agent.tool_observation",
            "message": "observation",
            "payload": {
                "observation": {
                    "tool_name": "list_dir",
                    "status": "succeeded",
                    "payload": {"entries": ["README.md"]},
                    "summary": "listed directory",
                }
            },
        },
        {
            "run_id": "run-1",
            "event_type": "agent.final_response",
            "message": "final",
            "payload": {"content": "当前目录包含 README.md。"},
        },
    ]
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events),
        encoding="utf-8",
    )

    transcript = parse_session_file(path)

    assert transcript.session_id == "trace"
    assert transcript.input_kind == "jsonl_trace"
    assert transcript.user_messages == ["列一下当前目录"]
    assert transcript.tool_calls[0].tool_name == "list_dir"
    assert transcript.observations[0].tool_name == "list_dir"
    assert transcript.final_answer == "当前目录包含 README.md。"


def test_parse_real_runtime_trace_extracts_started_action_and_completed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "agent-run.jsonl"
    events = [
        {
            "run_id": "run-1",
            "event_type": "agent.run.started",
            "message": "Started agent loop",
            "payload": {"problem_statement": "查看 git status"},
        },
        {
            "run_id": "run-1",
            "event_type": "agent.action.completed",
            "message": "Completed step 1: git",
            "payload": {
                "index": 1,
                "action": {
                    "type": "tool_call",
                    "tool_name": "git",
                    "args": {"operation": "status"},
                },
                "observation": {
                    "status": "succeeded",
                    "summary": "Git status",
                    "payload": {"status": "clean"},
                },
            },
        },
        {
            "run_id": "run-1",
            "event_type": "agent.run.completed",
            "message": "Completed agent loop",
            "payload": {"status": "completed", "summary": "工作区干净。"},
        },
    ]
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events),
        encoding="utf-8",
    )

    transcript = parse_session_file(path)

    assert transcript.user_messages == ["查看 git status"]
    assert transcript.tool_calls[0].tool_name == "git"
    assert transcript.tool_calls[0].arguments == {"operation": "status"}
    assert transcript.observations[0].tool_name == "git"
    assert transcript.observations[0].status == "succeeded"
    assert transcript.final_answer == "工作区干净。"


def test_parse_real_runtime_trace_extracts_permission_decision(
    tmp_path: Path,
) -> None:
    path = tmp_path / "agent-risk.jsonl"
    events = [
        {
            "run_id": "run-1",
            "event_type": "agent.run.started",
            "message": "Started agent loop",
            "payload": {"problem_statement": "删除所有文件"},
        },
        {
            "run_id": "run-1",
            "event_type": "agent.action.completed",
            "message": "Completed step 1: run_shell_command",
            "payload": {
                "index": 1,
                "action": {
                    "type": "tool_call",
                    "tool_name": "run_shell_command",
                    "args": {"command": "rm -rf ."},
                },
                "observation": {
                    "status": "needs_user_confirmation",
                    "summary": "Command requires confirmation",
                    "error_message": "confirmation required",
                    "payload": {
                        "permission_decision": {
                            "requires_confirmation": True,
                            "risk_level": "high",
                        }
                    },
                },
            },
        },
    ]
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events),
        encoding="utf-8",
    )

    transcript = parse_session_file(path)

    assert transcript.tool_calls[0].requires_confirmation is True
    assert transcript.tool_calls[0].risk_level == "high"
    assert transcript.observations[0].requires_confirmation is True
    assert transcript.observations[0].risk_level == "high"


def test_parse_session_rejects_unknown_suffix(tmp_path: Path) -> None:
    path = tmp_path / "session.txt"
    path.write_text("x", encoding="utf-8")

    try:
        parse_session_file(path)
    except ValueError as exc:
        assert "unsupported session file type" in str(exc)
    else:
        raise AssertionError("expected ValueError")
