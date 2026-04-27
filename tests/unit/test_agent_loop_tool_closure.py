from pathlib import Path

from app.agent.loop import AgentLoopInput, run_agent_loop
from app.config.settings import Settings
from tests.fixtures.mock_tool_provider import (
    MockToolProvider,
    assert_last_observation,
    assert_payload_contains,
    final_response_step,
    native_tool,
    tool_call_step,
)


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        app_name="MendCode",
        app_version="0.0.0",
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        traces_dir=tmp_path / "data" / "traces",
        workspace_root=tmp_path / ".worktrees",
        verification_timeout_seconds=60,
        cleanup_success_workspace=False,
    )


def test_mock_tool_provider_harness_drives_list_dir_roundtrip(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    provider = MockToolProvider(
        [
            tool_call_step(
                native_tool("list_dir", {"path": "."}, call_id="call_list"),
                expected_allowed_tools={"list_dir", "read_file"},
                expected_observation_count=0,
            ),
            final_response_step(
                "当前目录包含 README.md",
                expected_observation_count=1,
                assertions=(assert_last_observation(tool_name="list_dir"),),
            ),
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="帮我查看当前文件夹里的文件",
            provider=provider,
            verification_commands=[],
            allowed_tools={"list_dir", "read_file"},
            step_budget=4,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.summary == "当前目录包含 README.md"
    assert len(provider.calls) == 2


def test_read_file_roundtrip_returns_observation_before_final_answer(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("MendCode demo\n", encoding="utf-8")
    provider = MockToolProvider(
        [
            tool_call_step(native_tool("read_file", {"path": "README.md"})),
            final_response_step(
                "README.md 内容是 MendCode demo",
                expected_observation_count=1,
                assertions=(
                    assert_last_observation(tool_name="read_file"),
                    assert_payload_contains("content", "MendCode demo\n"),
                ),
            ),
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="读取 README.md",
            provider=provider,
            verification_commands=[],
            allowed_tools={"read_file"},
            step_budget=4,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.summary == "README.md 内容是 MendCode demo"


def test_read_file_tail_lines_roundtrip_answers_last_sentence(tmp_path: Path) -> None:
    (tmp_path / "MendCode_问题记录.md").write_text(
        "# MendCode 问题记录\n\n第一段。\n\n最后一句：只回答必要内容。\n",
        encoding="utf-8",
    )
    provider = MockToolProvider(
        [
            tool_call_step(
                native_tool("read_file", {"path": "MendCode_问题记录.md", "tail_lines": 2})
            ),
            final_response_step(
                "最后一句是：只回答必要内容。",
                expected_observation_count=1,
                assertions=(
                    assert_last_observation(tool_name="read_file"),
                    assert_payload_contains("start_line", 4),
                    assert_payload_contains("content", "\n最后一句：只回答必要内容。\n"),
                ),
            ),
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="MendCode 问题记录的最后一句是什么",
            provider=provider,
            verification_commands=[],
            allowed_tools={"read_file"},
            step_budget=4,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.summary == "最后一句是：只回答必要内容。"


def test_rg_roundtrip_returns_matches_before_final_answer(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("needle\n", encoding="utf-8")
    provider = MockToolProvider(
        [
            tool_call_step(native_tool("rg", {"query": "needle", "glob": "*.py"})),
            final_response_step(
                "needle 出现在 app.py",
                expected_observation_count=1,
                assertions=(
                    assert_last_observation(tool_name="rg"),
                    assert_payload_contains("total_matches", 1),
                ),
            ),
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="查找 needle",
            provider=provider,
            verification_commands=[],
            allowed_tools={"rg"},
            step_budget=4,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.summary == "needle 出现在 app.py"


def test_multi_tool_turn_preserves_both_observations(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("readme content\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("notes content\n", encoding="utf-8")
    provider = MockToolProvider(
        [
            tool_call_step(
                native_tool("read_file", {"path": "README.md"}, call_id="call_readme"),
                native_tool("read_file", {"path": "notes.txt"}, call_id="call_notes"),
            ),
            final_response_step(
                "读取了 README.md 和 notes.txt",
                expected_observation_count=2,
                assertions=(
                    assert_last_observation(tool_name="read_file"),
                    assert_payload_contains("content", "notes content\n"),
                ),
            ),
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="读取两个文件",
            provider=provider,
            verification_commands=[],
            allowed_tools={"read_file"},
            step_budget=5,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.steps[0].observation.payload["tool_name"] == "read_file"
    assert result.steps[0].observation.payload["content"] == "readme content\n"
    assert result.steps[1].observation.payload["tool_name"] == "read_file"
    assert result.steps[1].observation.payload["content"] == "notes content\n"


def test_shell_stdout_roundtrip_includes_exit_code_and_stdout(tmp_path: Path) -> None:
    provider = MockToolProvider(
        [
            tool_call_step(native_tool("run_shell_command", {"command": "printf 'hello-shell'"})),
            final_response_step(
                "shell 输出 hello-shell",
                expected_observation_count=1,
                assertions=(
                    assert_last_observation(tool_name="run_shell_command"),
                    assert_payload_contains("exit_code", 0),
                    assert_payload_contains("stdout_excerpt", "hello-shell"),
                ),
            ),
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="运行 shell 输出",
            provider=provider,
            verification_commands=[],
            allowed_tools={"run_shell_command"},
            step_budget=4,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.summary == "shell 输出 hello-shell"


def test_tool_error_roundtrip_is_structured_and_blocks_completed_final(tmp_path: Path) -> None:
    provider = MockToolProvider(
        [
            tool_call_step(native_tool("read_file", {"path": "missing.md"})),
            final_response_step(
                "不应完成",
                expected_observation_count=1,
                assertions=(assert_last_observation(tool_name="read_file", status="rejected"),),
            ),
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="读取不存在的文件",
            provider=provider,
            verification_commands=[],
            allowed_tools={"read_file"},
            step_budget=4,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.summary == "Agent loop ended with failed observations"
    assert result.steps[0].observation.payload["is_error"] is True


def test_allowed_tools_denial_stops_before_execution(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    provider = MockToolProvider(
        [
            tool_call_step(
                native_tool("run_shell_command", {"command": "touch marker.txt"}),
                expected_allowed_tools={"read_file"},
            ),
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="尝试写入 marker",
            provider=provider,
            verification_commands=[],
            allowed_tools={"read_file"},
            step_budget=4,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.steps[0].observation.status == "rejected"
    assert result.summary == "Tool denied by allowed-tools gate"
    assert not marker.exists()


def test_tool_search_uses_allowed_tools_as_available_pool(tmp_path: Path) -> None:
    provider = MockToolProvider(
        [
            tool_call_step(
                native_tool("tool_search", {"query": "write", "max_results": 10}),
                expected_allowed_tools={"tool_search", "read_file"},
            ),
            final_response_step(
                "当前工具池没有写入工具。",
                expected_observation_count=1,
                assertions=(assert_last_observation(tool_name="tool_search"),),
            ),
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="当前能不能写文件",
            provider=provider,
            verification_commands=[],
            allowed_tools={"tool_search", "read_file"},
            step_budget=4,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.steps[0].observation.payload["matches"] == []
    assert result.steps[0].observation.payload["total_matches"] == 0


def test_permission_confirmation_stop_does_not_run_restricted_shell(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    provider = MockToolProvider(
        [
            tool_call_step(
                native_tool("run_shell_command", {"command": "touch marker.txt"}),
                expected_allowed_tools={"run_shell_command"},
            ),
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="尝试写入 marker",
            provider=provider,
            verification_commands=[],
            allowed_tools={"run_shell_command"},
            permission_mode="guided",
            step_budget=4,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "needs_user_confirmation"
    assert result.steps[0].action.type == "user_confirmation_request"
    assert result.steps[0].observation.status == "rejected"
    assert not marker.exists()
