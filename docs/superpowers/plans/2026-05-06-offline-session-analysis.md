# Offline Session Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `mendcode trace analyze-session <path>` to produce bounded JSON and Markdown reports for conversation Markdown and JSONL trace files.

**Architecture:** Implement a standalone `app/runtime/session_analysis/` package with strict models, parsers, deterministic analyzer rules, and renderers. Keep CLI code thin: it resolves paths, calls the runtime package, writes reports, and prints output paths.

**Tech Stack:** Python 3.12, Typer, Pydantic, pytest, Rich console output, existing MendCode trace/conversation files.

---

## File Structure

- Create `app/runtime/session_analysis/__init__.py`
  - Public exports for the analyzer package.
- Create `app/runtime/session_analysis/models.py`
  - Pydantic models: `SessionTranscript`, `ToolCallEvent`, `ObservationEvent`, `SessionAnalysisReport`, and finding models.
- Create `app/runtime/session_analysis/parsers.py`
  - `parse_session_file(path: Path) -> SessionTranscript`.
  - Markdown parser for `*.md`.
  - JSONL parser for `*.jsonl`.
- Create `app/runtime/session_analysis/analyzer.py`
  - `analyze_transcript(transcript: SessionTranscript) -> SessionAnalysisReport`.
  - Rule helpers for expected tools, missing tools, repeats, failures, oversized outputs, unsupported claims, risk events, recommendations.
- Create `app/runtime/session_analysis/renderer.py`
  - `render_report_json(report: SessionAnalysisReport) -> str`.
  - `render_report_markdown(report: SessionAnalysisReport) -> str`.
  - `write_analysis_report(report, output_dir, output_format) -> list[Path]`.
- Modify `app/cli/main.py`
  - Add `trace_app = typer.Typer(...)`.
  - Register `app.add_typer(trace_app, name="trace")`.
  - Add `trace analyze-session` command.
- Create `tests/unit/test_session_analysis_models.py`
- Create `tests/unit/test_session_analysis_parsers.py`
- Create `tests/unit/test_session_analysis_analyzer.py`
- Create `tests/unit/test_session_analysis_renderer.py`
- Modify `tests/integration/test_cli.py`
  - Add CLI integration coverage.
- Modify `README.md` and `MendCode_开发方案.md`
  - Document the new offline analysis command and where it fits in the memory/self-evolution loop.

Implementation should happen in a fresh worktree:

```bash
git worktree add .worktrees/offline-session-analysis -b offline-session-analysis develop
cd .worktrees/offline-session-analysis
```

Do not edit or revert the parent workspace `.gitignore` change.

---

### Task 1: Add Analysis Models

**Files:**
- Create: `app/runtime/session_analysis/__init__.py`
- Create: `app/runtime/session_analysis/models.py`
- Test: `tests/unit/test_session_analysis_models.py`

- [ ] **Step 1: Write model tests**

Create `tests/unit/test_session_analysis_models.py`:

```python
from pathlib import Path

from app.runtime.session_analysis.models import (
    ObservationEvent,
    SessionAnalysisReport,
    SessionTranscript,
    ToolCallEvent,
)


def test_session_transcript_defaults_are_stable(tmp_path: Path) -> None:
    transcript = SessionTranscript(
        session_id="conversation-1",
        source_path=tmp_path / "conversation.md",
        input_kind="conversation_markdown",
        user_messages=["查看 git 状态"],
    )

    assert transcript.assistant_messages == []
    assert transcript.tool_calls == []
    assert transcript.observations == []
    assert transcript.final_answer == ""


def test_tool_call_fingerprint_uses_tool_and_arguments() -> None:
    call = ToolCallEvent(
        tool_name="read_file",
        arguments={"path": "README.md", "tail": 1},
        call_index=2,
    )

    assert call.arguments_excerpt == '{"path":"README.md","tail":1}'
    assert len(call.arguments_fingerprint) == 16


def test_observation_visible_chars_counts_bounded_content() -> None:
    observation = ObservationEvent(
        tool_name="read_file",
        status="succeeded",
        content_excerpt="abc",
        stdout_excerpt="de",
    )

    assert observation.visible_chars == 5


def test_report_computed_observed_tools_are_unique(tmp_path: Path) -> None:
    report = SessionAnalysisReport(
        session_id="trace-1",
        source_path=tmp_path / "trace.jsonl",
        input_kind="jsonl_trace",
        user_messages=["列文件"],
        tool_calls=[
            ToolCallEvent(tool_name="list_dir", arguments={"path": "."}, call_index=1),
            ToolCallEvent(tool_name="list_dir", arguments={"path": "."}, call_index=2),
        ],
    )

    assert report.observed_tools == ["list_dir"]
```

- [ ] **Step 2: Run model tests and verify failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_session_analysis_models.py -q
```

Expected: import failure because `app.runtime.session_analysis` does not exist.

- [ ] **Step 3: Implement models**

Create `app/runtime/session_analysis/__init__.py`:

```python
from app.runtime.session_analysis.analyzer import analyze_transcript
from app.runtime.session_analysis.parsers import parse_session_file
from app.runtime.session_analysis.renderer import (
    render_report_json,
    render_report_markdown,
    write_analysis_report,
)

__all__ = [
    "analyze_transcript",
    "parse_session_file",
    "render_report_json",
    "render_report_markdown",
    "write_analysis_report",
]
```

Create `app/runtime/session_analysis/models.py`:

```python
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

InputKind = Literal["conversation_markdown", "jsonl_trace"]
FindingSeverity = Literal["info", "warning", "error"]

MAX_EXCERPT_CHARS = 1200


def compact_text(value: Any, *, max_chars: int = MAX_EXCERPT_CHARS) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n[truncated]"


def compact_json(value: Any, *, max_chars: int = MAX_EXCERPT_CHARS) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except TypeError:
        text = str(value)
    return compact_text(text, max_chars=max_chars)


def fingerprint_value(value: Any) -> str:
    raw = compact_json(value, max_chars=8000)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class ToolCallEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_index: int = 0
    status: str = "unknown"
    requires_confirmation: bool = False
    risk_level: str = "unknown"
    duration_ms: int | None = None
    raw_excerpt: str = ""

    @field_validator("tool_name")
    @classmethod
    def validate_tool_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("tool_name is required")
        return stripped

    @computed_field
    @property
    def arguments_excerpt(self) -> str:
        return compact_json(self.arguments)

    @computed_field
    @property
    def arguments_fingerprint(self) -> str:
        return fingerprint_value({"tool_name": self.tool_name, "arguments": self.arguments})


class ObservationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    status: str = "unknown"
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    content_excerpt: str = ""
    exit_code: int | None = None
    error_excerpt: str = ""
    raw_excerpt: str = ""
    call_index: int | None = None
    requires_confirmation: bool = False
    risk_level: str = "unknown"

    @field_validator(
        "stdout_excerpt",
        "stderr_excerpt",
        "content_excerpt",
        "error_excerpt",
        "raw_excerpt",
    )
    @classmethod
    def bound_text(cls, value: str) -> str:
        return compact_text(value)

    @computed_field
    @property
    def visible_chars(self) -> int:
        return len(self.stdout_excerpt) + len(self.stderr_excerpt) + len(self.content_excerpt)


class SessionTranscript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    source_path: Path
    input_kind: InputKind
    user_messages: list[str] = Field(default_factory=list)
    assistant_messages: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallEvent] = Field(default_factory=list)
    observations: list[ObservationEvent] = Field(default_factory=list)
    final_answer: str = ""

    @field_validator("final_answer")
    @classmethod
    def bound_final_answer(cls, value: str) -> str:
        return compact_text(value, max_chars=6000)


class AnalysisFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: FindingSeverity = "warning"
    summary: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class SessionAnalysisReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    source_path: Path
    input_kind: InputKind
    user_messages: list[str] = Field(default_factory=list)
    final_answer_excerpt: str = ""
    tool_calls: list[ToolCallEvent] = Field(default_factory=list)
    observations: list[ObservationEvent] = Field(default_factory=list)
    expected_tools: list[AnalysisFinding] = Field(default_factory=list)
    missing_tools: list[AnalysisFinding] = Field(default_factory=list)
    repeated_tools: list[AnalysisFinding] = Field(default_factory=list)
    failed_tools: list[AnalysisFinding] = Field(default_factory=list)
    oversized_outputs: list[AnalysisFinding] = Field(default_factory=list)
    unsupported_claims: list[AnalysisFinding] = Field(default_factory=list)
    risk_events: list[AnalysisFinding] = Field(default_factory=list)
    root_causes: list[AnalysisFinding] = Field(default_factory=list)
    recommendations: list[AnalysisFinding] = Field(default_factory=list)
    confidence: str = "medium"

    @computed_field
    @property
    def observed_tools(self) -> list[str]:
        return sorted({call.tool_name for call in self.tool_calls} | {obs.tool_name for obs in self.observations})
```

- [ ] **Step 4: Add temporary module stubs required by `__init__` imports**

Create `app/runtime/session_analysis/analyzer.py`:

```python
from app.runtime.session_analysis.models import SessionAnalysisReport, SessionTranscript


def analyze_transcript(transcript: SessionTranscript) -> SessionAnalysisReport:
    return SessionAnalysisReport(
        session_id=transcript.session_id,
        source_path=transcript.source_path,
        input_kind=transcript.input_kind,
        user_messages=transcript.user_messages,
        final_answer_excerpt=transcript.final_answer,
        tool_calls=transcript.tool_calls,
        observations=transcript.observations,
        confidence="high" if transcript.input_kind == "jsonl_trace" else "medium",
    )
```

Create `app/runtime/session_analysis/parsers.py`:

```python
from pathlib import Path

from app.runtime.session_analysis.models import SessionTranscript


def parse_session_file(path: Path) -> SessionTranscript:
    raise NotImplementedError("parse_session_file is implemented in Task 2")
```

Create `app/runtime/session_analysis/renderer.py`:

```python
from pathlib import Path

from app.runtime.session_analysis.models import SessionAnalysisReport


def render_report_json(report: SessionAnalysisReport) -> str:
    return report.model_dump_json(indent=2)


def render_report_markdown(report: SessionAnalysisReport) -> str:
    return f"# MendCode Session Analysis\n\nSession: {report.session_id}\n"


def write_analysis_report(
    report: SessionAnalysisReport,
    output_dir: Path,
    output_format: str = "both",
) -> list[Path]:
    raise NotImplementedError("write_analysis_report is implemented in Task 4")
```

- [ ] **Step 5: Run model tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_session_analysis_models.py -q
```

Expected: all model tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add app/runtime/session_analysis tests/unit/test_session_analysis_models.py
git commit -m "feat: add session analysis models"
```

---

### Task 2: Add Markdown And JSONL Parsers

**Files:**
- Modify: `app/runtime/session_analysis/parsers.py`
- Test: `tests/unit/test_session_analysis_parsers.py`

- [ ] **Step 1: Write parser tests**

Create `tests/unit/test_session_analysis_parsers.py`:

```python
import json
from pathlib import Path

from app.runtime.session_analysis.parsers import parse_session_file


def test_parse_markdown_conversation_extracts_messages(tmp_path: Path) -> None:
    path = tmp_path / "2026-04-27_160326-323e138850fe.md"
    path.write_text(
        "\n".join(
            [
                "# Conversation",
                "## User",
                "MendCode问题记录的最后一句是什么",
                "## Assistant",
                "我需要查看文件。",
                "## Assistant",
                "这是最终回答。",
            ]
        ),
        encoding="utf-8",
    )

    transcript = parse_session_file(path)

    assert transcript.session_id == "2026-04-27_160326-323e138850fe"
    assert transcript.input_kind == "conversation_markdown"
    assert transcript.user_messages == ["MendCode问题记录的最后一句是什么"]
    assert transcript.final_answer == "这是最终回答。"


def test_parse_markdown_conversation_extracts_visible_tool_block(tmp_path: Path) -> None:
    path = tmp_path / "session.md"
    path.write_text(
        "\n".join(
            [
                "## User",
                "查看 git 状态",
                "## Tool",
                "tool: git",
                "status: failed",
                "stderr: fatal error",
                "## Assistant",
                "当前仓库是干净的。",
            ]
        ),
        encoding="utf-8",
    )

    transcript = parse_session_file(path)

    assert transcript.tool_calls[0].tool_name == "git"
    assert transcript.observations[0].status == "failed"
    assert "fatal error" in transcript.observations[0].stderr_excerpt


def test_parse_jsonl_trace_extracts_tool_and_final_response(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    events = [
        {
            "run_id": "run-1",
            "event_type": "agent.user_message",
            "message": "user",
            "payload": {"message": "列一下当前目录"},
        },
        {
            "run_id": "run-1",
            "event_type": "agent.tool_call",
            "message": "tool",
            "payload": {"tool_name": "list_dir", "arguments": {"path": "."}},
        },
        {
            "run_id": "run-1",
            "event_type": "agent.tool_observation",
            "message": "observation",
            "payload": {
                "observation": {
                    "tool_name": "list_dir",
                    "status": "succeeded",
                    "payload": {"entries": ["README.md"]},
                    "summary": "listed directory",
                }
            },
        },
        {
            "run_id": "run-1",
            "event_type": "agent.final_response",
            "message": "final",
            "payload": {"content": "当前目录包含 README.md。"},
        },
    ]
    path.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events), encoding="utf-8")

    transcript = parse_session_file(path)

    assert transcript.session_id == "trace"
    assert transcript.input_kind == "jsonl_trace"
    assert transcript.user_messages == ["列一下当前目录"]
    assert transcript.tool_calls[0].tool_name == "list_dir"
    assert transcript.observations[0].tool_name == "list_dir"
    assert transcript.final_answer == "当前目录包含 README.md。"


def test_parse_session_rejects_unknown_suffix(tmp_path: Path) -> None:
    path = tmp_path / "session.txt"
    path.write_text("x", encoding="utf-8")

    try:
        parse_session_file(path)
    except ValueError as exc:
        assert "unsupported session file type" in str(exc)
    else:
        raise AssertionError("expected ValueError")
```

- [ ] **Step 2: Run parser tests and verify failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_session_analysis_parsers.py -q
```

Expected: tests fail because `parse_session_file` is still a stub.

- [ ] **Step 3: Implement parsers**

Replace `app/runtime/session_analysis/parsers.py` with:

```python
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.runtime.session_analysis.models import (
    ObservationEvent,
    SessionTranscript,
    ToolCallEvent,
    compact_json,
    compact_text,
)

_HEADING_RE = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*$")
_TOOL_RE = re.compile(r"tool\s*[:=]\s*(?P<tool>[A-Za-z0-9_./-]+)", re.IGNORECASE)
_STATUS_RE = re.compile(r"status\s*[:=]\s*(?P<status>[A-Za-z0-9_./-]+)", re.IGNORECASE)
_STDERR_RE = re.compile(r"stderr\s*[:=]\s*(?P<stderr>.*)", re.IGNORECASE | re.DOTALL)


def parse_session_file(path: Path) -> SessionTranscript:
    resolved = path.expanduser()
    if not resolved.exists():
        raise FileNotFoundError(resolved)
    if resolved.suffix.lower() == ".md":
        return _parse_markdown(resolved)
    if resolved.suffix.lower() == ".jsonl":
        return _parse_jsonl(resolved)
    raise ValueError(f"unsupported session file type: {resolved.suffix}")


def _parse_markdown(path: Path) -> SessionTranscript:
    sections = _split_markdown_sections(path.read_text(encoding="utf-8"))
    user_messages: list[str] = []
    assistant_messages: list[str] = []
    tool_calls: list[ToolCallEvent] = []
    observations: list[ObservationEvent] = []

    for title, body in sections:
        normalized = title.casefold()
        content = compact_text(body.strip(), max_chars=6000)
        if not content:
            continue
        if "user" in normalized or "用户" in normalized:
            user_messages.append(content)
            continue
        if "assistant" in normalized or "mendcode" in normalized or "助手" in normalized:
            assistant_messages.append(content)
            continue
        if "tool" in normalized or "工具" in normalized or "command" in normalized:
            tool_name = _extract_regex(_TOOL_RE, content, "tool") or "unknown"
            status = _extract_regex(_STATUS_RE, content, "status") or "unknown"
            stderr = _extract_regex(_STDERR_RE, content, "stderr") or ""
            call_index = len(tool_calls) + 1
            tool_calls.append(
                ToolCallEvent(
                    tool_name=tool_name,
                    arguments={},
                    call_index=call_index,
                    status=status,
                    raw_excerpt=content,
                )
            )
            observations.append(
                ObservationEvent(
                    tool_name=tool_name,
                    status=status,
                    stderr_excerpt=stderr,
                    raw_excerpt=content,
                    call_index=call_index,
                )
            )

    final_answer = assistant_messages[-1] if assistant_messages else ""
    return SessionTranscript(
        session_id=path.stem,
        source_path=path,
        input_kind="conversation_markdown",
        user_messages=user_messages,
        assistant_messages=assistant_messages,
        tool_calls=tool_calls,
        observations=observations,
        final_answer=final_answer,
    )


def _split_markdown_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = []
    current_title = "document"
    current_lines: list[str] = []
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            sections.append((current_title, current_lines))
            current_title = match.group("title")
            current_lines = []
        else:
            current_lines.append(line)
    sections.append((current_title, current_lines))
    return [(title, "\n".join(lines)) for title, lines in sections]


def _parse_jsonl(path: Path) -> SessionTranscript:
    user_messages: list[str] = []
    assistant_messages: list[str] = []
    tool_calls: list[ToolCallEvent] = []
    observations: list[ObservationEvent] = []
    final_answer = ""

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        payload = payload if isinstance(payload, dict) else {}

        if "user" in event_type:
            message = _first_text(payload, ["message", "content", "user_message"]) or event.get("message")
            if message:
                user_messages.append(compact_text(message, max_chars=6000))
        if "assistant" in event_type and "tool" not in event_type:
            message = _first_text(payload, ["message", "content", "text"]) or event.get("message")
            if message:
                assistant_messages.append(compact_text(message, max_chars=6000))
        if "tool_call" in event_type or event_type.endswith(".tool.call"):
            tool_calls.append(_tool_call_from_payload(payload, len(tool_calls) + 1, event))
        if "observation" in event_type or "tool_result" in event_type:
            observations.append(_observation_from_payload(payload, len(observations) + 1, event))
        if "final" in event_type or event_type == "agent.run.completed":
            text = _first_text(payload, ["content", "final_response", "response", "summary"])
            if text:
                final_answer = compact_text(text, max_chars=6000)

    if not final_answer and assistant_messages:
        final_answer = assistant_messages[-1]

    return SessionTranscript(
        session_id=path.stem,
        source_path=path,
        input_kind="jsonl_trace",
        user_messages=user_messages,
        assistant_messages=assistant_messages,
        tool_calls=tool_calls,
        observations=observations,
        final_answer=final_answer,
    )


def _tool_call_from_payload(
    payload: dict[str, Any],
    call_index: int,
    raw_event: dict[str, Any],
) -> ToolCallEvent:
    action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
    arguments = payload.get("arguments")
    if arguments is None and isinstance(action, dict):
        arguments = action.get("args") or action.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    tool_name = (
        _first_text(payload, ["tool_name", "name", "action"])
        or _first_text(action if isinstance(action, dict) else {}, ["tool_name", "name", "type"])
        or "unknown"
    )
    return ToolCallEvent(
        tool_name=tool_name,
        arguments=arguments,
        call_index=call_index,
        status=str(payload.get("status") or "unknown"),
        requires_confirmation=bool(payload.get("requires_confirmation") or payload.get("needs_user_confirmation")),
        risk_level=str(payload.get("risk_level") or "unknown"),
        duration_ms=_optional_int(payload.get("duration_ms")),
        raw_excerpt=compact_json(raw_event),
    )


def _observation_from_payload(
    payload: dict[str, Any],
    call_index: int,
    raw_event: dict[str, Any],
) -> ObservationEvent:
    observation = payload.get("observation")
    if not isinstance(observation, dict):
        observation = payload
    nested_payload = observation.get("payload") if isinstance(observation.get("payload"), dict) else {}
    return ObservationEvent(
        tool_name=str(observation.get("tool_name") or payload.get("tool_name") or payload.get("action") or "unknown"),
        status=str(observation.get("status") or payload.get("status") or "unknown"),
        stdout_excerpt=compact_text(nested_payload.get("stdout") or observation.get("stdout") or ""),
        stderr_excerpt=compact_text(nested_payload.get("stderr") or observation.get("stderr") or ""),
        content_excerpt=compact_json(nested_payload if nested_payload else observation.get("content") or ""),
        exit_code=_optional_int(nested_payload.get("exit_code") or observation.get("exit_code")),
        error_excerpt=compact_text(observation.get("error_message") or payload.get("error_message") or ""),
        raw_excerpt=compact_json(raw_event),
        call_index=call_index,
        requires_confirmation=bool(observation.get("requires_confirmation") or observation.get("needs_user_confirmation")),
        risk_level=str(observation.get("risk_level") or payload.get("risk_level") or "unknown"),
    )


def _extract_regex(pattern: re.Pattern[str], text: str, group: str) -> str | None:
    match = pattern.search(text)
    if match is None:
        return None
    return match.group(group).strip()


def _first_text(payload: dict[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 4: Run parser tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_session_analysis_parsers.py -q
```

Expected: all parser tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add app/runtime/session_analysis/parsers.py tests/unit/test_session_analysis_parsers.py
git commit -m "feat: parse session analysis inputs"
```

---

### Task 3: Add Deterministic Analyzer Rules

**Files:**
- Modify: `app/runtime/session_analysis/analyzer.py`
- Test: `tests/unit/test_session_analysis_analyzer.py`

- [ ] **Step 1: Write analyzer tests**

Create `tests/unit/test_session_analysis_analyzer.py`:

```python
from pathlib import Path

from app.runtime.session_analysis.analyzer import analyze_transcript
from app.runtime.session_analysis.models import (
    ObservationEvent,
    SessionTranscript,
    ToolCallEvent,
)


def test_missing_list_dir_and_unsupported_claim_for_directory_question(tmp_path: Path) -> None:
    transcript = SessionTranscript(
        session_id="conversation",
        source_path=tmp_path / "conversation.md",
        input_kind="conversation_markdown",
        user_messages=["帮我查看当前文件夹里的文件"],
        final_answer="当前目录有 README.md 和 app 目录。",
    )

    report = analyze_transcript(transcript)

    assert _codes(report.missing_tools) == ["missing_directory_listing"]
    assert _codes(report.unsupported_claims) == ["unsupported_local_claim"]
    assert "prompt_rule" in _targets(report.recommendations)


def test_git_status_question_requires_git_or_shell(tmp_path: Path) -> None:
    transcript = SessionTranscript(
        session_id="trace",
        source_path=tmp_path / "trace.jsonl",
        input_kind="jsonl_trace",
        user_messages=["查看 git status"],
        final_answer="工作区干净。",
    )

    report = analyze_transcript(transcript)

    assert _codes(report.missing_tools) == ["missing_git_status"]
    assert report.confidence == "high"


def test_repeated_failed_tool_then_certain_answer_is_flagged(tmp_path: Path) -> None:
    transcript = SessionTranscript(
        session_id="trace",
        source_path=tmp_path / "trace.jsonl",
        input_kind="jsonl_trace",
        user_messages=["MendCode问题记录的最后一句是什么"],
        tool_calls=[
            ToolCallEvent(tool_name="read_file", arguments={"path": "MendCode_问题记录.md"}, call_index=1),
            ToolCallEvent(tool_name="read_file", arguments={"path": "MendCode_问题记录.md"}, call_index=2),
            ToolCallEvent(tool_name="read_file", arguments={"path": "MendCode_问题记录.md"}, call_index=3),
        ],
        observations=[
            ObservationEvent(tool_name="read_file", status="failed", error_excerpt="file not found", call_index=1),
            ObservationEvent(tool_name="read_file", status="failed", error_excerpt="file not found", call_index=2),
            ObservationEvent(tool_name="read_file", status="failed", error_excerpt="file not found", call_index=3),
        ],
        final_answer="最后一句是：已修复。",
    )

    report = analyze_transcript(transcript)

    assert _codes(report.repeated_tools) == ["repeated_tool_call"]
    assert _codes(report.failed_tools) == ["failed_tool_observation"]
    assert _codes(report.unsupported_claims) == ["unsupported_after_failed_tool"]
    assert "final_response_gate" in _targets(report.recommendations)


def test_oversized_final_answer_is_flagged(tmp_path: Path) -> None:
    transcript = SessionTranscript(
        session_id="conversation",
        source_path=tmp_path / "conversation.md",
        input_kind="conversation_markdown",
        user_messages=["某文档最后一句是什么"],
        tool_calls=[ToolCallEvent(tool_name="read_file", arguments={"path": "README.md"}, call_index=1)],
        observations=[ObservationEvent(tool_name="read_file", status="succeeded", content_excerpt="ok")],
        final_answer="x" * 3500,
    )

    report = analyze_transcript(transcript)

    assert _codes(report.oversized_outputs) == ["oversized_final_answer"]
    assert "context_compaction" in _targets(report.recommendations)


def test_dangerous_confirmation_observation_becomes_risk_event(tmp_path: Path) -> None:
    transcript = SessionTranscript(
        session_id="trace",
        source_path=tmp_path / "trace.jsonl",
        input_kind="jsonl_trace",
        user_messages=["删除所有文件"],
        observations=[
            ObservationEvent(
                tool_name="run_shell_command",
                status="needs_user_confirmation",
                risk_level="high",
                error_excerpt="confirmation required",
            )
        ],
    )

    report = analyze_transcript(transcript)

    assert _codes(report.risk_events) == ["permission_confirmation_required"]
    assert "permission_policy" in _targets(report.recommendations)


def _codes(findings) -> list[str]:
    return [finding.code for finding in findings]


def _targets(findings) -> list[str]:
    return [str(finding.evidence.get("target")) for finding in findings]
```

- [ ] **Step 2: Run analyzer tests and verify failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_session_analysis_analyzer.py -q
```

Expected: analyzer tests fail because the stub has no rules.

- [ ] **Step 3: Implement analyzer rules**

Replace `app/runtime/session_analysis/analyzer.py` with:

```python
from __future__ import annotations

from collections import Counter

from app.runtime.session_analysis.models import (
    AnalysisFinding,
    ObservationEvent,
    SessionAnalysisReport,
    SessionTranscript,
    ToolCallEvent,
    compact_text,
)

FINAL_ANSWER_VISIBLE_LIMIT = 3000
OBSERVATION_VISIBLE_LIMIT = 6000
FAILED_STATUSES = {
    "failed",
    "rejected",
    "timed_out",
    "permission_required",
    "needs_user_confirmation",
}
LOCAL_FACT_PATTERNS = [
    "当前目录",
    "当前文件夹",
    "工作区",
    "仓库",
    "最后一句",
    "文件",
    "README",
    "git",
]


def analyze_transcript(transcript: SessionTranscript) -> SessionAnalysisReport:
    expected_tools = _expected_tools(transcript.user_messages)
    missing_tools = _missing_tools(expected_tools, transcript)
    repeated_tools = _repeated_tools(transcript.tool_calls)
    failed_tools = _failed_tools(transcript.observations)
    oversized_outputs = _oversized_outputs(transcript)
    unsupported_claims = _unsupported_claims(transcript, missing_tools, failed_tools)
    risk_events = _risk_events(transcript.observations)
    root_causes = _root_causes(
        missing_tools=missing_tools,
        repeated_tools=repeated_tools,
        failed_tools=failed_tools,
        oversized_outputs=oversized_outputs,
        unsupported_claims=unsupported_claims,
        risk_events=risk_events,
    )
    recommendations = _recommendations(
        missing_tools=missing_tools,
        repeated_tools=repeated_tools,
        failed_tools=failed_tools,
        oversized_outputs=oversized_outputs,
        unsupported_claims=unsupported_claims,
        risk_events=risk_events,
    )
    return SessionAnalysisReport(
        session_id=transcript.session_id,
        source_path=transcript.source_path,
        input_kind=transcript.input_kind,
        user_messages=transcript.user_messages,
        final_answer_excerpt=compact_text(transcript.final_answer, max_chars=1200),
        tool_calls=transcript.tool_calls,
        observations=transcript.observations,
        expected_tools=expected_tools,
        missing_tools=missing_tools,
        repeated_tools=repeated_tools,
        failed_tools=failed_tools,
        oversized_outputs=oversized_outputs,
        unsupported_claims=unsupported_claims,
        risk_events=risk_events,
        root_causes=root_causes,
        recommendations=recommendations,
        confidence="high" if transcript.input_kind == "jsonl_trace" else "medium",
    )


def _expected_tools(user_messages: list[str]) -> list[AnalysisFinding]:
    text = "\n".join(user_messages).casefold()
    findings: list[AnalysisFinding] = []
    if any(term in text for term in ["当前文件夹", "当前目录", "列文件", "列一下", "ls"]):
        findings.append(_finding("expected_directory_listing", "Expected directory listing tool", tools=["list_dir", "run_shell_command"]))
    if "git status" in text or "git 状态" in text or "查看 git" in text:
        findings.append(_finding("expected_git_status", "Expected git status tool", tools=["git", "run_shell_command"]))
    if any(term in text for term in ["最后一句", "last sentence", "last line", "tail"]):
        findings.append(_finding("expected_file_read", "Expected file read for precise file question", tools=["read_file"]))
    if any(term in text for term in ["搜索", "查找", "rg ", "grep", "在哪"]):
        findings.append(_finding("expected_code_search", "Expected code search tool", tools=["rg", "search_code", "glob_file_search"]))
    if any(term in text for term in ["修复", "patch", "报错", "测试失败"]):
        findings.append(_finding("expected_repair_chain", "Expected repair tool chain", tools=["read_file", "apply_patch", "run_command"]))
    if any(term in text for term in ["删除", "rm ", "安装", "pip install", "push", "reset"]):
        findings.append(_finding("expected_risk_event", "Expected permission or risk event", tools=["run_shell_command"]))
    return findings


def _missing_tools(expected: list[AnalysisFinding], transcript: SessionTranscript) -> list[AnalysisFinding]:
    observed = set(transcript_tool_names(transcript))
    findings: list[AnalysisFinding] = []
    for item in expected:
        tools = [str(tool) for tool in item.evidence.get("tools", [])]
        if any(tool in observed for tool in tools):
            continue
        code = {
            "expected_directory_listing": "missing_directory_listing",
            "expected_git_status": "missing_git_status",
            "expected_file_read": "missing_file_read",
            "expected_code_search": "missing_code_search",
            "expected_repair_chain": "missing_repair_tool_chain",
            "expected_risk_event": "missing_risk_event",
        }.get(item.code, "missing_expected_tool")
        findings.append(_finding(code, f"Missing expected tool group: {', '.join(tools)}", tools=tools))
    return findings


def _repeated_tools(tool_calls: list[ToolCallEvent]) -> list[AnalysisFinding]:
    counts = Counter((call.tool_name, call.arguments_fingerprint) for call in tool_calls)
    repeated = [key for key, count in counts.items() if count > 1 and key[0] not in {"unknown"}]
    if not repeated:
        return []
    return [
        _finding(
            "repeated_tool_call",
            "Same tool and arguments were called repeatedly",
            severity="warning",
            repeated=[{"tool_name": tool, "count": counts[(tool, fingerprint)]} for tool, fingerprint in repeated],
        )
    ]


def _failed_tools(observations: list[ObservationEvent]) -> list[AnalysisFinding]:
    failed = [obs for obs in observations if obs.status in FAILED_STATUSES]
    if not failed:
        return []
    return [
        _finding(
            "failed_tool_observation",
            "One or more tool observations failed or were rejected",
            severity="error",
            failed=[{"tool_name": obs.tool_name, "status": obs.status, "error": obs.error_excerpt} for obs in failed],
        )
    ]


def _oversized_outputs(transcript: SessionTranscript) -> list[AnalysisFinding]:
    findings: list[AnalysisFinding] = []
    if len(transcript.final_answer) > FINAL_ANSWER_VISIBLE_LIMIT:
        findings.append(_finding("oversized_final_answer", "Final answer is too long for a precise response", chars=len(transcript.final_answer)))
    oversized_obs = [obs for obs in transcript.observations if obs.visible_chars > OBSERVATION_VISIBLE_LIMIT]
    if oversized_obs:
        findings.append(
            _finding(
                "oversized_observation",
                "Tool observation visible output exceeds bounded report threshold",
                observations=[{"tool_name": obs.tool_name, "visible_chars": obs.visible_chars} for obs in oversized_obs],
            )
        )
    return findings


def _unsupported_claims(
    transcript: SessionTranscript,
    missing_tools: list[AnalysisFinding],
    failed_tools: list[AnalysisFinding],
) -> list[AnalysisFinding]:
    final_answer = transcript.final_answer.strip()
    if not final_answer:
        return []
    if failed_tools and _looks_certain(final_answer):
        return [_finding("unsupported_after_failed_tool", "Final answer is certain after failed tool observation", severity="error")]
    if missing_tools and _mentions_local_fact(final_answer):
        return [_finding("unsupported_local_claim", "Final answer states local facts without required observation", severity="error")]
    return []


def _risk_events(observations: list[ObservationEvent]) -> list[AnalysisFinding]:
    findings: list[AnalysisFinding] = []
    for observation in observations:
        if observation.status in {"needs_user_confirmation", "permission_required"}:
            findings.append(
                _finding(
                    "permission_confirmation_required",
                    "Tool required confirmation before execution",
                    tool_name=observation.tool_name,
                    risk_level=observation.risk_level,
                )
            )
        elif observation.status == "rejected" and (
            observation.risk_level in {"high", "critical"} or "permission" in observation.error_excerpt.casefold()
        ):
            findings.append(
                _finding(
                    "dangerous_tool_rejected",
                    "Dangerous or unauthorized tool was rejected",
                    tool_name=observation.tool_name,
                    risk_level=observation.risk_level,
                )
            )
    return findings


def _root_causes(**groups: list[AnalysisFinding]) -> list[AnalysisFinding]:
    causes: list[AnalysisFinding] = []
    if groups["missing_tools"]:
        causes.append(_finding("tool_selection_gap", "Model did not call a required local tool", target="prompt_rule"))
    if groups["failed_tools"] and groups["unsupported_claims"]:
        causes.append(_finding("failed_observation_ignored", "Final response was not gated after tool failure", target="final_response_gate"))
    if groups["repeated_tools"]:
        causes.append(_finding("tool_repetition", "Agent repeated equivalent tool calls", target="context_compaction"))
    if groups["oversized_outputs"]:
        causes.append(_finding("context_waste", "Response or observation exceeded concise output budget", target="context_compaction"))
    if groups["risk_events"]:
        causes.append(_finding("permission_boundary", "Permission event must remain explicit and traceable", target="permission_policy"))
    return causes


def _recommendations(**groups: list[AnalysisFinding]) -> list[AnalysisFinding]:
    recommendations: list[AnalysisFinding] = []
    if groups["missing_tools"]:
        recommendations.append(_finding("recommend_prompt_rule", "Strengthen prompt rule for required tool use", target="prompt_rule"))
        recommendations.append(_finding("recommend_tool_schema", "Review tool schema discoverability", target="tool_schema"))
    if groups["failed_tools"] and groups["unsupported_claims"]:
        recommendations.append(_finding("recommend_final_response_gate", "Prevent certain local answers after failed observations", target="final_response_gate"))
    if groups["repeated_tools"]:
        recommendations.append(_finding("recommend_memory_or_compaction", "Reuse prior observations or summaries before repeating reads", target="memory"))
    if groups["oversized_outputs"]:
        recommendations.append(_finding("recommend_context_budget", "Compact long outputs before showing or storing them", target="context_compaction"))
    if groups["risk_events"]:
        recommendations.append(_finding("recommend_permission_policy", "Keep confirmation and denial behavior explicit", target="permission_policy"))
    if any(groups.values()):
        recommendations.append(_finding("recommend_benchmark_case", "Add or update a benchmark case for this failure pattern", target="benchmark_case"))
    return recommendations


def transcript_tool_names(transcript: SessionTranscript) -> list[str]:
    return [call.tool_name for call in transcript.tool_calls] + [obs.tool_name for obs in transcript.observations]


def _mentions_local_fact(text: str) -> bool:
    return any(pattern.casefold() in text.casefold() for pattern in LOCAL_FACT_PATTERNS)


def _looks_certain(text: str) -> bool:
    uncertain = ["无法", "不能确定", "没有成功", "需要", "请提供"]
    return not any(word in text for word in uncertain)


def _finding(
    code: str,
    summary: str,
    *,
    severity: str = "warning",
    **evidence: object,
) -> AnalysisFinding:
    return AnalysisFinding(code=code, severity=severity, summary=summary, evidence=evidence)
```

- [ ] **Step 4: Run analyzer tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_session_analysis_analyzer.py -q
```

Expected: all analyzer tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add app/runtime/session_analysis/analyzer.py tests/unit/test_session_analysis_analyzer.py
git commit -m "feat: analyze session tool grounding"
```

---

### Task 4: Add JSON And Markdown Renderers

**Files:**
- Modify: `app/runtime/session_analysis/renderer.py`
- Test: `tests/unit/test_session_analysis_renderer.py`

- [ ] **Step 1: Write renderer tests**

Create `tests/unit/test_session_analysis_renderer.py`:

```python
import json
from pathlib import Path

from app.runtime.session_analysis.analyzer import analyze_transcript
from app.runtime.session_analysis.models import SessionTranscript
from app.runtime.session_analysis.renderer import (
    render_report_json,
    render_report_markdown,
    write_analysis_report,
)


def test_render_report_json_contains_structured_fields(tmp_path: Path) -> None:
    report = analyze_transcript(
        SessionTranscript(
            session_id="session-1",
            source_path=tmp_path / "session.md",
            input_kind="conversation_markdown",
            user_messages=["查看 git status"],
            final_answer="工作区干净。",
        )
    )

    payload = json.loads(render_report_json(report))

    assert payload["session_id"] == "session-1"
    assert payload["missing_tools"][0]["code"] == "missing_git_status"
    assert payload["observed_tools"] == []


def test_render_report_markdown_is_bounded_and_readable(tmp_path: Path) -> None:
    report = analyze_transcript(
        SessionTranscript(
            session_id="session-1",
            source_path=tmp_path / "session.md",
            input_kind="conversation_markdown",
            user_messages=["某文档最后一句是什么"],
            final_answer="x" * 4000,
        )
    )

    markdown = render_report_markdown(report)

    assert "# MendCode Session Analysis" in markdown
    assert "## Missing / Repeated / Failed Tools" in markdown
    assert "oversized_final_answer" in markdown
    assert len(markdown) < 12000


def test_write_analysis_report_respects_format(tmp_path: Path) -> None:
    report = analyze_transcript(
        SessionTranscript(
            session_id="session-1",
            source_path=tmp_path / "session.md",
            input_kind="conversation_markdown",
            user_messages=["列文件"],
        )
    )

    written = write_analysis_report(report, tmp_path / "reports", output_format="json")

    assert written == [tmp_path / "reports" / "session-1.json"]
    assert written[0].exists()
    assert not (tmp_path / "reports" / "session-1.md").exists()


def test_write_analysis_report_rejects_unknown_format(tmp_path: Path) -> None:
    report = analyze_transcript(
        SessionTranscript(
            session_id="session-1",
            source_path=tmp_path / "session.md",
            input_kind="conversation_markdown",
        )
    )

    try:
        write_analysis_report(report, tmp_path / "reports", output_format="xml")
    except ValueError as exc:
        assert "output_format must be one of" in str(exc)
    else:
        raise AssertionError("expected ValueError")
```

- [ ] **Step 2: Run renderer tests and verify failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_session_analysis_renderer.py -q
```

Expected: at least write-format tests fail because `write_analysis_report` is still a stub.

- [ ] **Step 3: Implement renderer**

Replace `app/runtime/session_analysis/renderer.py` with:

```python
from __future__ import annotations

from pathlib import Path

from app.runtime.session_analysis.models import AnalysisFinding, SessionAnalysisReport, compact_text

VALID_OUTPUT_FORMATS = {"json", "md", "both"}


def render_report_json(report: SessionAnalysisReport) -> str:
    return report.model_dump_json(indent=2)


def render_report_markdown(report: SessionAnalysisReport) -> str:
    lines = [
        "# MendCode Session Analysis",
        "",
        "## Summary",
        f"- session_id: `{report.session_id}`",
        f"- input_kind: `{report.input_kind}`",
        f"- source_path: `{report.source_path}`",
        f"- confidence: `{report.confidence}`",
        f"- observed_tools: {_inline_list(report.observed_tools)}",
        "",
        "## User Request",
        _bullet_text(report.user_messages),
        "",
        "## Expected Tool Chain",
        _finding_list(report.expected_tools),
        "",
        "## Actual Tool Chain",
        _actual_tool_chain(report),
        "",
        "## Missing / Repeated / Failed Tools",
        _finding_list(report.missing_tools + report.repeated_tools + report.failed_tools),
        "",
        "## Observation Grounding",
        _finding_list(report.unsupported_claims),
        "",
        "## Context Waste",
        _finding_list(report.oversized_outputs),
        "",
        "## Permission And Risk Events",
        _finding_list(report.risk_events),
        "",
        "## Root Causes",
        _finding_list(report.root_causes),
        "",
        "## Recommendations",
        _finding_list(report.recommendations),
        "",
        "## Final Answer Excerpt",
        compact_text(report.final_answer_excerpt, max_chars=1200) or "none",
        "",
    ]
    return "\n".join(lines)


def write_analysis_report(
    report: SessionAnalysisReport,
    output_dir: Path,
    output_format: str = "both",
) -> list[Path]:
    if output_format not in VALID_OUTPUT_FORMATS:
        raise ValueError("output_format must be one of: both, json, md")
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if output_format in {"json", "both"}:
        path = output_dir / f"{report.session_id}.json"
        path.write_text(render_report_json(report), encoding="utf-8")
        written.append(path)
    if output_format in {"md", "both"}:
        path = output_dir / f"{report.session_id}.md"
        path.write_text(render_report_markdown(report), encoding="utf-8")
        written.append(path)
    return written


def _finding_list(findings: list[AnalysisFinding]) -> str:
    if not findings:
        return "- none"
    lines: list[str] = []
    for finding in findings:
        lines.append(f"- `{finding.code}` ({finding.severity}): {finding.summary}")
        if finding.evidence:
            rendered = ", ".join(f"{key}={compact_text(value, max_chars=200)!r}" for key, value in finding.evidence.items())
            lines.append(f"  evidence: {rendered}")
    return "\n".join(lines)


def _actual_tool_chain(report: SessionAnalysisReport) -> str:
    if not report.tool_calls and not report.observations:
        return "- none"
    lines: list[str] = []
    for call in report.tool_calls:
        lines.append(f"- call #{call.call_index}: `{call.tool_name}` status={call.status}")
    for observation in report.observations:
        lines.append(f"- observation: `{observation.tool_name}` status={observation.status} visible_chars={observation.visible_chars}")
    return "\n".join(lines)


def _bullet_text(items: list[str]) -> str:
    if not items:
        return "- none"
    return "\n".join(f"- {compact_text(item, max_chars=500)}" for item in items)


def _inline_list(items: list[str]) -> str:
    return ", ".join(f"`{item}`" for item in items) if items else "none"
```

- [ ] **Step 4: Run renderer tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_session_analysis_renderer.py -q
```

Expected: all renderer tests pass.

- [ ] **Step 5: Commit Task 4**

```bash
git add app/runtime/session_analysis/renderer.py tests/unit/test_session_analysis_renderer.py
git commit -m "feat: render session analysis reports"
```

---

### Task 5: Add CLI Command

**Files:**
- Modify: `app/cli/main.py`
- Test: `tests/integration/test_cli.py`

- [ ] **Step 1: Write CLI integration tests**

Append these tests near the benchmark CLI tests in `tests/integration/test_cli.py`:

```python
def test_trace_analyze_session_writes_json_and_markdown(tmp_path: Path) -> None:
    conversation = tmp_path / "conversation.md"
    conversation.write_text(
        "\n".join(
            [
                "## User",
                "帮我查看当前文件夹里的文件",
                "## Assistant",
                "当前目录有 README.md。",
            ]
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "reports"

    result = runner.invoke(
        app,
        ["trace", "analyze-session", str(conversation), "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 0
    assert "Analysis reports written" in result.stdout
    assert (output_dir / "conversation.json").exists()
    assert (output_dir / "conversation.md").exists()
    assert "missing_directory_listing" in (output_dir / "conversation.json").read_text(encoding="utf-8")


def test_trace_analyze_session_json_format_only(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "event_type": "agent.user_message",
                "message": "user",
                "payload": {"message": "查看 git status"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "reports"

    result = runner.invoke(
        app,
        [
            "trace",
            "analyze-session",
            str(trace),
            "--output-dir",
            str(output_dir),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert (output_dir / "trace.json").exists()
    assert not (output_dir / "trace.md").exists()


def test_trace_analyze_session_rejects_llm_flag_for_first_version(tmp_path: Path) -> None:
    conversation = tmp_path / "conversation.md"
    conversation.write_text("## User\n列文件\n", encoding="utf-8")

    result = runner.invoke(app, ["trace", "analyze-session", str(conversation), "--llm"])

    assert result.exit_code != 0
    assert "--llm is reserved" in result.stdout
```

- [ ] **Step 2: Run CLI tests and verify failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/integration/test_cli.py -q -k "trace_analyze_session"
```

Expected: Typer reports no such command.

- [ ] **Step 3: Add trace subcommand**

Modify imports near the existing runtime imports in `app/cli/main.py`:

```python
from app.runtime.session_analysis import (
    analyze_transcript,
    parse_session_file,
    write_analysis_report,
)
```

Add a Typer app next to `story_app` and `benchmark_app`:

```python
trace_app = typer.Typer(help="Trace and conversation analysis utilities")
```

Register it:

```python
app.add_typer(trace_app, name="trace")
```

Add this command near the benchmark commands:

```python
@trace_app.command("analyze-session")
def trace_analyze_session(
    path: Path,
    output_dir: Path = typer.Option(Path("data/analysis-reports"), "--output-dir"),
    output_format: str = typer.Option("both", "--format"),
    llm: bool = typer.Option(False, "--llm"),
) -> None:
    if llm:
        raise typer.BadParameter("--llm is reserved for a later evidence-grounded summary layer")
    transcript = parse_session_file(path)
    report = analyze_transcript(transcript)
    written = write_analysis_report(report, output_dir, output_format=output_format)
    console.print("Analysis reports written")
    for item in written:
        console.print(str(item))
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/integration/test_cli.py -q -k "trace_analyze_session"
```

Expected: all new CLI tests pass.

- [ ] **Step 5: Commit Task 5**

```bash
git add app/cli/main.py tests/integration/test_cli.py
git commit -m "feat: add trace analyze-session cli"
```

---

### Task 6: Add End-To-End Fixtures For Target Failure Patterns

**Files:**
- Test: `tests/unit/test_session_analysis_end_to_end.py`

- [ ] **Step 1: Write combined parser/analyzer/renderer tests**

Create `tests/unit/test_session_analysis_end_to_end.py`:

```python
import json
from pathlib import Path

from app.runtime.session_analysis import (
    analyze_transcript,
    parse_session_file,
    render_report_markdown,
)


def test_markdown_directory_question_without_tool_is_diagnosed(tmp_path: Path) -> None:
    path = tmp_path / "directory.md"
    path.write_text(
        "## User\n帮我查看当前文件夹里的文件\n## Assistant\n当前目录包含 README.md。\n",
        encoding="utf-8",
    )

    report = analyze_transcript(parse_session_file(path))

    assert [finding.code for finding in report.missing_tools] == ["missing_directory_listing"]
    assert [finding.code for finding in report.unsupported_claims] == ["unsupported_local_claim"]


def test_jsonl_repeated_failed_read_then_fabricated_answer_is_diagnosed(tmp_path: Path) -> None:
    path = tmp_path / "failed-read.jsonl"
    events = [
        {"run_id": "run", "event_type": "agent.user_message", "message": "user", "payload": {"message": "问题记录最后一句是什么"}},
        {"run_id": "run", "event_type": "agent.tool_call", "message": "tool", "payload": {"tool_name": "read_file", "arguments": {"path": "MendCode_问题记录.md"}}},
        {"run_id": "run", "event_type": "agent.tool_call", "message": "tool", "payload": {"tool_name": "read_file", "arguments": {"path": "MendCode_问题记录.md"}}},
        {"run_id": "run", "event_type": "agent.tool_observation", "message": "obs", "payload": {"observation": {"tool_name": "read_file", "status": "failed", "error_message": "not found"}}},
        {"run_id": "run", "event_type": "agent.final_response", "message": "final", "payload": {"content": "最后一句是：已修复。"}},
    ]
    path.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events), encoding="utf-8")

    report = analyze_transcript(parse_session_file(path))
    markdown = render_report_markdown(report)

    assert "repeated_tool_call" in markdown
    assert "failed_tool_observation" in markdown
    assert "unsupported_after_failed_tool" in markdown
```

- [ ] **Step 2: Run end-to-end tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_session_analysis_end_to_end.py -q
```

Expected: all end-to-end tests pass.

- [ ] **Step 3: Commit Task 6**

```bash
git add tests/unit/test_session_analysis_end_to_end.py
git commit -m "test: cover session analysis failure patterns"
```

---

### Task 7: Update User And Developer Documentation

**Files:**
- Modify: `README.md`
- Modify: `MendCode_开发方案.md`

- [ ] **Step 1: Update README**

Add a short section near existing CLI/runtime usage:

```markdown
### 离线对话复盘

MendCode 可以对本地 conversation Markdown 或 JSONL trace 做离线分析，帮助判断一轮对话中是否缺少工具调用、是否重复读取、是否忽略失败 observation、是否输出过长内容。

```bash
mendcode trace analyze-session data/conversations/session.md
mendcode trace analyze-session data/traces/session.jsonl --format json
```

默认报告写入 `data/analysis-reports/`，该目录属于本地运行产物，不应提交到仓库。第一版分析器默认使用规则引擎；`--llm` 入口预留给后续基于证据的自然语言归因。
```

- [ ] **Step 2: Update development plan**

In `MendCode_开发方案.md`, add this under the current memory/evolution or trace section:

```markdown
### 离线 Session Analysis

已规划并实现 `mendcode trace analyze-session <path>`，用于分析 `data/conversations/*.md` 和 `data/traces/*.jsonl`。它默认生成 `data/analysis-reports/<session-id>.json` 与 `<session-id>.md`，报告包含 expected tools、observed tools、missing/repeated/failed tools、oversized outputs、unsupported claims、risk events、root causes 和 recommendations。

该能力是自进化闭环的前置证据层：Benchmark / PTY 场景失败后可以调用分析器生成归因报告，后续再由 EvolutionRuntime 读取 JSON 报告生成可审查的 Memory / SKILL / Prompt Rule / Tool Schema 候选。
```

- [ ] **Step 3: Commit docs**

```bash
git add README.md MendCode_开发方案.md
git commit -m "docs: document offline session analysis"
```

---

### Task 8: Verification And Merge Back

**Files:**
- No planned source changes in this task.

- [ ] **Step 1: Run focused tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_session_analysis_models.py tests/unit/test_session_analysis_parsers.py tests/unit/test_session_analysis_analyzer.py tests/unit/test_session_analysis_renderer.py tests/unit/test_session_analysis_end_to_end.py tests/integration/test_cli.py -q -k "session_analysis or trace_analyze_session"
```

Expected: all selected tests pass.

- [ ] **Step 2: Run full non-e2e test suite**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q --ignore=tests/e2e
```

Expected: all non-e2e tests pass.

- [ ] **Step 3: Run lint**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

Expected: ruff passes.

- [ ] **Step 4: Smoke test CLI manually**

Run:

```bash
printf '## User\n查看 git status\n## Assistant\n工作区干净。\n' > /tmp/mendcode-analysis-smoke.md
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m app.cli.main trace analyze-session /tmp/mendcode-analysis-smoke.md --output-dir /tmp/mendcode-analysis-report
cat /tmp/mendcode-analysis-report/mendcode-analysis-smoke.md
```

Expected: command writes JSON and Markdown, and the Markdown includes `missing_git_status`.

- [ ] **Step 5: Merge back to develop**

From the parent repo:

```bash
cd /home/wxh/MendCode
git status --short --branch
git merge --ff-only offline-session-analysis
```

Expected: fast-forward merge into `develop`. The parent `.gitignore` user change remains untouched.

- [ ] **Step 6: Remove worktree after merge**

```bash
git worktree remove .worktrees/offline-session-analysis
git branch -d offline-session-analysis
```

Expected: worktree removed and feature branch deleted after merge.

---

## Spec Coverage Self-Review

- Supports Markdown and JSONL inputs: Tasks 2 and 6.
- Produces JSON and Markdown reports: Task 4.
- Adds `mendcode trace analyze-session`: Task 5.
- Keeps `--llm` reserved: Task 5.
- Detects expected, observed, missing, repeated, failed, oversized, unsupported-claim, risk, root-cause, and recommendation fields: Tasks 1 and 3.
- Keeps reports bounded: Tasks 1 and 4.
- Adds deterministic tests without live providers: Tasks 1 through 6.
- Documents the command and evolution role: Task 7.
- Verifies with focused tests, full non-e2e suite, ruff, and manual smoke: Task 8.
