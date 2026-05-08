import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.agent.provider import AgentObservationRecord
from app.context.compaction import (
    compact_memory_hit,
    compact_observation_record,
    compact_text,
)
from app.context.metrics import (
    merge_context_metrics,
    metrics_for_observations,
    normalized_read_file_paths,
)
from app.context.models import (
    ContextBudget,
    ContextBundle,
    ContextItem,
    ContextMetrics,
    ContextWarning,
)
from app.context.token_budget import estimate_token_count
from app.memory.recall import MemoryRecallHit
from app.memory.runtime import MemoryRuntime
from app.repo_map.models import RepoMap
from app.repo_map.store import RepoMapStore

PLAN_ACT_OBSERVE_CONTRACT = {
    "local_facts": "local facts must come from tool observations",
    "code_changes": "verify code changes before claiming completion",
    "tool_failures": "if a required tool fails, explain the blocker instead of guessing",
}


class ContextManager:
    def __init__(
        self,
        *,
        memory_runtime: MemoryRuntime,
        evolution_rule_runtime: object | None = None,
        base_context: str | dict[str, Any] | list[Any] | None = None,
        budget: ContextBudget | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.memory_runtime = memory_runtime
        self.evolution_rule_runtime = evolution_rule_runtime
        self.base_context = base_context
        self.budget = budget or ContextBudget()
        self.data_dir = data_dir or self._default_data_dir()
        self._observations: list[AgentObservationRecord] = []
        self._memory_recall: list[MemoryRecallHit] = []
        self._evolution_rules: list[dict[str, object]] = []
        self._evolution_guidance: list[dict[str, object]] = []
        self._warnings: list[ContextWarning] = []
        self._latest_bundle: ContextBundle | None = None
        self._repo_path: Path | None = None
        self._user_message = ""

    def begin_turn(self, *, user_message: str, repo_path: Path) -> ContextBundle:
        self._observations = []
        self._memory_recall = []
        self._evolution_rules = []
        self._evolution_guidance = []
        self._warnings = []
        self._repo_path = repo_path
        self._user_message = user_message
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
        if self.evolution_rule_runtime is not None and self.budget.max_evolution_rules > 0:
            try:
                recall_for_turn = getattr(self.evolution_rule_runtime, "recall_for_turn")
                recall = recall_for_turn(
                    user_message,
                    max_rules=self.budget.max_evolution_rules,
                    max_chars=self.budget.max_evolution_rule_chars,
                )
                self._evolution_rules = [
                    self._compact_evolution_rule(rule)
                    for rule in getattr(recall, "rules", [])
                ]
                self._evolution_guidance = [
                    self._compact_evolution_guidance(guidance)
                    for guidance in getattr(recall, "guidance", [])
                ]
            except Exception as exc:  # pragma: no cover - defensive integration guard.
                self._warnings.append(
                    ContextWarning(
                        code="evolution_rule_recall_failed",
                        message=str(exc),
                        source="evolution_rule_runtime",
                    )
                )
        return self.build_provider_context()

    def record_observation(self, observation: AgentObservationRecord) -> ContextBundle:
        self._observations.append(observation)
        return self.build_provider_context()

    def build_provider_context(self) -> ContextBundle:
        memory_metrics = ContextMetrics(memory_recall_hits=len(self._memory_recall))
        observation_metrics = metrics_for_observations(self._observations)
        observation_items = self._observation_items()
        file_summary_items = self._file_summary_items()
        repo_context_item = self._repo_context_item()
        repo_context_metrics = self._repo_context_metrics(repo_context_item)
        metrics = merge_context_metrics(
            memory_metrics,
            observation_metrics,
            repo_context_metrics,
        )
        metrics = self._with_compaction_metrics(
            metrics,
            observation_items=observation_items,
            file_summary_items=file_summary_items,
            repo_context_item=repo_context_item,
        )
        items = self._context_items(
            observation_items=observation_items,
            file_summary_items=file_summary_items,
            repo_context_item=repo_context_item,
        )
        metrics = self._with_section_metrics(
            metrics,
            observation_items=observation_items,
            file_summary_items=file_summary_items,
            repo_context_item=repo_context_item,
        )
        provider_context = self._provider_context_json(metrics)
        metrics.context_chars = len(provider_context)
        metrics.estimated_context_tokens = estimate_token_count(provider_context)
        metrics.raw_context_tokens = sum(
            estimate_token_count(record.observation.model_dump_json())
            for record in self._observations
        )
        metrics.compacted_context_tokens = sum(
            estimate_token_count(item.model_dump_json()) for item in observation_items
        )
        metrics.observation_tokens_saved = max(
            0,
            metrics.raw_context_tokens - metrics.compacted_context_tokens,
        )

        while True:
            provider_context = self._provider_context_json(
                metrics,
                observation_items=observation_items,
                file_summary_items=file_summary_items,
                repo_context_item=repo_context_item,
            )
            context_chars = len(provider_context)
            context_tokens = estimate_token_count(provider_context)
            if context_chars == metrics.context_chars:
                if context_tokens == metrics.estimated_context_tokens:
                    break
            metrics.context_chars = context_chars
            metrics.estimated_context_tokens = context_tokens
        metrics.context_chars = len(provider_context)
        metrics.estimated_context_tokens = estimate_token_count(provider_context)

        self._latest_bundle = ContextBundle(
            provider_context=provider_context,
            metrics=metrics,
            warnings=list(self._warnings),
            items=items,
        )
        return self._latest_bundle

    def _with_section_metrics(
        self,
        metrics: ContextMetrics,
        *,
        observation_items: list[ContextItem],
        file_summary_items: list[ContextItem],
        repo_context_item: ContextItem | None,
    ) -> ContextMetrics:
        section_payloads = self._provider_section_payloads(
            observation_items=observation_items,
            file_summary_items=file_summary_items,
            repo_context_item=repo_context_item,
        )
        section_chars = {
            section: self._section_char_count(value)
            for section, value in section_payloads.items()
        }
        section_tokens = {
            section: self._section_token_count(value)
            for section, value in section_payloads.items()
        }
        return metrics.model_copy(
            update={
                "section_chars": section_chars,
                "section_tokens": section_tokens,
                "section_token_budgets": self.budget.section_token_budgets(),
            }
        )

    @property
    def latest_bundle(self) -> ContextBundle | None:
        return self._latest_bundle

    def _provider_context_json(
        self,
        metrics: ContextMetrics,
        *,
        observation_items: list[ContextItem] | None = None,
        file_summary_items: list[ContextItem] | None = None,
        repo_context_item: ContextItem | None = None,
    ) -> str:
        observation_items = observation_items if observation_items is not None else []
        file_summary_items = file_summary_items if file_summary_items is not None else []
        sections = self._provider_section_payloads(
            observation_items=observation_items,
            file_summary_items=file_summary_items,
            repo_context_item=repo_context_item,
        )
        payload: dict[str, Any] = {
            "plan_act_observe_contract": sections["task_state"],
            "base_context": sections["base"],
            "memory_recall": sections["memory"],
            "evolution_rules": sections["guidance"]["evolution_rules"],
            "evolution_guidance": sections["guidance"]["evolution_guidance"],
            "observations": sections["observations"],
            "file_summaries": sections["file_summaries"],
            "repo_context": sections["repo_context"],
            "context_metrics": metrics.model_dump(mode="json"),
        }
        if self._warnings:
            payload["context_warnings"] = [
                warning.model_dump(mode="json", exclude_none=True)
                for warning in self._warnings
            ]
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _provider_section_payloads(
        self,
        *,
        observation_items: list[ContextItem],
        file_summary_items: list[ContextItem],
        repo_context_item: ContextItem | None,
    ) -> dict[str, Any]:
        return {
            "base": self._parsed_base_context(),
            "task_state": PLAN_ACT_OBSERVE_CONTRACT,
            "repo_context": (
                repo_context_item.model_dump(mode="json", exclude_none=True)
                if repo_context_item is not None
                else None
            ),
            "memory": [
                compact_memory_hit(hit, max_chars=self.budget.max_memory_chars)
                for hit in self._memory_recall
            ],
            "guidance": {
                "evolution_rules": list(self._evolution_rules),
                "evolution_guidance": list(self._evolution_guidance),
            },
            "observations": [
                item.model_dump(mode="json", exclude_none=True)
                for item in observation_items
            ],
            "file_summaries": [
                item.model_dump(mode="json", exclude_none=True)
                for item in file_summary_items
            ],
        }

    def _section_char_count(self, value: Any) -> int:
        if self._is_empty_section_value(value):
            return 0
        return len(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        )

    def _section_token_count(self, value: Any) -> int:
        if self._is_empty_section_value(value):
            return 0
        return estimate_token_count(value)

    def _is_empty_section_value(self, value: Any) -> bool:
        if value is None:
            return True
        if value in ({}, [], ""):
            return True
        if isinstance(value, dict) and set(value) == {
            "evolution_rules",
            "evolution_guidance",
        }:
            return not value["evolution_rules"] and not value["evolution_guidance"]
        return False

    def _parsed_base_context(self) -> Any:
        if self.base_context is None:
            return None
        if isinstance(self.base_context, str):
            try:
                return json.loads(self.base_context)
            except json.JSONDecodeError:
                return self.base_context
        return self.base_context

    def _context_items(
        self,
        *,
        observation_items: list[ContextItem],
        file_summary_items: list[ContextItem],
        repo_context_item: ContextItem | None,
    ) -> list[ContextItem]:
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
                content=str(
                    compact_memory_hit(
                        hit,
                        max_chars=self.budget.max_memory_chars,
                    ).get("content_excerpt")
                    or ""
                ),
                metadata={"id": hit.id, "kind": hit.kind, "score": hit.score},
            )
            for hit in self._memory_recall
        )
        items.extend(
            ContextItem(
                kind="evolution_rule",
                title=f"Evolution rule: {rule.get('rule_type', 'rule')}",
                content=str(rule.get("rule_text") or ""),
                metadata={
                    key: value
                    for key, value in rule.items()
                    if key != "rule_text" and value not in {None, ""}
                },
            )
            for rule in self._evolution_rules
        )
        items.extend(
            ContextItem(
                kind="evolution_guidance",
                title=f"Accepted {guidance.get('target_kind', 'guidance')}",
                content=str(guidance.get("content") or ""),
                metadata={
                    key: value
                    for key, value in guidance.items()
                    if key != "content" and value not in {None, ""}
                },
            )
            for guidance in self._evolution_guidance
        )
        items.extend(observation_items)
        items.extend(file_summary_items)
        if repo_context_item is not None:
            items.append(repo_context_item)
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

    def _repo_context_item(self) -> ContextItem | None:
        if not self._should_include_repo_context():
            return None
        if self.budget.max_repo_context_chars <= 0:
            return None
        try:
            repo_map = RepoMapStore(self.data_dir).load_latest()
        except (OSError, ValueError) as exc:
            self._append_warning_once(
                ContextWarning(
                    code="repo_map_read_failed",
                    message=str(exc),
                    source="repo_map_store",
                )
            )
            return None
        if repo_map is None:
            return None
        content, truncated = self._repo_map_content(repo_map)
        return ContextItem(
            kind="repo_context",
            title="Repository map",
            content=content,
            metadata={
                "root": repo_map.root,
                "entry_count": len(repo_map.entries),
                "entry_points": repo_map.entry_points,
                "test_commands": repo_map.test_commands,
                "core_modules": repo_map.core_modules,
                "truncated": truncated,
            },
        )

    def _should_include_repo_context(self) -> bool:
        message = self._user_message.casefold()
        activation_terms = (
            "项目结构",
            "仓库结构",
            "目录结构",
            "文件结构",
            "测试命令",
            "入口文件",
            "核心模块",
            "列出项目",
            "repo map",
            "repository map",
            "project structure",
            "repo structure",
            "directory structure",
            "test command",
            "entry point",
            "core module",
        )
        return any(term in message for term in activation_terms)

    def _repo_map_content(self, repo_map: RepoMap) -> tuple[str, bool]:
        max_chars = self.budget.max_repo_context_chars
        entries = [entry.model_dump(mode="json") for entry in repo_map.entries]
        truncated = False
        while True:
            payload = {
                "root": repo_map.root,
                "generated_at": repo_map.model_dump(mode="json")["generated_at"],
                "entry_points": repo_map.entry_points,
                "test_commands": repo_map.test_commands,
                "core_modules": repo_map.core_modules,
                "entries": entries,
                "metadata": {
                    **repo_map.metadata,
                    "context_entries_returned": len(entries),
                    "context_truncated": truncated,
                },
            }
            content = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if len(content) <= max_chars:
                return content, truncated
            if not entries:
                return compact_text(content, max_chars=max_chars), True
            truncated = True
            entries = entries[:-1]

    def _repo_context_metrics(self, item: ContextItem | None) -> ContextMetrics:
        if item is None or item.content is None:
            return ContextMetrics()
        return ContextMetrics(
            repo_context_chars=len(item.content),
            repo_context_tokens=estimate_token_count(item.content),
        )

    def _observation_items(self) -> list[ContextItem]:
        items = [
            compact_observation_record(
                observation,
                max_chars=self.budget.max_item_excerpt_chars,
            )
            for observation in self._observations[-self.budget.max_observation_items :]
        ]
        if self.budget.max_observation_chars <= 0:
            return []
        bounded: list[ContextItem] = []
        total_chars = 0
        for item in reversed(items):
            item_chars = len(item.model_dump_json())
            if bounded and total_chars + item_chars > self.budget.max_observation_chars:
                break
            bounded.append(item)
            total_chars += item_chars
        return list(reversed(bounded))

    def _file_summary_items(self) -> list[ContextItem]:
        if self._repo_path is None or self.budget.max_file_summary_chars <= 0:
            return []
        items: list[ContextItem] = []
        for path in self._repeated_read_paths():
            try:
                summary = self.memory_runtime.get_file_summary(self._repo_path, path)
            except (OSError, ValueError) as exc:
                self._append_warning_once(
                    ContextWarning(
                        code="file_summary_failed",
                        message=f"{path}: {exc}",
                        source="memory_runtime",
                    )
                )
                continue
            items.append(
                ContextItem(
                    kind="file_summary",
                    title=f"File summary: {summary.path}",
                    content=compact_text(
                        summary.summary,
                        max_chars=self.budget.max_file_summary_chars,
                    ),
                    metadata={
                        "path": summary.path,
                        "content_sha256": summary.content_sha256,
                        "line_count": summary.line_count,
                        "size_bytes": summary.size_bytes,
                        "symbols": summary.symbols[:20],
                    },
                )
            )
        return items

    def _repeated_read_paths(self) -> list[str]:
        counts = Counter(normalized_read_file_paths(self._observations))
        repeated: list[str] = []
        for path in normalized_read_file_paths(self._observations):
            if counts[path] > 1 and path not in repeated:
                repeated.append(path)
        return repeated

    def _compact_evolution_rule(self, rule: object) -> dict[str, object]:
        return {
            "rule_id": str(getattr(rule, "rule_id")),
            "rule_type": str(getattr(rule, "rule_type")),
            "rule_text": str(getattr(rule, "rule_text")),
            "scope": str(getattr(rule, "scope", "")),
            "activation_hint": str(getattr(rule, "activation_hint", "")),
        }

    def _compact_evolution_guidance(self, guidance: object) -> dict[str, object]:
        return {
            "guidance_id": str(getattr(guidance, "guidance_id")),
            "candidate_id": str(getattr(guidance, "candidate_id")),
            "target_kind": str(getattr(guidance, "target_kind")),
            "title": str(getattr(guidance, "title")),
            "content": str(getattr(guidance, "content")),
            "activation_hint": str(getattr(guidance, "activation_hint", "")),
            "suggested_skill": str(getattr(guidance, "suggested_skill", "") or ""),
            "source_report": str(getattr(guidance, "source_report", "") or ""),
            "source_trace": str(getattr(guidance, "source_trace", "") or ""),
        }

    def _with_compaction_metrics(
        self,
        metrics: ContextMetrics,
        *,
        observation_items: list[ContextItem],
        file_summary_items: list[ContextItem],
        repo_context_item: ContextItem | None,
    ) -> ContextMetrics:
        raw_observation_chars = sum(
            len(record.observation.model_dump_json()) for record in self._observations
        )
        compact_observation_chars = sum(
            len(item.model_dump_json()) for item in observation_items
        )
        return metrics.model_copy(
            update={
                "raw_context_chars": raw_observation_chars,
                "raw_context_tokens": sum(
                    estimate_token_count(record.observation.model_dump_json())
                    for record in self._observations
                ),
                "compacted_context_chars": compact_observation_chars,
                "compacted_context_tokens": sum(
                    estimate_token_count(item.model_dump_json()) for item in observation_items
                ),
                "compacted_item_count": (
                    len(observation_items)
                    + len(file_summary_items)
                    + (1 if repo_context_item is not None else 0)
                ),
                "file_summary_hit_count": len(file_summary_items),
                "observation_chars_saved": max(
                    0,
                    raw_observation_chars - compact_observation_chars,
                ),
                "observation_tokens_saved": max(
                    0,
                    sum(
                        estimate_token_count(record.observation.model_dump_json())
                        for record in self._observations
                    )
                    - sum(
                        estimate_token_count(item.model_dump_json())
                        for item in observation_items
                    ),
                ),
            }
        )

    def _append_warning_once(self, warning: ContextWarning) -> None:
        for existing in self._warnings:
            if (
                existing.code == warning.code
                and existing.message == warning.message
                and existing.source == warning.source
            ):
                return
        self._warnings.append(warning)

    def _default_data_dir(self) -> Path:
        store = getattr(self.memory_runtime, "store", None)
        root = getattr(store, "root", None)
        if isinstance(root, Path):
            return root.parent
        return Path("data")
