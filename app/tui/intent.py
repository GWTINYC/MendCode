import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from app.agent.openai_compatible import (
    OpenAIChatCompletionsClient,
    OpenAICompatibleClient,
)
from app.agent.prompt_context import ChatMessage
from app.agent.provider_factory import ProviderConfigurationError
from app.config.settings import Settings

IntentKind = Literal["chat", "fix", "shell", "tool"]

FIX_INTENT_TERMS = (
    "fix",
    "repair",
    "resolve",
    "make tests pass",
    "failed",
    "failing",
    "bug",
    "error",
    "修复",
    "解决",
    "改一下",
    "修改",
    "失败",
    "报错",
)
DIRECT_SHELL_COMMANDS = {
    "ls",
    "pwd",
    "git",
    "rg",
    "cat",
    "head",
    "tail",
    "find",
    "rm",
    "mv",
    "cp",
    "pip",
    "pip3",
    "uv",
    "npm",
    "pnpm",
    "yarn",
    "curl",
    "wget",
    "python",
    "python3",
    "pytest",
    "make",
    "echo",
}


@dataclass(frozen=True)
class IntentContext:
    repo_path: Path
    verification_command: str | None = None


@dataclass(frozen=True)
class IntentDecision:
    kind: IntentKind
    source: str = "rule"
    command: str | None = None


class IntentRouter(Protocol):
    def route(self, message: str, context: IntentContext) -> IntentDecision:
        ...


class RuleBasedIntentRouter:
    def route(self, message: str, context: IntentContext) -> IntentDecision:
        if looks_like_fix_request(message):
            return IntentDecision(kind="fix", source="rule")
        if looks_like_tool_request(message) or looks_like_file_content_request(message):
            return IntentDecision(kind="tool", source="rule")
        shell_command = plan_rule_based_shell_command(message)
        if shell_command is not None:
            return IntentDecision(kind="shell", source="rule", command=shell_command)
        return IntentDecision(kind="chat", source="rule")


class OpenAICompatibleIntentRouter:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        timeout_seconds: int,
        client: OpenAICompatibleClient,
    ) -> None:
        self._rule_router = RuleBasedIntentRouter()
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client = client

    def route(self, message: str, context: IntentContext) -> IntentDecision:
        rule_decision = self._rule_router.route(message, context)
        if rule_decision.kind in {"fix", "shell", "tool"}:
            return rule_decision

        try:
            content = self._client.complete(
                model=self._model,
                messages=_build_intent_messages(message=message, context=context),
                timeout_seconds=self._timeout_seconds,
            )
        except Exception:
            return IntentDecision(kind="chat", source="model_fallback")

        normalized = content.strip().lower()
        if normalized.startswith("fix"):
            return IntentDecision(kind="fix", source="model")
        if normalized.startswith("tool"):
            return IntentDecision(kind="tool", source="model")
        shell_command = _parse_model_shell_command(content)
        if shell_command is not None:
            return IntentDecision(kind="shell", source="model", command=shell_command)
        return IntentDecision(kind="chat", source="model")


def looks_like_fix_request(message: str) -> bool:
    normalized = message.strip().lower()
    return any(term in normalized for term in FIX_INTENT_TERMS)


def looks_like_tool_request(message: str) -> bool:
    normalized = message.strip().lower()
    file_terms = ("文件", "file", "files")
    directory_terms = ("当前文件夹", "当前目录", "current folder", "current directory")
    inspection_terms = ("查看", "看一下", "看下", "列出", "列一下", "有哪些", "list", "show")
    project_stack_terms = (
        "技术栈",
        "tech stack",
        "technology stack",
        "项目类型",
        "project type",
    )
    project_question_terms = (
        "项目",
        "仓库",
        "代码库",
        "project",
        "repo",
        "repository",
        "codebase",
    )
    if any(term in normalized for term in project_stack_terms) and any(
        term in normalized for term in project_question_terms
    ):
        return True
    return (
        any(term in normalized for term in file_terms)
        and any(term in normalized for term in directory_terms)
        and any(term in normalized for term in inspection_terms)
    )


def looks_like_file_content_request(message: str) -> bool:
    normalized = message.strip().lower()
    document_terms = (
        "文件",
        "文档",
        ".md",
        "readme",
        "开发方案",
        "路线图",
        "交互方案",
        "问题记录",
    )
    content_terms = (
        "第一句话",
        "第一行",
        "开头",
        "内容",
        "写了什么",
        "是什么",
        "查看",
        "读取",
        "看一下",
        "看下",
    )
    return any(term in normalized for term in document_terms) and any(
        term in normalized for term in content_terms
    )


def plan_rule_based_shell_command(message: str) -> str | None:
    stripped = message.strip()
    normalized = stripped.lower()
    if not stripped:
        return None

    if any(term in normalized for term in ["列一下当前目录", "列出当前目录", "当前目录有哪些"]):
        return "ls"
    if any(term in normalized for term in ["看下当前路径", "当前路径", "当前目录是哪里"]):
        return "pwd"
    if "git status" in normalized or "仓库状态" in normalized:
        return "git status"
    if "git diff" in normalized or "看下 diff" in normalized or "查看 diff" in normalized:
        return "git diff"

    try:
        tokens = shlex.split(stripped, posix=True)
    except ValueError:
        return None
    if not tokens:
        return None
    executable = tokens[1] if tokens[0] == "sudo" and len(tokens) > 1 else tokens[0]
    if executable in DIRECT_SHELL_COMMANDS:
        return stripped
    return None


def _parse_model_shell_command(content: str) -> str | None:
    stripped = content.strip()
    lower = stripped.lower()
    if not lower.startswith("shell:"):
        return None
    command = stripped.split(":", 1)[1].strip()
    return command or None


def _build_intent_messages(*, message: str, context: IntentContext) -> list[ChatMessage]:
    verification = context.verification_command or "not set"
    return [
        ChatMessage(
            role="system",
            content=(
                "Classify the user's message for MendCode. Return exactly one word: "
                "fix, tool, or chat, or return shell: <command>. Return fix only when the "
                "user wants code changes, debugging, tests fixed, or command-driven "
                "repair. Return tool when the user asks MendCode to inspect local "
                "repository files, directories, code, or git state using its tools, "
                "for example listing current folder files or reading a file. Return "
                "shell: <command> only for explicit terminal commands such as ls, pwd, "
                "git status, git diff, rg, cat, head, tail, and find. Return chat for "
                "questions, explanations, thanks, or general discussion.\n"
                f"repo_path: {context.repo_path}\n"
                f"verification_command: {verification}"
            ),
        ),
        ChatMessage(role="user", content=message),
    ]


def build_intent_router(settings: Settings) -> IntentRouter:
    if settings.provider == "scripted":
        return RuleBasedIntentRouter()
    if settings.provider in {"openai-compatible", "minimax"}:
        if (
            not settings.provider_model
            or not settings.provider_base_url
            or not settings.provider_api_key
        ):
            raise ProviderConfigurationError(
                "openai-compatible provider requires MENDCODE_MODEL, "
                "MENDCODE_BASE_URL, and MENDCODE_API_KEY"
            )
        return OpenAICompatibleIntentRouter(
            model=settings.provider_model,
            api_key=settings.provider_api_key,
            timeout_seconds=settings.provider_timeout_seconds,
            client=OpenAIChatCompletionsClient(
                api_key=settings.provider_api_key,
                base_url=settings.provider_base_url,
            ),
        )
    raise ProviderConfigurationError(f"unsupported provider: {settings.provider}")
