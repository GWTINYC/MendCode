from pathlib import Path

from app.agent.loop import AgentLoopInput, AgentLoopResult, AgentStep
from app.config.settings import Settings
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.turn import (
    RuntimeTaskState,
    RuntimeToolStep,
    RuntimeTurnInput,
    RuntimeTurnResult,
)
from app.schemas.agent_action import FinalResponseAction, Observation


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


def final_step(index: int = 1) -> AgentStep:
    return AgentStep(
        index=index,
        action=FinalResponseAction(
            type="final_response",
            status="completed",
            summary="done",
        ),
        observation=Observation(
            status="succeeded",
            summary="Recorded agent action",
            payload={},
        ),
    )


def test_runtime_turn_models_capture_tool_step_contract() -> None:
    step = final_step()
    runtime_step = RuntimeToolStep(
        index=step.index,
        action=step.action,
        observation=step.observation,
    )
    result = RuntimeTurnResult(
        run_id="agent-test",
        status="completed",
        summary="done",
        trace_path=None,
        workspace_path=None,
        steps=[runtime_step],
        task_state=RuntimeTaskState(goal="inspect", phase="started"),
    )

    assert RuntimeTurnInput(problem_statement="inspect").problem_statement == "inspect"
    assert result.status == "completed"
    assert result.steps[0].action.type == "final_response"
    assert result.task_state is not None
    assert result.task_state.goal == "inspect"
    assert result.task_state.phase == "started"
    assert result.task_state.verified is False
    assert result.task_state.completed_steps == []


def test_runtime_turn_result_can_carry_default_task_state() -> None:
    task_state = RuntimeTaskState(goal="inspect runtime")

    result = RuntimeTurnResult(
        run_id="agent-test",
        status="completed",
        summary="done",
        trace_path=None,
        task_state=task_state,
    )

    assert result.task_state is not None
    assert result.task_state.goal == "inspect runtime"
    assert result.task_state.phase == "started"
    assert result.task_state.blocked_reason is None
    assert result.task_state.verified is False


def test_agent_runtime_run_turn_delegates_to_runner(tmp_path: Path) -> None:
    seen: list[AgentLoopInput] = []

    def runner(loop_input: AgentLoopInput, settings: Settings) -> AgentLoopResult:
        seen.append(loop_input)
        return AgentLoopResult(
            run_id="agent-runtime-test",
            status="completed",
            summary=f"runtime handled {loop_input.problem_statement}",
            trace_path=None,
            workspace_path=str(loop_input.repo_path),
            steps=[final_step()],
        )

    runtime = AgentRuntime(settings=settings_for(tmp_path), runner=runner)

    result = runtime.run_turn(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="inspect runtime",
            actions=[],
        )
    )

    assert result.status == "completed"
    assert result.summary == "runtime handled inspect runtime"
    assert seen[0].problem_statement == "inspect runtime"


def test_agent_runtime_default_runner_uses_runtime_loop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.runtime import agent_loop as runtime_agent_loop

    seen: list[AgentLoopInput] = []

    def fake_run_agent_loop_turn(
        loop_input: AgentLoopInput,
        settings: Settings,
    ) -> AgentLoopResult:
        seen.append(loop_input)
        return AgentLoopResult(
            run_id="agent-runtime-default",
            status="completed",
            summary="runtime loop handled turn",
            trace_path=None,
            workspace_path=str(loop_input.repo_path),
            steps=[final_step()],
        )

    monkeypatch.setattr(
        runtime_agent_loop,
        "run_agent_loop_turn",
        fake_run_agent_loop_turn,
    )

    result = AgentRuntime(settings=settings_for(tmp_path)).run_turn(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="inspect default runner",
            actions=[],
        )
    )

    assert result.summary == "runtime loop handled turn"
    assert seen[0].problem_statement == "inspect default runner"
