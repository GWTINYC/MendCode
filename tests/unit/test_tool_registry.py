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
