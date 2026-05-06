import json
from pathlib import Path

from app.runtime.benchmark import BenchmarkCaseResult, BenchmarkManifest, BenchmarkReport
from app.runtime.benchmark_gate import (
    PytestRunResult,
    build_case_result_from_live_records,
    build_gate_report,
    select_pytest_nodeids,
    write_failure_analysis_reports,
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
                        "tests/e2e/test_tui_pty_live.py::"
                        "test_live_tui_checks_git_status_without_fabricating"
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


def test_write_failure_analysis_reports_creates_one_json_per_failed_case(
    tmp_path: Path,
) -> None:
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
    assert payload["recommendations"] == [
        "review tool schema and prompt rules for expected tools"
    ]
