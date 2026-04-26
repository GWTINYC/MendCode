from pathlib import Path

from app.agent.loop import AgentLoopInput, run_agent_loop
from app.config.settings import Settings
from tests.fixtures.mock_tool_provider import (
    MockToolProvider,
    assert_last_observation,
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
