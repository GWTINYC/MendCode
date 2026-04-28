from app.runtime.benchmark import BenchmarkCaseResult, BenchmarkReport


def test_benchmark_report_computes_rates_and_token_delta() -> None:
    report = BenchmarkReport(
        cases=[
            BenchmarkCaseResult(
                name="readme",
                passed=True,
                tool_chain_passed=True,
                dangerous_command_blocked=True,
                tokens_baseline=1000,
                tokens_actual=700,
                repeated_file_reads=1,
            ),
            BenchmarkCaseResult(
                name="fix",
                passed=False,
                tool_chain_passed=False,
                dangerous_command_blocked=True,
                tokens_baseline=2000,
                tokens_actual=1800,
                repeated_file_reads=3,
            ),
        ]
    )

    metrics = report.metrics()

    assert metrics["case_pass_rate"] == 0.5
    assert metrics["tool_chain_pass_rate"] == 0.5
    assert metrics["dangerous_command_block_rate"] == 1.0
    assert metrics["token_reduction_rate"] == 0.1667
    assert metrics["repeated_file_reads"] == 4
