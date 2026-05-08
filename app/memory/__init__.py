from app.memory.models import (
    FileSummary,
    MemoryKind,
    MemoryLayer,
    MemoryRecord,
    MemorySearchResult,
    infer_memory_layer,
)
from app.memory.store import MemoryStore

__all__ = [
    "FileSummary",
    "MemoryKind",
    "MemoryLayer",
    "MemoryRecord",
    "MemoryRuntime",
    "MemorySearchResult",
    "MemoryStore",
    "infer_memory_layer",
]


def __getattr__(name: str) -> object:
    if name == "MemoryRuntime":
        from app.memory.runtime import MemoryRuntime

        return MemoryRuntime
    raise AttributeError(f"module 'app.memory' has no attribute {name!r}")
