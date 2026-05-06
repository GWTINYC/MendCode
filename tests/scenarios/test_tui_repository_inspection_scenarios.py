import pytest

from tests.scenarios.tui_scenario_runner import (
    ScenarioToolStep,
    ScenarioTranscript,
    TuiScenario,
    TuiScenarioRunner,
    assert_answer_is_concise,
    assert_benchmark_case_passed,
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
    assert_benchmark_case_passed(
        transcript,
        case_id="repo-list-current-directory",
        category="repository_inspection",
        expected_tools=["list_dir"],
        max_visible_chars=900,
    )


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
    assert_benchmark_case_passed(
        transcript,
        case_id="git-status",
        category="git_status",
        expected_tools=["git"],
        max_visible_chars=900,
    )


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


async def test_review_queue_question_uses_review_queue_tool(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="review queue list",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["列出待审查的经验候选"],
            tool_steps=[
                ScenarioToolStep(
                    action="review_queue_list",
                    status="succeeded",
                    summary="Found 1 review candidates",
                    payload={
                        "status": "pending",
                        "total_candidates": 1,
                        "candidates": [
                            {
                                "id": "candidate-1",
                                "kind": "context_lesson",
                                "summary": "Use tail_lines for final-line questions.",
                                "suggested_memory_kind": "failure_lesson",
                                "confidence": 0.8,
                                "status": "pending",
                            }
                        ],
                    },
                    args={"status": "pending"},
                )
            ],
            final_summary="当前有 1 条待审查经验候选：Use tail_lines for final-line questions。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_has_evidence_from_observation(transcript, "review_queue_list")
    assert_visible_answer_contains(transcript, "待审查")
    assert_visible_answer_contains(transcript, "tail_lines")
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


async def test_tool_availability_question_uses_session_status(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="tool availability",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["现在你能用哪些工具"],
            tool_steps=[
                ScenarioToolStep(
                    action="session_status",
                    status="succeeded",
                    summary="Read session status",
                    payload={
                        "repo_path": str(tmp_path),
                        "workspace_path": str(tmp_path),
                        "permission_mode": "guided",
                        "allowed_tools": ["read_file", "session_status", "tool_search"],
                        "available_tools": ["read_file", "session_status", "tool_search"],
                        "denied_tools": [],
                    },
                )
            ],
            final_summary="当前可用工具包括 read_file、tool_search 和 session_status。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_has_evidence_from_observation(transcript, "session_status")
    assert_visible_answer_contains(transcript, "session_status")
    assert_visible_answer_contains(transcript, "tool_search")
    assert_answer_is_concise(transcript, max_lines=10, max_chars=700)
    assert_no_raw_trace_or_large_json_dump(transcript)


async def test_memory_recall_question_uses_memory_search(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="memory recall",
            repo_files={"README.md": "Demo\n"},
            user_inputs=["之前记录的 pytest 命令是什么"],
            tool_steps=[
                ScenarioToolStep(
                    action="memory_search",
                    status="succeeded",
                    summary="Found 1 memory records",
                    payload={
                        "total_matches": 1,
                        "matches": [
                            {
                                "id": "m1",
                                "kind": "project_fact",
                                "title": "pytest command",
                                "content_excerpt": "Use python -m pytest -q.",
                                "tags": ["verification"],
                                "score": 3,
                            }
                        ],
                    },
                    args={"query": "pytest", "limit": 5},
                )
            ],
            final_summary="之前记录的 pytest 命令是 python -m pytest -q。",
        )
    )

    assert_used_tool_path(transcript)
    assert_has_evidence_from_observation(transcript, "memory_search")
    memory_step = _tool_step(transcript, "memory_search")
    assert memory_step["args"]["query"] == "pytest"
    assert memory_step["args"]["limit"] == 5
    assert memory_step["payload"]["matches_sample"][0]["content_excerpt"] == (
        "Use python -m pytest -q."
    )
    assert memory_step["payload"]["matches_sample"][0]["title"] == "pytest command"
    assert any(
        record.get("event_type") == "tool_result"
        and isinstance(record.get("payload"), dict)
        and isinstance(record["payload"].get("context_summary"), dict)
        and record["payload"]["context_summary"]["metrics"]["observation_count"] >= 1
        for record in transcript.jsonl_records
    )
    assert_visible_answer_contains(transcript, "python -m pytest -q")
    assert_answer_is_concise(transcript, max_lines=8, max_chars=500)
    assert_benchmark_case_passed(
        transcript,
        case_id="memory-recall-verification-command",
        category="memory_context",
        expected_tools=["memory_search"],
        max_visible_chars=500,
    )


async def test_tui_stores_pending_tool_from_agent_loop_confirmation(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="pending tool confirmation",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["记住这个经验"],
            pending_confirmation={
                "id": "confirm-memory-write",
                "tool_call_id": "call_memory_write",
                "tool_name": "memory_write",
                "arguments": {
                    "kind": "failure_lesson",
                    "title": "Use concise tool summaries",
                    "content": "Keep TUI tool output compact.",
                },
                "reason": "tool memory_write requires confirmation",
                "risk_level": "medium",
                "required_mode": "workspace-write",
                "preview": {
                    "kind": "failure_lesson",
                    "title": "Use concise tool summaries",
                    "content_chars": 29,
                },
                "source": "agent_loop",
            },
        )
    )

    assert_visible_answer_contains(transcript, "工具调用需要确认")
    assert transcript.pending_tool is not None
    assert transcript.pending_tool["tool_name"] == "memory_write"


def _tool_step(transcript: ScenarioTranscript, tool_name: str) -> dict[str, object]:
    for result in transcript.tool_results:
        for step in result.get("steps", []):
            if isinstance(step, dict) and step.get("action") == tool_name:
                return step
    raise AssertionError(f"missing tool step {tool_name}: {transcript.debug_text()}")


async def test_symbol_definition_question_uses_lsp_or_explicit_fallback(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="symbol definition",
            repo_files={"app/main.py": "def target():\n    return 1\n"},
            user_inputs=["target 函数在哪里定义"],
            tool_steps=[
                ScenarioToolStep(
                    action="lsp",
                    status="rejected",
                    summary="Language server unavailable",
                    payload={
                        "operation": "definition",
                        "path": "app/main.py",
                        "line": 1,
                        "column": 5,
                    },
                    error_message="language server unavailable",
                    args={
                        "operation": "definition",
                        "path": "app/main.py",
                        "line": 1,
                        "column": 5,
                    },
                ),
                ScenarioToolStep(
                    action="rg",
                    status="succeeded",
                    summary="Searched target",
                    payload={
                        "query": "target",
                        "matches": [
                            {
                                "relative_path": "app/main.py",
                                "line_number": 1,
                                "line_text": "def target():",
                            }
                        ],
                    },
                    args={"query": "target"},
                ),
            ],
            final_summary="target 定义在 app/main.py 第 1 行。",
        )
    )

    assert_used_tool_path(transcript)
    assert_has_evidence_from_any_observation(transcript, ("lsp", "rg"))
    assert_visible_answer_contains(transcript, "app/main.py")
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
