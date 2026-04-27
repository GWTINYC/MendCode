import pytest

from tests.scenarios.tui_scenario_runner import (
    ScenarioToolStep,
    TuiScenario,
    TuiScenarioRunner,
    assert_answer_is_concise,
    assert_did_not_use_chat,
    assert_no_raw_trace_or_large_json_dump,
    assert_used_tool_path,
    assert_visible_answer_contains,
    message_record,
    write_saved_conversation,
)

pytestmark = pytest.mark.asyncio


async def test_resume_restores_compact_context_for_followup(tmp_path):
    full_content = "large README content\n" * 500
    write_saved_conversation(
        tmp_path / "data",
        stem="2026-04-26_100000-oldrun",
        records=[
            message_record(1, "2026-04-26T10:00:00+08:00", "You", "读取 README"),
            {
                "sequence": 2,
                "timestamp": "2026-04-26T10:00:01+08:00",
                "event_type": "tool_result",
                "payload": {
                    "status": "completed",
                    "summary": "Read README.md",
                    "trace_path": "/tmp/trace.jsonl",
                    "steps": [
                        {
                            "index": 1,
                            "action": {"type": "tool_call", "action": "read_file"},
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
                "2026-04-26T10:00:02+08:00",
                "MendCode",
                "README 第一行是 MendCode。",
            ),
        ],
    )

    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="resume followup",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["/resume oldrun", "请根据刚才恢复的上下文回答我的追问"],
            tool_steps=[
                ScenarioToolStep(
                    action="read_file",
                    status="succeeded",
                    summary="Read README.md",
                    payload={
                        "relative_path": "README.md",
                        "content_excerpt": "MendCode\n",
                        "content_length": 9,
                    },
                    args={"path": "README.md"},
                )
            ],
            final_summary="README 第一行是 MendCode。",
        )
    )

    assert_did_not_use_chat(transcript)
    assert_used_tool_path(transcript)
    assert_visible_answer_contains(transcript, "session_id: oldrun")
    assert_visible_answer_contains(transcript, "README 第一行是 MendCode")
    assert_visible_answer_contains(transcript, "content_length=")
    assert_visible_answer_contains(transcript, "content_truncated=True")
    if full_content in transcript.visible_text:
        pytest.fail(transcript.debug_text())
    if full_content[:500] in transcript.visible_text:
        pytest.fail(transcript.debug_text())
    repeated_raw_excerpt = (
        "large README content\nlarge README content\nlarge README content"
    )
    if repeated_raw_excerpt in transcript.visible_text:
        pytest.fail(transcript.debug_text())
    if "session_id: oldrun" not in transcript.chat_history_text:
        pytest.fail(transcript.debug_text())
    if "README 第一行是 MendCode" not in transcript.chat_history_text:
        pytest.fail(transcript.debug_text())
    resume_message = next(
        message
        for message in transcript.visible_messages
        if message.startswith("System: Resume Context")
    )
    assert len(resume_message.splitlines()) <= 18, transcript.debug_text()
    assert len(resume_message) <= 1500, transcript.debug_text()
    assert_no_raw_trace_or_large_json_dump(transcript)
    assert_answer_is_concise(transcript, max_lines=18, max_chars=1500)


async def test_sessions_lists_saved_conversation_ids(tmp_path):
    write_saved_conversation(
        tmp_path / "data",
        stem="2026-04-26_100000-oldrun",
        records=[
            message_record(1, "2026-04-26T10:00:00+08:00", "You", "old task"),
        ],
    )

    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="sessions list",
            user_inputs=["/sessions"],
        )
    )

    assert_visible_answer_contains(transcript, "Session List")
    assert_visible_answer_contains(transcript, "oldrun")
    assert transcript.visible_text.count("oldrun") == 1, transcript.debug_text()
    assert_visible_answer_contains(
        transcript,
        "oldrun | 2026-04-26T10:00:00+08:00 | /repo/old | events=1",
    )
    assert_answer_is_concise(transcript, max_lines=8, max_chars=700)
