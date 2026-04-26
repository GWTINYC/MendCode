from app.agent.loop import AgentLoopStatus, AgentStep, FinalResponseAction, _HandledAction


def apply_final_response_gate(
    *,
    steps: list[AgentStep],
    handled: _HandledAction,
) -> tuple[AgentLoopStatus, str]:
    if not isinstance(handled.step.action, FinalResponseAction):
        return handled.status, handled.summary

    last_patch_index = next(
        (
            index
            for index, step in reversed(list(enumerate(steps)))
            if _is_successful_patch_boundary(step)
        ),
        None,
    )
    observation_start_index = 0 if last_patch_index is None else last_patch_index + 1
    meaningful_steps = [
        step
        for step in steps[observation_start_index:]
        if step.action.type != "assistant_message"
    ]
    if handled.step.action.status == "completed" and last_patch_index is not None:
        last_post_patch_verification = next(
            (
                step.observation
                for step in reversed(steps[last_patch_index + 1 :])
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
    if handled.step.action.status == "completed" and any(
        step.observation.status != "succeeded" for step in meaningful_steps
    ):
        return "failed", "Agent loop ended with failed observations"
    return handled.status, handled.summary


def _is_successful_patch_boundary(step: AgentStep) -> bool:
    if step.observation.status != "succeeded":
        return False
    if step.action.type == "patch_proposal":
        return True
    return (
        step.action.type == "tool_call"
        and getattr(step.action, "action", None)
        in {"apply_patch", "apply_patch_to_worktree"}
    )
