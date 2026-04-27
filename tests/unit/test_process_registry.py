import sys
import time
from pathlib import Path

import app.runtime.process_registry as process_registry_module
from app.runtime.process_registry import ProcessRegistry


def test_process_registry_starts_and_polls_output(tmp_path: Path) -> None:
    registry = ProcessRegistry(log_dir=tmp_path / "processes")
    started = registry.start(
        command=f"{sys.executable} -c \"print('hello')\"",
        cwd=tmp_path,
        name="hello",
        pty=False,
    )

    for _ in range(20):
        polled = registry.poll(started.process_id, max_chars=2000)
        if "hello" in polled.stdout_excerpt:
            break
        time.sleep(0.1)

    assert polled.status in {"running", "exited"}
    assert "hello" in polled.stdout_excerpt


def test_process_registry_polls_line_output_while_process_is_running(tmp_path: Path) -> None:
    registry = ProcessRegistry(log_dir=tmp_path / "processes")
    started = registry.start(
        command=f"{sys.executable} -c \"import time; print('ready', flush=True); time.sleep(5)\"",
        cwd=tmp_path,
        name="prompt",
        pty=False,
    )

    for _ in range(20):
        polled = registry.poll(started.process_id, max_chars=2000)
        if "ready" in polled.stdout_excerpt:
            break
        time.sleep(0.1)

    registry.stop(started.process_id, signal="term")
    assert "ready" in polled.stdout_excerpt
    assert polled.status == "running"


def test_process_registry_stops_running_process(tmp_path: Path) -> None:
    registry = ProcessRegistry(log_dir=tmp_path / "processes")
    started = registry.start(
        command=f"{sys.executable} -c \"import time; time.sleep(30)\"",
        cwd=tmp_path,
        name="sleep",
        pty=False,
    )
    stopped = registry.stop(started.process_id, signal="term")
    assert stopped.status in {"stopped", "exited"}


def test_process_registry_rejects_unknown_process(tmp_path: Path) -> None:
    registry = ProcessRegistry(log_dir=tmp_path / "processes")
    result = registry.poll("missing", max_chars=2000)
    assert result.status == "missing"
    assert result.error_message == "unknown process_id: missing"


def test_process_registry_stop_all_stops_running_processes(tmp_path: Path) -> None:
    registry = ProcessRegistry(log_dir=tmp_path / "processes")
    started = registry.start(
        command=f"{sys.executable} -c \"import time; time.sleep(30)\"",
        cwd=tmp_path,
        name="sleep",
        pty=False,
    )

    registry.stop_all()
    polled = registry.poll(started.process_id, max_chars=2000)

    assert polled.status in {"stopped", "exited"}


def test_process_registry_caps_log_file_size(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(process_registry_module, "_MAX_LOG_BYTES", 128)
    registry = ProcessRegistry(log_dir=tmp_path / "processes")
    started = registry.start(
        command=f"{sys.executable} -c \"print('x' * 1000)\"",
        cwd=tmp_path,
        name="noisy",
        pty=False,
    )

    for _ in range(20):
        polled = registry.poll(started.process_id, max_chars=2000)
        if polled.status == "exited" and "truncated" in polled.stdout_excerpt:
            break
        time.sleep(0.1)

    polled = registry.poll(started.process_id, max_chars=2000)
    assert "process log truncated" in polled.stdout_excerpt


def test_process_registry_tracks_stdout_and_stderr_offsets_separately(
    tmp_path: Path,
) -> None:
    registry = ProcessRegistry(log_dir=tmp_path / "processes")
    started = registry.start(
        command=(
            f"{sys.executable} -c \"import sys; "
            "print('out1'); print('err1', file=sys.stderr)\""
        ),
        cwd=tmp_path,
        name="offsets",
        pty=False,
    )

    for _ in range(20):
        first = registry.poll(started.process_id, max_chars=2000)
        if "out1" in first.stdout_excerpt and "err1" in first.stderr_excerpt:
            break
        time.sleep(0.1)

    second = registry.poll(
        started.process_id,
        stdout_offset=first.next_stdout_offset,
        stderr_offset=0,
        max_chars=2000,
    )

    assert second.stdout_excerpt == ""
    assert "err1" in second.stderr_excerpt
