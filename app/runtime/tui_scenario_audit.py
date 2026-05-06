import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.runtime.benchmark import (
    BenchmarkCaseResult,
    BenchmarkManifest,
    BenchmarkReport,
    load_manifest,
)
from app.runtime.benchmark_gate import select_pytest_nodeids, write_failure_analysis_reports

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


def default_tui_scenario_audit_command(
    *,
    benchmark_manifest: Path | None = None,
) -> list[str]:
    if benchmark_manifest is not None:
        manifest = load_manifest(benchmark_manifest)
        nodeids = select_pytest_nodeids(manifest)
        if nodeids:
            return [sys.executable, "-m", "pytest", "-q", *nodeids]
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


def build_benchmark_report_from_audit(
    *,
    result: ScenarioAuditResult,
    manifest: BenchmarkManifest,
) -> BenchmarkReport:
    combined_output = "\n".join(part for part in [result.stdout, result.stderr] if part)
    failures = set(extract_pytest_failures(combined_output))
    cases: list[BenchmarkCaseResult] = []
    clean_run = result.exit_code == 0
    for case in manifest.cases:
        case_failed = any(_matches_failed_node(nodeid, failures) for nodeid in case.pytest_nodeids)
        passed = not case_failed if case.pytest_nodeids else clean_run
        tool_chain_passed = passed
        dangerous_command_blocked = None
        if case.expects_dangerous_block:
            dangerous_command_blocked = passed
        cases.append(
            BenchmarkCaseResult(
                name=case.id,
                passed=passed,
                tool_chain_passed=tool_chain_passed,
                dangerous_command_blocked=dangerous_command_blocked,
                repeated_file_reads=0,
            )
        )
    return BenchmarkReport(cases=cases)


def _matches_failed_node(nodeid: str, failures: set[str]) -> bool:
    return any(
        failure == nodeid
        or failure.startswith(f"{nodeid}[")
        or failure.startswith(f"{nodeid}::")
        for failure in failures
    )


def write_benchmark_report_from_audit(
    *,
    output_path: Path,
    result: ScenarioAuditResult,
    manifest: BenchmarkManifest,
    analysis_report_dir: Path | None = None,
    run_id: str | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report = build_benchmark_report_from_audit(result=result, manifest=manifest)
    output_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    if analysis_report_dir is not None:
        write_failure_analysis_reports(
            output_dir=analysis_report_dir,
            report=report,
            run_id=run_id or output_path.stem,
        )
    return output_path


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
    parser.add_argument("--benchmark-manifest")
    parser.add_argument("--benchmark-output")
    parser.add_argument("--analysis-report-dir", default="data/analysis-reports")
    args = parser.parse_args(argv)

    cwd = Path(args.cwd).resolve()
    run_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    command = default_tui_scenario_audit_command(
        benchmark_manifest=Path(args.benchmark_manifest) if args.benchmark_manifest else None
    )
    result = run_tui_scenario_audit_command(cwd=cwd, command=command)
    report_path = write_tui_scenario_audit_report(
        report_dir=Path(args.report_dir),
        result=result,
        run_at=run_at,
        commit=current_git_commit(cwd),
    )
    print(report_path)
    if args.benchmark_manifest and args.benchmark_output:
        benchmark_path = write_benchmark_report_from_audit(
            output_path=Path(args.benchmark_output),
            result=result,
            manifest=load_manifest(Path(args.benchmark_manifest)),
            analysis_report_dir=Path(args.analysis_report_dir),
        )
        print(benchmark_path)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
