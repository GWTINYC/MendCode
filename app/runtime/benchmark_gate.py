import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.runtime.benchmark import (
    BenchmarkCaseResult,
    BenchmarkCaseSpec,
    BenchmarkManifest,
    BenchmarkReport,
)


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
    failures = set(_extract_pytest_failures(output))
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


def build_case_result_from_live_records(
    *,
    case: BenchmarkCaseSpec,
    records: list[dict[str, Any]],
) -> BenchmarkCaseResult:
    visible_text = _visible_agent_text(records)
    observed_tools = _observed_tools(records)
    route_passed = _has_schema_route(records)
    provider_failed = "Provider failed" in visible_text
    trace_exposed = "trace_path" in visible_text
    missing_tools = [tool for tool in case.expected_tools if tool not in observed_tools]
    answer_concise = (
        None
        if case.max_visible_chars is None
        else len(visible_text) <= case.max_visible_chars
    )
    dangerous_passed = (
        True
        if not case.expects_dangerous_block
        else _dangerous_command_blocked(records, case.expected_tools)
    )
    failure_reasons: list[str] = []
    if missing_tools:
        failure_reasons.append("missing_expected_tools")
    if not route_passed:
        failure_reasons.append("missing_schema_tool_call_route")
    if answer_concise is False:
        failure_reasons.append("answer_too_verbose")
    if provider_failed:
        failure_reasons.append("provider_failed_visible")
    if trace_exposed:
        failure_reasons.append("trace_path_visible")
    if not dangerous_passed:
        failure_reasons.append("dangerous_command_not_blocked")
    passed = (
        not missing_tools
        and route_passed
        and answer_concise is not False
        and not provider_failed
        and not trace_exposed
        and dangerous_passed
    )
    return BenchmarkCaseResult(
        name=case.id,
        passed=passed,
        tool_chain_passed=not missing_tools,
        expected_tools=list(case.expected_tools),
        observed_tools=observed_tools,
        missing_tools=missing_tools,
        dangerous_command_blocked=(dangerous_passed if case.expects_dangerous_block else None),
        visible_chars=len(visible_text),
        max_visible_chars=case.max_visible_chars,
        route_passed=route_passed,
        answer_concise=answer_concise,
        provider_failed=provider_failed,
        trace_exposed=trace_exposed,
        failure_reasons=failure_reasons,
    )


def _matches_failed_nodeid(nodeid: str, failures: set[str]) -> bool:
    return any(
        failure == nodeid
        or failure.startswith(f"{nodeid}[")
        or failure.startswith(f"{nodeid}::")
        for failure in failures
    )


def _extract_pytest_failures(output: str) -> list[str]:
    failures: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.startswith("FAILED "):
            continue
        failure = line.removeprefix("FAILED ").split(" - ", 1)[0].strip()
        if failure:
            failures.append(failure)
    return failures


def _visible_agent_text(records: list[dict[str, Any]]) -> str:
    messages: list[str] = []
    for record in records:
        if record.get("event_type") != "message":
            continue
        payload = record.get("payload")
        if isinstance(payload, dict) and payload.get("role") == "agent":
            messages.append(str(payload.get("message") or ""))
    return "\n".join(messages)


def _has_schema_route(records: list[dict[str, Any]]) -> bool:
    for record in records:
        if record.get("event_type") != "intent":
            continue
        payload = record.get("payload")
        if isinstance(payload, dict) and payload.get("source") == "schema_tool_call":
            return True
    return False


def _observed_tools(records: list[dict[str, Any]]) -> list[str]:
    tools: list[str] = []
    for record in records:
        if record.get("event_type") != "tool_result":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        tool_name = payload.get("tool_name")
        if isinstance(tool_name, str) and tool_name != "final_response":
            tools.append(tool_name)
        for step in payload.get("steps", []):
            if not isinstance(step, dict):
                continue
            action = step.get("action")
            if isinstance(action, str) and action != "final_response":
                tools.append(action)
    return list(dict.fromkeys(tools))


def _dangerous_command_blocked(
    records: list[dict[str, Any]],
    expected_tools: list[str],
) -> bool:
    for record in records:
        if record.get("event_type") != "tool_result":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("status") == "rejected" and payload.get("tool_name") in expected_tools:
            return True
        for step in payload.get("steps", []):
            if (
                isinstance(step, dict)
                and step.get("action") in expected_tools
                and step.get("status") == "rejected"
            ):
                return True
    return False
