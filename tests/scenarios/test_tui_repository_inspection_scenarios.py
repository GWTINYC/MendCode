import pytest

from tests.scenarios.tui_scenario_runner import (
    ScenarioToolStep,
    ScenarioTranscript,
    TuiScenario,
    TuiScenarioRunner,
    assert_answer_is_concise,
    assert_did_not_use_chat,
    assert_has_evidence_from_observation,
    assert_no_raw_trace_or_large_json_dump,
    assert_used_tool_path,
    assert_visible_answer_contains,
)

pytestmark = pytest.mark.asyncio


async def test_directory_listing_is_tool_backed_and_concise(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="directory listing",
            repo_files={
                "README.md": "MendCode\n",
                "app/main.py": "print('hello')\n",
            },
            user_inputs=["帮我查看当前文件夹里的文件"],
            tool_steps=[
                ScenarioToolStep(
                    action="list_dir",
                    status="succeeded",
                    summary="Listed .",
                    payload={
                        "relative_path": ".",
                        "total_entries": 2,
                        "entries": [
                            {
                                "relative_path": "README.md",
                                "name": "README.md",
                                "type": "file",
                            },
                            {
                                "relative_path": "app",
                                "name": "app",
                                "type": "directory",
                            },
                        ],
                    },
                )
            ],
            final_summary="当前文件夹包含 README.md 和 app。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_has_evidence_from_observation(transcript, "list_dir")
    assert_visible_answer_contains(transcript, "README.md")
    assert_visible_answer_contains(transcript, "app")
    assert_answer_is_concise(transcript, max_lines=12, max_chars=900)
    assert_no_raw_trace_or_large_json_dump(transcript)


async def test_observation_evidence_requires_successful_meaningful_tool_step():
    transcript = ScenarioTranscript(
        scenario_name="failed evidence",
        user_inputs=["list files"],
        visible_messages=["Agent: Tool Result\n1. list_dir: failed - Listed ."],
        jsonl_records=[
            {
                "event_type": "tool_result",
                "payload": {
                    "steps": [
                        {
                            "action": "list_dir",
                            "status": "failed",
                            "summary": "Listed .",
                            "payload": {"relative_path": "."},
                        },
                        {
                            "action": "list_dir",
                            "status": "succeeded",
                            "summary": "",
                        },
                    ]
                },
            }
        ],
        chat_calls=[],
        tool_calls=["list files"],
        shell_calls=[],
    )

    with pytest.raises(AssertionError, match="successful meaningful"):
        assert_has_evidence_from_observation(transcript, "list_dir")


async def test_raw_trace_assertion_catches_python_repr_internal_leaks():
    transcript = ScenarioTranscript(
        scenario_name="repr leak",
        user_inputs=["list files"],
        visible_messages=["Agent: {'payload': {'tool_name': 'list_dir'}}"],
        jsonl_records=[],
        chat_calls=[],
        tool_calls=[],
        shell_calls=[],
    )

    with pytest.raises(AssertionError, match="raw internals"):
        assert_no_raw_trace_or_large_json_dump(transcript)
