import pytest

from tests.scenarios.tui_scenario_runner import (
    ScenarioToolStep,
    ScenarioTranscript,
    TuiScenario,
    TuiScenarioRunner,
    assert_answer_is_concise,
    assert_has_rejected_evidence_from_observation,
    assert_no_contradictory_success_claims,
    assert_no_fabricated_command_claims,
    assert_no_raw_trace_or_large_json_dump,
    assert_no_repeated_equivalent_tool_calls,
    assert_routed_shell_command,
    assert_used_tool_path,
    assert_visible_answer_contains,
)

pytestmark = pytest.mark.asyncio


async def test_missing_file_response_is_short_and_honest(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="missing file",
            repo_files={"README.md": "demo\n"},
            user_inputs=["读取 missing.md"],
            tool_steps=[
                ScenarioToolStep(
                    action="read_file",
                    status="rejected",
                    summary="Unable to read missing.md",
                    payload={"relative_path": "missing.md"},
                    error_message="file does not exist",
                    args={"path": "missing.md"},
                )
            ],
            final_summary="没有找到 missing.md，无法读取该文件。",
        )
    )

    assert_used_tool_path(transcript)
    assert_has_rejected_evidence_from_observation(transcript, "read_file")
    assert_visible_answer_contains(transcript, "无法读取")
    assert_no_fabricated_command_claims(transcript)
    assert_no_contradictory_success_claims(transcript, target="missing.md")
    assert_no_raw_trace_or_large_json_dump(transcript)
    assert_answer_is_concise(transcript, max_lines=8, max_chars=500)


async def test_repeated_equivalent_tool_calls_within_limit_are_allowed(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="repeated list dir",
            repo_files={"README.md": "demo\n"},
            user_inputs=["帮我查看当前文件夹里的文件"],
            tool_steps=[
                ScenarioToolStep(
                    action="list_dir",
                    status="succeeded",
                    summary="Listed .",
                    payload={"relative_path": ".", "entries": [], "total_entries": 0},
                ),
                ScenarioToolStep(
                    action="list_dir",
                    status="succeeded",
                    summary="Listed .",
                    payload={"relative_path": ".", "entries": [], "total_entries": 0},
                ),
            ],
            final_summary="当前目录为空。",
        )
    )

    assert_no_repeated_equivalent_tool_calls(transcript, limit=2)


async def test_repeated_equivalent_tool_calls_are_flagged_by_assertion():
    transcript = ScenarioTranscript(
        scenario_name="repeated list dir",
        user_inputs=["帮我查看当前文件夹里的文件"],
        visible_messages=["当前目录为空。"],
        jsonl_records=[
            {
                "event_type": "tool_result",
                "payload": {
                    "steps": [
                        {
                            "action": "list_dir",
                            "status": "succeeded",
                            "payload": {"relative_path": "."},
                        },
                        {
                            "action": "list_dir",
                            "status": "succeeded",
                            "payload": {"relative_path": "."},
                        },
                        {
                            "action": "list_dir",
                            "status": "succeeded",
                            "payload": {"relative_path": "."},
                        },
                    ]
                },
            }
        ],
        chat_calls=[],
        tool_calls=["帮我查看当前文件夹里的文件"],
        shell_calls=[],
    )

    with pytest.raises(AssertionError, match="repeated equivalent tool calls exceeded limit 2"):
        assert_no_repeated_equivalent_tool_calls(transcript, limit=2)


async def test_rejected_evidence_requires_specific_error_or_target():
    transcript = ScenarioTranscript(
        scenario_name="generic rejected evidence",
        user_inputs=["读取 missing.md"],
        visible_messages=["没有找到 missing.md。"],
        jsonl_records=[
            {
                "event_type": "tool_result",
                "payload": {
                    "steps": [
                        {
                            "action": "read_file",
                            "status": "rejected",
                            "summary": "rejected",
                            "payload": {"tool_name": "read_file"},
                        }
                    ]
                },
            }
        ],
        chat_calls=[],
        tool_calls=["读取 missing.md"],
        shell_calls=[],
    )

    with pytest.raises(AssertionError, match="expected rejected compact tool_result evidence"):
        assert_has_rejected_evidence_from_observation(transcript, "read_file")


async def test_rejected_evidence_rejects_generic_error_message():
    transcript = ScenarioTranscript(
        scenario_name="generic rejected error",
        user_inputs=["读取 missing.md"],
        visible_messages=["没有找到 missing.md。"],
        jsonl_records=[
            {
                "event_type": "tool_result",
                "payload": {
                    "steps": [
                        {
                            "action": "read_file",
                            "status": "rejected",
                            "summary": "rejected",
                            "error_message": "rejected",
                            "payload": {"tool_name": "read_file"},
                        }
                    ]
                },
            }
        ],
        chat_calls=[],
        tool_calls=["读取 missing.md"],
        shell_calls=[],
    )

    with pytest.raises(AssertionError, match="expected rejected compact tool_result evidence"):
        assert_has_rejected_evidence_from_observation(transcript, "read_file")


async def test_missing_file_assertion_rejects_contradictory_success_claims():
    transcript = ScenarioTranscript(
        scenario_name="contradictory missing file",
        user_inputs=["读取 missing.md"],
        visible_messages=["已读取 missing.md\n内容如下：demo"],
        jsonl_records=[],
        chat_calls=[],
        tool_calls=[],
        shell_calls=[],
    )

    with pytest.raises(AssertionError, match="contradictory success claim"):
        assert_no_contradictory_success_claims(transcript, target="missing.md")


async def test_dangerous_shell_requests_confirmation_without_execution(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="dangerous shell",
            repo_files={"README.md": "demo\n"},
            user_inputs=["rm README.md"],
        )
    )

    if transcript.shell_calls:
        raise AssertionError(transcript.debug_text())
    assert_visible_answer_contains(transcript, "需要确认")
    assert_visible_answer_contains(transcript, "rm README.md")
    assert_visible_answer_contains(transcript, "risk_level: high")
    assert_visible_answer_contains(transcript, "write command requires confirmation")
    assert_visible_answer_contains(transcript, "回复“确认”")
    assert_routed_shell_command(transcript, "rm README.md")
    assert_answer_is_concise(transcript, max_lines=8, max_chars=700)
