import pytest
from pydantic import ValidationError

from app.tools import ToolResult


def test_tool_result_serializes_expected_fields():
    result = ToolResult(
        tool_name="read_file",
        status="passed",
        summary="Read file successfully",
        payload={"lines": 12},
        error_message=None,
        workspace_path="/tmp/worktree",
    )

    assert result.model_dump() == {
        "tool_name": "read_file",
        "status": "passed",
        "summary": "Read file successfully",
        "payload": {"lines": 12},
        "error_message": None,
        "workspace_path": "/tmp/worktree",
    }


def test_tool_result_rejects_invalid_status():
    with pytest.raises(ValidationError):
        ToolResult(
            tool_name="read_file",
            status="unknown",
            summary="Read file successfully",
            workspace_path="/tmp/worktree",
        )


def test_tool_result_rejects_passed_status_with_error_message():
    with pytest.raises(ValidationError):
        ToolResult(
            tool_name="read_file",
            status="passed",
            summary="Read file successfully",
            error_message="unexpected failure",
            workspace_path="/tmp/worktree",
        )


def test_tool_result_rejects_failed_status_without_error_message():
    with pytest.raises(ValidationError):
        ToolResult(
            tool_name="read_file",
            status="failed",
            summary="Read file successfully",
            workspace_path="/tmp/worktree",
        )


def test_tool_result_rejects_rejected_status_without_error_message():
    with pytest.raises(ValidationError):
        ToolResult(
            tool_name="read_file",
            status="rejected",
            summary="Read file successfully",
            workspace_path="/tmp/worktree",
        )


def test_tool_result_rejects_extra_fields():
    with pytest.raises(ValidationError):
        ToolResult(
            tool_name="read_file",
            status="passed",
            summary="Read file successfully",
            workspace_path="/tmp/worktree",
            unexpected="value",
        )
