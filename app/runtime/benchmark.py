import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

BenchmarkCategory = Literal[
    "repository_inspection",
    "file_question",
    "code_search",
    "git_status",
    "patch_repair",
    "permission_safety",
    "memory_context",
]

TARGET_CATEGORIES: tuple[BenchmarkCategory, ...] = (
    "repository_inspection",
    "file_question",
    "code_search",
    "git_status",
    "patch_repair",
    "permission_safety",
    "memory_context",
)


class BenchmarkCaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    category: BenchmarkCategory
    prompt: str
    expected_tools: list[str] = Field(default_factory=list)
    expects_dangerous_block: bool = False
    max_visible_chars: int | None = Field(default=None, gt=0)
    max_context_tokens: int | None = Field(default=None, gt=0)
    requires_token_evidence: bool = False
    pytest_nodeids: list[str] = Field(default_factory=list)
    notes: str | None = None


class BenchmarkManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    cases: list[BenchmarkCaseSpec] = Field(default_factory=list)

    @property
    def case_count(self) -> int:
        return len(self.cases)

    def category_counts(self) -> dict[str, int]:
        counts = {category: 0 for category in TARGET_CATEGORIES}
        for case in self.cases:
            counts[case.category] += 1
        return {category: count for category, count in counts.items() if count > 0}

    def missing_target_categories(self) -> list[str]:
        present = {case.category for case in self.cases}
        return [category for category in TARGET_CATEGORIES if category not in present]

    def to_markdown(self) -> str:
        lines = [
            "# MendCode Benchmark Manifest",
            "",
            f"- name: {self.name}",
            f"- case_count: {self.case_count}",
            f"- missing_target_categories: {_format_missing(self.missing_target_categories())}",
            "",
            "## Categories",
            "",
        ]
        for category, count in self.category_counts().items():
            lines.append(f"- {category}: {count}")
        lines.extend(["", "## Cases", ""])
        for case in self.cases:
            lines.append(
                f"- {case.id}: category={case.category}, "
                f"expected_tools={','.join(case.expected_tools)}"
            )
        return "\n".join(lines) + "\n"


class BenchmarkCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    tool_chain_passed: bool
    expected_tools: list[str] = Field(default_factory=list)
    observed_tools: list[str] = Field(default_factory=list)
    missing_tools: list[str] = Field(default_factory=list)
    dangerous_command_blocked: bool | None = None
    visible_chars: int | None = Field(default=None, ge=0)
    max_visible_chars: int | None = Field(default=None, gt=0)
    tokens_baseline: int | None = Field(default=None, ge=0)
    tokens_actual: int | None = Field(default=None, ge=0)
    max_context_tokens: int | None = Field(default=None, gt=0)
    requires_token_evidence: bool = False
    observation_tokens_saved: int = Field(default=0, ge=0)
    repeated_file_reads: int = Field(default=0, ge=0)
    route_passed: bool | None = None
    answer_concise: bool | None = None
    provider_failed: bool = False
    trace_exposed: bool = False
    failure_reasons: list[str] = Field(default_factory=list)


class BenchmarkCaseEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    observed_tools: list[str] = Field(default_factory=list)
    visible_chars: int | None = Field(default=None, ge=0)
    context_baseline_chars: int | None = Field(default=None, ge=0)
    context_actual_chars: int | None = Field(default=None, ge=0)
    context_baseline_tokens: int | None = Field(default=None, ge=0)
    context_actual_tokens: int | None = Field(default=None, ge=0)
    observation_tokens_saved: int = Field(default=0, ge=0)
    repeated_file_reads: int = Field(default=0, ge=0)
    dangerous_command_blocked: bool | None = None


class BenchmarkReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[BenchmarkCaseResult] = Field(default_factory=list)

    def metrics(self) -> dict[str, float | int]:
        total = len(self.cases)
        blocked_cases = [
            case for case in self.cases if case.dangerous_command_blocked is not None
        ]
        route_cases = [case for case in self.cases if case.route_passed is not None]
        concise_cases = [case for case in self.cases if case.answer_concise is not None]
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
            "observation_tokens_saved": sum(
                case.observation_tokens_saved for case in self.cases
            ),
            "repeated_file_reads": sum(case.repeated_file_reads for case in self.cases),
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
            f"- observation_tokens_saved: {metrics['observation_tokens_saved']}",
            f"- repeated_file_reads: {metrics['repeated_file_reads']}",
            f"- route_pass_rate: {metrics['route_pass_rate']}",
            f"- answer_concise_rate: {metrics['answer_concise_rate']}",
            f"- provider_failure_count: {metrics['provider_failure_count']}",
            f"- trace_exposed_count: {metrics['trace_exposed_count']}",
            "",
            "## Cases",
            "",
        ]
        for case in self.cases:
            reason_text = ",".join(case.failure_reasons) if case.failure_reasons else "none"
            lines.append(
                f"- {case.name}: passed={case.passed}, "
                f"tool_chain_passed={case.tool_chain_passed}, "
                f"failure_reasons={reason_text}"
            )
        return "\n".join(lines) + "\n"


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def load_report(path: Path) -> BenchmarkReport:
    data = json.loads(path.read_text(encoding="utf-8"))
    return BenchmarkReport.model_validate(data)


def build_case_result_from_evidence(
    case: BenchmarkCaseSpec,
    evidence: BenchmarkCaseEvidence,
) -> BenchmarkCaseResult:
    observed_tools = list(dict.fromkeys(evidence.observed_tools))
    missing_tools = [tool for tool in case.expected_tools if tool not in observed_tools]
    tool_chain_passed = not missing_tools
    visible_passed = (
        True
        if case.max_visible_chars is None or evidence.visible_chars is None
        else evidence.visible_chars <= case.max_visible_chars
    )
    actual_tokens = (
        evidence.context_actual_tokens
        if evidence.context_actual_tokens is not None
        else evidence.context_actual_chars
    )
    baseline_tokens = (
        evidence.context_baseline_tokens
        if evidence.context_baseline_tokens is not None
        else evidence.context_baseline_chars
    )
    token_evidence_present = actual_tokens is not None or baseline_tokens is not None
    token_evidence_passed = not case.requires_token_evidence or token_evidence_present
    context_tokens_passed = (
        True
        if case.max_context_tokens is None or actual_tokens is None
        else actual_tokens <= case.max_context_tokens
    )
    dangerous_passed = (
        True
        if not case.expects_dangerous_block
        else evidence.dangerous_command_blocked is True
    )
    failure_reasons: list[str] = []
    if missing_tools:
        failure_reasons.append("missing_tools")
    if not visible_passed:
        failure_reasons.append("visible_chars_exceeded")
    if not token_evidence_passed:
        failure_reasons.append("missing_token_evidence")
    if not context_tokens_passed:
        failure_reasons.append("context_tokens_exceeded")
    if not dangerous_passed:
        failure_reasons.append("dangerous_command_not_blocked")
    return BenchmarkCaseResult(
        name=case.id,
        passed=(
            tool_chain_passed
            and visible_passed
            and token_evidence_passed
            and context_tokens_passed
            and dangerous_passed
        ),
        tool_chain_passed=tool_chain_passed,
        expected_tools=list(case.expected_tools),
        observed_tools=observed_tools,
        missing_tools=missing_tools,
        dangerous_command_blocked=(
            evidence.dangerous_command_blocked if case.expects_dangerous_block else None
        ),
        visible_chars=evidence.visible_chars,
        max_visible_chars=case.max_visible_chars,
        tokens_baseline=baseline_tokens,
        tokens_actual=actual_tokens,
        max_context_tokens=case.max_context_tokens,
        requires_token_evidence=case.requires_token_evidence,
        observation_tokens_saved=evidence.observation_tokens_saved,
        repeated_file_reads=evidence.repeated_file_reads,
        failure_reasons=failure_reasons,
    )


def load_manifest(path: Path) -> BenchmarkManifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    return BenchmarkManifest.model_validate(data)


def validate_report_coverage(
    manifest: BenchmarkManifest,
    report: BenchmarkReport,
) -> dict[str, object]:
    expected_ids = [case.id for case in manifest.cases]
    expected = set(expected_ids)
    actual_ids = [case.name for case in report.cases]
    actual = set(actual_ids)
    missing = [case_id for case_id in expected_ids if case_id not in actual]
    unexpected = [case_id for case_id in actual_ids if case_id not in expected]
    return {
        "manifest_case_count": len(expected_ids),
        "result_case_count": len(actual_ids),
        "missing_case_ids": missing,
        "unexpected_case_ids": unexpected,
        "complete": not missing and not unexpected,
    }


def _format_missing(missing: list[str]) -> str:
    return ", ".join(missing) if missing else "none"


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
