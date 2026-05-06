import json
from dataclasses import dataclass
from pathlib import Path

from app.context.manager import ContextManager
from app.memory.runtime import MemoryRuntime
from app.memory.store import MemoryStore


@dataclass(frozen=True)
class FakeRule:
    rule_id: str
    rule_type: str
    rule_text: str
    scope: str = ""
    activation_hint: str = ""


@dataclass(frozen=True)
class FakeRuleRecall:
    rules: list[FakeRule]
    context_block: str = ""


class FakeRuleRuntime:
    def __init__(self, rules: list[FakeRule]) -> None:
        self.rules = rules
        self.calls: list[dict[str, object]] = []

    def recall_for_turn(
        self,
        user_message: str,
        *,
        max_rules: int,
        max_chars: int,
    ) -> FakeRuleRecall:
        self.calls.append(
            {
                "user_message": user_message,
                "max_rules": max_rules,
                "max_chars": max_chars,
            }
        )
        return FakeRuleRecall(rules=self.rules[:max_rules])


def _memory_runtime(tmp_path: Path) -> MemoryRuntime:
    return MemoryRuntime(MemoryStore(tmp_path / "data" / "memory"))


def test_context_manager_injects_relevant_accepted_rules(tmp_path: Path) -> None:
    runtime = FakeRuleRuntime(
        [
            FakeRule(
                rule_id="rule-git",
                rule_type="tool_required",
                rule_text="回答 Git 状态前必须调用 git 工具。",
                scope="git status",
                activation_hint="git status",
            )
        ]
    )
    manager = ContextManager(
        memory_runtime=_memory_runtime(tmp_path),
        evolution_rule_runtime=runtime,
    )

    bundle = manager.begin_turn(user_message="请查看 git status", repo_path=tmp_path)
    payload = json.loads(bundle.provider_context)

    assert runtime.calls == [
        {
            "user_message": "请查看 git status",
            "max_rules": 3,
            "max_chars": 1200,
        }
    ]
    assert payload["evolution_rules"][0]["rule_type"] == "tool_required"
    assert "Git 状态" in payload["evolution_rules"][0]["rule_text"]
    assert any(item.kind == "evolution_rule" for item in bundle.items)


def test_context_manager_omits_empty_rule_recall(tmp_path: Path) -> None:
    manager = ContextManager(
        memory_runtime=_memory_runtime(tmp_path),
        evolution_rule_runtime=FakeRuleRuntime([]),
    )

    bundle = manager.begin_turn(user_message="请查看 git status", repo_path=tmp_path)
    payload = json.loads(bundle.provider_context)

    assert payload["evolution_rules"] == []
    assert not [item for item in bundle.items if item.kind == "evolution_rule"]


def test_context_manager_rule_recall_failure_becomes_warning(tmp_path: Path) -> None:
    class FailingRuleRuntime:
        def recall_for_turn(self, *_args, **_kwargs):
            raise RuntimeError("rule store unavailable")

    manager = ContextManager(
        memory_runtime=_memory_runtime(tmp_path),
        evolution_rule_runtime=FailingRuleRuntime(),
    )

    bundle = manager.begin_turn(user_message="git status", repo_path=tmp_path)
    payload = json.loads(bundle.provider_context)

    assert payload["evolution_rules"] == []
    assert any(warning.code == "evolution_rule_recall_failed" for warning in bundle.warnings)


def test_context_manager_respects_evolution_rule_budget(tmp_path: Path) -> None:
    runtime = FakeRuleRuntime(
        [
            FakeRule("rule-1", "tool_required", "rule one"),
            FakeRule("rule-2", "answer_style", "rule two"),
        ]
    )
    manager = ContextManager(
        memory_runtime=_memory_runtime(tmp_path),
        evolution_rule_runtime=runtime,
    )
    manager.budget = manager.budget.model_copy(
        update={"max_evolution_rules": 1, "max_evolution_rule_chars": 80}
    )

    bundle = manager.begin_turn(user_message="anything", repo_path=tmp_path)
    payload = json.loads(bundle.provider_context)

    assert runtime.calls[0]["max_rules"] == 1
    assert runtime.calls[0]["max_chars"] == 80
    assert [rule["rule_id"] for rule in payload["evolution_rules"]] == ["rule-1"]
