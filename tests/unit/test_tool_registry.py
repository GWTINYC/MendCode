import subprocess
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

import app.tools as tool_exports
import app.tools.structured as structured
from app.config.settings import Settings
from app.schemas.agent_action import Observation
from app.tools.registry import default_tool_registry, tool_result_to_observation
from app.tools.schemas import ToolResult
from app.tools.structured import (
    ToolExecutionContext,
    ToolInvocation,
    ToolPool,
    ToolRegistry,
    ToolRisk,
    ToolSpec,
)


class ExampleArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    max_chars: int = Field(default=2000, ge=0)


def execute_example(args: ExampleArgs, context: ToolExecutionContext) -> Observation:
    return Observation(
        status="succeeded",
        summary=f"Read {args.path}",
        payload={"workspace": str(context.workspace_path), "max_chars": args.max_chars},
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


def test_tool_spec_validates_args_and_executes(tmp_path: Path) -> None:
    spec = ToolSpec(
        name="example",
        description="Read an example path.",
        args_model=ExampleArgs,
        risk_level=ToolRisk.READ_ONLY,
        executor=execute_example,
    )
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = spec.execute({"path": "README.md"}, context)

    assert observation.status == "succeeded"
    assert observation.payload == {"workspace": str(tmp_path), "max_chars": 2000}


def test_tool_spec_rejects_invalid_args(tmp_path: Path) -> None:
    spec = ToolSpec(
        name="example",
        description="Read an example path.",
        args_model=ExampleArgs,
        risk_level=ToolRisk.READ_ONLY,
        executor=execute_example,
    )
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = spec.execute({"path": "README.md", "max_chars": -1}, context)

    assert observation.status == "rejected"
    assert observation.summary == "Invalid tool arguments"
    assert "greater than or equal to 0" in str(observation.error_message)


def test_tool_spec_generates_openai_tool_schema() -> None:
    spec = ToolSpec(
        name="example",
        description="Read an example path.",
        args_model=ExampleArgs,
        risk_level=ToolRisk.READ_ONLY,
        executor=execute_example,
    )

    assert spec.to_openai_tool()["function"]["name"] == "example"
    assert spec.to_openai_tool()["function"]["parameters"]["type"] == "object"
    assert "path" in spec.to_openai_tool()["function"]["parameters"]["properties"]


def test_registry_rejects_duplicate_tool_names() -> None:
    registry = ToolRegistry()
    spec = ToolSpec(
        name="example",
        description="Read an example path.",
        args_model=ExampleArgs,
        risk_level=ToolRisk.READ_ONLY,
        executor=execute_example,
    )

    registry.register(spec)

    with pytest.raises(ValueError, match="duplicate tool name: example"):
        registry.register(spec)


def test_tool_invocation_requires_non_empty_name() -> None:
    with pytest.raises(ValidationError):
        ToolInvocation(id=None, name="", args={}, source="json_action")


def test_tool_names_accept_letters_digits_underscores_and_dashes() -> None:
    spec = ToolSpec(
        name="read_file-1",
        description="Read an example path.",
        args_model=ExampleArgs,
        risk_level=ToolRisk.READ_ONLY,
        executor=execute_example,
    )
    invocation = ToolInvocation(
        id=None,
        name="read_file-1",
        args={},
        source="json_action",
    )

    assert spec.name == "read_file-1"
    assert invocation.name == "read_file-1"


def test_tool_spec_rejects_names_with_spaces() -> None:
    with pytest.raises(ValidationError, match="tool name"):
        ToolSpec(
            name="read file",
            description="Read an example path.",
            args_model=ExampleArgs,
            risk_level=ToolRisk.READ_ONLY,
            executor=execute_example,
        )


def test_tool_invocation_rejects_names_longer_than_64_characters() -> None:
    with pytest.raises(ValidationError, match="tool name"):
        ToolInvocation(id=None, name="a" * 65, args={}, source="json_action")


def test_package_exports_structured_tool_aliases() -> None:
    assert "ToolExecutor" in tool_exports.__all__
    assert "ToolInvocationSource" in tool_exports.__all__
    assert tool_exports.ToolExecutor is structured.ToolExecutor
    assert tool_exports.ToolInvocationSource is structured.ToolInvocationSource


def test_default_registry_contains_read_only_tools() -> None:
    registry = default_tool_registry()

    for tool_name in [
        "detect_project",
        "glob_file_search",
        "list_dir",
        "read_file",
        "repo_status",
        "rg",
        "search_code",
        "show_diff",
    ]:
        assert tool_name in registry.names()


def test_tool_result_to_observation_maps_passed_result(tmp_path: Path) -> None:
    result = ToolResult(
        tool_name="read_file",
        status="passed",
        summary="Read README.md",
        payload={"relative_path": "README.md"},
        error_message=None,
        workspace_path=str(tmp_path),
    )

    observation = tool_result_to_observation(result)

    assert observation.status == "succeeded"
    assert observation.summary == "Read README.md"
    assert observation.payload["tool_name"] == "read_file"
    assert observation.payload["status"] == "succeeded"
    assert observation.payload["summary"] == "Read README.md"
    assert observation.payload["is_error"] is False
    assert observation.payload["payload"] == {"relative_path": "README.md"}
    assert observation.payload["relative_path"] == "README.md"
    assert observation.error_message is None


def test_default_registry_generates_openai_schemas() -> None:
    registry = default_tool_registry()

    tools = registry.openai_tools()

    names = [tool["function"]["name"] for tool in tools]
    assert "read_file" in names
    read_file_schema = next(tool for tool in tools if tool["function"]["name"] == "read_file")
    assert "path" in read_file_schema["function"]["parameters"]["properties"]
    assert "tail_lines" in read_file_schema["function"]["parameters"]["properties"]


def test_registry_filters_openai_schemas_to_allowed_tools() -> None:
    registry = default_tool_registry()

    tools = registry.openai_tools(allowed_tools={"read", "glob", "grep", "status", "diff"})

    assert [tool["function"]["name"] for tool in tools] == [
        "glob_file_search",
        "read_file",
        "repo_status",
        "rg",
        "search_code",
        "show_diff",
    ]


def test_registry_builds_permission_scoped_tool_pool() -> None:
    registry = default_tool_registry()

    pool = registry.tool_pool(permission_mode="read-only")

    assert isinstance(pool, ToolPool)
    assert "read_file" in pool.names()
    assert "list_dir" in pool.names()
    assert "tool_search" in pool.names()
    assert "write_file" not in pool.names()
    assert "apply_patch" not in pool.names()
    assert "run_shell_command" not in pool.names()
    manifest = pool.manifest()
    assert manifest["permission_mode"] == "read-only"
    assert "read_file" in manifest["tools"]
    assert "write_file" in manifest["excluded_tools"]


def test_registry_expands_tool_groups() -> None:
    registry = default_tool_registry()
    names = set(registry.names(allowed_tools={"fs_read", "introspection"}))
    assert {"read_file", "list_dir", "glob_file_search", "rg", "search_code"} <= names
    assert {"tool_search", "session_status"} <= names
    assert "write_file" not in names


def test_registry_expands_tool_profiles_then_applies_permission() -> None:
    registry = default_tool_registry()
    pool = registry.tool_pool(permission_mode="read-only", allowed_tools={"coding_agent"})
    names = set(pool.names())
    assert "read_file" in names
    assert "session_status" in names
    assert "lsp" in names
    assert "write_file" not in names
    assert "run_shell_command" not in names


def test_registry_rejects_unknown_tool_group() -> None:
    registry = default_tool_registry()
    with pytest.raises(KeyError, match="unknown allowed tool: unknown_group"):
        registry.names(allowed_tools={"unknown_group"})


def test_simple_tool_pool_keeps_core_inspection_tools_only() -> None:
    registry = default_tool_registry()

    pool = registry.tool_pool(
        permission_mode="danger-full-access",
        simple_mode=True,
        allowed_tools={"read", "glob", "grep", "shell", "write", "tools"},
    )

    assert pool.names() == [
        "glob_file_search",
        "read_file",
        "rg",
        "search_code",
        "tool_search",
    ]


def test_tool_search_respects_context_available_tool_pool(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
        available_tools={"read_file", "tool_search"},
    )

    observation = registry.get("tool_search").execute(
        {"query": "write", "max_results": 10},
        context,
    )

    assert observation.status == "succeeded"
    assert observation.payload["matches"] == []
    assert observation.payload["total_matches"] == 0


def test_session_status_reports_effective_context(tmp_path: Path) -> None:
    registry = default_tool_registry()
    recent_steps = [{"index": index} for index in range(12)]
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=["pytest -q"],
        available_tools={"read_file", "session_status"},
        permission_mode="read-only",
        allowed_tools={"read_file", "session_status", "write_file"},
        denied_tools={"write_file"},
        run_id="run-123",
        trace_path=str(tmp_path / "trace.json"),
        recent_steps=recent_steps,
        pending_confirmation={"tool": "run_shell_command"},
    )

    observation = registry.get("session_status").execute({}, context)

    assert observation.status == "succeeded"
    assert observation.payload["permission_mode"] == "read-only"
    assert observation.payload["verification_commands"] == ["pytest -q"]
    assert observation.payload["pending_confirmation"] == {"tool": "run_shell_command"}
    assert observation.payload["trace_path"] == str(tmp_path / "trace.json")
    assert observation.payload["run_id"] == "run-123"
    assert observation.payload["available_tools"] == ["read_file", "session_status"]
    assert observation.payload["allowed_tools"] == [
        "read_file",
        "session_status",
        "write_file",
    ]
    assert observation.payload["denied_tools"] == ["write_file"]
    assert observation.payload["recent_steps"] == recent_steps[-10:]


def test_registry_rejects_unknown_allowed_tool_name() -> None:
    registry = default_tool_registry()

    try:
        registry.openai_tools(allowed_tools={"delete_repo"})
    except KeyError as exc:
        assert "unknown allowed tool" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected unknown allowed tool to be rejected")


def test_registry_executes_read_file_tool(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("read_file").execute({"path": "README.md"}, context)

    assert observation.status == "succeeded"
    assert observation.payload["tool_name"] == "read_file"
    assert observation.payload["status"] == "succeeded"
    assert observation.payload["payload"]["relative_path"] == "README.md"
    assert observation.payload["payload"]["content"] == "hello\n"
    assert observation.payload["relative_path"] == "README.md"
    assert observation.payload["content"] == "hello\n"


def test_registry_executes_read_file_tail_lines(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("first\nmiddle\nlast\n", encoding="utf-8")
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("read_file").execute(
        {"path": "README.md", "tail_lines": 1},
        context,
    )

    assert observation.status == "succeeded"
    assert observation.payload["payload"]["start_line"] == 3
    assert observation.payload["payload"]["end_line"] == 3
    assert observation.payload["payload"]["content"] == "last\n"


def test_registry_executes_search_code_alias(tmp_path: Path) -> None:
    (tmp_path / "src.py").write_text("alpha\nbeta alpha\n", encoding="utf-8")
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("search_code").execute(
        {"query": "alpha", "glob": "*.py", "max_results": 1},
        context,
    )

    assert observation.status == "succeeded"
    assert observation.payload["tool_name"] == "search_code"
    assert observation.payload["payload"]["total_matches"] == 2
    assert observation.payload["total_matches"] == 2
    assert observation.payload["matches"] == [
        {"relative_path": "src.py", "line_number": 1, "line_text": "alpha"}
    ]


def test_registry_rejects_bad_read_file_args(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("read_file").execute(
        {"path": "README.md", "max_chars": -1},
        context,
    )

    assert observation.status == "rejected"
    assert observation.summary == "Invalid tool arguments"


def init_repo(path: Path) -> Path:
    repo = path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    return repo


def test_default_registry_contains_command_tools() -> None:
    registry = default_tool_registry()

    assert "git" in registry.names()
    assert "apply_patch" in registry.names()
    assert "run_shell_command" in registry.names()
    assert "run_command" in registry.names()


def test_repo_status_runs_through_registry(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "README.md").write_text("demo\n", encoding="utf-8")
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=repo,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("repo_status").execute({}, context)

    assert observation.status == "succeeded"
    assert observation.payload["tool_name"] == "repo_status"
    assert observation.payload["payload"]["dirty"] is True
    assert observation.payload["dirty"] is True
    assert observation.payload["dirty_count"] == 1


def test_detect_project_runs_through_registry(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("detect_project").execute({}, context)

    assert observation.status == "succeeded"
    assert observation.payload["tool_name"] == "detect_project"
    assert observation.payload["payload"]["languages"] == ["python"]
    assert observation.payload["languages"] == ["python"]


def test_show_diff_runs_through_registry(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "README.md").write_text("demo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo, check=True)
    (repo / "README.md").write_text("demo\nchanged\n", encoding="utf-8")
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=repo,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("show_diff").execute({}, context)

    assert observation.status == "succeeded"
    assert observation.payload["tool_name"] == "show_diff"
    assert "README.md" in observation.payload["payload"]["diff_stat"]
    assert "README.md" in observation.payload["diff_stat"]


def test_git_status_uses_structured_operation(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "README.md").write_text("demo\n", encoding="utf-8")
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=repo,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("git").execute({"operation": "status"}, context)

    assert observation.status == "succeeded"
    assert observation.payload["tool_name"] == "git"
    assert observation.payload["payload"]["command"] == "git status --short"
    assert observation.payload["command"] == "git status --short"
    assert "README.md" in observation.payload["stdout_excerpt"]


def test_git_log_uses_structured_operation(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "README.md").write_text("demo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo, check=True)
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=repo,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("git").execute({"operation": "log", "limit": 1}, context)

    assert observation.status == "succeeded"
    assert observation.payload["tool_name"] == "git"
    assert observation.payload["payload"]["command"] == "git log --oneline -n 1"
    assert observation.payload["command"] == "git log --oneline -n 1"
    assert "initial commit" in observation.payload["stdout_excerpt"]


def test_git_rejects_unknown_operation_before_shell(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("git").execute({"operation": "reset"}, context)

    assert observation.status == "rejected"
    assert observation.summary == "Invalid tool arguments"


def test_run_command_keeps_verification_allowlist(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("run_command").execute(
        {"command": "python -c 'print(123)'"},
        context,
    )

    assert observation.status == "rejected"
    assert observation.payload["tool_name"] == "run_command"
    assert observation.payload["is_error"] is True
    assert "declared" in str(observation.error_message)


def test_apply_patch_rejects_repo_escaping_path(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )
    patch = "\n".join(
        [
            "diff --git a/../outside.txt b/../outside.txt",
            "--- a/../outside.txt",
            "+++ b/../outside.txt",
            "@@ -0,0 +1 @@",
            "+bad",
            "",
        ]
    )

    observation = registry.get("apply_patch").execute({"patch": patch}, context)

    assert observation.status == "rejected"
    assert observation.payload["tool_name"] == "apply_patch"
    assert observation.payload["is_error"] is True
    assert "patch path escapes workspace root" in str(observation.error_message)


def test_write_file_creates_workspace_file(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("write_file").execute(
        {"path": "notes/todo.txt", "content": "alpha\n"},
        context,
    )

    assert observation.status == "succeeded"
    assert (tmp_path / "notes" / "todo.txt").read_text(encoding="utf-8") == "alpha\n"
    assert observation.payload["tool_name"] == "write_file"
    assert observation.payload["relative_path"] == "notes/todo.txt"
    assert observation.payload["bytes_written"] == len("alpha\n".encode())


def test_write_file_rejects_repo_escaping_path(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("write_file").execute(
        {"path": "../outside.txt", "content": "bad"},
        context,
    )

    assert observation.status == "rejected"
    assert "path escapes workspace root" in str(observation.error_message)
    assert not (tmp_path.parent / "outside.txt").exists()


def test_write_file_rejects_content_over_size_limit(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("write_file").execute(
        {"path": "large.txt", "content": "x" * (1024 * 1024 + 1)},
        context,
    )

    assert observation.status == "rejected"
    assert "content exceeds write_file size limit" in str(observation.error_message)
    assert not (tmp_path / "large.txt").exists()


def test_edit_file_replaces_exact_text(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    target.write_text("alpha\nbeta\n", encoding="utf-8")
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("edit_file").execute(
        {
            "path": "README.md",
            "old_string": "beta\n",
            "new_string": "gamma\n",
        },
        context,
    )

    assert observation.status == "succeeded"
    assert target.read_text(encoding="utf-8") == "alpha\ngamma\n"
    assert observation.payload["relative_path"] == "README.md"
    assert observation.payload["replacements"] == 1


def test_edit_file_rejects_missing_old_text(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    target.write_text("alpha\n", encoding="utf-8")
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("edit_file").execute(
        {
            "path": "README.md",
            "old_string": "missing",
            "new_string": "replacement",
        },
        context,
    )

    assert observation.status == "failed"
    assert "old_string not found" in str(observation.error_message)
    assert target.read_text(encoding="utf-8") == "alpha\n"


def test_edit_file_rejects_binary_content(tmp_path: Path) -> None:
    target = tmp_path / "image.bin"
    target.write_bytes(b"\x00old\x00")
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("edit_file").execute(
        {
            "path": "image.bin",
            "old_string": "old",
            "new_string": "new",
        },
        context,
    )

    assert observation.status == "rejected"
    assert "binary file cannot be edited as text" in str(observation.error_message)
    assert target.read_bytes() == b"\x00old\x00"


def test_todo_write_returns_structured_todos(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("todo_write").execute(
        {
            "todos": [
                {
                    "content": "Add write tools",
                    "status": "in_progress",
                },
                {
                    "content": "Run tests",
                    "status": "pending",
                },
            ]
        },
        context,
    )

    assert observation.status == "succeeded"
    assert observation.payload["tool_name"] == "todo_write"
    assert observation.payload["todo_count"] == 2
    assert observation.payload["todos"][0]["content"] == "Add write tools"


def test_tool_search_finds_tools_by_name_and_description(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = registry.get("tool_search").execute(
        {"query": "write", "max_results": 5},
        context,
    )

    assert observation.status == "succeeded"
    names = [match["name"] for match in observation.payload["matches"]]
    assert "write_file" in names
    assert "edit_file" in names
    assert observation.payload["total_matches"] >= 2
