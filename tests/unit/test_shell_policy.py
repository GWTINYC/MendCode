from pathlib import Path

import pytest

from app.workspace.shell_policy import ShellPolicy


def make_policy(root: Path) -> ShellPolicy:
    return ShellPolicy(allowed_root=root, timeout_seconds=10)


@pytest.mark.parametrize(
    "command",
    [
        "ls",
        "pwd",
        "git status",
        "git diff",
        "rg TODO",
        "cat README.md",
        "head README.md",
        "tail README.md",
        "find . -maxdepth 1 -type f",
        "printf hello",
    ],
)
def test_shell_policy_auto_allows_low_risk_read_only_commands(
    tmp_path: Path,
    command: str,
) -> None:
    decision = make_policy(tmp_path).evaluate(command, tmp_path)

    assert decision.allowed is True
    assert decision.requires_confirmation is False
    assert decision.risk_level == "low"


@pytest.mark.parametrize(
    "command",
    [
        "rm README.md",
        "git commit -m update",
        "git push",
        "pip install requests",
        "curl https://example.test",
        "echo hello > README.md",
        "printf hello > marker.txt",
    ],
)
def test_shell_policy_requires_confirmation_for_risky_commands(
    tmp_path: Path,
    command: str,
) -> None:
    decision = make_policy(tmp_path).evaluate(command, tmp_path)

    assert decision.allowed is False
    assert decision.requires_confirmation is True
    assert decision.risk_level in {"medium", "high"}


@pytest.mark.parametrize("command", ["rm -rf /", "sudo rm -rf /", "rm ../outside.txt"])
def test_shell_policy_rejects_critical_commands(tmp_path: Path, command: str) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    decision = make_policy(repo_path).evaluate(command, repo_path)

    assert decision.allowed is False
    assert decision.requires_confirmation is False
    assert decision.risk_level == "critical"


def test_shell_policy_rejects_cwd_outside_allowed_root(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    outside_path = tmp_path / "outside"
    repo_path.mkdir()
    outside_path.mkdir()

    decision = make_policy(repo_path).evaluate("ls", outside_path)

    assert decision.allowed is False
    assert decision.requires_confirmation is False
    assert decision.reason == "cwd escapes allowed workspace root"
