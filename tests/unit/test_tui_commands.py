import pytest

from app.tui.commands import ChatCommand, CommandParseError, ParsedChatInput, parse_chat_input


def test_test_command_parses_command_body() -> None:
    parsed = parse_chat_input("/test python -m pytest -q")

    assert parsed == ParsedChatInput(
        kind="command",
        command=ChatCommand(name="test", args="python -m pytest -q"),
    )


def test_plain_text_parses_as_task_message() -> None:
    parsed = parse_chat_input("pytest is failing, fix it")

    assert parsed == ParsedChatInput(kind="task", task_text="pytest is failing, fix it")


def test_empty_slash_command_returns_clear_error() -> None:
    with pytest.raises(CommandParseError, match="empty slash command"):
        parse_chat_input("/")


def test_unknown_slash_command_returns_clear_error() -> None:
    with pytest.raises(CommandParseError, match="unknown command: /wat"):
        parse_chat_input("/wat now")
