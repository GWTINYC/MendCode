import json
from pathlib import Path

from app.evolution.proof import CandidateProofStore, ProofRecord, build_candidate_proof
from app.runtime.benchmark import BenchmarkCaseResult


def _case_result(
    *,
    name: str = "git-status-natural-language",
    passed: bool,
    tool_chain_passed: bool,
    failure_reasons: list[str] | None = None,
) -> BenchmarkCaseResult:
    return BenchmarkCaseResult(
        name=name,
        passed=passed,
        tool_chain_passed=tool_chain_passed,
        expected_tools=["repo_status"],
        observed_tools=[] if failure_reasons else ["repo_status"],
        missing_tools=["repo_status"] if failure_reasons else [],
        failure_reasons=failure_reasons or [],
    )


def test_proof_record_contains_candidate_case_metrics_and_verdict() -> None:
    before = _case_result(
        passed=False,
        tool_chain_passed=False,
        failure_reasons=["missing_tools"],
    )
    after = _case_result(passed=True, tool_chain_passed=True)

    proof = build_candidate_proof("candidate-1", before, after)

    assert isinstance(proof, ProofRecord)
    assert proof.candidate_id == "candidate-1"
    assert proof.source_case == "git-status-natural-language"
    assert proof.before_metrics["passed"] is False
    assert proof.before_metrics["failure_reason_count"] == 1
    assert proof.after_metrics["passed"] is True
    assert proof.after_metrics["failure_reason_count"] == 0
    assert proof.verdict == "improved"


def test_proof_store_writes_json_under_data_evolution_proofs(tmp_path: Path) -> None:
    proof = build_candidate_proof(
        "candidate-1",
        _case_result(passed=False, tool_chain_passed=False, failure_reasons=["missing_tools"]),
        _case_result(passed=True, tool_chain_passed=True),
    )
    store = CandidateProofStore(tmp_path / "data" / "evolution")

    written = store.save(proof)

    assert written == tmp_path / "data" / "evolution" / "proofs" / f"{proof.proof_id}.json"
    assert written.exists()
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["candidate_id"] == "candidate-1"
    assert payload["source_case"] == "git-status-natural-language"
    assert payload["verdict"] == "improved"


def test_candidate_proof_marks_regression_when_after_score_drops() -> None:
    proof = build_candidate_proof(
        "candidate-1",
        _case_result(passed=True, tool_chain_passed=True),
        _case_result(passed=False, tool_chain_passed=False, failure_reasons=["missing_tools"]),
    )

    assert proof.verdict == "regressed"


def test_candidate_proof_rejects_mismatched_source_cases() -> None:
    before = _case_result(name="case-a", passed=True, tool_chain_passed=True)
    after = _case_result(name="case-b", passed=True, tool_chain_passed=True)

    try:
        build_candidate_proof("candidate-1", before, after)
    except ValueError as exc:
        assert "source case mismatch" in str(exc)
    else:
        raise AssertionError("expected mismatched benchmark cases to be rejected")
