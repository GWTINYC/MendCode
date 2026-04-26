from pathlib import Path

import pytest

from app.tools.observations import (
    observation_from_tool_result,
    tool_observation,
)
from app.tools.schemas import ToolResult


def test_tool_observation_adds_envelope_and_preserves_payload_keys() -> None:
    observation = tool_observation(
        tool_name="list_dir",
        status="succeeded",
        summary="Listed .",
        payload={
            "relative_path": ".",
            "entries": [{"relative_path": "README.md"}],
            "truncated": False,
        },
    )

    assert observation.status == "succeeded"
    assert observation.payload["tool_name"] == "list_dir"
    assert observation.payload["status"] == "succeeded"
    assert observation.payload["summary"] == "Listed ."
    assert observation.payload["is_error"] is False
    assert observation.payload["truncated"] is False
    assert observation.payload["next_offset"] is None
    assert observation.payload["stdout_excerpt"] == ""
    assert observation.payload["stderr_excerpt"] == ""
    assert observation.payload["duration_ms"] is None
    assert observation.payload["payload"]["entries"] == [{"relative_path": "README.md"}]
    assert observation.payload["entries"] == [{"relative_path": "README.md"}]
    assert observation.error_message is None


def test_tool_observation_requires_error_message_for_failed_status() -> None:
    observation = tool_observation(
        tool_name="read_file",
        status="rejected",
        summary="Unable to read missing.txt",
        payload={"relative_path": "missing.txt"},
        error_message="path does not exist",
    )

    assert observation.status == "rejected"
    assert observation.payload["is_error"] is True
    assert observation.payload["payload"]["relative_path"] == "missing.txt"
    assert observation.error_message == "path does not exist"


def test_tool_observation_preserves_reserved_key_collisions_in_nested_payload() -> None:
    observation = tool_observation(
        tool_name="read_file",
        status="succeeded",
        summary="Read file",
        payload={
            "status": "passed",
            "summary": "raw",
            "tool_name": "raw_tool",
            "truncated": "raw",
            "content": "demo",
        },
    )

    assert observation.payload["tool_name"] == "read_file"
    assert observation.payload["status"] == "succeeded"
    assert observation.payload["summary"] == "Read file"
    assert observation.payload["truncated"] is False
    assert observation.payload["payload"]["tool_name"] == "raw_tool"
    assert observation.payload["payload"]["status"] == "passed"
    assert observation.payload["payload"]["summary"] == "raw"
    assert observation.payload["payload"]["truncated"] == "raw"
    assert observation.payload["content"] == "demo"


def test_tool_observation_rejects_failed_status_without_error_message() -> None:
    with pytest.raises(ValueError):
        tool_observation(
            tool_name="read_file",
            status="failed",
            summary="Failed to read file",
        )


def test_observation_from_tool_result_maps_passed_to_succeeded(tmp_path: Path) -> None:
    result = ToolResult(
        tool_name="read_file",
        status="passed",
        summary="Read README.md",
        payload={"relative_path": "README.md", "content": "demo\n", "truncated": False},
        error_message=None,
        workspace_path=str(tmp_path),
    )

    observation = observation_from_tool_result(result)

    assert observation.status == "succeeded"
    assert observation.payload["tool_name"] == "read_file"
    assert observation.payload["status"] == "succeeded"
    assert observation.payload["payload"]["content"] == "demo\n"
    assert observation.payload["content"] == "demo\n"
