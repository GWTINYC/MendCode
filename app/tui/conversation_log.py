import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _format_timestamp(value: datetime) -> str:
    return value.astimezone().isoformat(timespec="seconds")


def _safe_fence(value: str) -> str:
    return "````text" if "```" in value else "```text"


@dataclass(frozen=True)
class ConversationLog:
    markdown_path: Path
    jsonl_path: Path
    repo_path: Path
    started_at: datetime
    run_id: str
    _sequence: int = 0

    @classmethod
    def create(
        cls,
        *,
        data_dir: Path,
        repo_path: Path,
        now: datetime | None = None,
        run_id: str | None = None,
    ) -> "ConversationLog":
        started_at = now or datetime.now().astimezone()
        conversation_id = run_id or uuid4().hex[:12]
        filename = f"{started_at.astimezone().strftime('%Y-%m-%d_%H%M%S')}-{conversation_id}"
        directory = data_dir / "conversations"
        directory.mkdir(parents=True, exist_ok=True)
        log = cls(
            markdown_path=directory / f"{filename}.md",
            jsonl_path=directory / f"{filename}.jsonl",
            repo_path=repo_path,
            started_at=started_at,
            run_id=conversation_id,
        )
        log._write_header()
        return log

    def append_message(self, role: str, message: str) -> None:
        self.append_event("message", {"role": role, "message": message})

    def append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        sequence = self._next_sequence()
        timestamp = _format_timestamp(datetime.now().astimezone())
        record = {
            "sequence": sequence,
            "timestamp": timestamp,
            "event_type": event_type,
            "payload": payload,
        }
        self._append_jsonl(record)
        self._append_markdown(record)

    def _next_sequence(self) -> int:
        object.__setattr__(self, "_sequence", self._sequence + 1)
        return self._sequence

    def _write_header(self) -> None:
        self.markdown_path.write_text(
            "\n".join(
                [
                    "# MendCode Conversation",
                    "",
                    f"repo: {self.repo_path}",
                    f"started_at: {_format_timestamp(self.started_at)}",
                    f"run_id: {self.run_id}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self.jsonl_path.write_text("", encoding="utf-8")

    def _append_jsonl(self, record: dict[str, Any]) -> None:
        with self.jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    def _append_markdown(self, record: dict[str, Any]) -> None:
        event_type = str(record["event_type"])
        payload = record["payload"]
        if event_type == "message" and isinstance(payload, dict):
            title = f"Message {record['sequence']} - {payload.get('role', 'Unknown')}"
            body = str(payload.get("message", ""))
        else:
            title = f"Event {record['sequence']} - {event_type}"
            body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        fence = _safe_fence(body)
        closing_fence = "````" if fence.startswith("````") else "```"
        with self.markdown_path.open("a", encoding="utf-8") as handle:
            handle.write(f"## {title}\n\n")
            handle.write(f"timestamp: {record['timestamp']}\n\n")
            handle.write(f"{fence}\n{body}\n{closing_fence}\n\n")
