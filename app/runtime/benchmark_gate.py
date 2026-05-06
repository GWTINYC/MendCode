import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from app.runtime.benchmark import (
    BenchmarkCaseResult,
    BenchmarkManifest,
    BenchmarkReport,
)
from app.runtime.tui_scenario_audit import extract_pytest_failures


@dataclass(frozen=True)
class PytestRunResult:
    command: list[str]
    cwd: Path
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


def select_pytest_nodeids(manifest: BenchmarkManifest) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for case in manifest.cases:
        for nodeid in case.pytest_nodeids:
            if nodeid in seen:
                continue
            seen.add(nodeid)
            selected.append(nodeid)
    return selected


def run_pytest_nodeids(*, cwd: Path, nodeids: list[str]) -> PytestRunResult:
    command = ["python", "-m", "pytest", "-q", *nodeids]
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return PytestRunResult(
        command=command,
        cwd=cwd,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def build_gate_report(
    *,
    manifest: BenchmarkManifest,
    result: PytestRunResult,
) -> BenchmarkReport:
    output = "\n".join(part for part in [result.stdout, result.stderr] if part)
    failures = set(extract_pytest_failures(output))
    cases: list[BenchmarkCaseResult] = []
    clean_run = result.exit_code == 0
    for case in manifest.cases:
        failed = any(_matches_failed_nodeid(nodeid, failures) for nodeid in case.pytest_nodeids)
        passed = clean_run and not failed
        reasons = ["pytest_node_failed"] if failed else []
        if result.exit_code != 0 and not failed:
            reasons.append("pytest_run_failed_without_case_match")
        cases.append(
            BenchmarkCaseResult(
                name=case.id,
                passed=passed,
                tool_chain_passed=passed,
                expected_tools=list(case.expected_tools),
                observed_tools=[],
                missing_tools=list(case.expected_tools) if not passed else [],
                dangerous_command_blocked=(passed if case.expects_dangerous_block else None),
                max_visible_chars=case.max_visible_chars,
                route_passed=passed,
                answer_concise=passed if case.max_visible_chars is not None else None,
                provider_failed=False,
                trace_exposed=False,
                failure_reasons=reasons,
            )
        )
    return BenchmarkReport(cases=cases)


def _matches_failed_nodeid(nodeid: str, failures: set[str]) -> bool:
    return any(
        failure == nodeid
        or failure.startswith(f"{nodeid}[")
        or failure.startswith(f"{nodeid}::")
        for failure in failures
    )
