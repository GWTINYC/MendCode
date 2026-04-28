from pathlib import Path

from app.memory.models import MemoryRecord


def analyze_trace(trace_path: Path) -> MemoryRecord | None:
    """Task 3 placeholder; Task 5 owns full trace analysis behavior."""
    if not trace_path.is_file():
        return None
    return None
