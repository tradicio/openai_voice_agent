import asyncio
import inspect
import logging

import streamlit as st


@st.cache_resource
def get_logger(name: str, level: int = logging.DEBUG) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    return logger


@st.cache_resource
def get_event_loop(*, _logger = None) -> asyncio.AbstractEventLoop:
    """Get a new event loop
    """
    if _logger is not None:
        _logger.info('Creating new event loop')
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop


def hash_by_code(obj) -> int:
    """Hash function to detect code changes
    """
    return hash(inspect.getsource(obj))
