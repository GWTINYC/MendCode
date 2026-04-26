import re
import shlex
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ShellRiskLevel = Literal["low", "medium", "high", "critical"]

_LOW_RISK_COMMANDS = {"ls", "pwd", "rg", "cat", "head", "tail", "find", "printf"}
_WRITE_COMMANDS = {"rm", "mv", "cp"}
_NETWORK_COMMANDS = {"curl", "wget"}
_INSTALL_COMMANDS = {"apt", "apt-get", "brew"}
_SHELL_SUBSTITUTION_RE = re.compile(r"(`|\$\()")
_REDIRECT_RE = re.compile(r"^(?:&>|[0-9]?>>|[0-9]?>)(?P<path>.*)$")
_INLINE_REDIRECT_RE = re.compile(r"(?:&>|[0-9]?>>|[0-9]?>)(?P<path>.*)$")
_CRITICAL_RM_ROOT_RE = re.compile(
    r"^(?:sudo\s+)?rm\s+-(?:[^\s]*r[^\s]*f|[^\s]*f[^\s]*r)\s+/(?:\s|$)"
)


class ShellPolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    requires_confirmation: bool
    risk_level: ShellRiskLevel
    reason: str | None = None


class ShellPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_root: Path
    timeout_seconds: int = Field(default=30, ge=1)

    def evaluate(self, command: str, cwd: Path) -> ShellPolicyDecision:
        stripped = command.strip()
        if not stripped:
            return _reject("command is required", risk_level="medium")

        root_decision = _evaluate_cwd(allowed_root=self.allowed_root, cwd=cwd)
        if root_decision is not None:
            return root_decision

        if _CRITICAL_RM_ROOT_RE.search(stripped):
            return _reject("refusing destructive root removal", risk_level="critical")

        try:
            tokens = shlex.split(stripped, posix=True)
        except ValueError as exc:
            return _confirm(f"unable to safely parse command: {exc}", risk_level="high")
        if not tokens:
            return _reject("command is required", risk_level="medium")

        redirect_decision = _evaluate_redirection(
            tokens=tokens,
            cwd=cwd,
            allowed_root=self.allowed_root,
        )
        if redirect_decision is not None:
            return redirect_decision

        executable, args = _strip_sudo(tokens)

        path_decision = _evaluate_write_paths(
            executable=executable,
            args=args,
            cwd=cwd,
            allowed_root=self.allowed_root,
        )
        if path_decision is not None:
            return path_decision

        if _has_shell_control(stripped=stripped, tokens=tokens):
            return _confirm("compound shell command requires confirmation", risk_level="high")

        if executable == "git":
            return _evaluate_git(args)
        if executable in _NETWORK_COMMANDS:
            return _confirm("network command requires confirmation", risk_level="high")
        if _is_install_command(executable, args):
            return _confirm("install command requires confirmation", risk_level="high")
        if executable in _WRITE_COMMANDS:
            return _confirm("write command requires confirmation", risk_level="high")
        if executable in _LOW_RISK_COMMANDS:
            return _evaluate_low_risk_command(
                executable=executable,
                args=args,
                cwd=cwd,
                allowed_root=self.allowed_root,
            )

        return _confirm("command is not in the low-risk allowlist", risk_level="medium")


def _allow(reason: str = "low-risk read-only command") -> ShellPolicyDecision:
    return ShellPolicyDecision(
        allowed=True,
        requires_confirmation=False,
        risk_level="low",
        reason=reason,
    )


def _confirm(reason: str, *, risk_level: Literal["medium", "high"]) -> ShellPolicyDecision:
    return ShellPolicyDecision(
        allowed=False,
        requires_confirmation=True,
        risk_level=risk_level,
        reason=reason,
    )


def _reject(reason: str, *, risk_level: ShellRiskLevel) -> ShellPolicyDecision:
    return ShellPolicyDecision(
        allowed=False,
        requires_confirmation=False,
        risk_level=risk_level,
        reason=reason,
    )


def _evaluate_cwd(*, allowed_root: Path, cwd: Path) -> ShellPolicyDecision | None:
    resolved_root = allowed_root.resolve()
    resolved_cwd = cwd.resolve()
    try:
        resolved_cwd.relative_to(resolved_root)
    except ValueError:
        return _reject("cwd escapes allowed workspace root", risk_level="critical")
    return None


def _strip_sudo(tokens: list[str]) -> tuple[str, list[str]]:
    if tokens[0] == "sudo" and len(tokens) > 1:
        return tokens[1], tokens[2:]
    return tokens[0], tokens[1:]


def _is_install_command(executable: str, args: list[str]) -> bool:
    if executable in _INSTALL_COMMANDS:
        return bool(args and args[0] in {"install", "add"})
    if executable in {"pip", "pip3"}:
        return bool(args and args[0] == "install")
    if executable == "uv":
        return bool(args[:2] == ["pip", "install"] or (args and args[0] in {"add", "sync"}))
    if executable in {"npm", "pnpm"}:
        return bool(args and args[0] in {"install", "i", "add"})
    if executable == "yarn":
        return bool(args and args[0] in {"add", "install"})
    return False


def _has_shell_control(*, stripped: str, tokens: list[str]) -> bool:
    if _SHELL_SUBSTITUTION_RE.search(stripped):
        return True
    return any(token in {"&&", "||", ";", "|"} for token in tokens)


def _evaluate_git(args: list[str]) -> ShellPolicyDecision:
    if not args:
        return _confirm("git command requires an explicit subcommand", risk_level="medium")
    subcommand = args[0]
    if subcommand in {"status", "diff"}:
        return _allow("low-risk git inspection command")
    if subcommand in {
        "add",
        "commit",
        "push",
        "checkout",
        "reset",
        "clean",
        "merge",
        "rebase",
        "restore",
        "switch",
    }:
        return _confirm(f"git {subcommand} requires confirmation", risk_level="high")
    return _confirm(f"git {subcommand} requires confirmation", risk_level="medium")


def _evaluate_low_risk_command(
    *,
    executable: str,
    args: list[str],
    cwd: Path,
    allowed_root: Path,
) -> ShellPolicyDecision:
    if executable == "find" and any(arg in {"-delete", "-exec", "-execdir", "-ok"} for arg in args):
        return _confirm("find with side-effecting actions requires confirmation", risk_level="high")
    if executable == "pwd":
        return _allow()
    if executable in {"cat", "head", "tail", "ls", "find"}:
        if _has_escaping_path(args=args, cwd=cwd, allowed_root=allowed_root):
            return _confirm("read path escapes allowed workspace root", risk_level="medium")
    return _allow()


def _evaluate_write_paths(
    *,
    executable: str,
    args: list[str],
    cwd: Path,
    allowed_root: Path,
) -> ShellPolicyDecision | None:
    if executable not in _WRITE_COMMANDS:
        return None
    for arg in args:
        if arg.startswith("-"):
            continue
        if _path_escapes_root(arg, cwd=cwd, allowed_root=allowed_root):
            return _reject("write path escapes allowed workspace root", risk_level="critical")
    return None


def _evaluate_redirection(
    *,
    tokens: list[str],
    cwd: Path,
    allowed_root: Path,
) -> ShellPolicyDecision | None:
    for index, token in enumerate(tokens):
        target: str | None = None
        if token in {">", ">>", "1>", "2>", "1>>", "2>>", "&>"}:
            target = tokens[index + 1] if index + 1 < len(tokens) else ""
        else:
            match = _REDIRECT_RE.match(token)
            if match is not None:
                target = match.group("path")
            else:
                inline_match = _INLINE_REDIRECT_RE.search(token)
                if inline_match is not None:
                    target = inline_match.group("path")
        if target is None:
            continue
        if target and _path_escapes_root(target, cwd=cwd, allowed_root=allowed_root):
            return _reject(
                "redirection target escapes allowed workspace root",
                risk_level="critical",
            )
        return _confirm("shell redirection requires confirmation", risk_level="high")
    return None


def _has_escaping_path(*, args: list[str], cwd: Path, allowed_root: Path) -> bool:
    for arg in args:
        if arg.startswith("-"):
            continue
        if _path_escapes_root(arg, cwd=cwd, allowed_root=allowed_root):
            return True
    return False


def _path_escapes_root(value: str, *, cwd: Path, allowed_root: Path) -> bool:
    if not value:
        return False
    candidate = Path(value)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (cwd / candidate).resolve()
    try:
        resolved.relative_to(allowed_root.resolve())
    except ValueError:
        return True
    return False
