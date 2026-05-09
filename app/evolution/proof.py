from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.runtime.benchmark import BenchmarkCaseResult

ProofVerdict = Literal["improved", "regressed", "unchanged"]


class ProofRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proof_id: str = Field(default_factory=lambda: uuid4().hex)
    candidate_id: str = Field(min_length=1, max_length=120)
    source_case: str = Field(min_length=1, max_length=240)
    before_metrics: dict[str, object] = Field(default_factory=dict)
    after_metrics: dict[str, object] = Field(default_factory=dict)
    verdict: ProofVerdict
    created_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())


class CandidateProofStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.proofs_dir = root / "proofs"

    def save(self, proof: ProofRecord) -> Path:
        self.proofs_dir.mkdir(parents=True, exist_ok=True)
        path = self.proofs_dir / f"{proof.proof_id}.json"
        path.write_text(
            json.dumps(proof.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def list_records(self) -> list[ProofRecord]:
        if not self.proofs_dir.exists():
            return []
        records: list[ProofRecord] = []
        for path in sorted(self.proofs_dir.glob("*.json")):
            try:
                records.append(ProofRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        return records


def build_candidate_proof(
    candidate_id: str,
    before: BenchmarkCaseResult,
    after: BenchmarkCaseResult,
) -> ProofRecord:
    if before.name != after.name:
        raise ValueError(
            f"source case mismatch: before={before.name!r} after={after.name!r}"
        )
    before_metrics = before.proof_metrics()
    after_metrics = after.proof_metrics()
    verdict = _verdict(before_metrics, after_metrics)
    return ProofRecord(
        candidate_id=candidate_id,
        source_case=before.name,
        before_metrics=before_metrics,
        after_metrics=after_metrics,
        verdict=verdict,
    )


def _verdict(before_metrics: dict[str, object], after_metrics: dict[str, object]) -> ProofVerdict:
    before_score = _score(before_metrics)
    after_score = _score(after_metrics)
    if after_score > before_score:
        return "improved"
    if after_score < before_score:
        return "regressed"
    return "unchanged"


def _score(metrics: dict[str, object]) -> int:
    score = 0
    if metrics.get("passed") is True:
        score += 5
    if metrics.get("tool_chain_passed") is True:
        score += 3
    failure_reason_count = metrics.get("failure_reason_count")
    if isinstance(failure_reason_count, int):
        score -= failure_reason_count
    missing_tool_count = metrics.get("missing_tool_count")
    if isinstance(missing_tool_count, int):
        score -= missing_tool_count
    if metrics.get("dangerous_command_blocked") is True:
        score += 1
    if metrics.get("provider_failed") is True:
        score -= 3
    if metrics.get("trace_exposed") is True:
        score -= 2
    return score
