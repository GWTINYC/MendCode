from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

VerificationStatus = Literal["passed", "failed"]


class VerificationCommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str
    exit_code: int
    status: VerificationStatus
    duration_ms: int
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""

    @model_validator(mode="after")
    def validate_exit_code_matches_status(self) -> "VerificationCommandResult":
        expected_status: VerificationStatus = "passed" if self.exit_code == 0 else "failed"
        if self.status != expected_status:
            raise ValueError("status must match exit_code")
        return self


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: VerificationStatus
    command_results: list[VerificationCommandResult] = Field(default_factory=list)
    passed_count: int
    failed_count: int

    @model_validator(mode="after")
    def validate_aggregate_consistency(self) -> "VerificationResult":
        passed_results = sum(1 for result in self.command_results if result.status == "passed")
        failed_results = len(self.command_results) - passed_results

        if self.passed_count != passed_results:
            raise ValueError("passed_count must match command_results")
        if self.failed_count != failed_results:
            raise ValueError("failed_count must match command_results")

        expected_status: VerificationStatus = "passed" if failed_results == 0 else "failed"
        if self.status != expected_status:
            raise ValueError("status must match command_results")

        return self
