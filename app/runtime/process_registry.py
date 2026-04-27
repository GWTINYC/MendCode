from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

ProcessStatus = Literal["running", "exited", "stopped", "missing", "failed"]
_MAX_LOG_BYTES = 2 * 1024 * 1024


class ProcessSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    process_id: str
    command: str | None = None
    cwd: str | None = None
    name: str | None = None
    pid: int | None = None
    status: ProcessStatus
    returncode: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    stdout_offset: int = 0
    stderr_offset: int = 0
    next_stdout_offset: int = 0
    next_stderr_offset: int = 0
    error_message: str | None = None


class _ProcessEntry(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    process_id: str
    command: str
    cwd: Path
    name: str | None = None
    process: subprocess.Popen[str]
    stdout_path: Path
    stderr_path: Path
    stdout_thread: threading.Thread | None = None
    stderr_thread: threading.Thread | None = None
    started_at: float = Field(default_factory=time.monotonic)
    stopped: bool = False


class ProcessRegistry:
    def __init__(self, *, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, _ProcessEntry] = {}

    def start(
        self,
        *,
        command: str,
        cwd: Path,
        name: str | None = None,
        pty: bool = False,
    ) -> ProcessSnapshot:
        del pty
        process_id = self._next_process_id()
        stdout_path = self.log_dir / f"{process_id}.stdout.log"
        stderr_path = self.log_dir / f"{process_id}.stderr.log"
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        process = subprocess.Popen(
            command,
            cwd=cwd,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

        entry = _ProcessEntry(
            process_id=process_id,
            command=command,
            cwd=cwd,
            name=name,
            process=process,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        if process.stdout is not None:
            entry.stdout_thread = _start_log_pump(process.stdout, stdout_path)
        if process.stderr is not None:
            entry.stderr_thread = _start_log_pump(process.stderr, stderr_path)
        self._entries[process_id] = entry
        return self._snapshot(entry, max_chars=0)

    def poll(
        self,
        process_id: str,
        *,
        offset: int | None = None,
        stdout_offset: int | None = None,
        stderr_offset: int | None = None,
        max_chars: int = 12000,
    ) -> ProcessSnapshot:
        entry = self._entries.get(process_id)
        if entry is None:
            return self._missing_snapshot(process_id)
        return self._snapshot(
            entry,
            offset=offset,
            stdout_offset=stdout_offset,
            stderr_offset=stderr_offset,
            max_chars=max_chars,
        )

    def list(self, *, max_chars: int = 0) -> list[ProcessSnapshot]:
        return [self._snapshot(entry, max_chars=max_chars) for entry in self._entries.values()]

    def write(self, process_id: str, input: str) -> ProcessSnapshot:
        entry = self._entries.get(process_id)
        if entry is None:
            return self._missing_snapshot(process_id)
        if entry.process.poll() is not None or entry.process.stdin is None:
            return self._snapshot(
                entry,
                max_chars=0,
                error_message=f"process is not running: {process_id}",
            )
        try:
            entry.process.stdin.write(input)
            entry.process.stdin.flush()
        except OSError as exc:
            return self._snapshot(entry, max_chars=0, error_message=str(exc))
        return self._snapshot(entry, max_chars=0)

    def stop(
        self,
        process_id: str,
        *,
        signal: Literal["term", "kill"] = "term",
    ) -> ProcessSnapshot:
        entry = self._entries.get(process_id)
        if entry is None:
            return self._missing_snapshot(process_id)
        if entry.process.poll() is not None:
            _join_log_threads(entry)
            return self._snapshot(entry, max_chars=0)

        if signal == "kill":
            _kill_process_group(entry.process)
        else:
            _terminate_process_group(entry.process)
        try:
            entry.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _kill_process_group(entry.process)
            entry.process.wait(timeout=2)
        entry.stopped = True
        _join_log_threads(entry)
        return self._snapshot(entry, max_chars=0)

    def stop_all(self) -> None:
        for process_id in list(self._entries):
            self.stop(process_id, signal="term")

    def _next_process_id(self) -> str:
        while True:
            process_id = f"proc-{uuid4().hex[:12]}"
            if process_id not in self._entries:
                return process_id

    def _missing_snapshot(self, process_id: str) -> ProcessSnapshot:
        return ProcessSnapshot(
            process_id=process_id,
            status="missing",
            error_message=f"unknown process_id: {process_id}",
        )

    def _snapshot(
        self,
        entry: _ProcessEntry,
        *,
        offset: int | None = None,
        stdout_offset: int | None = None,
        stderr_offset: int | None = None,
        max_chars: int,
        error_message: str | None = None,
    ) -> ProcessSnapshot:
        returncode = entry.process.poll()
        if returncode is None:
            status: ProcessStatus = "running"
        elif entry.stopped:
            status = "stopped"
        else:
            status = "exited"

        resolved_stdout_offset = stdout_offset if stdout_offset is not None else offset or 0
        resolved_stderr_offset = stderr_offset if stderr_offset is not None else offset or 0
        stdout_excerpt, next_stdout_offset = _read_excerpt(
            entry.stdout_path,
            offset=resolved_stdout_offset,
            max_chars=max_chars,
        )
        stderr_excerpt, next_stderr_offset = _read_excerpt(
            entry.stderr_path,
            offset=resolved_stderr_offset,
            max_chars=max_chars,
        )
        return ProcessSnapshot(
            process_id=entry.process_id,
            command=entry.command,
            cwd=str(entry.cwd),
            name=entry.name,
            pid=entry.process.pid,
            status=status,
            returncode=returncode,
            stdout_path=str(entry.stdout_path),
            stderr_path=str(entry.stderr_path),
            stdout_excerpt=stdout_excerpt,
            stderr_excerpt=stderr_excerpt,
            stdout_offset=resolved_stdout_offset,
            stderr_offset=resolved_stderr_offset,
            next_stdout_offset=next_stdout_offset,
            next_stderr_offset=next_stderr_offset,
            error_message=error_message,
        )


def _read_excerpt(path: Path, *, offset: int, max_chars: int) -> tuple[str, int]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            excerpt = handle.read(max_chars)
            next_offset = handle.tell()
    except OSError:
        return "", offset
    return excerpt, next_offset


def _start_log_pump(stream, path: Path) -> threading.Thread:
    thread = threading.Thread(
        target=_pump_stream_to_capped_log,
        args=(stream, path, _MAX_LOG_BYTES),
        daemon=True,
    )
    thread.start()
    return thread


def _pump_stream_to_capped_log(stream, path: Path, max_bytes: int) -> None:
    written = 0
    truncated = False
    try:
        with path.open("a", encoding="utf-8", errors="replace") as handle:
            while True:
                chunk = stream.readline()
                if not chunk:
                    break
                encoded_size = len(chunk.encode("utf-8", errors="replace"))
                remaining = max_bytes - written
                if remaining > 0:
                    if encoded_size <= remaining:
                        handle.write(chunk)
                        written += encoded_size
                    else:
                        encoded = chunk.encode("utf-8", errors="replace")[:remaining]
                        handle.write(encoded.decode("utf-8", errors="ignore"))
                        written = max_bytes
                        handle.write("\n[process log truncated]\n")
                        truncated = True
                elif not truncated:
                    handle.write("\n[process log truncated]\n")
                    truncated = True
                handle.flush()
    finally:
        stream.close()


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    _signal_process_group(process, signal.SIGTERM)


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    _signal_process_group(process, signal.SIGKILL)


def _signal_process_group(process: subprocess.Popen[str], signal_number: int) -> None:
    try:
        os.killpg(os.getpgid(process.pid), signal_number)
    except ProcessLookupError:
        return
    except OSError:
        if signal_number == signal.SIGKILL:
            process.kill()
        else:
            process.terminate()


def _join_log_threads(entry: _ProcessEntry) -> None:
    for thread in (entry.stdout_thread, entry.stderr_thread):
        if thread is not None:
            thread.join(timeout=1)
