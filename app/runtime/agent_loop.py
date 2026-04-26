import subprocess
from uuid import uuid4

from app.agent.loop import (
    AgentLoopInput,
    AgentLoopResult,
    AgentLoopStatus,
    AgentStep,
    FinalResponseAction,
    _failed_observation,
    _handle_action_payload,
    _handle_tool_invocation,
    _HandledAction,
    _record_step,
)
from app.agent.provider import AgentObservationRecord, AgentProviderStepInput
from app.config.settings import Settings
from app.schemas.agent_action import build_invalid_action_observation
from app.schemas.trace import TraceEvent
from app.tracing.recorder import TraceRecorder
from app.workspace.worktree import prepare_worktree


def run_agent_loop_turn(loop_input: AgentLoopInput, settings: Settings) -> AgentLoopResult:
    recorder = TraceRecorder(settings.traces_dir)
    run_id = f"agent-{uuid4().hex[:12]}"
    workspace_path = loop_input.repo_path
    if loop_input.use_worktree:
        try:
            workspace_path = prepare_worktree(
                repo_path=loop_input.repo_path,
                workspace_root=settings.workspace_root,
                run_id=run_id,
                base_ref=loop_input.base_ref,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = str(exc)
            if isinstance(exc, subprocess.CalledProcessError):
                detail = exc.stderr or exc.stdout or str(exc)
            trace_path = recorder.record(
                TraceEvent(
                    run_id=run_id,
                    event_type="agent.run.completed",
                    message="Agent loop failed before start",
                    payload={"status": "failed", "summary": detail.strip()},
                )
            )
            return AgentLoopResult(
                run_id=run_id,
                status="failed",
                summary=f"Workspace setup failed: {detail.strip()}",
                trace_path=str(trace_path),
                workspace_path=None,
                steps=[],
            )

    trace_path = recorder.record(
        TraceEvent(
            run_id=run_id,
            event_type="agent.run.started",
            message="Started agent loop",
            payload={
                "problem_statement": loop_input.problem_statement,
                "repo_path": str(loop_input.repo_path),
                "workspace_path": str(workspace_path),
                "permission_mode": loop_input.permission_mode,
                "step_budget": loop_input.step_budget,
            },
        )
    )

    steps: list[AgentStep] = []
    status = "failed"
    summary = "Agent loop ended without final response"
    observation_history: list[AgentObservationRecord] = []

    def record_handled_action(handled, tool_invocation=None) -> None:
        nonlocal trace_path
        steps.append(handled.step)
        trace_path = _record_step(
            recorder=recorder,
            run_id=run_id,
            index=handled.step.index,
            action=handled.step.action,
            observation=handled.step.observation,
        )
        observation_history.append(
            AgentObservationRecord(
                action=handled.step.action,
                tool_invocation=tool_invocation,
                observation=handled.step.observation,
            )
        )

    def apply_final_response_gate(handled) -> tuple[AgentLoopStatus, str]:
        if isinstance(handled.step.action, FinalResponseAction):

            def is_successful_patch_boundary(step: AgentStep) -> bool:
                if step.observation.status != "succeeded":
                    return False
                if step.action.type == "patch_proposal":
                    return True
                return (
                    step.action.type == "tool_call"
                    and getattr(step.action, "action", None)
                    in {"apply_patch", "apply_patch_to_worktree"}
                )

            last_patch_index = next(
                (
                    index
                    for index, step in reversed(list(enumerate(steps[:-1])))
                    if is_successful_patch_boundary(step)
                ),
                None,
            )
            observation_start_index = (
                0 if last_patch_index is None else last_patch_index + 1
            )
            meaningful_steps = [
                step
                for step in steps[observation_start_index:-1]
                if step.action.type != "assistant_message"
            ]
            if handled.step.action.status == "completed" and last_patch_index is not None:
                last_post_patch_verification = next(
                    (
                        step.observation
                        for step in reversed(steps[last_patch_index + 1 : -1])
                        if step.action.type == "tool_call"
                        and getattr(step.action, "action", None) == "run_command"
                    ),
                    None,
                )
                if (
                    last_post_patch_verification is None
                    or last_post_patch_verification.status != "succeeded"
                ):
                    return "failed", "Agent loop ended with failed observations"
            if (
                handled.step.action.status == "completed"
                and any(step.observation.status != "succeeded" for step in meaningful_steps)
            ):
                return "failed", "Agent loop ended with failed observations"
        return handled.status, handled.summary

    if loop_input.provider is not None:
        index = 1
        provider_turn = 0
        while index <= loop_input.step_budget:
            provider_turn += 1
            provider_response = loop_input.provider.next_action(
                AgentProviderStepInput(
                    problem_statement=loop_input.problem_statement,
                    verification_commands=loop_input.verification_commands,
                    step_index=index,
                    remaining_steps=loop_input.step_budget - index,
                    observations=observation_history,
                    context=loop_input.provider_context,
                    allowed_tools=loop_input.allowed_tools,
                )
            )
            if provider_response.status != "succeeded":
                observation = provider_response.observation or _failed_observation(
                    "Provider failed",
                    "provider failed without observation",
                )
                action = FinalResponseAction(
                    type="final_response",
                    status="failed",
                    summary="Provider failed",
                )
                handled = _handled_response(
                    status="failed",
                    summary=observation.summary,
                    index=index,
                    action=action,
                    observation=observation,
                )
                record_handled_action(handled)
                status = "failed"
                summary = observation.summary
                break

            if provider_response.tool_invocations:
                group_id = f"provider-{provider_turn}"
                stop_after_invocation = False
                for raw_invocation in provider_response.tool_invocations:
                    if index > loop_input.step_budget:
                        status = "failed"
                        summary = "Agent loop exhausted step budget without final response"
                        stop_after_invocation = True
                        break
                    invocation = raw_invocation.model_copy(update={"group_id": group_id})
                    handled = _handle_tool_invocation(
                        invocation=invocation,
                        index=index,
                        workspace_path=workspace_path,
                        settings=settings,
                        permission_mode=loop_input.permission_mode,
                        verification_commands=loop_input.verification_commands,
                        allowed_tools=loop_input.allowed_tools,
                    )
                    record_handled_action(handled, tool_invocation=invocation)
                    index += 1
                    if handled.stop:
                        status = handled.status
                        summary = handled.summary
                        stop_after_invocation = True
                        break
                if stop_after_invocation:
                    break
                continue

            if len(provider_response.actions) != 1:
                observation = build_invalid_action_observation(
                    payload={"actions": provider_response.actions},
                    error_message="provider step responses must include exactly one action",
                )
                action = FinalResponseAction(
                    type="final_response",
                    status="failed",
                    summary="Invalid MendCode action",
                )
                handled = _handled_response(
                    status="failed",
                    summary=observation.summary,
                    index=index,
                    action=action,
                    observation=observation,
                )
                record_handled_action(handled)
                status = "failed"
                summary = observation.summary
                break

            handled = _handle_action_payload(
                payload=provider_response.actions[0],
                index=index,
                workspace_path=workspace_path,
                settings=settings,
                permission_mode=loop_input.permission_mode,
                verification_commands=loop_input.verification_commands,
            )
            record_handled_action(handled)
            if handled.stop:
                status, summary = apply_final_response_gate(handled)
                break
            index += 1
        if index > loop_input.step_budget and summary == "Agent loop ended without final response":
            status = "failed"
            summary = "Agent loop exhausted step budget without final response"
    else:
        for index, payload in enumerate(loop_input.actions[: loop_input.step_budget], start=1):
            handled = _handle_action_payload(
                payload=payload,
                index=index,
                workspace_path=workspace_path,
                settings=settings,
                permission_mode=loop_input.permission_mode,
                verification_commands=loop_input.verification_commands,
            )
            record_handled_action(handled)
            if handled.stop:
                status, summary = apply_final_response_gate(handled)
                break

    trace_path = recorder.record(
        TraceEvent(
            run_id=run_id,
            event_type="agent.run.completed",
            message="Completed agent loop",
            payload={"status": status, "summary": summary, "step_count": len(steps)},
        )
    )
    return AgentLoopResult(
        run_id=run_id,
        status=status,
        summary=summary,
        trace_path=str(trace_path),
        workspace_path=str(workspace_path),
        steps=steps,
    )


def _handled_response(
    *,
    status: AgentLoopStatus,
    summary: str,
    index: int,
    action: FinalResponseAction,
    observation,
) -> _HandledAction:
    return _HandledAction(
        stop=True,
        status=status,
        summary=summary,
        step=AgentStep(index=index, action=action, observation=observation),
    )
