import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pexpect
import pytest
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_PROVIDER_ENV = (
    "MENDCODE_PROVIDER",
    "MENDCODE_MODEL",
    "MENDCODE_BASE_URL",
    "MENDCODE_API_KEY",
)
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@dataclass(frozen=True)
class LiveTuiResult:
    visible_text: str
    conversation_markdown: str
    conversation_jsonl: str


@dataclass(frozen=True)
class LiveTuiStep:
    user_input: str
    expected_text: str
    timeout_seconds: int = 90


@pytest.fixture
def live_repo(tmp_path: Path) -> Iterator[Path]:
    repo_path = tmp_path / "live-repo"
    repo_path.mkdir()
    _run_git(repo_path, "init")
    _run_git(repo_path, "config", "user.email", "test@example.com")
    _run_git(repo_path, "config", "user.name", "Test User")
    (repo_path / "README.md").write_text("# Demo\n\nHello MendCode.\n", encoding="utf-8")
    (repo_path / "CONTRIBUTING.md").write_text(
        "请先运行测试，再提交变更。\n",
        encoding="utf-8",
    )
    (repo_path / "MendCode_问题记录.md").write_text(
        "\n".join(
            [
                "# MendCode 问题记录",
                "",
                "## 问题",
                "",
                "这里记录需要持续修复的问题。",
                "不再记录纯讨论、一次性环境噪声、旧路线细枝末节。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (repo_path / "src").mkdir()
    (repo_path / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    _run_git(repo_path, "add", ".")
    _run_git(repo_path, "commit", "-m", "init")
    (repo_path / "work.txt").write_text("dirty\n", encoding="utf-8")
    yield repo_path


def test_live_tui_answers_last_sentence_with_tools(live_repo: Path) -> None:
    result = run_live_tui_question(
        live_repo,
        "MendCode问题记录的最后一句话是什么",
        expected_text="不再记录纯讨论、一次性环境噪声、旧路线细枝末节。",
        timeout_seconds=120,
    )

    assert "Provider failed" not in result.visible_text
    assert "trace_path" not in result.visible_text
    assert "不再记录纯讨论、一次性环境噪声、旧路线细枝末节。" in result.visible_text
    assert "read_file" in result.conversation_jsonl


def test_live_tui_lists_current_directory(live_repo: Path) -> None:
    result = run_live_tui_question(
        live_repo,
        "帮我查看当前文件夹里的文件",
        expected_text="README.md",
        timeout_seconds=90,
    )

    assert "Provider failed" not in result.visible_text
    assert "README.md" in result.visible_text
    assert "MendCode_问题记录.md" in result.visible_text
    assert "src" in result.visible_text
    assert ("list_dir" in result.conversation_jsonl) or (
        '"kind":"shell"' in _compact_jsonl(result)
    )


def test_live_tui_checks_git_status_without_fabricating(live_repo: Path) -> None:
    result = run_live_tui_question(
        live_repo,
        "查看当前git状态",
        expected_text="work.txt",
        timeout_seconds=90,
    )

    assert "Provider failed" not in result.visible_text
    assert "work.txt" in result.visible_text
    assert "shell_result" in result.conversation_jsonl
    assert "git status" in result.conversation_jsonl


def test_live_tui_handles_multi_turn_directory_then_git_status(live_repo: Path) -> None:
    result = run_live_tui_dialog(
        live_repo,
        [
            LiveTuiStep("先帮我看看当前目录里有什么", "README.md"),
            LiveTuiStep("再看一下 git 状态", "work.txt"),
        ],
    )

    assert "Provider failed" not in result.visible_text
    assert "README.md" in result.visible_text
    assert "work.txt" in result.visible_text
    assert '"message": "先帮我看看当前目录里有什么"' in result.conversation_jsonl
    assert '"message": "再看一下 git 状态"' in result.conversation_jsonl


def test_live_tui_reads_named_file_concisely(live_repo: Path) -> None:
    result = run_live_tui_question(
        live_repo,
        "帮我读取 README.md，告诉我里面写了什么",
        expected_text="Hello MendCode",
        timeout_seconds=120,
    )

    assert "Provider failed" not in result.visible_text
    assert "Hello MendCode" in result.visible_text
    assert "read_file" in result.conversation_jsonl
    latest_agent_message = _latest_agent_message(result)
    assert len(latest_agent_message.splitlines()) <= 18
    assert len(latest_agent_message) <= 800


def test_live_tui_finds_code_location(live_repo: Path) -> None:
    result = run_live_tui_question(
        live_repo,
        "帮我找一下 print('hello') 在哪个文件",
        expected_text="src/app.py",
        timeout_seconds=120,
    )

    assert "Provider failed" not in result.visible_text
    assert "src/app.py" in result.visible_text
    assert ("search_code" in result.conversation_jsonl) or ("rg" in result.conversation_jsonl)


def test_live_tui_requires_confirmation_and_cancels_dangerous_shell(live_repo: Path) -> None:
    result = run_live_tui_dialog(
        live_repo,
        [
            LiveTuiStep("rm README.md", "Shell 命令需要确认后执行。"),
            LiveTuiStep("取消", "已取消待确认的 shell 命令。", timeout_seconds=30),
        ],
    )

    assert (live_repo / "README.md").exists()
    assert "rm README.md" in result.conversation_jsonl
    assert "Shell 命令需要确认后执行。" in result.visible_text
    assert "已取消待确认的 shell 命令。" in result.visible_text
    assert '"event_type": "shell_result"' not in result.conversation_jsonl


def run_live_tui_question(
    repo_path: Path,
    question: str,
    *,
    expected_text: str,
    timeout_seconds: int,
) -> LiveTuiResult:
    env = _live_provider_env(repo_path)
    child = pexpect.spawn(
        sys.executable,
        ["-m", "app.cli.main"],
        cwd=str(repo_path),
        env=env,
        encoding="utf-8",
        timeout=timeout_seconds,
        dimensions=(32, 140),
    )
    chunks: list[str] = []
    try:
        child.expect("Tell me what is broken", timeout=30)
        chunks.append(child.before + child.after)
        _submit_textual_input(child, question)
        child.expect(expected_text, timeout=timeout_seconds)
        chunks.append(child.before + child.after)
        _submit_textual_input(child, "/exit")
        child.expect(pexpect.EOF, timeout=15)
        chunks.append(child.before)
    finally:
        if child.isalive():
            _submit_textual_input(child, "/exit")
            child.close(force=True)

    visible_text = _strip_ansi("".join(chunks))
    markdown, jsonl = _read_latest_conversation(repo_path)
    return LiveTuiResult(
        visible_text=visible_text,
        conversation_markdown=markdown,
        conversation_jsonl=jsonl,
    )


def run_live_tui_dialog(repo_path: Path, steps: list[LiveTuiStep]) -> LiveTuiResult:
    env = _live_provider_env(repo_path)
    child = pexpect.spawn(
        sys.executable,
        ["-m", "app.cli.main"],
        cwd=str(repo_path),
        env=env,
        encoding="utf-8",
        timeout=max((step.timeout_seconds for step in steps), default=90),
        dimensions=(32, 140),
    )
    chunks: list[str] = []
    try:
        child.expect("Tell me what is broken", timeout=30)
        chunks.append(child.before + child.after)
        for step in steps:
            _submit_textual_input(child, step.user_input)
            child.expect(step.expected_text, timeout=step.timeout_seconds)
            chunks.append(child.before + child.after)
        _submit_textual_input(child, "/exit")
        child.expect(pexpect.EOF, timeout=15)
        chunks.append(child.before)
    finally:
        if child.isalive():
            _submit_textual_input(child, "/exit")
            child.close(force=True)

    visible_text = _strip_ansi("".join(chunks))
    markdown, jsonl = _read_latest_conversation(repo_path)
    return LiveTuiResult(
        visible_text=visible_text,
        conversation_markdown=markdown,
        conversation_jsonl=jsonl,
    )


def _live_provider_env(repo_path: Path) -> dict[str, str]:
    env_file_values = dotenv_values(PROJECT_ROOT / ".env")
    missing = [
        name
        for name in REQUIRED_PROVIDER_ENV
        if not (os.environ.get(name) or env_file_values.get(name))
    ]
    if missing:
        pytest.fail(
            "Live PTY TUI tests require real OpenAI-compatible provider env: "
            + ", ".join(missing)
        )
    env = os.environ.copy()
    for key, value in env_file_values.items():
        if value is not None and key not in env:
            env[key] = value
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["MENDCODE_PROJECT_ROOT"] = str(repo_path)
    env["MENDCODE_PROVIDER"] = "openai-compatible"
    return env


def _read_latest_conversation(repo_path: Path) -> tuple[str, str]:
    conversations_dir = repo_path / "data" / "conversations"
    markdown_files = sorted(conversations_dir.glob("*.md"))
    jsonl_files = sorted(conversations_dir.glob("*.jsonl"))
    assert markdown_files, f"no conversation markdown files under {conversations_dir}"
    assert jsonl_files, f"no conversation jsonl files under {conversations_dir}"
    return (
        markdown_files[-1].read_text(encoding="utf-8"),
        jsonl_files[-1].read_text(encoding="utf-8"),
    )


def _run_git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _compact_jsonl(result: LiveTuiResult) -> str:
    return result.conversation_jsonl.replace(" ", "")


def _latest_agent_message(result: LiveTuiResult) -> str:
    messages: list[str] = []
    for line in result.conversation_jsonl.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("event_type") != "message":
            continue
        payload = record.get("payload", {})
        if not isinstance(payload, dict) or payload.get("role") != "Agent":
            continue
        message = payload.get("message")
        if isinstance(message, str):
            messages.append(message)
    return messages[-1] if messages else ""


def _submit_textual_input(child: pexpect.spawn, text: str) -> None:
    child.send(text)
    child.send("\r")
