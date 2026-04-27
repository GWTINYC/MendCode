import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_OUTPUT_LIMIT = 12_000
_DEFAULT_TUI_SCENARIO_TARGETS = ["tests/scenarios", "tests/e2e"]


@dataclass(frozen=True)
class ScenarioAuditResult:
    command: list[str]
    cwd: Path
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


def extract_pytest_failures(output: str) -> list[str]:
    failures: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.startswith("FAILED "):
            continue
        failure = line.removeprefix("FAILED ").split(" - ", 1)[0].strip()
        if failure:
            failures.append(failure)
    return failures


def default_tui_scenario_audit_command() -> list[str]:
    return [sys.executable, "-m", "pytest", "-q", *_DEFAULT_TUI_SCENARIO_TARGETS]


def run_tui_scenario_audit_command(
    *,
    cwd: Path,
    command: list[str] | None = None,
) -> ScenarioAuditResult:
    audit_command = command or default_tui_scenario_audit_command()
    started = time.monotonic()
    completed = subprocess.run(
        audit_command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    return ScenarioAuditResult(
        command=audit_command,
        cwd=cwd,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_ms=duration_ms,
    )


def write_tui_scenario_audit_report(
    *,
    report_dir: Path,
    result: ScenarioAuditResult,
    run_at: str,
    commit: str,
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{_report_stem(run_at)}-tui-scenario-audit.md"
    combined_output = "\n".join(part for part in [result.stdout, result.stderr] if part)
    failures = extract_pytest_failures(combined_output)
    issue_count = len(failures) if failures else int(result.exit_code != 0)

    lines = [
        "# TUI 场景自动巡检报告",
        "",
        f"- run_at: {run_at}",
        f"- commit: {commit}",
        f"- cwd: {result.cwd}",
        f"- command: {' '.join(result.command)}",
        f"- exit_code: {result.exit_code}",
        f"- duration_ms: {result.duration_ms}",
        f"- 问题数：{issue_count}",
        "",
        "## 覆盖范围",
        "",
        "- 自动运行 `tests/scenarios`，通过 Textual `run_test()` 模拟用户输入。",
        (
            "- 自动运行 `tests/e2e`，通过 PTY 启动真实 TUI 进程，并要求真实 "
            "OpenAI-compatible provider 环境变量。"
        ),
        (
            "- 覆盖目录查看、中文 Git 状态、技术栈识别、文件读取、文档末句提问、"
            "搜索、路径查看、git diff、失败提示、危险命令确认、会话列表和恢复。"
        ),
        (
            "- 断言 route、tool evidence、可见输出简洁性、no-fabrication、"
            "文件内容不刷屏和 resume compact context。"
        ),
        "",
        "## 问题记录",
        "",
    ]
    if not failures and result.exit_code == 0:
        lines.append("- 未发现失败场景。")
    elif failures:
        lines.extend(f"- {failure}" for failure in failures)
    else:
        lines.append("- 场景命令非零退出，但未解析到 pytest FAILED 行；请查看输出摘要。")

    lines.extend(
        [
            "",
            "## 输出摘要",
            "",
            "```text",
            _excerpt(combined_output),
            "```",
            "",
        ]
    )
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def current_git_commit(cwd: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() or "unknown"


def _excerpt(text: str) -> str:
    if len(text) <= _OUTPUT_LIMIT:
        return text.rstrip()
    return text[:_OUTPUT_LIMIT].rstrip() + "\n...[truncated]"


def _report_stem(run_at: str) -> str:
    return (
        run_at.replace(":", "")
        .replace("+", "")
        .replace(" ", "_")
        .replace("-", "")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run TUI scenario tests and write an audit report."
    )
    parser.add_argument("--report-dir", default="data/tui-scenario-reports")
    parser.add_argument("--cwd", default=".")
    args = parser.parse_args(argv)

    cwd = Path(args.cwd).resolve()
    run_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    result = run_tui_scenario_audit_command(cwd=cwd)
    report_path = write_tui_scenario_audit_report(
        report_dir=Path(args.report_dir),
        result=result,
        run_at=run_at,
        commit=current_git_commit(cwd),
    )
    print(report_path)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
