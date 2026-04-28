import json
from pathlib import Path
from typing import Any

from app.agent.provider import AgentObservationRecord
from app.context.metrics import merge_context_metrics, metrics_for_observations
from app.context.models import (
    ContextBudget,
    ContextBundle,
    ContextItem,
    ContextMetrics,
    ContextWarning,
)
from app.memory.recall import MemoryRecallHit
from app.memory.runtime import MemoryRuntime


class ContextManager:
    def __init__(
        self,
        *,
        memory_runtime: MemoryRuntime,
        base_context: str | dict[str, Any] | list[Any] | None = None,
        budget: ContextBudget | None = None,
    ) -> None:
        self.memory_runtime = memory_runtime
        self.base_context = base_context
        self.budget = budget or ContextBudget()
        self._observations: list[AgentObservationRecord] = []
        self._memory_recall: list[MemoryRecallHit] = []
        self._warnings: list[ContextWarning] = []
        self._latest_bundle: ContextBundle | None = None

    def begin_turn(self, *, user_message: str, repo_path: Path) -> ContextBundle:
        self._observations = []
        self._memory_recall = []
        self._warnings = []
        try:
            recall = self.memory_runtime.recall_for_turn(
                user_message=user_message,
                repo_state={"repo_path": str(repo_path)},
                max_items=self.budget.max_memory_items,
            )
            self._memory_recall = recall.hits
        except Exception as exc:  # pragma: no cover - defensive integration guard.
            self._warnings.append(
                ContextWarning(
                    code="memory_recall_failed",
                    message=str(exc),
                    source="memory_runtime",
                )
            )
        return self.build_provider_context()

    def record_observation(self, observation: AgentObservationRecord) -> ContextBundle:
        self._observations.append(observation)
        return self.build_provider_context()

    def build_provider_context(self) -> ContextBundle:
        memory_metrics = ContextMetrics(memory_recall_hits=len(self._memory_recall))
        observation_metrics = metrics_for_observations(self._observations)
        metrics = merge_context_metrics(memory_metrics, observation_metrics)
        items = self._context_items()
        provider_context = self._provider_context_json(metrics)
        metrics.context_chars = len(provider_context)

        while True:
            provider_context = self._provider_context_json(metrics)
            context_chars = len(provider_context)
            if context_chars == metrics.context_chars:
                break
            metrics.context_chars = context_chars

        self._latest_bundle = ContextBundle(
            provider_context=provider_context,
            metrics=metrics,
            warnings=list(self._warnings),
            items=items,
        )
        return self._latest_bundle

    @property
    def latest_bundle(self) -> ContextBundle | None:
        return self._latest_bundle

    def _provider_context_json(self, metrics: ContextMetrics) -> str:
        payload: dict[str, Any] = {
            "base_context": self._parsed_base_context(),
            "memory_recall": [
                hit.model_dump(mode="json", exclude_none=True)
                for hit in self._memory_recall
            ],
            "context_metrics": metrics.model_dump(mode="json"),
        }
        if self._warnings:
            payload["context_warnings"] = [
                warning.model_dump(mode="json", exclude_none=True)
                for warning in self._warnings
            ]
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _parsed_base_context(self) -> Any:
        if self.base_context is None:
            return None
        if isinstance(self.base_context, str):
            try:
                return json.loads(self.base_context)
            except json.JSONDecodeError:
                return self.base_context
        return self.base_context

    def _context_items(self) -> list[ContextItem]:
        items: list[ContextItem] = []
        if self.base_context is not None:
            items.append(
                ContextItem(
                    kind="base_context",
                    title="Base context",
                    content=json.dumps(
                        self._parsed_base_context(),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                )
            )
        items.extend(
            ContextItem(
                kind="memory_recall",
                title=hit.title,
                content=hit.content_excerpt,
                metadata={"id": hit.id, "kind": hit.kind, "score": hit.score},
            )
            for hit in self._memory_recall
        )
        items.extend(
            ContextItem(
                kind="context_warning",
                title=warning.code,
                content=warning.message,
                metadata={"source": warning.source} if warning.source else {},
            )
            for warning in self._warnings
        )
        return items
