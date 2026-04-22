import pytest
from pydantic import ValidationError

from app.schemas.verification import VerificationCommandResult, VerificationResult


def test_verification_result_serializes_expected_fields():
    result = VerificationResult(
        status="failed",
        passed_count=1,
        failed_count=1,
        command_results=[
            VerificationCommandResult(
                command="pytest -q",
                exit_code=0,
                status="passed",
                duration_ms=120,
                stdout_excerpt="2 passed",
                stderr_excerpt="",
            ),
            VerificationCommandResult(
                command="python -m bad.module",
                exit_code=1,
                status="failed",
                duration_ms=80,
                stdout_excerpt="",
                stderr_excerpt="ModuleNotFoundError",
            ),
        ],
    )

    assert result.model_dump() == {
        "status": "failed",
        "command_results": [
            {
                "command": "pytest -q",
                "exit_code": 0,
                "status": "passed",
                "duration_ms": 120,
                "stdout_excerpt": "2 passed",
                "stderr_excerpt": "",
                "timed_out": False,
                "rejected": False,
                "cwd": None,
            },
            {
                "command": "python -m bad.module",
                "exit_code": 1,
                "status": "failed",
                "duration_ms": 80,
                "stdout_excerpt": "",
                "stderr_excerpt": "ModuleNotFoundError",
                "timed_out": False,
                "rejected": False,
                "cwd": None,
            },
        ],
        "passed_count": 1,
        "failed_count": 1,
    }


def test_verification_schema_rejects_invalid_status():
    with pytest.raises(ValidationError):
        VerificationCommandResult(
            command="pytest -q",
            exit_code=0,
            status="unknown",
            duration_ms=100,
            stdout_excerpt="ok",
            stderr_excerpt="",
        )


def test_verification_result_rejects_invalid_status():
    with pytest.raises(ValidationError):
        VerificationResult(
            status="unknown",
            passed_count=0,
            failed_count=0,
            command_results=[],
        )


def test_verification_result_rejects_inconsistent_aggregate():
    with pytest.raises(ValidationError):
        VerificationResult(
            status="passed",
            passed_count=2,
            failed_count=1,
            command_results=[
                VerificationCommandResult(
                    command="pytest -q",
                    exit_code=0,
                    status="passed",
                    duration_ms=120,
                    stdout_excerpt="2 passed",
                    stderr_excerpt="",
                ),
                VerificationCommandResult(
                    command="python -m bad.module",
                    exit_code=1,
                    status="failed",
                    duration_ms=80,
                    stdout_excerpt="",
                    stderr_excerpt="ModuleNotFoundError",
                ),
            ],
        )


def test_verification_models_forbid_extra_fields():
    with pytest.raises(ValidationError):
        VerificationCommandResult(
            command="pytest -q",
            exit_code=0,
            status="passed",
            duration_ms=120,
            stdout_excerpt="2 passed",
            stderr_excerpt="",
            extra_field=True,
        )

    with pytest.raises(ValidationError):
        VerificationResult(
            status="passed",
            passed_count=0,
            failed_count=0,
            command_results=[],
            extra_field=True,
        )


def test_verification_command_result_rejects_zero_exit_code_with_failed_status():
    with pytest.raises(ValidationError):
        VerificationCommandResult(
            command="pytest -q",
            exit_code=0,
            status="failed",
            duration_ms=120,
            stdout_excerpt="2 passed",
            stderr_excerpt="",
        )


def test_verification_command_result_rejects_nonzero_exit_code_with_passed_status():
    with pytest.raises(ValidationError):
        VerificationCommandResult(
            command="python -m bad.module",
            exit_code=1,
            status="passed",
            duration_ms=80,
            stdout_excerpt="",
            stderr_excerpt="ModuleNotFoundError",
        )


def test_verification_command_result_supports_timeout_and_rejection_statuses():
    timed_out = VerificationCommandResult(
        command="pytest -q",
        exit_code=-1,
        status="timed_out",
        duration_ms=1000,
        stdout_excerpt="",
        stderr_excerpt="command timed out after 1 seconds",
        timed_out=True,
        rejected=False,
        cwd="/tmp/worktree",
    )
    rejected = VerificationCommandResult(
        command="pytest -q",
        exit_code=-1,
        status="rejected",
        duration_ms=0,
        stdout_excerpt="",
        stderr_excerpt="command rejected by policy",
        timed_out=False,
        rejected=True,
        cwd="/tmp/worktree",
    )

    assert timed_out.status == "timed_out"
    assert timed_out.timed_out is True
    assert rejected.status == "rejected"
    assert rejected.rejected is True
    assert timed_out.model_dump() == {
        "command": "pytest -q",
        "exit_code": -1,
        "status": "timed_out",
        "duration_ms": 1000,
        "stdout_excerpt": "",
        "stderr_excerpt": "command timed out after 1 seconds",
        "timed_out": True,
        "rejected": False,
        "cwd": "/tmp/worktree",
    }
    assert rejected.model_dump() == {
        "command": "pytest -q",
        "exit_code": -1,
        "status": "rejected",
        "duration_ms": 0,
        "stdout_excerpt": "",
        "stderr_excerpt": "command rejected by policy",
        "timed_out": False,
        "rejected": True,
        "cwd": "/tmp/worktree",
    }
