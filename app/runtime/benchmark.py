import argparse
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class BenchmarkCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    tool_chain_passed: bool
    dangerous_command_blocked: bool | None = None
    tokens_baseline: int | None = Field(default=None, ge=0)
    tokens_actual: int | None = Field(default=None, ge=0)
    repeated_file_reads: int = Field(default=0, ge=0)


class BenchmarkReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[BenchmarkCaseResult] = Field(default_factory=list)

    def metrics(self) -> dict[str, float | int]:
        total = len(self.cases)
        blocked_cases = [
            case for case in self.cases if case.dangerous_command_blocked is not None
        ]
        baseline_tokens = sum(case.tokens_baseline or 0 for case in self.cases)
        actual_tokens = sum(case.tokens_actual or 0 for case in self.cases)
        token_reduction = 0.0
        if baseline_tokens > 0:
            token_reduction = (baseline_tokens - actual_tokens) / baseline_tokens
        return {
            "case_count": total,
            "case_pass_rate": _rate(
                sum(1 for case in self.cases if case.passed),
                total,
            ),
            "tool_chain_pass_rate": _rate(
                sum(1 for case in self.cases if case.tool_chain_passed),
                total,
            ),
            "dangerous_command_block_rate": _rate(
                sum(1 for case in blocked_cases if case.dangerous_command_blocked),
                len(blocked_cases),
            ),
            "token_reduction_rate": round(token_reduction, 4),
            "repeated_file_reads": sum(case.repeated_file_reads for case in self.cases),
        }

    def to_markdown(self) -> str:
        metrics = self.metrics()
        lines = [
            "# MendCode Benchmark Report",
            "",
            "## Metrics",
            "",
            f"- case_count: {metrics['case_count']}",
            f"- case_pass_rate: {metrics['case_pass_rate']}",
            f"- tool_chain_pass_rate: {metrics['tool_chain_pass_rate']}",
            f"- dangerous_command_block_rate: {metrics['dangerous_command_block_rate']}",
            f"- token_reduction_rate: {metrics['token_reduction_rate']}",
            f"- repeated_file_reads: {metrics['repeated_file_reads']}",
            "",
            "## Cases",
            "",
        ]
        for case in self.cases:
            lines.append(
                f"- {case.name}: passed={case.passed}, "
                f"tool_chain_passed={case.tool_chain_passed}"
            )
        return "\n".join(lines) + "\n"


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def load_report(path: Path) -> BenchmarkReport:
    data = json.loads(path.read_text(encoding="utf-8"))
    return BenchmarkReport.model_validate(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize MendCode benchmark JSON into metrics."
    )
    parser.add_argument("input", help="Benchmark JSON file with a cases array.")
    parser.add_argument("--output", help="Optional Markdown report path.")
    args = parser.parse_args(argv)

    report = load_report(Path(args.input))
    output = report.to_markdown()
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
