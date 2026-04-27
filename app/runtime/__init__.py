__all__ = [
    "AgentRuntime",
    "RuntimeStatus",
    "RuntimeToolStep",
    "RuntimeTurnInput",
    "RuntimeTurnResult",
    "SessionIndexEntry",
    "SessionNotFoundError",
    "SessionStore",
    "TraceToolEvent",
    "TraceView",
    "read_trace_view",
]


def __getattr__(name: str):
    if name == "AgentRuntime":
        from app.runtime.agent_runtime import AgentRuntime

        return AgentRuntime
    if name in {
        "SessionIndexEntry",
        "SessionNotFoundError",
        "SessionStore",
        "TraceToolEvent",
        "TraceView",
        "read_trace_view",
    }:
        from app.runtime import session_store

        return getattr(session_store, name)
    if name in {
        "RuntimeStatus",
        "RuntimeToolStep",
        "RuntimeTurnInput",
        "RuntimeTurnResult",
    }:
        from app.runtime import turn

        return getattr(turn, name)
    raise AttributeError(f"module 'app.runtime' has no attribute {name!r}")
