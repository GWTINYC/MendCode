import shlex
import subprocess
import sys
from pathlib import Path

from app.agent.loop import AgentLoopInput, run_agent_loop
from app.agent.openai_compatible import (
    ChatMessage,
    OpenAICompatibleAgentProvider,
    OpenAICompletion,
    OpenAIToolCall,
)
from app.agent.provider import AgentProviderStepInput, ProviderResponse
from app.agent.provider_factory import build_agent_provider
from app.config.settings import Settings
from app.memory.models import MemoryRecord
from app.memory.store import MemoryStore
from app.tools.structured import ToolInvocation

PYTHON = shlex.quote(sys.executable)


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


def init_git_repo(path: Path) -> Path:
    repo_path = path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return repo_path


class RecordingProvider:
    def __init__(self, actions: list[dict[str, object]]) -> None:
        self.actions = actions
        self.calls: list[AgentProviderStepInput] = []

    def next_action(self, step_input: AgentProviderStepInput) -> ProviderResponse:
        self.calls.append(step_input)
        index = len(self.calls) - 1
        if index >= len(self.actions):
            return ProviderResponse(
                status="succeeded",
                actions=[
                    {
                        "type": "final_response",
                        "status": "completed",
                        "summary": "done",
                    }
                ],
            )
        return ProviderResponse(status="succeeded", actions=[self.actions[index]])


class NativeToolProvider:
    def __init__(self, batches: list[list[ToolInvocation] | dict[str, object]]) -> None:
        self.batches = batches
        self.calls: list[AgentProviderStepInput] = []

    def next_action(self, step_input: AgentProviderStepInput) -> ProviderResponse:
        self.calls.append(step_input)
        index = len(self.calls) - 1
        batch = self.batches[index]
        if isinstance(batch, dict):
            return ProviderResponse(status="succeeded", actions=[batch])
        return ProviderResponse(status="succeeded", tool_invocations=batch)


class FailingProvider:
    def next_action(self, step_input: AgentProviderStepInput) -> ProviderResponse:
        return ProviderResponse.failed("provider unavailable")


class DirectoryListingProvider:
    def __init__(self) -> None:
        self.calls: list[AgentProviderStepInput] = []

    def next_action(self, step_input: AgentProviderStepInput) -> ProviderResponse:
        self.calls.append(step_input)
        if len(self.calls) == 1:
            return ProviderResponse(
                status="succeeded",
                tool_invocations=[
                    ToolInvocation(
                        id="call_list",
                        name="list_dir",
                        args={"path": "."},
                        source="openai_tool_call",
                    )
                ],
            )
        entries = step_input.observations[-1].observation.payload["entries"]
        names = ", ".join(str(entry["relative_path"]) for entry in entries)
        return ProviderResponse(
            status="succeeded",
            actions=[
                {
                    "type": "final_response",
                    "status": "completed",
                    "summary": f"当前目录包含: {names}",
                }
            ],
        )


class RepeatingReadProvider:
    def __init__(self) -> None:
        self.calls: list[AgentProviderStepInput] = []

    def next_action(self, step_input: AgentProviderStepInput) -> ProviderResponse:
        self.calls.append(step_input)
        if len(self.calls) <= 3:
            return ProviderResponse(
                status="succeeded",
                tool_invocations=[
                    ToolInvocation(
                        id=f"call_read_{len(self.calls)}",
                        name="read_file",
                        args={"path": "README.md"},
                        source="openai_tool_call",
                    )
                ],
            )
        return ProviderResponse(
            status="succeeded",
            actions=[
                {
                    "type": "final_response",
                    "status": "failed",
                    "summary": "stopped after repeated call rejection",
                }
            ],
        )


class SequentialOpenAIClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, object]],
        timeout_seconds: int,
    ) -> OpenAICompletion:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "timeout_seconds": timeout_seconds,
            }
        )
        if len(self.calls) == 1:
            return OpenAICompletion(
                tool_calls=[
                    OpenAIToolCall(
                        id="call_list",
                        name="list_dir",
                        arguments='{"path":"."}',
                    )
                ]
            )
        assert any(message.role == "tool" for message in messages)
        return OpenAICompletion(
            tool_calls=[
                OpenAIToolCall(
                    id="call_final",
                    name="final_response",
                    arguments='{"summary":"当前目录包含 README.md。"}',
                )
            ]
        )


class LastSentenceOpenAIClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, object]],
        timeout_seconds: int,
    ) -> OpenAICompletion:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "timeout_seconds": timeout_seconds,
            }
        )
        if len(self.calls) == 1:
            return OpenAICompletion(
                tool_calls=[
                    OpenAIToolCall(
                        id="call_glob",
                        name="glob_file_search",
                        arguments='{"pattern":"**/*问题记录*"}',
                    )
                ]
            )
        if len(self.calls) == 2:
            return OpenAICompletion(
                tool_calls=[
                    OpenAIToolCall(
                        id="call_read",
                        name="read_file",
                        arguments='{"path":"MendCode_问题记录.md","tail_lines":10}',
                    )
                ]
            )
        assert any(tool["function"]["name"] == "final_response" for tool in tools)
        return OpenAICompletion(
            tool_calls=[
                OpenAIToolCall(
                    id="call_final",
                    name="final_response",
                    arguments='{"summary":"最后一句是：不再记录纯讨论、一次性环境噪声、旧路线细枝末节。"}',
                )
            ]
        )


def test_agent_loop_tool_request_passes_allowed_tools_and_grounds_final_answer(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    (repo_path / "README.md").write_text("demo\n", encoding="utf-8")
    provider = DirectoryListingProvider()

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
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
    assert "README.md" in result.summary
    assert provider.calls[0].allowed_tools == {"list_dir", "read_file"}
    assert provider.calls[1].observations[0].tool_invocation is not None
    assert provider.calls[1].observations[0].tool_invocation.id == "call_list"
    assert any(
        entry["relative_path"] == "README.md"
        for entry in result.steps[0].observation.payload["entries"]
    )


def test_agent_loop_executes_memory_search_with_runtime_store(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    memory_store = MemoryStore(settings.data_dir / "memory")
    memory_store.append(
        MemoryRecord(
            kind="project_fact",
            title="test command",
            content="Use python -m pytest -q.",
            source="test",
            tags=["verification"],
        )
    )
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_memory",
                    name="memory_search",
                    args={"query": "pytest", "limit": 5},
                    source="openai_tool_call",
                )
            ],
            {
                "type": "final_response",
                "status": "completed",
                "summary": "Memory recalled pytest command.",
            },
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(repo_path=tmp_path, problem_statement="recall pytest", provider=provider),
        settings,
    )

    assert result.status == "completed"
    assert result.steps[0].action.action == "memory_search"
    assert result.steps[0].observation.payload["total_matches"] == 1


def test_agent_loop_openai_native_tool_call_roundtrip_grounds_final_text(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    (repo_path / "README.md").write_text("demo\n", encoding="utf-8")
    client = SequentialOpenAIClient()
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=client,
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
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
    assert result.summary == "当前目录包含 README.md。"
    assert len(client.calls) == 2
    assert [tool["function"]["name"] for tool in client.calls[0]["tools"]] == [
        "list_dir",
        "read_file",
        "final_response",
    ]
    assert any(message.role == "tool" for message in client.calls[1]["messages"])


def test_agent_loop_openai_final_response_tool_call_completes_last_sentence_question(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    (repo_path / "MendCode_问题记录.md").write_text(
        "# MendCode 问题记录\n\n"
        "新增问题必须满足至少一条：\n\n"
        "- 影响工具闭环正确性\n"
        "- 影响权限边界\n"
        "- 影响会话可复盘性\n"
        "- 影响验证结论可信度\n"
        "- 影响长期架构方向\n\n"
        "不再记录纯讨论、一次性环境噪声、旧路线细枝末节。\n",
        encoding="utf-8",
    )
    client = LastSentenceOpenAIClient()
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=client,
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="Mendcode问题记录的最后一句话是什么",
            provider=provider,
            verification_commands=[],
            allowed_tools={"glob_file_search", "read_file"},
            step_budget=12,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.summary == "最后一句是：不再记录纯讨论、一次性环境噪声、旧路线细枝末节。"
    assert [step.action.type for step in result.steps] == [
        "tool_call",
        "tool_call",
        "final_response",
    ]
    assert len(client.calls) == 3


def test_agent_loop_rejects_native_tool_outside_allowed_tools(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_patch",
                    name="apply_patch",
                    args={"patch": "diff --git a/README.md b/README.md"},
                    source="openai_tool_call",
                )
            ]
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="inspect files",
            provider=provider,
            allowed_tools={"list_dir", "read_file"},
            step_budget=2,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.steps[0].observation.status == "rejected"
    assert result.steps[0].observation.error_message == "tool is not allowed in this turn"


def test_agent_loop_executes_allowed_search_code_action(tmp_path: Path) -> None:
    (tmp_path / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n",
        encoding="utf-8",
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="find add",
            actions=[
                {
                    "type": "tool_call",
                    "action": "search_code",
                    "reason": "locate implementation",
                    "args": {"query": "def add", "glob": "*.py"},
                },
                {"type": "final_response", "status": "completed", "summary": "done"},
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.steps[0].observation.status == "succeeded"
    assert result.steps[0].observation.payload["total_matches"] == 1
    assert result.trace_path is not None


def test_agent_loop_executes_run_shell_command_action(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="list files",
            actions=[
                {
                    "type": "tool_call",
                    "action": "run_shell_command",
                    "reason": "inspect current directory",
                    "args": {"command": "ls"},
                },
                {"type": "final_response", "status": "completed", "summary": "done"},
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.steps[0].observation.status == "succeeded"
    assert result.steps[0].observation.payload["command"] == "ls"
    assert result.steps[0].observation.payload["payload"]["status"] == "passed"
    assert "README.md" in result.steps[0].observation.payload["stdout_excerpt"]


def test_agent_loop_allows_low_risk_process_start_in_guided_mode(tmp_path: Path) -> None:
    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="start background inspection",
            actions=[
                {
                    "type": "tool_call",
                    "action": "process_start",
                    "reason": "inspect current directory",
                    "args": {"command": "pwd"},
                },
                {"type": "final_response", "status": "completed", "summary": "done"},
            ],
            allowed_tools={"full_coding_agent"},
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.steps[0].action.type == "tool_call"
    assert result.steps[0].observation.status == "succeeded"
    assert result.steps[0].observation.payload["command"] == "pwd"


def test_agent_loop_process_start_permission_uses_requested_cwd(tmp_path: Path) -> None:
    subdir = tmp_path / "sub"
    subdir.mkdir()
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="start cwd-sensitive background read",
            actions=[
                {
                    "type": "tool_call",
                    "action": "process_start",
                    "reason": "read from subdir",
                    "args": {"command": "cat ../README.md", "cwd": "sub"},
                },
                {"type": "final_response", "status": "completed", "summary": "done"},
            ],
            allowed_tools={"full_coding_agent"},
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.steps[0].observation.status == "succeeded"


def test_agent_loop_process_start_rejects_missing_cwd(tmp_path: Path) -> None:
    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="start in missing cwd",
            actions=[
                {
                    "type": "tool_call",
                    "action": "process_start",
                    "reason": "bad cwd",
                    "args": {"command": "pwd", "cwd": "missing"},
                },
                {"type": "final_response", "status": "completed", "summary": "done"},
            ],
            allowed_tools={"full_coding_agent"},
            permission_mode="danger-full-access",
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.summary == "Agent loop ended with failed observations"
    assert result.steps[0].observation.status == "rejected"
    assert result.steps[0].observation.error_message == "cwd must exist and be a directory"


def test_agent_loop_executes_list_dir_action(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "README.md").write_text("demo\n", encoding="utf-8")
    (repo_path / "app").mkdir()

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="list files",
            actions=[
                {
                    "type": "tool_call",
                    "action": "list_dir",
                    "reason": "inspect current directory",
                    "args": {"path": "."},
                },
                {"type": "final_response", "status": "completed", "summary": "done"},
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.steps[0].observation.status == "succeeded"
    assert result.steps[0].observation.payload["entries"] == [
        {"relative_path": "README.md", "name": "README.md", "type": "file", "size_bytes": 5},
        {"relative_path": "app", "name": "app", "type": "directory", "size_bytes": None},
    ]


def test_agent_loop_executes_structured_git_status_action(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    (repo_path / "README.md").write_text("demo\n", encoding="utf-8")

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="check status",
            actions=[
                {
                    "type": "tool_call",
                    "action": "git",
                    "reason": "inspect repository state",
                    "args": {"operation": "status"},
                },
                {"type": "final_response", "status": "completed", "summary": "done"},
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.steps[0].observation.status == "succeeded"
    assert result.steps[0].observation.payload["command"] == "git status --short"
    assert "README.md" in result.steps[0].observation.payload["stdout_excerpt"]


def test_agent_loop_preserves_legacy_json_git_status_action(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    (repo_path / "README.md").write_text("demo\n", encoding="utf-8")

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="check status",
            actions=[
                {
                    "type": "tool_call",
                    "action": "git",
                    "reason": "inspect repository state",
                    "args": {"args": ["status", "--short"]},
                },
                {"type": "final_response", "status": "completed", "summary": "done"},
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.steps[0].observation.status == "succeeded"
    assert result.steps[0].observation.payload["command"] == "git status --short"
    assert "README.md" in result.steps[0].observation.payload["stdout_excerpt"]


def test_agent_loop_executes_structured_rg_action(tmp_path: Path) -> None:
    (tmp_path / "src.py").write_text("alpha\nbeta alpha\n", encoding="utf-8")

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="search",
            actions=[
                {
                    "type": "tool_call",
                    "action": "rg",
                    "reason": "find references",
                    "args": {"query": "alpha", "glob": "*.py", "max_results": 1},
                },
                {"type": "final_response", "status": "completed", "summary": "done"},
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.steps[0].observation.status == "succeeded"
    assert result.steps[0].observation.payload["total_matches"] == 2
    assert result.steps[0].observation.payload["matches"] == [
        {"relative_path": "src.py", "line_number": 1, "line_text": "alpha"}
    ]


def test_agent_loop_executes_native_search_code_tool(tmp_path: Path) -> None:
    (tmp_path / "src.py").write_text("alpha\nbeta alpha\n", encoding="utf-8")
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_1",
                    name="search_code",
                    args={"query": "alpha", "glob": "*.py", "max_results": 1},
                    source="openai_tool_call",
                )
            ],
            {"type": "final_response", "status": "completed", "summary": "done"},
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="search",
            provider=provider,
            step_budget=4,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.steps[0].observation.status == "succeeded"
    assert result.steps[0].observation.payload["total_matches"] == 2
    assert result.steps[0].observation.payload["matches"] == [
        {"relative_path": "src.py", "line_number": 1, "line_text": "alpha"}
    ]


def test_agent_loop_executes_structured_apply_patch_action(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("alpha\n", encoding="utf-8")
    command = (
        f"{PYTHON} -c "
        '"from pathlib import Path; '
        "raise SystemExit(0 if Path('notes.txt').read_text() == 'beta\\\\n' else 1)\""
    )
    patch = "\n".join(
        [
            "diff --git a/notes.txt b/notes.txt",
            "index 4a58007..8ab3c1e 100644",
            "--- a/notes.txt",
            "+++ b/notes.txt",
            "@@ -1 +1 @@",
            "-alpha",
            "+beta",
            "",
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="patch file",
            verification_commands=[command],
            actions=[
                {
                    "type": "tool_call",
                    "action": "apply_patch",
                    "reason": "edit notes",
                    "args": {"patch": patch},
                },
                {
                    "type": "tool_call",
                    "action": "run_command",
                    "reason": "verify notes",
                    "args": {"command": command},
                },
                {"type": "final_response", "status": "completed", "summary": "done"},
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.steps[0].observation.status == "succeeded"
    assert result.steps[1].observation.status == "succeeded"
    assert target.read_text(encoding="utf-8") == "beta\n"


def test_agent_loop_structured_git_write_requires_confirmation(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="switch branch",
            actions=[
                {
                    "type": "tool_call",
                    "action": "git",
                    "reason": "try branch switch",
                    "args": {"args": ["checkout", "-b", "demo"]},
                }
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "needs_user_confirmation"
    assert result.steps[0].action.type == "user_confirmation_request"
    assert result.steps[0].observation.status == "rejected"
    assert "git checkout requires confirmation" in str(result.steps[0].observation.error_message)


def test_agent_loop_run_command_rejects_undeclared_verification_command(
    tmp_path: Path,
) -> None:
    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="run arbitrary command",
            actions=[
                {
                    "type": "tool_call",
                    "action": "run_command",
                    "reason": "not declared",
                    "args": {"command": "python -c 'print(123)'"},
                },
                {"type": "final_response", "status": "completed", "summary": "done"},
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.steps[0].observation.status == "rejected"
    assert result.steps[0].observation.payload["payload"]["status"] == "rejected"
    assert "declared" in str(result.steps[0].observation.error_message)


def test_agent_loop_asks_provider_for_each_next_action(tmp_path: Path) -> None:
    (tmp_path / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n",
        encoding="utf-8",
    )
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_search",
                    name="search_code",
                    args={"query": "def add", "glob": "*.py"},
                    source="openai_tool_call",
                )
            ],
            {"type": "final_response", "status": "completed", "summary": "done"},
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="find add",
            provider=provider,
            verification_commands=[],
            step_budget=4,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.steps[0].observation.status == "succeeded"
    assert len(provider.calls) == 2
    assert provider.calls[0].step_index == 1
    assert provider.calls[1].step_index == 2
    assert provider.calls[1].observations[0].observation.status == "succeeded"


def test_agent_loop_passes_failed_observation_to_provider(tmp_path: Path) -> None:
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_run",
                    name="run_command",
                    args={"command": "python -c 'raise SystemExit(1)'"},
                    source="openai_tool_call",
                )
            ],
            {"type": "final_response", "status": "failed", "summary": "failed"},
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="failed verification",
            provider=provider,
            verification_commands=["python -c 'raise SystemExit(1)'"],
            step_budget=4,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert len(provider.calls) == 2
    assert provider.calls[1].observations[0].observation.status == "failed"


def test_agent_loop_executes_native_tool_invocation(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_1",
                    name="read_file",
                    args={"path": "README.md"},
                    source="openai_tool_call",
                )
            ],
            {"type": "final_response", "status": "completed", "summary": "done"},
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="read readme",
            provider=provider,
            step_budget=4,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.steps[0].observation.status == "succeeded"
    assert len(provider.calls) == 2
    assert provider.calls[1].observations[0].tool_invocation is not None
    assert provider.calls[1].observations[0].tool_invocation.id == "call_1"


def test_agent_loop_returns_repeated_tool_rejection_to_provider(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    (repo_path / "README.md").write_text("demo\n", encoding="utf-8")
    provider = RepeatingReadProvider()
    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="read repeatedly",
            provider=provider,
            allowed_tools={"read_file"},
            step_budget=5,
        ),
        settings_for(tmp_path),
    )
    assert len(provider.calls) == 4
    assert result.steps[2].observation.status == "rejected"
    assert result.steps[2].observation.summary == "Repeated equivalent tool call"
    assert (
        provider.calls[3].observations[-1].observation.error_message
        == "equivalent tool call repeated too many times"
    )


def test_agent_loop_session_status_reports_effective_available_tools(
    tmp_path: Path,
) -> None:
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_status",
                    name="session_status",
                    args={},
                    source="openai_tool_call",
                )
            ],
            {"type": "final_response", "status": "completed", "summary": "done"},
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="what tools are available",
            provider=provider,
            allowed_tools={"coding_agent"},
            permission_mode="read-only",
            step_budget=4,
        ),
        settings_for(tmp_path),
    )

    payload = result.steps[0].observation.payload
    assert result.status == "completed"
    assert "session_status" in payload["available_tools"]
    assert "lsp" in payload["available_tools"]
    assert "write_file" not in payload["available_tools"]
    assert "run_shell_command" not in payload["available_tools"]
    assert "process_poll" not in payload["available_tools"]
    assert "write_file" in payload["allowed_tools"]
    assert "run_shell_command" in payload["denied_tools"]
    assert "write_file" in payload["denied_tools"]


def test_agent_loop_executes_multiple_native_tool_invocations_sequentially(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("notes\n", encoding="utf-8")
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_1",
                    name="read_file",
                    args={"path": "README.md"},
                    source="openai_tool_call",
                ),
                ToolInvocation(
                    id="call_2",
                    name="read_file",
                    args={"path": "notes.txt"},
                    source="openai_tool_call",
                ),
            ],
            {"type": "final_response", "status": "completed", "summary": "done"},
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="read files",
            provider=provider,
            step_budget=4,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.steps[0].observation.status == "succeeded"
    assert result.steps[1].observation.status == "succeeded"
    assert len(provider.calls) == 2
    second_call_observations = provider.calls[1].observations
    assert [record.tool_invocation.group_id for record in second_call_observations] == [
        "provider-1",
        "provider-1",
    ]


def test_agent_loop_executes_native_transitional_tool_invocation(tmp_path: Path) -> None:
    (tmp_path / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n",
        encoding="utf-8",
    )
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_1",
                    name="search_code",
                    args={"query": "def add", "glob": "*.py"},
                    source="openai_tool_call",
                )
            ],
            {"type": "final_response", "status": "completed", "summary": "done"},
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="find add",
            provider=provider,
            step_budget=4,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.steps[0].observation.status == "succeeded"
    assert result.steps[0].observation.payload["total_matches"] == 1
    assert len(provider.calls) == 2
    assert provider.calls[1].observations[0].tool_invocation is not None
    assert provider.calls[1].observations[0].tool_invocation.id == "call_1"


def test_agent_loop_fails_when_native_batch_exhausts_step_budget(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("notes\n", encoding="utf-8")
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_1",
                    name="read_file",
                    args={"path": "README.md"},
                    source="openai_tool_call",
                ),
                ToolInvocation(
                    id="call_2",
                    name="read_file",
                    args={"path": "notes.txt"},
                    source="openai_tool_call",
                ),
            ]
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="read files",
            provider=provider,
            step_budget=1,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.summary == "Agent loop exhausted step budget without final response"
    assert len(result.steps) == 1
    assert result.steps[0].observation.status == "succeeded"


def test_agent_loop_rejects_unknown_native_tool(tmp_path: Path) -> None:
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_1",
                    name="delete_repo",
                    args={},
                    source="openai_tool_call",
                )
            ]
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="bad native tool",
            provider=provider,
            step_budget=3,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.steps[0].observation.status == "rejected"
    assert "unknown tool: delete_repo" in str(result.steps[0].observation.error_message)


def test_agent_loop_native_write_tool_is_denied_in_safe_mode(tmp_path: Path) -> None:
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_1",
                    name="apply_patch",
                    args={"patch": ""},
                    source="openai_tool_call",
                )
            ]
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="patch file",
            provider=provider,
            permission_mode="safe",
            step_budget=3,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.steps[0].action.type == "tool_call"
    assert result.steps[0].observation.status == "rejected"
    assert "requires workspace-write permission" in str(result.steps[0].observation.error_message)


def test_agent_loop_native_failed_observation_blocks_completed_final_response(
    tmp_path: Path,
) -> None:
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_1",
                    name="read_file",
                    args={},
                    source="openai_tool_call",
                )
            ],
            {"type": "final_response", "status": "completed", "summary": "done"},
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="read missing path",
            provider=provider,
            step_budget=4,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.summary == "Agent loop ended with failed observations"
    assert result.steps[0].observation.status == "rejected"
    assert result.steps[1].action.type == "final_response"


def test_agent_loop_turns_provider_failure_into_failed_result(tmp_path: Path) -> None:
    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="provider failure",
            provider=FailingProvider(),
            step_budget=3,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.steps[0].observation.status == "failed"
    assert result.steps[0].observation.error_message == "provider unavailable"


def test_agent_loop_rejects_invalid_provider_action(tmp_path: Path) -> None:
    provider = RecordingProvider([{"type": "tool_call", "action": "delete_repo"}])

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="bad provider action",
            provider=provider,
            step_budget=3,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.steps[0].observation.status == "rejected"
    assert result.steps[0].observation.summary == "Legacy JSON actions are disabled"


def test_agent_loop_rejects_provider_json_tool_call_action(tmp_path: Path) -> None:
    provider = RecordingProvider(
        [
            {
                "type": "tool_call",
                "action": "search_code",
                "reason": "legacy JSON action",
                "args": {"query": "def add"},
            }
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="find add",
            provider=provider,
            step_budget=3,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert "Legacy JSON actions are disabled" in result.summary
    assert result.steps[0].observation.status == "rejected"
    assert result.steps[0].observation.summary == "Legacy JSON actions are disabled"
    assert result.steps[0].observation.error_message is not None
    assert "provider returned JSON action instead of schema tool_calls" in (
        result.steps[0].observation.error_message
    )


def test_agent_loop_default_scripted_provider_uses_native_tool_invocations(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    (repo_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    command = f"{PYTHON} -c 'raise SystemExit(0)'"

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="run smoke verification",
            provider=build_agent_provider(settings_for(tmp_path)),
            verification_commands=[command],
            step_budget=5,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert [step.action.type for step in result.steps] == [
        "tool_call",
        "tool_call",
        "tool_call",
        "final_response",
    ]
    assert [step.action.action for step in result.steps[:3] if step.action.type == "tool_call"] == [
        "repo_status",
        "detect_project",
        "run_command",
    ]
    assert result.summary == "Agent loop completed requested verification commands"


def test_provider_driven_loop_stops_for_permission_denial(tmp_path: Path) -> None:
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_run",
                    name="run_command",
                    args={"command": "pytest -q"},
                    source="openai_tool_call",
                )
            ]
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="safe mode command",
            provider=provider,
            permission_mode="safe",
            verification_commands=["pytest -q"],
            step_budget=3,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.steps[0].action.type == "tool_call"
    assert result.steps[0].observation.summary == "Tool denied by permission gate"


def test_provider_driven_loop_fails_when_step_budget_exhausted(tmp_path: Path) -> None:
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_search",
                    name="search_code",
                    args={"query": "missing"},
                    source="openai_tool_call",
                )
            ]
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="no final response",
            provider=provider,
            step_budget=1,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.summary == "Agent loop exhausted step budget without final response"


def test_agent_loop_turns_invalid_action_into_rejected_observation(tmp_path: Path) -> None:
    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="bad action",
            actions=[
                {
                    "type": "tool_call",
                    "action": "delete_repo",
                    "reason": "bad",
                    "args": {},
                }
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.steps[0].observation.status == "rejected"
    assert result.steps[0].observation.summary == "Invalid MendCode action"


def test_agent_loop_returns_denied_observation_when_permission_denies_it(
    tmp_path: Path,
) -> None:
    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="safe mode command",
            permission_mode="safe",
            actions=[
                {
                    "type": "tool_call",
                    "action": "run_command",
                    "reason": "run tests",
                    "args": {"command": "pytest -q"},
                }
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.steps[0].action.type == "tool_call"
    assert result.steps[0].observation.status == "rejected"
    assert "requires workspace-write permission" in str(result.steps[0].observation.error_message)


def test_agent_loop_does_not_complete_after_failed_tool_observation(tmp_path: Path) -> None:
    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="failed verification",
            actions=[
                {
                    "type": "tool_call",
                    "action": "run_command",
                    "reason": "run failing command",
                    "args": {"command": "python -c 'raise SystemExit(1)'"},
                },
                {
                    "type": "final_response",
                    "status": "completed",
                    "summary": "done",
                },
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.summary == "Agent loop ended with failed observations"


def test_agent_loop_does_not_complete_when_earlier_failure_is_followed_by_success(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    failing_command = f"{PYTHON} -c 'raise SystemExit(1)'"

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="failed verification",
            verification_commands=[failing_command],
            actions=[
                {
                    "type": "tool_call",
                    "action": "run_command",
                    "reason": "run failing command",
                    "args": {"command": failing_command},
                },
                {
                    "type": "tool_call",
                    "action": "list_dir",
                    "reason": "inspect current directory",
                    "args": {"path": "."},
                },
                {
                    "type": "final_response",
                    "status": "completed",
                    "summary": "done",
                },
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.summary == "Agent loop ended with failed observations"
    assert result.steps[0].observation.status == "failed"
    assert result.steps[1].observation.status == "succeeded"


def test_agent_loop_applies_patch_proposal_in_worktree_then_verifies(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    target = repo_path / "calculator.py"
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "calculator.py"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add calculator"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    command = (
        f'{PYTHON} -c "import calculator; raise SystemExit(0 if calculator.add(2, 3) == 5 else 1)"'
    )
    patch = """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="fix add",
            use_worktree=True,
            verification_commands=[command],
            actions=[
                {
                    "type": "tool_call",
                    "action": "run_command",
                    "reason": "reproduce failing verification",
                    "args": {"command": command},
                },
                {
                    "type": "patch_proposal",
                    "reason": "add should add operands",
                    "files_to_modify": ["calculator.py"],
                    "patch": patch,
                },
                {
                    "type": "tool_call",
                    "action": "run_command",
                    "reason": "verify patch",
                    "args": {"command": command},
                },
                {
                    "type": "tool_call",
                    "action": "show_diff",
                    "reason": "summarize changed files",
                    "args": {},
                },
                {
                    "type": "final_response",
                    "status": "completed",
                    "summary": "verification passed",
                },
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.workspace_path is not None
    workspace_path = Path(result.workspace_path)
    assert workspace_path != repo_path
    assert target.read_text(encoding="utf-8") == "def add(a, b):\n    return a - b\n"
    assert (workspace_path / "calculator.py").read_text(encoding="utf-8") == (
        "def add(a, b):\n    return a + b\n"
    )
    assert result.steps[1].observation.status == "succeeded"
    assert result.steps[1].observation.payload["files_to_modify"] == ["calculator.py"]
    assert "calculator.py" in result.steps[3].observation.payload["diff_stat"]


def test_agent_loop_native_apply_patch_can_complete_after_failed_verification(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    target = repo_path / "calculator.py"
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "calculator.py"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add calculator"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    command = (
        f'{PYTHON} -c "import calculator; raise SystemExit(0 if calculator.add(2, 3) == 5 else 1)"'
    )
    patch = """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_verify_fail",
                    name="run_command",
                    args={"command": command},
                    source="openai_tool_call",
                )
            ],
            [
                ToolInvocation(
                    id="call_patch",
                    name="apply_patch",
                    args={"patch": patch},
                    source="openai_tool_call",
                )
            ],
            [
                ToolInvocation(
                    id="call_verify_pass",
                    name="run_command",
                    args={"command": command},
                    source="openai_tool_call",
                )
            ],
            {
                "type": "final_response",
                "status": "completed",
                "summary": "verification passed",
            },
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="fix add",
            provider=provider,
            verification_commands=[command],
            step_budget=6,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.steps[0].observation.status == "failed"
    assert result.steps[1].observation.status == "succeeded"
    assert result.steps[2].observation.status == "succeeded"
    assert target.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"


def test_agent_loop_native_apply_patch_still_blocks_later_failed_observation(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    target = repo_path / "calculator.py"
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "calculator.py"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add calculator"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    command = (
        f'{PYTHON} -c "import calculator; raise SystemExit(0 if calculator.add(2, 3) == 5 else 1)"'
    )
    later_failing_command = f"{PYTHON} -c 'raise SystemExit(1)'"
    patch = """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_patch",
                    name="apply_patch",
                    args={"patch": patch},
                    source="openai_tool_call",
                )
            ],
            [
                ToolInvocation(
                    id="call_verify_pass",
                    name="run_command",
                    args={"command": command},
                    source="openai_tool_call",
                )
            ],
            [
                ToolInvocation(
                    id="call_verify_fail",
                    name="run_command",
                    args={"command": later_failing_command},
                    source="openai_tool_call",
                )
            ],
            [
                ToolInvocation(
                    id="call_list",
                    name="list_dir",
                    args={"path": "."},
                    source="openai_tool_call",
                )
            ],
            {
                "type": "final_response",
                "status": "completed",
                "summary": "verification passed",
            },
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="fix add",
            provider=provider,
            verification_commands=[command, later_failing_command],
            step_budget=7,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.summary == "Agent loop ended with failed observations"
    assert result.steps[0].observation.status == "succeeded"
    assert result.steps[1].observation.status == "succeeded"
    assert result.steps[2].observation.status == "failed"
    assert result.steps[3].observation.status == "succeeded"


def test_agent_loop_does_not_complete_when_post_patch_failure_follows_verification(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    target = repo_path / "calculator.py"
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "calculator.py"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add calculator"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    command = (
        f'{PYTHON} -c "import calculator; raise SystemExit(0 if calculator.add(2, 3) == 5 else 1)"'
    )
    later_failing_command = f"{PYTHON} -c 'raise SystemExit(1)'"
    patch = """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="fix add",
            use_worktree=True,
            verification_commands=[command, later_failing_command],
            actions=[
                {
                    "type": "patch_proposal",
                    "reason": "add should add operands",
                    "files_to_modify": ["calculator.py"],
                    "patch": patch,
                },
                {
                    "type": "tool_call",
                    "action": "run_command",
                    "reason": "verify patch",
                    "args": {"command": command},
                },
                {
                    "type": "tool_call",
                    "action": "run_command",
                    "reason": "later verification failed",
                    "args": {"command": later_failing_command},
                },
                {
                    "type": "tool_call",
                    "action": "list_dir",
                    "reason": "inspect current directory",
                    "args": {"path": "."},
                },
                {
                    "type": "final_response",
                    "status": "completed",
                    "summary": "verification passed",
                },
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.summary == "Agent loop ended with failed observations"
    assert result.steps[1].observation.status == "succeeded"
    assert result.steps[2].observation.status == "failed"
    assert result.steps[3].observation.status == "succeeded"
