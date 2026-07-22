def __getattr__(name):
    if name in ("OpenAIRealtimeAPIWrapper", "TerminateTaskGroup"):
        from src.realtime.client import OpenAIRealtimeAPIWrapper, TerminateTaskGroup
        return locals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["OpenAIRealtimeAPIWrapper", "TerminateTaskGroup"]
