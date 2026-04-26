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

    assert registry.names() == ["glob_file_search", "list_dir", "read_file", "rg"]


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
    assert observation.payload == {"relative_path": "README.md"}
    assert observation.error_message is None


def test_default_registry_generates_openai_schemas() -> None:
    registry = default_tool_registry()

    tools = registry.openai_tools()

    names = [tool["function"]["name"] for tool in tools]
    assert "read_file" in names
    read_file_schema = next(tool for tool in tools if tool["function"]["name"] == "read_file")
    assert "path" in read_file_schema["function"]["parameters"]["properties"]


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
    assert observation.payload["relative_path"] == "README.md"
    assert observation.payload["content"] == "hello\n"


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
