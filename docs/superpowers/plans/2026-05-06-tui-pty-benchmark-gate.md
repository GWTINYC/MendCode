# TUI PTY Benchmark Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repeatable evaluation gate that runs realistic TUI conversations, extracts tool evidence from conversation/trace records, produces benchmark metrics, and writes actionable failure analysis reports.

**Architecture:** Keep `tests/scenarios` for deterministic fake-provider experience tests and make `tests/e2e` the live PTY path for real OpenAI-compatible behavior. Add a manifest-driven audit runner that maps each benchmark case to either scenario, live PTY, or integration nodeids, then writes JSON + Markdown reports under `data/benchmark-reports/` and optional failure analysis under `data/analysis-reports/`. The gate must measure tool-chain pass rate, dangerous-command block rate, visible answer length, repeated file reads, and context/token-ish reduction without exposing raw payloads in TUI output.

**Tech Stack:** Python 3.12, pytest, pexpect, Pydantic, Textual test harness, JSONL conversation logs, JSON benchmark reports, Markdown reports, OpenAI-compatible provider configuration.

---

## File Structure

Create:

- `app/runtime/benchmark_gate.py`
  - Manifest-driven benchmark gate.
  - Runs pytest nodeids or target groups.
  - Parses pytest output.
  - Loads optional conversation JSONL evidence.
  - Writes benchmark JSON and Markdown summaries.
- `tests/unit/test_benchmark_gate.py`
  - Unit tests for nodeid selection, failure mapping, metrics, and report output.

Modify:

- `app/runtime/benchmark.py`
  - Add fields needed by the gate: `route_passed`, `answer_concise`, `provider_failed`, `trace_exposed`, `failure_reasons`.
  - Keep old fields backward-compatible.
- `app/runtime/tui_scenario_audit.py`
  - Delegate benchmark construction to `benchmark_gate`.
  - Keep current CLI flags working.
- `tests/scenarios/benchmark_manifest.json`
  - Expand from a small representative set into a stable v1 gate manifest.
- `tests/e2e/test_tui_pty_live.py`
  - Add missing live cases for current high-risk user questions.
- `tests/scenarios/tui_scenario_runner.py`
  - Add evidence helpers for route, trace exposure, provider failure, and compact answer length.
- `MendCode_开发方案.md`
  - Record the benchmark gate as the default quality route for future TUI work.
- `README.md`
  - Document the evaluation command and provider environment requirements.

Do not add a separate CLI product surface. Any command added here is a developer quality gate, not a user-facing workflow.

---

### Task 1: Extend Benchmark Result Schema

**Files:**
- Modify: `app/runtime/benchmark.py`
- Test: `tests/unit/test_benchmark_report.py`

- [ ] **Step 1: Write failing schema tests**

Add this test to `tests/unit/test_benchmark_report.py`:

```python
def test_benchmark_case_result_tracks_tui_quality_failures() -> None:
    report = BenchmarkReport(
        cases=[
            BenchmarkCaseResult(
                name="git-status",
                passed=False,
                tool_chain_passed=True,
                route_passed=False,
                answer_concise=True,
                provider_failed=False,
                trace_exposed=False,
                failure_reasons=["missing_schema_tool_call_route"],
            )
        ]
    )

    metrics = report.metrics()

    assert metrics["case_count"] == 1
    assert metrics["case_pass_rate"] == 0.0
    assert metrics["tool_chain_pass_rate"] == 1.0
    assert metrics["route_pass_rate"] == 0.0
    assert metrics["answer_concise_rate"] == 1.0
    assert metrics["provider_failure_count"] == 0
    assert metrics["trace_exposed_count"] == 0
    assert "missing_schema_tool_call_route" in report.to_markdown()
```

- [ ] **Step 2: Run test to verify red**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_benchmark_report.py::test_benchmark_case_result_tracks_tui_quality_failures -q
```

Expected: fail because `BenchmarkCaseResult` does not yet define the new fields.

- [ ] **Step 3: Add backward-compatible fields**

In `BenchmarkCaseResult`, add:

```python
route_passed: bool | None = None
answer_concise: bool | None = None
provider_failed: bool = False
trace_exposed: bool = False
failure_reasons: list[str] = Field(default_factory=list)
```

In `BenchmarkReport.metrics()`, add:

```python
route_cases = [case for case in self.cases if case.route_passed is not None]
concise_cases = [case for case in self.cases if case.answer_concise is not None]
```

and return:

```python
"route_pass_rate": _rate(
    sum(1 for case in route_cases if case.route_passed),
    len(route_cases),
),
"answer_concise_rate": _rate(
    sum(1 for case in concise_cases if case.answer_concise),
    len(concise_cases),
),
"provider_failure_count": sum(1 for case in self.cases if case.provider_failed),
"trace_exposed_count": sum(1 for case in self.cases if case.trace_exposed),
```

Update `to_markdown()` so each case line includes failure reasons:

```python
reason_text = ",".join(case.failure_reasons) if case.failure_reasons else "none"
lines.append(
    f"- {case.name}: passed={case.passed}, "
    f"tool_chain_passed={case.tool_chain_passed}, "
    f"failure_reasons={reason_text}"
)
```

- [ ] **Step 4: Run test to verify green**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_benchmark_report.py -q
```

Expected: all benchmark report tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/runtime/benchmark.py tests/unit/test_benchmark_report.py
git commit -m "feat: extend tui benchmark metrics"
```

---

### Task 2: Add Benchmark Gate Core

**Files:**
- Create: `app/runtime/benchmark_gate.py`
- Test: `tests/unit/test_benchmark_gate.py`

- [ ] **Step 1: Write failing tests for pytest failure mapping**

Create `tests/unit/test_benchmark_gate.py` with:

```python
from pathlib import Path

from app.runtime.benchmark import BenchmarkManifest
from app.runtime.benchmark_gate import (
    PytestRunResult,
    build_gate_report,
    select_pytest_nodeids,
)


def test_select_pytest_nodeids_deduplicates_manifest_order() -> None:
    manifest = BenchmarkManifest.model_validate(
        {
            "name": "gate",
            "cases": [
                {
                    "id": "git-status",
                    "category": "git_status",
                    "prompt": "看下 git status",
                    "expected_tools": ["git"],
                    "pytest_nodeids": ["tests/e2e/test_tui_pty_live.py::test_git"],
                },
                {
                    "id": "git-status-repeat",
                    "category": "git_status",
                    "prompt": "再看 git status",
                    "expected_tools": ["git"],
                    "pytest_nodeids": ["tests/e2e/test_tui_pty_live.py::test_git"],
                },
            ],
        }
    )

    assert select_pytest_nodeids(manifest) == ["tests/e2e/test_tui_pty_live.py::test_git"]


def test_build_gate_report_maps_failed_nodeid_to_case() -> None:
    manifest = BenchmarkManifest.model_validate(
        {
            "name": "gate",
            "cases": [
                {
                    "id": "git-status",
                    "category": "git_status",
                    "prompt": "看下 git status",
                    "expected_tools": ["git"],
                    "pytest_nodeids": [
                        "tests/e2e/test_tui_pty_live.py::test_live_tui_checks_git_status_without_fabricating"
                    ],
                    "max_visible_chars": 600,
                }
            ],
        }
    )
    result = PytestRunResult(
        command=["python", "-m", "pytest"],
        cwd=Path("/repo"),
        exit_code=1,
        stdout=(
            "FAILED tests/e2e/test_tui_pty_live.py::"
            "test_live_tui_checks_git_status_without_fabricating - AssertionError"
        ),
        stderr="",
        duration_ms=120,
    )

    report = build_gate_report(manifest=manifest, result=result)

    assert report.cases[0].name == "git-status"
    assert report.cases[0].passed is False
    assert report.cases[0].tool_chain_passed is False
    assert "pytest_node_failed" in report.cases[0].failure_reasons
```

- [ ] **Step 2: Run test to verify red**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_benchmark_gate.py -q
```

Expected: import error for `app.runtime.benchmark_gate`.

- [ ] **Step 3: Implement minimal gate module**

Add `app/runtime/benchmark_gate.py`:

```python
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
                dangerous_command_blocked=(
                    passed if case.expects_dangerous_block else None
                ),
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
```

- [ ] **Step 4: Run tests to verify green**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_benchmark_gate.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/runtime/benchmark_gate.py tests/unit/test_benchmark_gate.py
git commit -m "feat: add benchmark gate core"
```

---

### Task 3: Extract Live PTY Evidence Into Benchmark Results

**Files:**
- Modify: `tests/e2e/test_tui_pty_live.py`
- Modify: `app/runtime/benchmark_gate.py`
- Test: `tests/unit/test_benchmark_gate.py`

- [ ] **Step 1: Write failing evidence extraction test**

Add to `tests/unit/test_benchmark_gate.py`:

```python
from app.runtime.benchmark_gate import build_case_result_from_live_records


def test_build_case_result_from_live_records_tracks_tool_route_and_concision() -> None:
    records = [
        {
            "event_type": "intent",
            "payload": {"source": "schema_tool_call"},
        },
        {
            "event_type": "tool_result",
            "payload": {
                "steps": [
                    {"action": "git", "status": "succeeded"},
                    {"action": "final_response", "status": "succeeded"},
                ]
            },
        },
        {
            "event_type": "message",
            "payload": {"role": "agent", "message": "当前有未跟踪文件 work.txt。"},
        },
    ]
    case = BenchmarkManifest.model_validate(
        {
            "name": "gate",
            "cases": [
                {
                    "id": "git-status",
                    "category": "git_status",
                    "prompt": "查看 git 状态",
                    "expected_tools": ["git"],
                    "max_visible_chars": 80,
                }
            ],
        }
    ).cases[0]

    result = build_case_result_from_live_records(case=case, records=records)

    assert result.passed is True
    assert result.tool_chain_passed is True
    assert result.route_passed is True
    assert result.answer_concise is True
    assert result.observed_tools == ["git"]
    assert result.failure_reasons == []
```

- [ ] **Step 2: Run test to verify red**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_benchmark_gate.py::test_build_case_result_from_live_records_tracks_tool_route_and_concision -q
```

Expected: import error for `build_case_result_from_live_records`.

- [ ] **Step 3: Implement live record extraction**

In `app/runtime/benchmark_gate.py`, add:

```python
from typing import Any
from app.runtime.benchmark import BenchmarkCaseSpec


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
        dangerous_command_blocked=(
            dangerous_passed if case.expects_dangerous_block else None
        ),
        visible_chars=len(visible_text),
        max_visible_chars=case.max_visible_chars,
        route_passed=route_passed,
        answer_concise=answer_concise,
        provider_failed=provider_failed,
        trace_exposed=trace_exposed,
        failure_reasons=failure_reasons,
    )
```

Also add helper functions:

```python
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
```

- [ ] **Step 4: Run evidence tests**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_benchmark_gate.py -q
```

Expected: all benchmark gate unit tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/runtime/benchmark_gate.py tests/unit/test_benchmark_gate.py
git commit -m "feat: extract live tui benchmark evidence"
```

---

### Task 4: Add Gate CLI Entry Through Existing Audit Module

**Files:**
- Modify: `app/runtime/tui_scenario_audit.py`
- Test: `tests/unit/test_tui_scenario_audit.py`

- [ ] **Step 1: Write failing CLI unit test**

Add to `tests/unit/test_tui_scenario_audit.py`:

```python
def test_default_tui_scenario_audit_command_can_be_manifest_driven(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "name": "gate",
                "cases": [
                    {
                        "id": "git-status",
                        "category": "git_status",
                        "prompt": "看下 git status",
                        "expected_tools": ["git"],
                        "pytest_nodeids": ["tests/e2e/test_tui_pty_live.py::test_git"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    command = default_tui_scenario_audit_command(benchmark_manifest=manifest_path)

    assert command == [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/e2e/test_tui_pty_live.py::test_git",
    ]
```

- [ ] **Step 2: Run test to verify red**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tui_scenario_audit.py::test_default_tui_scenario_audit_command_can_be_manifest_driven -q
```

Expected: fail because `default_tui_scenario_audit_command()` has no `benchmark_manifest` parameter.

- [ ] **Step 3: Implement manifest-driven command selection**

In `app/runtime/tui_scenario_audit.py`, update:

```python
from app.runtime.benchmark_gate import select_pytest_nodeids
```

Change the function:

```python
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
```

In `main()`, pass `args.benchmark_manifest` when building the command:

```python
command = default_tui_scenario_audit_command(
    benchmark_manifest=Path(args.benchmark_manifest) if args.benchmark_manifest else None
)
result = run_tui_scenario_audit_command(cwd=cwd, command=command)
```

- [ ] **Step 4: Run audit tests**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tui_scenario_audit.py -q
```

Expected: all audit unit tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/runtime/tui_scenario_audit.py tests/unit/test_tui_scenario_audit.py
git commit -m "feat: run tui audit from benchmark manifest"
```

---

### Task 5: Expand V1 Benchmark Manifest

**Files:**
- Modify: `tests/scenarios/benchmark_manifest.json`
- Test: `tests/unit/test_benchmark_report.py`
- Test: `tests/scenarios/test_tool_parity_manifest.py`

- [ ] **Step 1: Write failing coverage test**

Add to `tests/unit/test_benchmark_report.py`:

```python
def test_checked_in_benchmark_manifest_has_minimum_v1_coverage() -> None:
    manifest = load_manifest(Path("tests/scenarios/benchmark_manifest.json"))

    assert manifest.case_count >= 12
    assert manifest.missing_target_categories() == []
    prompts = [case.prompt for case in manifest.cases]
    assert "MendCode问题记录的最后一句话是什么" in prompts
    assert "查看当前git状态" in prompts
    assert "帮我查看当前文件夹里的文件" in prompts
```

- [ ] **Step 2: Run test to verify red or coverage gap**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_benchmark_report.py::test_checked_in_benchmark_manifest_has_minimum_v1_coverage -q
```

Expected: fail if the manifest has fewer than 12 cases or misses exact prompts.

- [ ] **Step 3: Expand manifest with v1 cases**

Update `tests/scenarios/benchmark_manifest.json` to include at least these case IDs:

```json
[
  "repo-list-current-directory",
  "repo-current-path",
  "git-status",
  "git-diff",
  "file-last-sentence",
  "file-read-concise",
  "code-location-search",
  "tool-surface-question",
  "dangerous-shell-denied",
  "write-shell-no-local-pending",
  "session-list-after-question",
  "multi-turn-directory-then-git",
  "memory-recall-verification-command",
  "patch-repair-failing-test"
]
```

For each case, define:

```json
{
  "id": "repo-current-path",
  "category": "repository_inspection",
  "prompt": "当前路径在哪里",
  "expected_tools": ["list_dir"],
  "pytest_nodeids": [
    "tests/e2e/test_tui_pty_live.py::test_live_tui_reports_current_path"
  ],
  "max_visible_chars": 600,
  "notes": "Path claims must be backed by tool evidence and must not expose trace_path."
}
```

Use existing nodeids from `tests/e2e/test_tui_pty_live.py`, `tests/scenarios/test_tui_repository_inspection_scenarios.py`, `tests/scenarios/test_tui_file_question_scenarios.py`, `tests/scenarios/test_tui_failure_scenarios.py`, and integration repair tests.

- [ ] **Step 4: Validate manifest tests**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_benchmark_report.py tests/scenarios/test_tool_parity_manifest.py -q
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/scenarios/benchmark_manifest.json tests/unit/test_benchmark_report.py
git commit -m "test: expand tui benchmark manifest"
```

---

### Task 6: Add Live PTY Regression Cases For Current User Pain Points

**Files:**
- Modify: `tests/e2e/test_tui_pty_live.py`
- Test: `tests/e2e/test_tui_pty_live.py`

- [ ] **Step 1: Add live test for concise last-line answer**

Add:

```python
def test_live_tui_last_sentence_answer_is_not_full_file(live_repo: Path) -> None:
    result = run_live_tui_question(
        live_repo,
        "MendCode问题记录的最后一句话是什么",
        timeout_seconds=120,
    )

    latest_agent_message = _latest_agent_message(result)
    assert_no_provider_failure_or_trace_exposed(result)
    assert_response_evidence_contains(result, "不再记录纯讨论、一次性环境噪声、旧路线细枝末节。")
    assert_conversation_has_tool_evidence(result, "read_file")
    assert len(latest_agent_message) <= 300
    assert "这里记录需要持续修复的问题" not in latest_agent_message
```

- [ ] **Step 2: Add live test for git status fabrication guard**

Add:

```python
def test_live_tui_git_status_answer_requires_git_tool(live_repo: Path) -> None:
    result = run_live_tui_question(
        live_repo,
        "查看当前git状态",
        timeout_seconds=90,
    )

    assert_no_provider_failure_or_trace_exposed(result)
    assert_schema_tool_call_route(result)
    assert_response_evidence_contains(result, "work.txt")
    assert_conversation_has_tool_evidence(result, "git", "run_shell_command")
```

- [ ] **Step 3: Run the new live tests**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/e2e/test_tui_pty_live.py::test_live_tui_last_sentence_answer_is_not_full_file tests/e2e/test_tui_pty_live.py::test_live_tui_git_status_answer_requires_git_tool -q
```

Expected:

- Pass when real OpenAI-compatible provider env exists.
- Fail with a clear message listing missing provider env when env is absent.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_tui_pty_live.py
git commit -m "test: add live tui regression pain points"
```

---

### Task 7: Generate Analysis Reports For Failed Benchmark Cases

**Files:**
- Modify: `app/runtime/benchmark_gate.py`
- Test: `tests/unit/test_benchmark_gate.py`

- [ ] **Step 1: Write failing report test**

Add:

```python
from app.runtime.benchmark_gate import write_failure_analysis_reports


def test_write_failure_analysis_reports_creates_one_json_per_failed_case(tmp_path: Path) -> None:
    report = BenchmarkReport(
        cases=[
            BenchmarkCaseResult(
                name="git-status",
                passed=False,
                tool_chain_passed=False,
                failure_reasons=["missing_expected_tools"],
                expected_tools=["git"],
                observed_tools=[],
            ),
            BenchmarkCaseResult(
                name="repo-list",
                passed=True,
                tool_chain_passed=True,
            ),
        ]
    )

    paths = write_failure_analysis_reports(
        output_dir=tmp_path / "analysis-reports",
        report=report,
        run_id="gate-123",
    )

    assert len(paths) == 1
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert payload["case_id"] == "git-status"
    assert payload["root_causes"] == ["tool_selection_gap"]
    assert payload["recommendations"] == ["review tool schema and prompt rules for expected tools"]
```

- [ ] **Step 2: Run test to verify red**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_benchmark_gate.py::test_write_failure_analysis_reports_creates_one_json_per_failed_case -q
```

Expected: import error for `write_failure_analysis_reports`.

- [ ] **Step 3: Implement report writer**

In `app/runtime/benchmark_gate.py`, add:

```python
import json


def write_failure_analysis_reports(
    *,
    output_dir: Path,
    report: BenchmarkReport,
    run_id: str,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for case in report.cases:
        if case.passed:
            continue
        payload = {
            "run_id": run_id,
            "case_id": case.name,
            "failure_reasons": case.failure_reasons,
            "expected_tools": case.expected_tools,
            "observed_tools": case.observed_tools,
            "root_causes": _root_causes_for_case(case),
            "recommendations": _recommendations_for_case(case),
        }
        path = output_dir / f"{run_id}-{case.name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        paths.append(path)
    return paths


def _root_causes_for_case(case: BenchmarkCaseResult) -> list[str]:
    causes: list[str] = []
    if "missing_expected_tools" in case.failure_reasons or case.missing_tools:
        causes.append("tool_selection_gap")
    if "answer_too_verbose" in case.failure_reasons:
        causes.append("answer_style_gap")
    if "dangerous_command_not_blocked" in case.failure_reasons:
        causes.append("permission_policy_gap")
    if "trace_path_visible" in case.failure_reasons:
        causes.append("tui_visibility_gap")
    return causes or ["unknown"]


def _recommendations_for_case(case: BenchmarkCaseResult) -> list[str]:
    recommendations: list[str] = []
    if "tool_selection_gap" in _root_causes_for_case(case):
        recommendations.append("review tool schema and prompt rules for expected tools")
    if "answer_style_gap" in _root_causes_for_case(case):
        recommendations.append("tighten final response concision rule")
    if "permission_policy_gap" in _root_causes_for_case(case):
        recommendations.append("add permission regression and policy rule")
    if "tui_visibility_gap" in _root_causes_for_case(case):
        recommendations.append("keep trace paths in logs only, not visible TUI output")
    return recommendations
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_benchmark_gate.py -q
```

Expected: all benchmark gate tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/runtime/benchmark_gate.py tests/unit/test_benchmark_gate.py
git commit -m "feat: write benchmark failure analysis reports"
```

---

### Task 8: Wire Gate Outputs Into Audit CLI

**Files:**
- Modify: `app/runtime/tui_scenario_audit.py`
- Test: `tests/unit/test_tui_scenario_audit.py`

- [ ] **Step 1: Add CLI output contract test**

Add:

```python
def test_tui_scenario_audit_writes_benchmark_and_analysis_outputs(tmp_path: Path) -> None:
    result = ScenarioAuditResult(
        command=["python", "-m", "pytest"],
        cwd=tmp_path,
        exit_code=1,
        stdout="FAILED tests/e2e/test_tui_pty_live.py::test_git - AssertionError",
        stderr="",
        duration_ms=10,
    )
    manifest = BenchmarkManifest.model_validate(
        {
            "name": "gate",
            "cases": [
                {
                    "id": "git-status",
                    "category": "git_status",
                    "prompt": "看下 git status",
                    "expected_tools": ["git"],
                    "pytest_nodeids": ["tests/e2e/test_tui_pty_live.py::test_git"],
                }
            ],
        }
    )

    benchmark_path = write_benchmark_report_from_audit(
        output_path=tmp_path / "benchmark.json",
        result=result,
        manifest=manifest,
        analysis_report_dir=tmp_path / "analysis-reports",
        run_id="gate-123",
    )

    assert benchmark_path.exists()
    assert (tmp_path / "analysis-reports" / "gate-123-git-status.json").exists()
```

- [ ] **Step 2: Run test to verify red**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tui_scenario_audit.py::test_tui_scenario_audit_writes_benchmark_and_analysis_outputs -q
```

Expected: fail because `write_benchmark_report_from_audit()` does not accept `analysis_report_dir` or `run_id`.

- [ ] **Step 3: Extend audit writer**

Update `write_benchmark_report_from_audit()` signature:

```python
def write_benchmark_report_from_audit(
    *,
    output_path: Path,
    result: ScenarioAuditResult,
    manifest: BenchmarkManifest,
    analysis_report_dir: Path | None = None,
    run_id: str | None = None,
) -> Path:
```

After writing the benchmark report:

```python
if analysis_report_dir is not None:
    write_failure_analysis_reports(
        output_dir=analysis_report_dir,
        report=report,
        run_id=run_id or output_path.stem,
    )
```

Add CLI arg:

```python
parser.add_argument("--analysis-report-dir", default="data/analysis-reports")
```

When benchmark output is requested, pass:

```python
analysis_report_dir=Path(args.analysis_report_dir)
```

- [ ] **Step 4: Run audit tests**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tui_scenario_audit.py -q
```

Expected: all audit tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/runtime/tui_scenario_audit.py tests/unit/test_tui_scenario_audit.py
git commit -m "feat: connect benchmark gate analysis outputs"
```

---

### Task 9: Documentation And Developer Command

**Files:**
- Modify: `README.md`
- Modify: `MendCode_开发方案.md`

- [ ] **Step 1: Update README evaluation section**

Add this command block:

```markdown
运行 TUI benchmark gate：

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt \
  python -m app.runtime.tui_scenario_audit \
  --benchmark-manifest tests/scenarios/benchmark_manifest.json \
  --benchmark-output data/benchmark-reports/latest.json \
  --analysis-report-dir data/analysis-reports
```

这个命令会运行 manifest 中声明的 scenario / PTY / integration 用例，输出 benchmark JSON、Markdown audit report 和失败归因报告。真实 PTY 用例需要 `.env` 或环境变量中存在 `MENDCODE_PROVIDER`、`MENDCODE_MODEL`、`MENDCODE_BASE_URL`、`MENDCODE_API_KEY`。
```

- [ ] **Step 2: Update development plan**

In `MendCode_开发方案.md`, under TUI and Benchmark sections, record:

```markdown
- [x] TUI Benchmark Gate：manifest 驱动运行 scenario / PTY / integration 用例，输出 benchmark metrics 和失败归因报告。
- [x] 评测指标覆盖 tool-chain pass rate、dangerous-command block rate、route pass rate、answer concise rate、provider failure count、trace exposure count 和 repeated read count。

下一步：

- 每个用户暴露的 TUI 体验问题必须补 benchmark case。
- 每个 context / memory / tool schema 改动都要观察 benchmark report 中 token-ish、重复读文件和工具链路指标。
```

- [ ] **Step 3: Commit docs**

```bash
git add README.md MendCode_开发方案.md
git commit -m "docs: document tui benchmark gate"
```

---

### Task 10: Full Verification

**Files:**
- No source changes unless fixing failures.

- [ ] **Step 1: Run focused tests**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest \
  tests/unit/test_benchmark_report.py \
  tests/unit/test_benchmark_gate.py \
  tests/unit/test_tui_scenario_audit.py \
  tests/scenarios/test_tool_parity_manifest.py \
  -q
```

Expected: all focused evaluation tests pass.

- [ ] **Step 2: Run non-e2e suite**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q --ignore=tests/e2e
```

Expected: pass.

- [ ] **Step 3: Run ruff**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

Expected: pass.

- [ ] **Step 4: Run benchmark gate with live provider if env exists**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt \
  python -m app.runtime.tui_scenario_audit \
  --benchmark-manifest tests/scenarios/benchmark_manifest.json \
  --benchmark-output data/benchmark-reports/latest.json \
  --analysis-report-dir data/analysis-reports
```

Expected:

- If provider env exists: command exits according to scenario result and writes reports.
- If provider env is missing: failure message explicitly lists missing provider env; this is not treated as source failure, but must be reported.

- [ ] **Step 5: Final commit if verification fixes were needed**

```bash
git status --short
```

If files changed:

```bash
git add <changed-files>
git commit -m "test: stabilize tui benchmark gate"
```

---

## Completion Criteria

- Manifest contains at least 12 realistic user-facing cases.
- Gate produces a `BenchmarkReport` with:
  - `tool_chain_pass_rate`
  - `dangerous_command_block_rate`
  - `route_pass_rate`
  - `answer_concise_rate`
  - `provider_failure_count`
  - `trace_exposed_count`
  - `token_reduction_rate`
  - `repeated_file_reads`
- Failed cases produce compact JSON analysis reports under `data/analysis-reports/`.
- PTY live cases keep requiring real OpenAI-compatible provider env and fail clearly when env is missing.
- No visible TUI output contains `trace_path`.
- No benchmark report writes raw full tool payloads or full file contents.
- Non-e2e pytest and ruff pass.

