from app.agent.loop import AgentStep, _HandledAction
from app.runtime.final_response_gate import apply_final_response_gate
from app.schemas.agent_action import (
    AssistantMessageAction,
    FinalResponseAction,
    Observation,
    ToolCallAction,
)


def tool_step(
    *,
    index: int,
    action: str,
    status: str = "succeeded",
    summary: str = "ok",
) -> AgentStep:
    error_message = "error" if status in {"failed", "rejected"} else None
    return AgentStep(
        index=index,
        action=ToolCallAction(
            type="tool_call",
            action=action,
            reason="test",
            args={},
        ),
        observation=Observation(
            status=status,
            summary=summary,
            payload={},
            error_message=error_message,
        ),
    )


def handled_final(
    *,
    index: int,
    status: str = "completed",
    summary: str = "done",
) -> _HandledAction:
    action = FinalResponseAction(
        type="final_response",
        status=status,
        summary=summary,
    )
    return _HandledAction(
        stop=True,
        status=status,
        summary=summary,
        step=AgentStep(
            index=index,
            action=action,
            observation=Observation(
                status="succeeded",
                summary="Recorded agent action",
                payload={},
            ),
        ),
    )


def assistant_step(*, index: int, message: str = "thinking") -> AgentStep:
    return AgentStep(
        index=index,
        action=AssistantMessageAction(type="assistant_message", message=message),
        observation=Observation(
            status="succeeded",
            summary="Recorded assistant message",
            payload={},
        ),
    )


def final_response_step(*, index: int, summary: str = "done") -> AgentStep:
    return AgentStep(
        index=index,
        action=FinalResponseAction(
            type="final_response",
            status="completed",
            summary=summary,
        ),
        observation=Observation(
            status="succeeded",
            summary="Recorded final response",
            payload={},
        ),
    )


def test_gate_blocks_completed_final_after_failed_observation() -> None:
    status, summary = apply_final_response_gate(
        steps=[
            tool_step(index=1, action="read_file", status="rejected", summary="missing"),
        ],
        handled=handled_final(index=2),
    )

    assert status == "failed"
    assert summary == "Agent loop ended with failed observations"


def test_gate_blocks_local_fact_final_without_successful_tool_observation() -> None:
    status, summary = apply_final_response_gate(
        steps=[],
        handled=handled_final(index=1, summary="README.md 的最后一句是 Task 4。"),
    )

    assert status == "failed"
    assert "requires tool evidence" in summary


def test_gate_blocks_current_project_fact_without_successful_tool_observation() -> None:
    status, summary = apply_final_response_gate(
        steps=[],
        handled=handled_final(index=1, summary="当前项目使用 Pydantic。"),
    )

    assert status == "failed"
    assert "requires tool evidence" in summary


def test_gate_allows_local_fact_final_after_successful_tool_observation() -> None:
    status, summary = apply_final_response_gate(
        steps=[
            tool_step(index=1, action="read_file", summary="Read README.md"),
        ],
        handled=handled_final(index=2, summary="README.md 的最后一句是 Task 4。"),
    )

    assert status == "completed"
    assert summary == "README.md 的最后一句是 Task 4。"


def test_gate_allows_general_final_without_tool_observation() -> None:
    status, summary = apply_final_response_gate(
        steps=[],
        handled=handled_final(index=1, summary="Python 是一种通用编程语言。"),
    )

    assert status == "completed"
    assert summary == "Python 是一种通用编程语言。"


def test_gate_allows_general_git_explanation_without_tool_observation() -> None:
    status, summary = apply_final_response_gate(
        steps=[],
        handled=handled_final(index=1, summary="Git 是一个分布式版本控制系统。"),
    )

    assert status == "completed"
    assert summary == "Git 是一个分布式版本控制系统。"


def test_gate_allows_general_repository_explanation_without_tool_observation() -> None:
    status, summary = apply_final_response_gate(
        steps=[],
        handled=handled_final(index=1, summary="仓库是 Git 用来保存项目历史的地方。"),
    )

    assert status == "completed"
    assert summary == "仓库是 Git 用来保存项目历史的地方。"


def test_gate_allows_general_file_directory_path_explanations_without_tool_observation() -> None:
    for answer in [
        "文件是保存数据的一种基本单位。",
        "目录通常用于组织多个文件。",
        "路径用于描述文件或目录的位置。",
    ]:
        status, summary = apply_final_response_gate(
            steps=[],
            handled=handled_final(index=1, summary=answer),
        )

        assert status == "completed"
        assert summary == answer


def test_gate_allows_general_extension_readme_and_architecture_examples() -> None:
    for answer in [
        "Python files use .py extensions.",
        "Markdown files often use .md extensions.",
        "README files usually introduce a project.",
        "Client/server architecture separates responsibilities.",
    ]:
        status, summary = apply_final_response_gate(
            steps=[],
            handled=handled_final(index=1, summary=answer),
        )

        assert status == "completed"
        assert summary == answer


def test_gate_does_not_count_non_evidence_tools_for_local_fact() -> None:
    for action in [
        "write_file",
        "edit_file",
        "todo_write",
        "tool_search",
    ]:
        status, summary = apply_final_response_gate(
            steps=[tool_step(index=1, action=action)],
            handled=handled_final(index=2, summary="当前项目使用 Pydantic。"),
        )

        assert status == "failed"
        assert "requires tool evidence" in summary


def test_gate_does_not_allow_patch_tools_as_only_evidence_for_local_fact() -> None:
    for action in [
        "apply_patch",
        "apply_patch_to_worktree",
    ]:
        status, _summary = apply_final_response_gate(
            steps=[tool_step(index=1, action=action)],
            handled=handled_final(index=2, summary="当前项目使用 Pydantic。"),
        )

        assert status == "failed"


def test_gate_does_not_count_successful_non_tool_actions_for_local_fact() -> None:
    for step in [
        assistant_step(index=1),
        final_response_step(index=1),
    ]:
        status, summary = apply_final_response_gate(
            steps=[step],
            handled=handled_final(index=2, summary="当前项目使用 Pydantic。"),
        )

        assert status == "failed"
        assert "requires tool evidence" in summary


def test_gate_allows_local_fact_final_after_successful_information_bearing_observations() -> None:
    for action in [
        "repo_status",
        "detect_project",
        "show_diff",
        "read_file",
        "list_dir",
        "glob_file_search",
        "rg",
        "search_code",
        "git",
        "run_shell_command",
        "run_command",
    ]:
        status, summary = apply_final_response_gate(
            steps=[tool_step(index=1, action=action)],
            handled=handled_final(index=2, summary="当前项目使用 Pydantic。"),
        )

        assert status == "completed"
        assert summary == "当前项目使用 Pydantic。"


def test_gate_requires_successful_verification_after_patch() -> None:
    status, summary = apply_final_response_gate(
        steps=[
            tool_step(index=1, action="apply_patch"),
        ],
        handled=handled_final(index=2),
    )

    assert status == "failed"
    assert summary == "Agent loop ended with failed observations"


def test_gate_allows_completed_final_after_patch_and_successful_verification() -> None:
    status, summary = apply_final_response_gate(
        steps=[
            tool_step(index=1, action="apply_patch"),
            tool_step(index=2, action="run_command"),
        ],
        handled=handled_final(index=3),
    )

    assert status == "completed"
    assert summary == "done"
