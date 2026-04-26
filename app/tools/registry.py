import shlex
import shutil
import subprocess
from pathlib import Path

from app.schemas.agent_action import Observation
from app.tools.arguments import (
    ApplyPatchArgs,
    GitArgs,
    GlobFileSearchArgs,
    ListDirArgs,
    ReadFileArgs,
    RgArgs,
    RunCommandArgs,
    RunShellCommandArgs,
)
from app.tools.observations import observation_from_tool_result, tool_observation
from app.tools.read_only import (
    glob_file_search,
    list_dir,
    read_file,
    search_code,
)
from app.tools.schemas import ToolResult
from app.tools.structured import ToolExecutionContext, ToolRegistry, ToolRisk, ToolSpec
from app.workspace.command_policy import CommandPolicy
from app.workspace.executor import execute_verification_command
from app.workspace.shell_executor import ShellCommandResult, execute_shell_command
from app.workspace.shell_policy import ShellPolicy

_OUTPUT_EXCERPT_LIMIT = 2000


def _trim_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if len(value) <= _OUTPUT_EXCERPT_LIMIT:
        return value
    return value[:_OUTPUT_EXCERPT_LIMIT]


def tool_result_to_observation(result: ToolResult) -> Observation:
    return observation_from_tool_result(result)


def _failed(
    tool_name: str,
    summary: str,
    error_message: str,
    payload: dict[str, object] | None = None,
) -> Observation:
    return tool_observation(
        tool_name=tool_name,
        status="failed",
        summary=summary,
        payload=payload or {},
        error_message=error_message,
    )


def _rejected(
    tool_name: str,
    summary: str,
    error_message: str,
    payload: dict[str, object] | None = None,
) -> Observation:
    return tool_observation(
        tool_name=tool_name,
        status="rejected",
        summary=summary,
        payload=payload or {},
        error_message=error_message,
    )


def _execute_read_file(args: ReadFileArgs, context: ToolExecutionContext) -> Observation:
    return tool_result_to_observation(
        read_file(
            context.workspace_path,
            args.path,
            start_line=args.start_line,
            end_line=args.end_line,
            max_chars=args.max_chars,
        )
    )


def _execute_list_dir(args: ListDirArgs, context: ToolExecutionContext) -> Observation:
    return tool_result_to_observation(
        list_dir(
            context.workspace_path,
            args.path,
            max_entries=args.max_entries,
        )
    )


def _execute_glob_file_search(
    args: GlobFileSearchArgs,
    context: ToolExecutionContext,
) -> Observation:
    return tool_result_to_observation(
        glob_file_search(
            context.workspace_path,
            args.pattern,
            max_results=args.max_results,
        )
    )


def _execute_rg(args: RgArgs, context: ToolExecutionContext) -> Observation:
    return tool_result_to_observation(
        search_code(
            context.workspace_path,
            args.query,
            glob=args.glob,
            max_results=args.max_results,
        )
    )


def _shell_result_to_observation(result: ShellCommandResult) -> Observation:
    if result.status == "passed":
        status = "succeeded"
    elif result.status in {"rejected", "needs_confirmation"}:
        status = "rejected"
    else:
        status = "failed"
    payload = result.model_dump(mode="json")
    return tool_observation(
        tool_name="run_shell_command",
        status=status,
        summary=f"Ran shell command: {result.command}",
        payload=payload,
        error_message=None if status == "succeeded" else result.stderr_excerpt,
        stdout_excerpt=result.stdout_excerpt,
        stderr_excerpt=result.stderr_excerpt,
        duration_ms=result.duration_ms,
    )


def _path_escapes_workspace(path: str, workspace_path: Path) -> bool:
    candidate = Path(path)
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (workspace_path / candidate).resolve()
    )
    try:
        resolved.relative_to(workspace_path.resolve())
    except ValueError:
        return True
    return False


def _git_command(args: GitArgs, workspace_path: Path) -> tuple[list[str] | None, str | None]:
    command = ["git"]
    if args.operation == "status":
        command.extend(["status", "--short"])
    elif args.operation == "diff":
        command.append("diff")
    elif args.operation == "log":
        command.extend(["log", "--oneline", "-n", str(args.limit)])
    else:
        return None, f"unsupported git operation: {args.operation}"

    if args.path is not None:
        if _path_escapes_workspace(args.path, workspace_path):
            return None, "git path escapes workspace root"
        command.extend(["--", args.path])
    return command, None


def _git(args: GitArgs, context: ToolExecutionContext) -> Observation:
    command_parts, error_message = _git_command(args, context.workspace_path)
    if error_message is not None:
        return _rejected(
            "git",
            "Unable to run git",
            error_message,
            payload=args.model_dump(mode="json"),
        )
    assert command_parts is not None
    command = shlex.join(command_parts)
    try:
        completed = subprocess.run(
            command_parts,
            capture_output=True,
            text=True,
            cwd=context.workspace_path,
            timeout=context.settings.verification_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return _failed(
            "git",
            "Unable to run git",
            f"git command timed out after {context.settings.verification_timeout_seconds} seconds",
            payload={
                "command": command,
                "stdout_excerpt": _trim_output(exc.output),
                "stderr_excerpt": _trim_output(exc.stderr),
            },
        )
    except OSError as exc:
        return _failed("git", "Unable to run git", str(exc), payload={"command": command})

    payload = {
        "command": command,
        "exit_code": completed.returncode,
        "stdout_excerpt": _trim_output(completed.stdout),
        "stderr_excerpt": _trim_output(completed.stderr),
    }
    if completed.returncode != 0:
        return _failed(
            "git",
            "Unable to run git",
            completed.stderr.strip() or "git command failed",
            payload=payload,
        )
    return tool_observation(
        tool_name="git",
        status="succeeded",
        summary=f"Ran git: {command}",
        payload=payload,
        stdout_excerpt=payload["stdout_excerpt"],
        stderr_excerpt=payload["stderr_excerpt"],
    )


def _run_shell_command(args: RunShellCommandArgs, context: ToolExecutionContext) -> Observation:
    if not args.command.strip():
        return _rejected(
            "run_shell_command",
            "Unable to run shell command",
            "command must not be empty",
            payload={"command": args.command},
        )
    policy = ShellPolicy(
        allowed_root=context.workspace_path,
        timeout_seconds=context.settings.verification_timeout_seconds,
    )
    result = execute_shell_command(command=args.command, cwd=context.workspace_path, policy=policy)
    return _shell_result_to_observation(result)


def _run_command(args: RunCommandArgs, context: ToolExecutionContext) -> Observation:
    if not args.command.strip():
        return _rejected(
            "run_command",
            "Unable to run command",
            "command must not be empty",
            payload={"command": args.command},
        )
    policy = CommandPolicy(
        allowed_commands=context.verification_commands,
        allowed_root=context.workspace_path,
        timeout_seconds=context.settings.verification_timeout_seconds,
    )
    result = execute_verification_command(
        command=args.command,
        cwd=context.workspace_path,
        policy=policy,
    )
    status = "succeeded" if result.status == "passed" else result.status
    if status == "timed_out":
        status = "failed"
    payload = result.model_dump(mode="json")
    return tool_observation(
        tool_name="run_command",
        status=status,
        summary=f"Ran command: {args.command}",
        payload=payload,
        error_message=None if result.status == "passed" else result.stderr_excerpt,
        stdout_excerpt=result.stdout_excerpt,
        stderr_excerpt=result.stderr_excerpt,
        duration_ms=result.duration_ms,
    )


def _strip_patch_prefix(path: str) -> str:
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _patch_paths(patch: str) -> list[str]:
    paths: list[str] = []
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            parts = shlex.split(line)
            if len(parts) >= 4:
                paths.extend([_strip_patch_prefix(parts[2]), _strip_patch_prefix(parts[3])])
        elif line.startswith("--- ") or line.startswith("+++ "):
            path = line[4:].split("\t", maxsplit=1)[0].strip()
            if path != "/dev/null":
                paths.append(_strip_patch_prefix(path))
    return paths


def _validate_patch_paths(paths: list[str], workspace_path: Path) -> str | None:
    for path in paths:
        if path == "/dev/null":
            continue
        if _path_escapes_workspace(path, workspace_path):
            return f"patch path escapes workspace root: {path}"
    return None


def _apply_patch(args: ApplyPatchArgs, context: ToolExecutionContext) -> Observation:
    paths = [*args.files_to_modify, *_patch_paths(args.patch)]
    error_message = _validate_patch_paths(paths, context.workspace_path)
    if error_message is not None:
        return _rejected(
            "apply_patch",
            "Unable to apply patch",
            error_message,
            payload={"paths": paths},
        )

    command = ["git", "apply", "--whitespace=nowarn", "-"]
    try:
        completed = subprocess.run(
            command,
            input=args.patch,
            capture_output=True,
            text=True,
            cwd=context.workspace_path,
            timeout=context.settings.verification_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return _failed(
            "apply_patch",
            "Unable to apply patch",
            f"git apply timed out after {context.settings.verification_timeout_seconds} seconds",
            payload={
                "command": shlex.join(command),
                "stdout_excerpt": exc.output or "",
                "stderr_excerpt": exc.stderr or "",
                "paths": paths,
            },
        )
    except OSError as exc:
        return _failed(
            "apply_patch",
            "Unable to apply patch",
            str(exc),
            payload={"command": shlex.join(command)},
        )

    payload = {
        "command": shlex.join(command),
        "exit_code": completed.returncode,
        "stdout_excerpt": completed.stdout,
        "stderr_excerpt": completed.stderr,
        "paths": paths,
    }
    if completed.returncode != 0:
        return _failed(
            "apply_patch",
            "Unable to apply patch",
            completed.stderr.strip() or "git apply failed",
            payload=payload,
        )
    for pycache_path in context.workspace_path.rglob("__pycache__"):
        if pycache_path.is_dir():
            shutil.rmtree(pycache_path, ignore_errors=True)
    return tool_observation(
        tool_name="apply_patch",
        status="succeeded",
        summary="Applied patch",
        payload=payload,
        stdout_excerpt=payload["stdout_excerpt"],
        stderr_excerpt=payload["stderr_excerpt"],
    )


def default_tool_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            ToolSpec(
                name="glob_file_search",
                description="Find repo files using a relative glob pattern.",
                args_model=GlobFileSearchArgs,
                risk_level=ToolRisk.READ_ONLY,
                executor=_execute_glob_file_search,
            ),
            ToolSpec(
                name="list_dir",
                description="List entries in a repo-relative directory.",
                args_model=ListDirArgs,
                risk_level=ToolRisk.READ_ONLY,
                executor=_execute_list_dir,
            ),
            ToolSpec(
                name="read_file",
                description="Read text content from a repo-relative file.",
                args_model=ReadFileArgs,
                risk_level=ToolRisk.READ_ONLY,
                executor=_execute_read_file,
            ),
            ToolSpec(
                name="rg",
                description="Search repo text using ripgrep.",
                args_model=RgArgs,
                risk_level=ToolRisk.READ_ONLY,
                executor=_execute_rg,
            ),
            ToolSpec(
                name="search_code",
                description="Search repo text using ripgrep.",
                args_model=RgArgs,
                risk_level=ToolRisk.READ_ONLY,
                executor=_execute_rg,
            ),
            ToolSpec(
                name="git",
                description="Run a structured read-only git operation.",
                args_model=GitArgs,
                risk_level=ToolRisk.READ_ONLY,
                executor=_git,
            ),
            ToolSpec(
                name="run_shell_command",
                description="Run a shell command through the restricted shell policy.",
                args_model=RunShellCommandArgs,
                risk_level=ToolRisk.SHELL_RESTRICTED,
                executor=_run_shell_command,
            ),
            ToolSpec(
                name="run_command",
                description="Run a declared verification command.",
                args_model=RunCommandArgs,
                risk_level=ToolRisk.SHELL_RESTRICTED,
                executor=_run_command,
            ),
            ToolSpec(
                name="apply_patch",
                description="Apply a unified diff patch to the workspace.",
                args_model=ApplyPatchArgs,
                risk_level=ToolRisk.WRITE_WORKTREE,
                executor=_apply_patch,
            ),
        ]
    )
