from pathlib import Path

from app.tui.completions import (
    build_completion_state,
    insert_completion,
)


def test_slash_completion_lists_commands_with_descriptions(tmp_path: Path) -> None:
    state = build_completion_state(repo_path=tmp_path, text="/re", cursor_position=3)

    assert state is not None
    assert state.trigger == "/"
    assert state.items[0].label == "/resume"
    assert "恢复" in state.items[0].description


def test_context_completion_lists_dollar_items(tmp_path: Path) -> None:
    state = build_completion_state(repo_path=tmp_path, text="查看 $st", cursor_position=6)

    assert state is not None
    assert state.items[0].label == "$status"
    assert "仓库" in state.items[0].description


def test_file_completion_lists_repo_paths(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "trace.jsonl").write_text("{}\n", encoding="utf-8")

    state = build_completion_state(repo_path=tmp_path, text="读取 @app", cursor_position=7)

    assert state is not None
    assert state.trigger == "@"
    assert state.items[0].label == "@app/main.py"
    assert state.items[0].description == "文件路径"
    assert all("data/trace.jsonl" not in item.label for item in state.items)


def test_insert_completion_replaces_active_token(tmp_path: Path) -> None:
    state = build_completion_state(repo_path=tmp_path, text="看 /sta", cursor_position=6)

    assert state is not None
    assert insert_completion("看 /sta", 6, state.items[0]) == ("看 /status ", 10)
