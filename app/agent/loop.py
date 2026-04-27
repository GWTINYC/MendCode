import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.permission import (
    PermissionDecision,
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
from app.tools.read_only import glob_file_search, list_dir, read_file, search_code
from app.tools.registry import default_tool_registry
from app.tools.schemas import ToolResult
from app.tools.structured import ToolExecutionContext, ToolInvocation
from app.tracing.recorder import TraceRecorder
from app.workspace.command_policy import CommandPolicy
from app.workspace.executor import execute_verification_command
from app.workspace.project_detection import detect_project
from app.workspace.shell_executor import ShellCommandResult, execute_shell_command
from app.workspace.shell_policy import ShellPolicy

AgentLoopStatus = str
_BUILTIN_TOOL_NAMES = {
    "apply_patch_to_worktree",
}


class AgentLoopInput(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    repo_path: Path
    problem_statement: str
    actions: list[dict[str, object]] = Field(default_factory=list)
    provider: Any | None = None
    verification_commands: list[str] = Field(default_factory=list)
    provider_context: str | None = None
    allowed_tools: set[str] | None = None
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


class _HandledAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stop: bool
    status: AgentLoopStatus
    summary: str
    step: AgentStep


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


def _rejected_observation(
    summary: str,
    error_message: str,
    payload: dict[str, Any] | None = None,
) -> Observation:
    return Observation(
        status="rejected",
        summary=summary,
        payload=payload or {},
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
    result = detect_project(repo_path)
    return Observation(
        status="succeeded",
        summary="Detected project",
        payload=result.model_dump(mode="json"),
    )


def _run_command(
    repo_path: Path,
    settings: Settings,
    args: dict[str, object],
    verification_commands: list[str],
) -> Observation:
    command = str(args.get("command", ""))
    if not command.strip():
        return Observation(
            status="rejected",
            summary="Unable to run command",
            payload={"command": command},
            error_message="command must not be empty",
        )

    policy = CommandPolicy(
        allowed_commands=verification_commands,
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


def _shell_result_to_observation(result: ShellCommandResult) -> Observation:
    if result.status == "passed":
        status = "succeeded"
    elif result.status in {"rejected", "needs_confirmation"}:
        status = "rejected"
    else:
        status = "failed"
    return Observation(
        status=status,
        summary=f"Ran shell command: {result.command}",
        payload=result.model_dump(mode="json"),
        error_message=None if status == "succeeded" else result.stderr_excerpt,
    )


def _run_shell_command(repo_path: Path, settings: Settings, args: dict[str, object]) -> Observation:
    command = str(args.get("command", ""))
    if not command.strip():
        return Observation(
            status="rejected",
            summary="Unable to run shell command",
            payload={"command": command},
            error_message="command must not be empty",
        )

    policy = ShellPolicy(
        allowed_root=repo_path,
        timeout_seconds=settings.verification_timeout_seconds,
    )
    result = execute_shell_command(command=command, cwd=repo_path, policy=policy)
    return _shell_result_to_observation(result)


def _coerce_command_args(value: object) -> tuple[list[str] | None, str | None]:
    if isinstance(value, list):
        if not all(isinstance(item, str) and item.strip() for item in value):
            return None, "args must be a list of non-empty strings"
        return value, None
    if isinstance(value, str):
        try:
            return shlex.split(value), None
        except ValueError as exc:
            return None, f"unable to parse args: {exc}"
    return None, "args must be a list of strings or a shell-style string"


def _build_git_command(args: dict[str, object]) -> tuple[str | None, str | None]:
    raw_args = args.get("args", args.get("command", ""))
    git_args, error_message = _coerce_command_args(raw_args)
    if error_message is not None:
        return None, error_message
    assert git_args is not None
    if git_args and git_args[0] == "git":
        git_args = git_args[1:]
    if not git_args:
        return None, "git args must include a subcommand"
    return "git " + shlex.join(git_args), None


def _run_git(repo_path: Path, settings: Settings, args: dict[str, object]) -> Observation:
    command, error_message = _build_git_command(args)
    if error_message is not None:
        return _rejected_observation(
            "Unable to run git",
            error_message,
            payload={"args": args},
        )
    assert command is not None
    policy = ShellPolicy(
        allowed_root=repo_path,
        timeout_seconds=settings.verification_timeout_seconds,
    )
    result = execute_shell_command(command=command, cwd=repo_path, policy=policy)
    return _shell_result_to_observation(result)


def _run_rg(repo_path: Path, args: dict[str, object]) -> Observation:
    query = str(args.get("query") or args.get("pattern") or "")
    result = search_code(
        workspace_path=repo_path,
        query=query,
        glob=args.get("glob"),  # type: ignore[arg-type]
        max_results=args.get("max_results"),  # type: ignore[arg-type]
    )
    return _tool_result_to_observation(result)


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
    return _apply_unified_patch(
        workspace_path=workspace_path,
        patch=action.patch,
        files_to_modify=action.files_to_modify,
        summary="patch proposal",
    )


def _apply_unified_patch(
    *,
    workspace_path: Path,
    patch: str,
    files_to_modify: list[str],
    summary: str,
) -> Observation:
    if not patch.strip():
        return _rejected_observation(
            f"Unable to apply {summary}",
            "patch must not be empty",
            payload={"files_to_modify": files_to_modify},
        )
    try:
        completed = subprocess.run(
            ["git", "apply", "--whitespace=nowarn"],
            cwd=workspace_path,
            input=patch,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return _failed_observation(f"Unable to apply {summary}", str(exc))

    if completed.returncode != 0:
        return Observation(
            status="failed",
            summary=f"Unable to apply {summary}",
            payload={
                "files_to_modify": files_to_modify,
                "stderr": completed.stderr,
                "stdout": completed.stdout,
            },
            error_message=completed.stderr or completed.stdout or "git apply failed",
        )

    for pycache_path in workspace_path.rglob("__pycache__"):
        if pycache_path.is_dir():
            shutil.rmtree(pycache_path, ignore_errors=True)

    return Observation(
        status="succeeded",
        summary=f"Applied {summary}",
        payload={"files_to_modify": files_to_modify},
    )


def _apply_patch_tool(args: dict[str, object], workspace_path: Path) -> Observation:
    files_to_modify = args.get("files_to_modify", [])
    if not isinstance(files_to_modify, list) or not all(
        isinstance(item, str) for item in files_to_modify
    ):
        return _rejected_observation(
            "Unable to apply patch",
            "files_to_modify must be a list of strings",
            payload={"files_to_modify": files_to_modify},
        )
    return _apply_unified_patch(
        workspace_path=workspace_path,
        patch=str(args.get("patch", "")),
        files_to_modify=files_to_modify,
        summary="patch",
    )


def _tool_execution_context(
    *,
    repo_path: Path,
    settings: Settings,
    verification_commands: list[str],
    available_tools: set[str] | None = None,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_path=repo_path,
        settings=settings,
        verification_commands=verification_commands,
        available_tools=available_tools,
    )


def _registry_args_for_json_action(action: ToolCallAction) -> dict[str, Any]:
    args = dict(action.args)
    if action.action in {"read_file", "list_dir"} and "path" not in args:
        relative_path = args.pop("relative_path", None)
        if relative_path is not None:
            args["path"] = relative_path
    return args


def _execute_tool_invocation(
    *,
    invocation: ToolInvocation,
    repo_path: Path,
    settings: Settings,
    verification_commands: list[str],
    allowed_tools: set[str] | None = None,
) -> Observation:
    registry = default_tool_registry()
    try:
        spec = registry.get(invocation.name)
    except KeyError as exc:
        return _rejected_observation(
            "Unsupported tool",
            str(exc.args[0]),
            payload=invocation.model_dump(mode="json"),
        )
    return spec.execute(
        invocation.args,
        _tool_execution_context(
            repo_path=repo_path,
            settings=settings,
            verification_commands=verification_commands,
            available_tools=_allowed_tool_names(allowed_tools),
        ),
    )


def _execute_tool_call(
    *,
    action: ToolCallAction,
    repo_path: Path,
    settings: Settings,
    verification_commands: list[str],
    allowed_tools: set[str] | None = None,
    allow_legacy_git: bool = True,
) -> Observation:
    if (
        allow_legacy_git
        and action.action == "git"
        and ("args" in action.args or "command" in action.args)
    ):
        return _run_git(repo_path, settings, action.args)

    registry = default_tool_registry()
    try:
        registry.get(action.action)
    except KeyError:
        pass
    else:
        return _execute_tool_invocation(
            invocation=ToolInvocation(
                name=action.action,
                args=_registry_args_for_json_action(action),
                source="json_action",
            ),
            repo_path=repo_path,
            settings=settings,
            verification_commands=verification_commands,
            allowed_tools=allowed_tools,
        )

    if action.action == "repo_status":
        return _repo_status(repo_path)
    if action.action == "detect_project":
        return _detect_project(repo_path)
    if action.action == "run_command":
        return _run_command(repo_path, settings, action.args, verification_commands)
    if action.action == "run_shell_command":
        return _run_shell_command(repo_path, settings, action.args)
    if action.action == "read_file":
        result = read_file(
            workspace_path=repo_path,
            relative_path=str(action.args.get("relative_path") or action.args.get("path") or ""),
            start_line=action.args.get("start_line"),  # type: ignore[arg-type]
            end_line=action.args.get("end_line"),  # type: ignore[arg-type]
            tail_lines=action.args.get("tail_lines"),  # type: ignore[arg-type]
            max_chars=action.args.get("max_chars"),  # type: ignore[arg-type]
        )
        return _tool_result_to_observation(result)
    if action.action == "list_dir":
        result = list_dir(
            workspace_path=repo_path,
            relative_path=str(action.args.get("relative_path") or action.args.get("path") or "."),
            max_entries=action.args.get("max_entries"),  # type: ignore[arg-type]
        )
        return _tool_result_to_observation(result)
    if action.action == "glob_file_search":
        result = glob_file_search(
            workspace_path=repo_path,
            pattern=str(action.args.get("pattern", "")),
            max_results=action.args.get("max_results"),  # type: ignore[arg-type]
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
    if action.action == "rg":
        return _run_rg(repo_path, action.args)
    if action.action == "git":
        return _run_git(repo_path, settings, action.args)
    if action.action == "apply_patch":
        return _apply_patch_tool(action.args, repo_path)
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


def _shell_policy_command_for_action(action: ToolCallAction) -> str | None:
    if action.action == "run_shell_command":
        return str(action.args.get("command", ""))
    if action.action == "git":
        command, error_message = _build_git_command(action.args)
        if error_message is not None:
            return None
        return command
    return None


def _confirmation_handled_action(
    *,
    action: ToolCallAction,
    decision: PermissionDecision,
    index: int,
    payload: dict[str, Any],
    error_message: str | None,
) -> _HandledAction:
    confirmation = build_confirmation_request(action=action, decision=decision)
    observation = Observation(
        status="rejected",
        summary="User confirmation required",
        payload=payload,
        error_message=error_message,
    )
    return _HandledAction(
        stop=True,
        status="needs_user_confirmation",
        summary=observation.summary,
        step=AgentStep(index=index, action=confirmation, observation=observation),
    )


def _handle_tool_call_action(
    *,
    action: ToolCallAction,
    index: int,
    workspace_path: Path,
    settings: Settings,
    permission_mode: PermissionMode,
    verification_commands: list[str],
    allowed_tools: set[str] | None = None,
    allow_legacy_git: bool = True,
) -> _HandledAction:
    shell_policy_command = (
        _shell_policy_command_for_action(action)
        if allow_legacy_git or action.action != "git"
        else None
    )
    shell_decision = None
    if shell_policy_command is not None:
        shell_decision = ShellPolicy(
            allowed_root=workspace_path,
            timeout_seconds=settings.verification_timeout_seconds,
        ).evaluate(shell_policy_command, workspace_path)

    decision = decide_permission(
        action,
        permission_mode,
        shell_decision=shell_decision,
    )
    observation: Observation
    if decision.status == "confirm":
        payload: dict[str, Any] = {"permission_decision": decision.model_dump(mode="json")}
        if shell_decision is not None:
            payload["shell_policy_decision"] = shell_decision.model_dump(mode="json")
        return _confirmation_handled_action(
            action=action,
            decision=decision,
            index=index,
            payload=payload,
            error_message=decision.reason,
        )
    if decision.status == "deny":
        payload = {"permission_decision": decision.model_dump(mode="json")}
        if shell_decision is not None:
            payload["shell_policy_decision"] = shell_decision.model_dump(mode="json")
        observation = Observation(
            status="rejected",
            summary="Tool denied by permission gate",
            payload=payload,
            error_message=decision.reason,
        )
        return _HandledAction(
            stop=True,
            status="failed",
            summary=observation.summary,
            step=AgentStep(index=index, action=action, observation=observation),
        )
    else:
        observation = _execute_tool_call(
            action=action,
            repo_path=workspace_path,
            settings=settings,
            verification_commands=verification_commands,
            allowed_tools=allowed_tools,
            allow_legacy_git=allow_legacy_git,
        )
    return _HandledAction(
        stop=False,
        status="failed",
        summary="Agent loop ended without final response",
        step=AgentStep(index=index, action=action, observation=observation),
    )


def _tool_call_action_for_invocation(invocation: ToolInvocation) -> ToolCallAction | None:
    try:
        return ToolCallAction(
            type="tool_call",
            action=invocation.name,  # type: ignore[arg-type]
            reason=f"provider requested {invocation.name}",
            args=invocation.args,
        )
    except ValidationError:
        return None


def _allowed_tool_names(allowed_tools: set[str] | None) -> set[str] | None:
    if allowed_tools is None:
        return None
    registry_tools = default_tool_registry().names(
        allowed_tools={name for name in allowed_tools if name not in _BUILTIN_TOOL_NAMES}
    )
    return set(registry_tools).union(allowed_tools.intersection(_BUILTIN_TOOL_NAMES))


def _handle_tool_invocation(
    *,
    invocation: ToolInvocation,
    index: int,
    workspace_path: Path,
    settings: Settings,
    permission_mode: PermissionMode,
    verification_commands: list[str],
    allowed_tools: set[str] | None = None,
) -> _HandledAction:
    action = _tool_call_action_for_invocation(invocation)
    if action is None:
        observation = _rejected_observation(
            "Unsupported tool",
            f"unknown tool: {invocation.name}",
            payload=invocation.model_dump(mode="json"),
        )
        action = FinalResponseAction(
            type="final_response",
            status="failed",
            summary=observation.summary,
        )
        return _HandledAction(
            stop=True,
            status="failed",
            summary=observation.summary,
            step=AgentStep(index=index, action=action, observation=observation),
        )

    normalized_allowed_tools = _allowed_tool_names(allowed_tools)
    if normalized_allowed_tools is not None and invocation.name not in normalized_allowed_tools:
        observation = _rejected_observation(
            "Tool denied by allowed-tools gate",
            "tool is not allowed in this turn",
            payload={
                "tool_name": invocation.name,
                "allowed_tools": sorted(normalized_allowed_tools),
            },
        )
        return _HandledAction(
            stop=True,
            status="failed",
            summary=observation.summary,
            step=AgentStep(index=index, action=action, observation=observation),
        )

    return _handle_tool_call_action(
        action=action,
        index=index,
        workspace_path=workspace_path,
        settings=settings,
        permission_mode=permission_mode,
        verification_commands=verification_commands,
        allowed_tools=allowed_tools,
        allow_legacy_git=False,
    )


def _handle_action_payload(
    *,
    payload: dict[str, object],
    index: int,
    workspace_path: Path,
    settings: Settings,
    permission_mode: PermissionMode,
    verification_commands: list[str],
    allowed_tools: set[str] | None = None,
) -> _HandledAction:
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
        return _HandledAction(
            stop=True,
            status="failed",
            summary=observation.summary,
            step=AgentStep(index=index, action=action, observation=observation),
        )

    if isinstance(action, ToolCallAction):
        return _handle_tool_call_action(
            action=action,
            index=index,
            workspace_path=workspace_path,
            settings=settings,
            permission_mode=permission_mode,
            verification_commands=verification_commands,
            allowed_tools=allowed_tools,
        )

    if isinstance(action, PatchProposalAction):
        observation = _apply_patch_proposal(action, workspace_path)
        return _HandledAction(
            stop=False,
            status="failed",
            summary="Agent loop ended without final response",
            step=AgentStep(index=index, action=action, observation=observation),
        )

    observation = Observation(
        status="succeeded",
        summary="Recorded agent action",
        payload=action.model_dump(mode="json"),
    )
    if isinstance(action, FinalResponseAction):
        return _HandledAction(
            stop=True,
            status=action.status,
            summary=action.summary,
            step=AgentStep(index=index, action=action, observation=observation),
        )
    return _HandledAction(
        stop=False,
        status="failed",
        summary="Agent loop ended without final response",
        step=AgentStep(index=index, action=action, observation=observation),
    )


def _run_agent_loop_impl(loop_input: AgentLoopInput, settings: Settings) -> AgentLoopResult:
    from app.runtime.agent_loop import run_agent_loop_turn

    return run_agent_loop_turn(loop_input, settings)


def run_agent_loop(loop_input: AgentLoopInput, settings: Settings) -> AgentLoopResult:
    from app.runtime.agent_runtime import AgentRuntime

    return AgentRuntime(settings=settings).run_turn(loop_input)
