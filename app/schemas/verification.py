from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

VerificationCommandStatus = Literal["passed", "failed", "timed_out", "rejected"]
VerificationSummaryStatus = Literal["passed", "failed"]


class VerificationCommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str
    exit_code: int
    status: VerificationCommandStatus
    duration_ms: int
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    timed_out: bool = False
    rejected: bool = False
    cwd: str | None = None

    @model_validator(mode="after")
    def validate_status_flags(self) -> "VerificationCommandResult":
        if self.status == "passed" and self.exit_code != 0:
            raise ValueError("passed status requires exit_code 0")
        if self.status == "failed" and self.exit_code == 0:
            raise ValueError("failed status requires non-zero exit_code")
        if self.status == "timed_out" and not self.timed_out:
            raise ValueError("timed_out status requires timed_out=True")
        if self.status == "rejected" and not self.rejected:
            raise ValueError("rejected status requires rejected=True")
        if self.status in {"timed_out", "rejected"} and self.exit_code != -1:
            raise ValueError("timed_out and rejected statuses require exit_code -1")
        return self


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: VerificationSummaryStatus
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

        expected_status: VerificationSummaryStatus = "passed" if failed_results == 0 else "failed"
        if self.status != expected_status:
            raise ValueError("status must match command_results")

        return self
