import pytest

from tests.scenarios.tui_scenario_runner import (
    ScenarioToolStep,
    ScenarioTranscript,
    TuiScenario,
    TuiScenarioRunner,
    assert_answer_is_concise,
    assert_did_not_use_chat,
    assert_has_evidence_from_any_observation,
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


async def test_observation_evidence_rejects_metadata_only_tool_payload():
    transcript = ScenarioTranscript(
        scenario_name="metadata-only evidence",
        user_inputs=["list files"],
        visible_messages=["Agent: Tool Result\n1. list_dir: succeeded - list_dir"],
        jsonl_records=[
            {
                "event_type": "tool_result",
                "payload": {
                    "steps": [
                        {
                            "action": "list_dir",
                            "status": "succeeded",
                            "summary": "list_dir",
                            "payload": {"tool_name": "list_dir"},
                        }
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


async def test_git_status_request_uses_safe_shell_and_stays_compact(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="git status",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["看下 git status"],
            tool_steps=[
                ScenarioToolStep(
                    action="git",
                    status="succeeded",
                    summary="Ran git: git status --short",
                    payload={
                        "command": "git status --short",
                        "exit_code": 0,
                        "stdout_excerpt": " M README.md\n",
                    },
                    args={"operation": "status"},
                )
            ],
            final_summary="git status 显示 README.md 有修改。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_has_evidence_from_any_observation(transcript, ("git", "run_shell_command"))
    assert_visible_answer_contains(transcript, "git status")
    assert_answer_is_concise(transcript, max_lines=12, max_chars=900)
    assert_no_raw_trace_or_large_json_dump(transcript)


async def test_chinese_git_state_request_uses_safe_shell_not_chat(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="chinese git state",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["查看当前git状态"],
            tool_steps=[
                ScenarioToolStep(
                    action="run_shell_command",
                    status="succeeded",
                    summary="Shell command completed",
                    payload={
                        "command": "git status --short",
                        "exit_code": 0,
                        "stdout_excerpt": " M README.md\n",
                    },
                    args={"command": "git status --short"},
                )
            ],
            final_summary="git status 显示 M README.md。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_has_evidence_from_any_observation(transcript, ("git", "run_shell_command"))
    assert_visible_answer_contains(transcript, "git status")
    assert_visible_answer_contains(transcript, "M README.md")
    assert_answer_is_concise(transcript, max_lines=12, max_chars=900)
    assert_no_raw_trace_or_large_json_dump(transcript)


async def test_project_stack_question_is_tool_backed(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="project stack",
            repo_files={
                "pyproject.toml": "[project]\nname = 'demo'\n",
                "app/main.py": "print('hello')\n",
            },
            user_inputs=["这个仓库是什么技术栈"],
            tool_steps=[
                ScenarioToolStep(
                    action="detect_project",
                    status="succeeded",
                    summary="Detected project",
                    payload={
                        "project_type": "python",
                        "verification_commands": ["python -m pytest -q"],
                    },
                )
            ],
            final_summary="这是 Python 项目。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_has_evidence_from_observation(transcript, "detect_project")
    assert_visible_answer_contains(transcript, "Python")
    assert_answer_is_concise(transcript, max_lines=10, max_chars=700)


async def test_local_fact_question_never_uses_chat_path(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="local fact tool only",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["当前目录里有什么"],
            tool_steps=[
                ScenarioToolStep(
                    action="list_dir",
                    status="succeeded",
                    summary="Listed .",
                    payload={
                        "relative_path": ".",
                        "total_entries": 1,
                        "entries": [
                            {
                                "relative_path": "README.md",
                                "name": "README.md",
                                "type": "file",
                            }
                        ],
                    },
                )
            ],
            final_summary="当前目录包含 README.md。",
        )
    )

    assert_did_not_use_chat(transcript)
    assert_used_tool_path(transcript)
    assert_has_evidence_from_observation(transcript, "list_dir")
