import asyncio
import inspect
import logging
from functools import lru_cache


def get_logger(name: str, level: int = logging.DEBUG) -> logging.Logger:
    """Get or create a logger (non-Streamlit version)"""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    return logger


@lru_cache(maxsize=1)
def get_event_loop() -> asyncio.AbstractEventLoop:
    """Get the current event loop or create a new one"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def hash_by_code(obj) -> int:
    """Hash function to detect code changes"""
    return hash(inspect.getsource(obj))
