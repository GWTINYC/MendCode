from app.memory.models import FileSummary, MemoryKind, MemoryRecord, MemorySearchResult
from app.memory.store import MemoryStore

__all__ = [
    "FileSummary",
    "MemoryKind",
    "MemoryRecord",
    "MemoryRuntime",
    "MemorySearchResult",
    "MemoryStore",
]


def __getattr__(name: str) -> object:
    if name == "MemoryRuntime":
        from app.memory.runtime import MemoryRuntime

        return MemoryRuntime
    raise AttributeError(f"module 'app.memory' has no attribute {name!r}")
