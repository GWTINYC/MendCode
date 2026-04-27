from pathlib import Path

from app.runtime.tui_scenario_audit import (
    ScenarioAuditResult,
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
