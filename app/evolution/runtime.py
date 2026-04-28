from typing import TYPE_CHECKING

from app.evolution.lesson_builder import build_lesson_candidates
from app.evolution.models import EvolutionTurnInput, EvolutionTurnResult

if TYPE_CHECKING:
    from app.memory.runtime import MemoryRuntime


class EvolutionRuntime:
    def __init__(self, memory_runtime: "MemoryRuntime") -> None:
        self.memory_runtime = memory_runtime

    def after_turn(self, turn: EvolutionTurnInput) -> EvolutionTurnResult:
        signals, candidates = build_lesson_candidates(turn)
        for candidate in candidates:
            self.memory_runtime.enqueue_candidate(candidate)
        skipped_reason = None if candidates else "no evolution signals"
        return EvolutionTurnResult(
            generated_candidates=candidates,
            skipped_reason=skipped_reason,
            signals=signals,
        )
