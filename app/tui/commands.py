from dataclasses import dataclass
from typing import Literal

ChatInputKind = Literal["command", "task", "empty"]

KNOWN_COMMANDS = {
    "help",
    "status",
    "test",
    "fix",
    "diff",
    "trace",
    "apply",
    "discard",
    "sessions",
    "resume",
    "exit",
}


class CommandParseError(ValueError):
    pass


@dataclass(frozen=True)
class ChatCommand:
    name: str
    args: str = ""


@dataclass(frozen=True)
class ParsedChatInput:
    kind: ChatInputKind
    command: ChatCommand | None = None
    task_text: str | None = None


def parse_chat_input(raw_text: str) -> ParsedChatInput:
    text = raw_text.strip()
    if not text:
        return ParsedChatInput(kind="empty")

    if not text.startswith("/"):
        return ParsedChatInput(kind="task", task_text=text)

    command_text = text[1:].strip()
    if not command_text:
        raise CommandParseError("empty slash command")

    name, _, args = command_text.partition(" ")
    name = name.strip().lower()
    if name not in KNOWN_COMMANDS:
        raise CommandParseError(f"unknown command: /{name}")

    return ParsedChatInput(
        kind="command",
        command=ChatCommand(name=name, args=args.strip()),
    )
