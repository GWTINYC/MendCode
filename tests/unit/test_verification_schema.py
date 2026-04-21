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
            },
            {
                "command": "python -m bad.module",
                "exit_code": 1,
                "status": "failed",
                "duration_ms": 80,
                "stdout_excerpt": "",
                "stderr_excerpt": "ModuleNotFoundError",
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
