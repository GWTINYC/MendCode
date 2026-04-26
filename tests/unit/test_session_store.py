import json
from pathlib import Path

import pytest

from app.runtime.session_store import SessionNotFoundError, SessionStore, read_trace_view


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def write_conversation(
    data_dir: Path,
    *,
    stem: str,
    repo_path: str,
    started_at: str,
    records: list[dict[str, object]],
) -> Path:
    conversations_dir = data_dir / "conversations"
    jsonl_path = conversations_dir / f"{stem}.jsonl"
    markdown_path = conversations_dir / f"{stem}.md"
    write_jsonl(jsonl_path, records)
    markdown_path.write_text(
        "\n".join(
            [
                "# MendCode Conversation",
                "",
                f"repo: {repo_path}",
                f"started_at: {started_at}",
                f"run_id: {stem.rsplit('-', 1)[-1]}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return jsonl_path


def message_record(sequence: int, timestamp: str, role: str, message: str) -> dict[str, object]:
    return {
        "sequence": sequence,
        "timestamp": timestamp,
        "event_type": "message",
        "payload": {"role": role, "message": message},
    }


def test_session_store_lists_sessions_newest_first_and_loads_latest(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    write_conversation(
        data_dir,
        stem="2026-04-26_100000-oldrun",
        repo_path="/repo/old",
        started_at="2026-04-26T10:00:00+08:00",
        records=[
            message_record(1, "2026-04-26T10:00:00+08:00", "You", "old"),
        ],
    )
    write_conversation(
        data_dir,
        stem="2026-04-26_110000-newrun",
        repo_path="/repo/new",
        started_at="2026-04-26T11:00:00+08:00",
        records=[
            message_record(1, "2026-04-26T11:00:00+08:00", "You", "new"),
            message_record(2, "2026-04-26T11:01:00+08:00", "MendCode", "answer"),
        ],
    )

    store = SessionStore(data_dir=data_dir)
    sessions = store.list_sessions()

    assert [session.session_id for session in sessions] == ["newrun", "oldrun"]
    assert sessions[0].repo_path == "/repo/new"
    assert sessions[0].event_count == 2
    assert sessions[0].message_count == 2
    assert sessions[0].last_event_type == "message"
    assert sessions[0].markdown_path.name == "2026-04-26_110000-newrun.md"
    assert store.latest_session().session_id == "newrun"
    assert store.get_session("oldrun").repo_path == "/repo/old"


def test_session_store_raises_for_missing_session(tmp_path: Path) -> None:
    store = SessionStore(data_dir=tmp_path / "data")

    with pytest.raises(SessionNotFoundError, match="missing"):
        store.get_session("missing")

    with pytest.raises(SessionNotFoundError, match="no conversation sessions"):
        store.latest_session()


def test_resume_context_keeps_final_answers_and_compact_tool_summaries(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    full_content = "secret file content\n" * 500
    write_conversation(
        data_dir,
        stem="2026-04-26_120000-resume",
        repo_path="/repo/resume",
        started_at="2026-04-26T12:00:00+08:00",
        records=[
            message_record(1, "2026-04-26T12:00:00+08:00", "You", "读取 README"),
            {
                "sequence": 2,
                "timestamp": "2026-04-26T12:00:01+08:00",
                "event_type": "tool_result",
                "payload": {
                    "run_id": "agent-read",
                    "status": "completed",
                    "summary": "Read README.md",
                    "trace_path": "/tmp/trace.jsonl",
                    "steps": [
                        {
                            "index": 1,
                            "action": {
                                "type": "tool_call",
                                "action": "read_file",
                                "args": {"path": "README.md"},
                            },
                            "observation": {
                                "status": "succeeded",
                                "summary": "Read README.md",
                                "payload": {
                                    "relative_path": "README.md",
                                    "content": full_content,
                                },
                            },
                        }
                    ],
                },
            },
            message_record(
                3,
                "2026-04-26T12:00:02+08:00",
                "MendCode",
                "README 的第一行是 MendCode。",
            ),
        ],
    )

    context = SessionStore(data_dir=data_dir).build_resume_context("resume")

    assert "session_id: resume" in context
    assert "You: 读取 README" in context
    assert "MendCode: README 的第一行是 MendCode。" in context
    assert "read_file: succeeded - Read README.md" in context
    assert "relative_path=README.md" in context
    assert "content_excerpt=" in context
    assert full_content not in context
    assert "/tmp/trace.jsonl" in context


def test_trace_viewer_returns_tool_event_excerpts_and_full_payload(tmp_path: Path) -> None:
    trace_path = tmp_path / "agent.jsonl"
    full_content = "tool output\n" * 400
    write_jsonl(
        trace_path,
        [
            {
                "run_id": "agent-test",
                "event_type": "agent.run.started",
                "message": "Started",
                "timestamp": "2026-04-26T12:00:00Z",
                "payload": {"problem_statement": "read file"},
            },
            {
                "run_id": "agent-test",
                "event_type": "agent.action.completed",
                "message": "Completed agent action",
                "timestamp": "2026-04-26T12:00:01Z",
                "payload": {
                    "index": 1,
                    "action": {
                        "type": "tool_call",
                        "action": "read_file",
                        "args": {"path": "README.md"},
                    },
                    "observation": {
                        "status": "succeeded",
                        "summary": "Read README.md",
                        "payload": {
                            "relative_path": "README.md",
                            "content": full_content,
                        },
                    },
                },
            },
        ],
    )

    view = read_trace_view(trace_path, max_excerpt_chars=80)

    assert view.trace_path == trace_path
    assert len(view.tool_events) == 1
    event = view.tool_events[0]
    assert event.index == 1
    assert event.tool_name == "read_file"
    assert event.status == "succeeded"
    assert event.full_payload["observation"]["payload"]["content"] == full_content
    assert len(event.payload_excerpt) <= 95
    assert event.payload_truncated is True
