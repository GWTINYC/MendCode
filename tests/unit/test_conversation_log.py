import json
from datetime import datetime, timezone
from pathlib import Path

from app.tui.conversation_log import ConversationLog


def test_conversation_log_writes_readable_markdown_and_jsonl(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    log = ConversationLog.create(
        data_dir=tmp_path / "data",
        repo_path=repo_path,
        now=datetime(2026, 4, 26, 12, 30, tzinfo=timezone.utc),
        run_id="test-run",
    )

    log.append_message("You", "帮我查看当前文件夹里的文件")
    log.append_event(
        "intent",
        {
            "kind": "tool",
            "source": "rule",
        },
    )
    log.append_message("Agent", "Tool Result\n1. list_dir: succeeded - Listed .")

    markdown = log.markdown_path.read_text(encoding="utf-8")
    assert "# MendCode Conversation" in markdown
    assert f"repo: {repo_path}" in markdown
    assert "## Message 1 - You" in markdown
    assert "帮我查看当前文件夹里的文件" in markdown
    assert "## Event 2 - intent" in markdown
    assert '"kind": "tool"' in markdown
    assert "## Message 3 - Agent" in markdown
    assert "list_dir: succeeded" in markdown

    jsonl_records = [
        json.loads(line)
        for line in log.jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event_type"] for record in jsonl_records] == [
        "message",
        "intent",
        "message",
    ]
    assert jsonl_records[0]["payload"] == {
        "role": "You",
        "message": "帮我查看当前文件夹里的文件",
    }
    assert jsonl_records[1]["payload"] == {"kind": "tool", "source": "rule"}


def test_conversation_log_escapes_markdown_fences(tmp_path: Path) -> None:
    log = ConversationLog.create(
        data_dir=tmp_path / "data",
        repo_path=tmp_path,
        now=datetime(2026, 4, 26, 12, 30, tzinfo=timezone.utc),
        run_id="test-run",
    )

    log.append_message("MendCode", "```json\n{}\n```")

    markdown = log.markdown_path.read_text(encoding="utf-8")
    assert "````text" in markdown
    assert "```json" in markdown
