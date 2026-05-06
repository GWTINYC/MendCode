from pathlib import Path
from typing import TYPE_CHECKING

from app.evolution.analysis_ingestion import AnalysisIngestionResult, AnalysisIngestionRuntime
from app.evolution.lesson_builder import build_lesson_candidates
from app.evolution.models import EvolutionTurnInput, EvolutionTurnResult

if TYPE_CHECKING:
    from app.memory.runtime import MemoryRuntime


class EvolutionRuntime:
    def __init__(self, memory_runtime: "MemoryRuntime") -> None:
        self.memory_runtime = memory_runtime

    def after_turn(self, turn: EvolutionTurnInput) -> EvolutionTurnResult:
        signals, candidates = build_lesson_candidates(turn)
        error: dict[str, str] | None = None
        for candidate in candidates:
            try:
                self.memory_runtime.enqueue_candidate(candidate)
            except Exception as exc:  # pragma: no cover - covered by integration/unit tests.
                error = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
                break
        skipped_reason = None if candidates else "no evolution signals"
        return EvolutionTurnResult(
            generated_candidates=candidates,
            skipped_reason=skipped_reason,
            signals=signals,
            error=error,
        )

    def ingest_analysis_reports(
        self,
        reports_dir: Path,
        *,
        limit: int | None = None,
    ) -> AnalysisIngestionResult:
        return AnalysisIngestionRuntime(
            self.memory_runtime,
            reports_dir=reports_dir,
        ).ingest_reports(limit=limit)
