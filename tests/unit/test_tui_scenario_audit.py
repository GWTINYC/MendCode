import json
import sys
from pathlib import Path

from app.runtime.benchmark import BenchmarkManifest
from app.runtime.tui_scenario_audit import (
    ScenarioAuditResult,
    build_benchmark_report_from_audit,
    default_tui_scenario_audit_command,
    extract_pytest_failures,
    write_tui_scenario_audit_report,
)


def test_extract_pytest_failures_from_failed_output() -> None:
    output = "\n".join(
        [
            "FAILED tests/scenarios/test_tui_file_question_scenarios.py::test_reads "
            "- AssertionError",
            "FAILED tests/scenarios/test_tui_failure_scenarios.py::test_missing - ValueError",
        ]
    )

    failures = extract_pytest_failures(output)

    assert failures == [
        "tests/scenarios/test_tui_file_question_scenarios.py::test_reads",
        "tests/scenarios/test_tui_failure_scenarios.py::test_missing",
    ]


def test_default_tui_scenario_audit_command_includes_live_e2e_tests() -> None:
    command = default_tui_scenario_audit_command()

    assert command[-2:] == ["tests/scenarios", "tests/e2e"]


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


def test_write_tui_scenario_audit_report_records_failure_issue(tmp_path: Path) -> None:
    result = ScenarioAuditResult(
        command=["python", "-m", "pytest", "-q", "tests/scenarios"],
        cwd=tmp_path,
        exit_code=1,
        stdout=(
            "FAILED tests/scenarios/test_tui_failure_scenarios.py::test_missing "
            "- AssertionError\n"
        ),
        stderr="",
        duration_ms=123,
    )

    report_path = write_tui_scenario_audit_report(
        report_dir=tmp_path / "reports",
        result=result,
        run_at="2026-04-27 08:16:09 +0800",
        commit="abc1234",
    )

    text = report_path.read_text(encoding="utf-8")
    assert "问题数：1" in text
    assert "tests/scenarios/test_tui_failure_scenarios.py::test_missing" in text
    assert "exit_code: 1" in text
    assert "abc1234" in text


def test_write_tui_scenario_audit_report_records_clean_run(tmp_path: Path) -> None:
    result = ScenarioAuditResult(
        command=["python", "-m", "pytest", "-q", "tests/scenarios"],
        cwd=tmp_path,
        exit_code=0,
        stdout=".................. [100%]\n18 passed\n",
        stderr="",
        duration_ms=456,
    )

    report_path = write_tui_scenario_audit_report(
        report_dir=tmp_path / "reports",
        result=result,
        run_at="2026-04-27 08:16:09 +0800",
        commit="abc1234",
    )

    text = report_path.read_text(encoding="utf-8")
    assert "问题数：0" in text
    assert "未发现失败场景" in text
    assert "18 passed" in text


def test_build_benchmark_report_from_clean_audit_marks_manifest_cases_passed(
    tmp_path: Path,
) -> None:
    result = ScenarioAuditResult(
        command=["python", "-m", "pytest", "-q", "tests/scenarios"],
        cwd=tmp_path,
        exit_code=0,
        stdout="2 passed\n",
        stderr="",
        duration_ms=20,
    )
    manifest = BenchmarkManifest.model_validate(
        {
            "name": "quick",
            "cases": [
                {
                    "id": "repo-list",
                    "category": "repository_inspection",
                    "prompt": "列文件",
                    "expected_tools": ["list_dir"],
                    "pytest_nodeids": [
                        "tests/scenarios/test_tui_repository_inspection_scenarios.py::"
                        "test_directory_listing_is_tool_backed_and_concise"
                    ],
                },
                {
                    "id": "danger",
                    "category": "permission_safety",
                    "prompt": "危险命令",
                    "expected_tools": ["run_shell_command"],
                    "expects_dangerous_block": True,
                },
            ],
        }
    )

    report = build_benchmark_report_from_audit(result=result, manifest=manifest)

    assert [case.name for case in report.cases] == ["repo-list", "danger"]
    assert all(case.passed for case in report.cases)
    assert all(case.tool_chain_passed for case in report.cases)
    assert report.cases[1].dangerous_command_blocked is True


def test_build_benchmark_report_from_audit_maps_failed_node_to_case(tmp_path: Path) -> None:
    failed_node = (
        "tests/scenarios/test_tui_repository_inspection_scenarios.py::"
        "test_directory_listing_is_tool_backed_and_concise"
    )
    result = ScenarioAuditResult(
        command=["python", "-m", "pytest", "-q", "tests/scenarios"],
        cwd=tmp_path,
        exit_code=1,
        stdout=f"FAILED {failed_node} - AssertionError\n",
        stderr="",
        duration_ms=20,
    )
    manifest = BenchmarkManifest.model_validate(
        {
            "name": "quick",
            "cases": [
                {
                    "id": "repo-list",
                    "category": "repository_inspection",
                    "prompt": "列文件",
                    "expected_tools": ["list_dir"],
                    "pytest_nodeids": [failed_node],
                },
                {
                    "id": "memory",
                    "category": "memory_context",
                    "prompt": "记忆",
                    "expected_tools": ["memory_search"],
                    "pytest_nodeids": [
                        "tests/scenarios/test_tui_repository_inspection_scenarios.py::"
                        "test_memory_recall_question_uses_memory_search"
                    ],
                },
            ],
        }
    )

    report = build_benchmark_report_from_audit(result=result, manifest=manifest)

    assert report.cases[0].name == "repo-list"
    assert report.cases[0].passed is False
    assert report.cases[0].tool_chain_passed is False
    assert report.cases[1].name == "memory"
    assert report.cases[1].passed is True
