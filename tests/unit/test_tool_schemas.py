import pytest
from pydantic import ValidationError

from app.tools import ToolResult, ToolStatus


def test_tool_status_accepts_expected_literals():
    assert ToolStatus.__args__ == ("passed", "failed", "rejected")


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


def test_tool_result_rejects_extra_fields():
    with pytest.raises(ValidationError):
        ToolResult(
            tool_name="read_file",
            status="passed",
            summary="Read file successfully",
            workspace_path="/tmp/worktree",
            unexpected="value",
        )
