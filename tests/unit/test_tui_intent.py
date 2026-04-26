from pathlib import Path

from app.agent.openai_compatible import ChatMessage
from app.tui.intent import (
    IntentContext,
    OpenAICompatibleIntentRouter,
    RuleBasedIntentRouter,
)


class FakeClient:
    def __init__(self, response: str | None = None, exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc
        self.calls: list[dict[str, object]] = []

    def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        timeout_seconds: int,
    ) -> str:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.exc is not None:
            raise self.exc
        return self.response or ""


def test_rule_based_intent_router_detects_fix_requests(tmp_path: Path) -> None:
    decision = RuleBasedIntentRouter().route(
        "pytest 失败了，帮我修复",
        IntentContext(repo_path=tmp_path),
    )

    assert decision.kind == "fix"


def test_rule_based_intent_router_detects_direct_shell_commands(tmp_path: Path) -> None:
    decision = RuleBasedIntentRouter().route("git status", IntentContext(repo_path=tmp_path))

    assert decision.kind == "shell"
    assert decision.command == "git status"


def test_rule_based_intent_router_maps_natural_language_shell_requests(
    tmp_path: Path,
) -> None:
    decision = RuleBasedIntentRouter().route(
        "列一下当前目录",
        IntentContext(repo_path=tmp_path),
    )

    assert decision.kind == "shell"
    assert decision.command == "ls"


def test_rule_based_intent_router_maps_file_listing_to_tool_request(
    tmp_path: Path,
) -> None:
    decision = RuleBasedIntentRouter().route(
        "帮我查看当前文件夹里的文件",
        IntentContext(repo_path=tmp_path),
    )

    assert decision.kind == "tool"


def test_rule_based_intent_router_maps_document_content_questions_to_tool_request(
    tmp_path: Path,
) -> None:
    decision = RuleBasedIntentRouter().route(
        "mendcode开发方案的第一句话是什么",
        IntentContext(repo_path=tmp_path),
    )

    assert decision.kind == "tool"


def test_rule_based_intent_router_keeps_general_questions_as_chat(tmp_path: Path) -> None:
    decision = RuleBasedIntentRouter().route(
        "what can you do?",
        IntentContext(repo_path=tmp_path),
    )

    assert decision.kind == "chat"


def test_openai_intent_router_uses_model_for_ambiguous_messages(tmp_path: Path) -> None:
    client = FakeClient("fix")
    router = OpenAICompatibleIntentRouter(
        model="test-model",
        api_key="secret-key",
        timeout_seconds=12,
        client=client,
    )

    decision = router.route("the suite is red", IntentContext(repo_path=tmp_path))

    assert decision.kind == "fix"
    assert client.calls[0]["model"] == "test-model"
    assert client.calls[0]["timeout_seconds"] == 12


def test_openai_intent_router_keeps_rule_based_shell_commands_local(
    tmp_path: Path,
) -> None:
    client = FakeClient("chat")
    router = OpenAICompatibleIntentRouter(
        model="test-model",
        api_key="secret-key",
        timeout_seconds=12,
        client=client,
    )

    decision = router.route("ls", IntentContext(repo_path=tmp_path))

    assert decision.kind == "shell"
    assert decision.command == "ls"
    assert client.calls == []


def test_openai_intent_router_keeps_rule_based_tool_requests_local(
    tmp_path: Path,
) -> None:
    client = FakeClient("chat")
    router = OpenAICompatibleIntentRouter(
        model="test-model",
        api_key="secret-key",
        timeout_seconds=12,
        client=client,
    )

    decision = router.route("请查看当前文件夹下有哪些文件", IntentContext(repo_path=tmp_path))

    assert decision.kind == "tool"
    assert client.calls == []


def test_openai_intent_router_can_plan_shell_command_for_ambiguous_message(
    tmp_path: Path,
) -> None:
    client = FakeClient("shell: git status")
    router = OpenAICompatibleIntentRouter(
        model="test-model",
        api_key="secret-key",
        timeout_seconds=12,
        client=client,
    )

    decision = router.route("what is my repo state?", IntentContext(repo_path=tmp_path))

    assert decision.kind == "shell"
    assert decision.command == "git status"


def test_openai_intent_router_accepts_model_tool_classification(tmp_path: Path) -> None:
    client = FakeClient("tool")
    router = OpenAICompatibleIntentRouter(
        model="test-model",
        api_key="secret-key",
        timeout_seconds=12,
        client=client,
    )

    decision = router.route("show project files", IntentContext(repo_path=tmp_path))

    assert decision.kind == "tool"


def test_openai_intent_router_falls_back_to_chat_when_classification_fails(
    tmp_path: Path,
) -> None:
    router = OpenAICompatibleIntentRouter(
        model="test-model",
        api_key="secret-key",
        timeout_seconds=12,
        client=FakeClient(exc=RuntimeError("network failed")),
    )

    decision = router.route("the suite is red", IntentContext(repo_path=tmp_path))

    assert decision.kind == "chat"
