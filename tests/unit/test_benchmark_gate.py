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
