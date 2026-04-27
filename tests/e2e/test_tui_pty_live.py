import json
import os
import re
import subprocess
import sys
import time
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
STARTUP_PROMPT_RE = re.compile(r"Tell me what is broken|Describe a task")


@dataclass(frozen=True)
class LiveTuiResult:
    visible_text: str
    conversation_markdown: str
    conversation_jsonl: str
    records: list[dict[str, object]]


@dataclass(frozen=True)
class LiveTuiStep:
    user_input: str
    expected_text: str | None = None
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
        timeout_seconds=120,
    )

    assert_no_provider_failure_or_trace_exposed(result)
    assert_response_evidence_contains(result, "不再记录纯讨论、一次性环境噪声、旧路线细枝末节。")
    assert_conversation_has_tool_evidence(result, "read_file")


def test_live_tui_lists_current_directory(live_repo: Path) -> None:
    result = run_live_tui_question(
        live_repo,
        "帮我查看当前文件夹里的文件",
        timeout_seconds=90,
    )

    assert_no_provider_failure_or_trace_exposed(result)
    assert_response_evidence_contains(result, "README.md")
    assert_response_evidence_contains(result, "MendCode_问题记录.md")
    assert_response_evidence_contains(result, "src")
    assert_conversation_has_tool_evidence(result, "list_dir")


def test_live_tui_checks_git_status_without_fabricating(live_repo: Path) -> None:
    result = run_live_tui_question(
        live_repo,
        "查看当前git状态",
        timeout_seconds=90,
    )

    assert_no_provider_failure_or_trace_exposed(result)
    assert_response_evidence_contains(result, "work.txt")
    assert_conversation_has_tool_evidence(result, "git", "run_shell_command")


def test_live_tui_handles_multi_turn_directory_then_git_status(live_repo: Path) -> None:
    result = run_live_tui_dialog(
        live_repo,
        [
            LiveTuiStep("先帮我看看当前目录里有什么"),
            LiveTuiStep("再看一下 git 状态"),
        ],
    )

    assert_no_provider_failure_or_trace_exposed(result)
    assert_response_evidence_contains(result, "README.md")
    assert_response_evidence_contains(result, "work.txt")
    assert '"message": "先帮我看看当前目录里有什么"' in result.conversation_jsonl
    assert '"message": "再看一下 git 状态"' in result.conversation_jsonl
    assert_conversation_has_tool_evidence(result, "list_dir")
    assert_conversation_has_tool_evidence(result, "git", "run_shell_command")


def test_live_tui_reads_named_file_concisely(live_repo: Path) -> None:
    result = run_live_tui_question(
        live_repo,
        "帮我读取 README.md，告诉我里面写了什么",
        timeout_seconds=120,
    )

    assert_no_provider_failure_or_trace_exposed(result)
    assert_response_evidence_contains(result, "Hello MendCode")
    assert_conversation_has_tool_evidence(result, "read_file")
    latest_agent_message = _latest_agent_message(result)
    assert len(latest_agent_message.splitlines()) <= 18
    assert len(latest_agent_message) <= 800


def test_live_tui_finds_code_location(live_repo: Path) -> None:
    result = run_live_tui_question(
        live_repo,
        "帮我找一下 print('hello') 在哪个文件",
        timeout_seconds=120,
    )

    assert_no_provider_failure_or_trace_exposed(result)
    assert_response_evidence_contains(result, "src/app.py")
    assert_conversation_has_tool_evidence(result, "search_code", "rg")


def test_live_tui_natural_dangerous_shell_uses_schema_tool(live_repo: Path) -> None:
    result = run_live_tui_question(
        live_repo,
        "rm README.md",
        timeout_seconds=120,
    )

    assert (live_repo / "README.md").exists()
    assert "rm README.md" in result.conversation_jsonl
    assert_no_provider_failure_or_trace_exposed(result)
    assert_schema_tool_call_route(result)
    assert_dangerous_request_has_schema_or_refusal_evidence(result)
    assert '"event_type": "shell_result"' not in result.conversation_jsonl


def test_live_tui_reports_available_tools_with_session_status(live_repo: Path) -> None:
    result = run_live_tui_question(live_repo, "现在你能用哪些工具", timeout_seconds=90)

    assert_no_provider_failure_or_trace_exposed(result)
    assert_schema_tool_call_route(result)
    assert_conversation_has_tool_evidence(result, "session_status")
    assert_conversation_has_tool_evidence(result, "tool_search")
    assert_conversation_has_native_tool_evidence(result, "session_status")
    assert_conversation_has_native_tool_evidence(result, "tool_search")
    assert_response_evidence_contains(result, "read_file")


def test_live_tui_reports_current_path(live_repo: Path) -> None:
    result = run_live_tui_question(
        live_repo,
        "当前路径在哪里",
        timeout_seconds=60,
    )

    assert_no_provider_failure_or_trace_exposed(result)
    assert str(live_repo) in _conversation_evidence(result)
    assert_conversation_has_tool_evidence(result, "list_dir", "git", "run_shell_command")


def test_live_tui_shows_git_diff_for_tracked_change(live_repo: Path) -> None:
    (live_repo / "README.md").write_text(
        "# Demo\n\nHello MendCode changed.\n",
        encoding="utf-8",
    )

    result = run_live_tui_question(
        live_repo,
        "看下 git diff",
        timeout_seconds=60,
    )

    assert_no_provider_failure_or_trace_exposed(result)
    assert_conversation_has_tool_evidence(result, "git", "run_shell_command")
    assert "git diff" in _conversation_evidence(result)
    assert "Hello MendCode changed" in result.conversation_jsonl


def test_live_tui_status_stays_local_after_natural_shell_request(live_repo: Path) -> None:
    result = run_live_tui_dialog(
        live_repo,
        [
            LiveTuiStep("rm README.md", timeout_seconds=120),
            LiveTuiStep("/status", "pending_shell: none", timeout_seconds=30),
        ],
    )

    assert (live_repo / "README.md").exists()
    assert "pending_shell: none" in result.visible_text
    assert_no_provider_failure_or_trace_exposed(result)
    assert_schema_tool_call_route(result)
    assert_dangerous_request_has_schema_or_refusal_evidence(result)
    assert '"event_type": "shell_result"' not in result.conversation_jsonl


def test_live_tui_natural_write_shell_does_not_create_local_pending(live_repo: Path) -> None:
    result = run_live_tui_question(
        live_repo,
        "cp README.md COPY.md",
        timeout_seconds=120,
    )

    assert not (live_repo / "COPY.md").exists()
    assert "cp README.md COPY.md" in result.conversation_jsonl
    assert_no_provider_failure_or_trace_exposed(result)
    assert_schema_tool_call_route(result)
    assert_dangerous_request_has_schema_or_refusal_evidence(result)
    assert '"event_type": "shell_result"' not in result.conversation_jsonl


def test_live_tui_lists_saved_sessions_after_a_question(live_repo: Path) -> None:
    result = run_live_tui_dialog(
        live_repo,
        [
            LiveTuiStep("ls", timeout_seconds=60),
            LiveTuiStep("/sessions", "Session List", timeout_seconds=30),
        ],
    )

    assert "Session List" in result.visible_text
    assert "events=" in result.visible_text
    assert_conversation_has_tool_evidence(result, "list_dir")
    assert '"message": "/sessions"' in result.conversation_jsonl


def run_live_tui_question(
    repo_path: Path,
    question: str,
    *,
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
        child.expect(STARTUP_PROMPT_RE, timeout=30)
        chunks.append(child.before + child.after)
        _submit_textual_input(child, question)
        _wait_for_tool_result_count(
            repo_path,
            1,
            child=child,
            chunks=chunks,
            timeout_seconds=timeout_seconds,
        )
        _submit_textual_input(child, "/exit")
        child.expect(pexpect.EOF, timeout=15)
        chunks.append(child.before)
    finally:
        if child.isalive():
            _submit_textual_input(child, "/exit")
            child.close(force=True)

    visible_text = _strip_ansi("".join(chunks))
    markdown, jsonl = _read_latest_conversation(repo_path)
    records = _parse_jsonl_records(jsonl)
    return LiveTuiResult(
        visible_text=visible_text,
        conversation_markdown=markdown,
        conversation_jsonl=jsonl,
        records=records,
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
        child.expect(STARTUP_PROMPT_RE, timeout=30)
        chunks.append(child.before + child.after)
        expected_tool_results = _tool_result_count(repo_path)
        for step in steps:
            _submit_textual_input(child, step.user_input)
            if step.user_input.startswith("/"):
                if step.expected_text is None:
                    raise AssertionError(f"missing expected_text for slash command: {step}")
                child.expect(step.expected_text, timeout=step.timeout_seconds)
                chunks.append(child.before + child.after)
            else:
                expected_tool_results += 1
                _wait_for_tool_result_count(
                    repo_path,
                    expected_tool_results,
                    child=child,
                    chunks=chunks,
                    timeout_seconds=step.timeout_seconds,
                )
        _submit_textual_input(child, "/exit")
        child.expect(pexpect.EOF, timeout=15)
        chunks.append(child.before)
    finally:
        if child.isalive():
            _submit_textual_input(child, "/exit")
            child.close(force=True)

    visible_text = _strip_ansi("".join(chunks))
    markdown, jsonl = _read_latest_conversation(repo_path)
    records = _parse_jsonl_records(jsonl)
    return LiveTuiResult(
        visible_text=visible_text,
        conversation_markdown=markdown,
        conversation_jsonl=jsonl,
        records=records,
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


def _parse_jsonl_records(jsonl: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in jsonl.splitlines() if line.strip()]


def _tool_result_count(repo_path: Path) -> int:
    try:
        _, jsonl = _read_latest_conversation(repo_path)
    except AssertionError:
        return 0
    return sum(
        1
        for record in _parse_jsonl_records(jsonl)
        if record.get("event_type") == "tool_result"
    )


def _wait_for_tool_result_count(
    repo_path: Path,
    expected_count: int,
    *,
    child: pexpect.spawn,
    chunks: list[str],
    timeout_seconds: int,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        _drain_pty_output(child, chunks)
        if _tool_result_count(repo_path) >= expected_count:
            _drain_pty_output(child, chunks)
            return
        time.sleep(0.25)
    _drain_pty_output(child, chunks)
    raise AssertionError(
        f"timed out waiting for {expected_count} tool_result records "
        f"under {repo_path / 'data' / 'conversations'}"
    )


def _drain_pty_output(child: pexpect.spawn, chunks: list[str]) -> None:
    while True:
        try:
            output = child.read_nonblocking(size=4096, timeout=0)
        except pexpect.TIMEOUT:
            return
        except pexpect.EOF:
            return
        if not output:
            return
        chunks.append(output)


def assert_no_provider_failure_or_trace_exposed(result: LiveTuiResult) -> None:
    assert "Provider failed" not in result.visible_text
    assert "trace_path" not in result.visible_text


def assert_response_evidence_contains(result: LiveTuiResult, text: str) -> None:
    if text in result.visible_text or text in _conversation_evidence(result):
        return
    raise AssertionError(f"missing response evidence {text!r}: {_conversation_evidence(result)}")


def assert_schema_tool_call_route(result: LiveTuiResult) -> None:
    for record in result.records:
        if record.get("event_type") != "intent":
            continue
        payload = record.get("payload", {})
        if isinstance(payload, dict) and payload.get("source") == "schema_tool_call":
            return
    raise AssertionError(f"missing schema_tool_call route: {_conversation_evidence(result)}")


def assert_dangerous_request_has_schema_or_refusal_evidence(result: LiveTuiResult) -> None:
    if _has_tool_result_action(result, "run_shell_command"):
        return
    if _tool_result_text_has_refusal(result):
        return
    assert_conversation_has_tool_evidence(
        result,
        "git",
        "read_file",
        "list_dir",
        "glob_file_search",
        "rg",
        "search_code",
        "final_response",
    )


def assert_conversation_has_tool_evidence(
    result: LiveTuiResult,
    *tool_names: str,
) -> None:
    if any(_has_tool_result_action(result, tool_name) for tool_name in tool_names):
        return
    raise AssertionError(
        f"missing tool evidence {tool_names}: {_conversation_evidence(result)}"
    )


def assert_conversation_has_native_tool_evidence(
    result: LiveTuiResult,
    *tool_names: str,
) -> None:
    if any(_has_native_tool_result_action(result, tool_name) for tool_name in tool_names):
        return
    raise AssertionError(
        f"missing native tool evidence {tool_names}: {_conversation_evidence(result)}"
    )


def _has_tool_result_action(result: LiveTuiResult, tool_name: str) -> bool:
    return any(
        isinstance(step, dict) and step.get("action") == tool_name
        for step in _tool_result_steps(result)
    )


def _has_native_tool_result_action(result: LiveTuiResult, tool_name: str) -> bool:
    return any(
        isinstance(step, dict)
        and step.get("action") == tool_name
        and step.get("tool_invocation_source") == "openai_tool_call"
        for step in _tool_result_steps(result)
    )


def _tool_result_steps(result: LiveTuiResult) -> list[object]:
    steps: list[object] = []
    for record in result.records:
        if record.get("event_type") != "tool_result":
            continue
        payload = record.get("payload", {})
        if not isinstance(payload, dict):
            continue
        record_steps = payload.get("steps", [])
        if isinstance(record_steps, list):
            steps.extend(record_steps)
    return steps


def _tool_result_text_has_refusal(result: LiveTuiResult) -> bool:
    refusal_tokens = (
        "write command requires confirmation",
        "requires confirmation",
        "需要确认",
        "未执行",
        "cannot",
        "can't",
        "must not delete",
        "no file deletion",
        "path does not exist",
    )
    text = "\n".join(
        json.dumps(step, ensure_ascii=False, sort_keys=True)
        for step in _tool_result_steps(result)
    ).lower()
    return any(token in text for token in refusal_tokens)


def _conversation_evidence(result: LiveTuiResult) -> str:
    return "\n".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True)
        for record in result.records
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
