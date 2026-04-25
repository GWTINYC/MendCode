import subprocess
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.permission import (
    PermissionMode,
    build_confirmation_request,
    decide_permission,
)
from app.config.settings import Settings
from app.schemas.agent_action import (
    FinalResponseAction,
    MendCodeAction,
    Observation,
    PatchProposalAction,
    ToolCallAction,
    build_invalid_action_observation,
    parse_mendcode_action,
)
from app.schemas.trace import TraceEvent
from app.tools.patch import apply_patch
from app.tools.read_only import read_file, search_code
from app.tools.schemas import ToolResult
from app.tracing.recorder import TraceRecorder
from app.workspace.command_policy import CommandPolicy
from app.workspace.executor import execute_verification_command
from app.workspace.worktree import prepare_worktree

AgentLoopStatus = str


class AgentLoopInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_path: Path
    problem_statement: str
    actions: list[dict[str, object]]
    permission_mode: PermissionMode = "guided"
    step_budget: int = Field(default=12, ge=1)
    use_worktree: bool = False
    base_ref: str | None = None


class AgentStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    action: MendCodeAction
    observation: Observation


class AgentLoopResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: AgentLoopStatus
    summary: str
    trace_path: str | None
    workspace_path: str | None = None
    steps: list[AgentStep] = Field(default_factory=list)


def _tool_result_to_observation(result: ToolResult) -> Observation:
    status = "succeeded" if result.status == "passed" else result.status
    return Observation(
        status=status,
        summary=result.summary,
        payload=result.payload,
        error_message=result.error_message,
    )


def _failed_observation(summary: str, error_message: str) -> Observation:
    return Observation(
        status="failed",
        summary=summary,
        payload={},
        error_message=error_message,
    )


def _run_subprocess(args: list[str], cwd: Path) -> tuple[int, str, str]:
    completed = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _repo_status(repo_path: Path) -> Observation:
    try:
        branch_code, branch_stdout, branch_stderr = _run_subprocess(
            ["git", "branch", "--show-current"],
            repo_path,
        )
        status_code, status_stdout, status_stderr = _run_subprocess(
            ["git", "status", "--short"],
            repo_path,
        )
    except OSError as exc:
        return _failed_observation("Unable to read repo status", str(exc))

    if branch_code != 0 or status_code != 0:
        return _failed_observation(
            "Unable to read repo status",
            (branch_stderr or status_stderr or "git status failed").strip(),
        )

    dirty_files = [line for line in status_stdout.splitlines() if line.strip()]
    return Observation(
        status="succeeded",
        summary="Read repository status",
        payload={
            "branch": branch_stdout.strip(),
            "dirty": bool(dirty_files),
            "dirty_count": len(dirty_files),
            "files": dirty_files,
        },
    )


def _detect_project(repo_path: Path) -> Observation:
    markers = {
        "python": ["pyproject.toml", "requirements.txt", "setup.py"],
        "node": ["package.json"],
    }
    languages = [
        language
        for language, filenames in markers.items()
        if any((repo_path / filename).exists() for filename in filenames)
    ]
    suggested_test = "python -m pytest -q" if "python" in languages else None
    return Observation(
        status="succeeded",
        summary="Detected project",
        payload={"languages": languages, "suggested_test": suggested_test},
    )


def _run_command(repo_path: Path, settings: Settings, args: dict[str, object]) -> Observation:
    command = str(args.get("command", ""))
    if not command.strip():
        return Observation(
            status="rejected",
            summary="Unable to run command",
            payload={"command": command},
            error_message="command must not be empty",
        )

    policy = CommandPolicy(
        allowed_commands=[command],
        allowed_root=repo_path,
        timeout_seconds=settings.verification_timeout_seconds,
    )
    result = execute_verification_command(command=command, cwd=repo_path, policy=policy)
    status = "succeeded" if result.status == "passed" else result.status
    if status == "timed_out":
        status = "failed"
    return Observation(
        status=status,
        summary=f"Ran command: {command}",
        payload=result.model_dump(mode="json"),
        error_message=None if result.status == "passed" else result.stderr_excerpt,
    )


def _show_diff(repo_path: Path) -> Observation:
    try:
        code, stdout, stderr = _run_subprocess(["git", "diff", "--stat"], repo_path)
    except OSError as exc:
        return _failed_observation("Unable to show diff", str(exc))
    if code != 0:
        return _failed_observation("Unable to show diff", stderr.strip() or "git diff failed")
    return Observation(
        status="succeeded",
        summary="Read diff summary",
        payload={"diff_stat": stdout},
    )


def _apply_patch_proposal(action: PatchProposalAction, workspace_path: Path) -> Observation:
    try:
        completed = subprocess.run(
            ["git", "apply", "--whitespace=nowarn"],
            cwd=workspace_path,
            input=action.patch,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return _failed_observation("Unable to apply patch proposal", str(exc))

    if completed.returncode != 0:
        return Observation(
            status="failed",
            summary="Unable to apply patch proposal",
            payload={
                "files_to_modify": action.files_to_modify,
                "stderr": completed.stderr,
                "stdout": completed.stdout,
            },
            error_message=completed.stderr or completed.stdout or "git apply failed",
        )

    return Observation(
        status="succeeded",
        summary="Applied patch proposal",
        payload={"files_to_modify": action.files_to_modify},
    )


def _execute_tool_call(
    *,
    action: ToolCallAction,
    repo_path: Path,
    settings: Settings,
) -> Observation:
    if action.action == "repo_status":
        return _repo_status(repo_path)
    if action.action == "detect_project":
        return _detect_project(repo_path)
    if action.action == "run_command":
        return _run_command(repo_path, settings, action.args)
    if action.action == "read_file":
        result = read_file(
            workspace_path=repo_path,
            relative_path=str(action.args.get("relative_path") or action.args.get("path") or ""),
            start_line=action.args.get("start_line"),  # type: ignore[arg-type]
            end_line=action.args.get("end_line"),  # type: ignore[arg-type]
            max_chars=action.args.get("max_chars"),  # type: ignore[arg-type]
        )
        return _tool_result_to_observation(result)
    if action.action == "search_code":
        result = search_code(
            workspace_path=repo_path,
            query=str(action.args.get("query", "")),
            glob=action.args.get("glob"),  # type: ignore[arg-type]
            max_results=action.args.get("max_results"),  # type: ignore[arg-type]
        )
        return _tool_result_to_observation(result)
    if action.action == "apply_patch_to_worktree":
        result = apply_patch(
            workspace_path=repo_path,
            relative_path=str(action.args.get("relative_path", "")),
            target_text=str(action.args.get("target_text", "")),
            replacement_text=str(action.args.get("replacement_text", "")),
            replace_all=bool(action.args.get("replace_all", False)),
        )
        return _tool_result_to_observation(result)
    if action.action == "show_diff":
        return _show_diff(repo_path)

    return Observation(
        status="rejected",
        summary="Unsupported tool",
        payload=action.model_dump(mode="json"),
        error_message=f"unsupported tool: {action.action}",
    )


def _record_step(
    *,
    recorder: TraceRecorder,
    run_id: str,
    index: int,
    action: MendCodeAction,
    observation: Observation,
) -> Path:
    return recorder.record(
        TraceEvent(
            run_id=run_id,
            event_type="agent.action.completed",
            message="Completed agent action",
            payload={
                "index": index,
                "action": action.model_dump(mode="json"),
                "observation": observation.model_dump(mode="json"),
            },
        )
    )


def run_agent_loop(loop_input: AgentLoopInput, settings: Settings) -> AgentLoopResult:
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

    for index, payload in enumerate(loop_input.actions[: loop_input.step_budget], start=1):
        try:
            action = parse_mendcode_action(payload)
        except ValidationError as exc:
            observation = build_invalid_action_observation(
                payload=payload,
                error_message=str(exc),
            )
            action = FinalResponseAction(
                type="final_response",
                status="failed",
                summary="Invalid MendCode action",
            )
            steps.append(AgentStep(index=index, action=action, observation=observation))
            trace_path = _record_step(
                recorder=recorder,
                run_id=run_id,
                index=index,
                action=action,
                observation=observation,
            )
            summary = observation.summary
            status = "failed"
            break

        if isinstance(action, ToolCallAction):
            decision = decide_permission(action, loop_input.permission_mode)
            if decision.status == "confirm":
                confirmation = build_confirmation_request(action=action, decision=decision)
                observation = Observation(
                    status="rejected",
                    summary="User confirmation required",
                    payload={"permission_decision": decision.model_dump(mode="json")},
                    error_message=decision.reason,
                )
                steps.append(AgentStep(index=index, action=confirmation, observation=observation))
                trace_path = _record_step(
                    recorder=recorder,
                    run_id=run_id,
                    index=index,
                    action=confirmation,
                    observation=observation,
                )
                summary = observation.summary
                status = "needs_user_confirmation"
                break
            if decision.status == "deny":
                observation = Observation(
                    status="rejected",
                    summary="Tool denied by permission gate",
                    payload={"permission_decision": decision.model_dump(mode="json")},
                    error_message=decision.reason,
                )
            else:
                observation = _execute_tool_call(
                    action=action,
                    repo_path=workspace_path,
                    settings=settings,
                )
            steps.append(AgentStep(index=index, action=action, observation=observation))
            trace_path = _record_step(
                recorder=recorder,
                run_id=run_id,
                index=index,
                action=action,
                observation=observation,
            )
            continue

        if isinstance(action, PatchProposalAction):
            observation = _apply_patch_proposal(action, workspace_path)
            steps.append(AgentStep(index=index, action=action, observation=observation))
            trace_path = _record_step(
                recorder=recorder,
                run_id=run_id,
                index=index,
                action=action,
                observation=observation,
            )
            continue

        observation = Observation(
            status="succeeded",
            summary="Recorded agent action",
            payload=action.model_dump(mode="json"),
        )
        steps.append(AgentStep(index=index, action=action, observation=observation))
        trace_path = _record_step(
            recorder=recorder,
            run_id=run_id,
            index=index,
            action=action,
            observation=observation,
        )
        if isinstance(action, FinalResponseAction):
            last_non_final_observation = next(
                (
                    step.observation
                    for step in reversed(steps[:-1])
                    if step.action.type != "assistant_message"
                ),
                None,
            )
            if (
                action.status == "completed"
                and last_non_final_observation is not None
                and last_non_final_observation.status != "succeeded"
            ):
                status = "failed"
                summary = "Agent loop ended with failed observations"
            else:
                status = action.status
                summary = action.summary
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
