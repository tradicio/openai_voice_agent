import logging
import time
from collections import deque

logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding-window rate limiter over a trailing one-second window."""

    def __init__(self, max_per_second: int):
        self._max_per_second = max_per_second
        self._times: deque = deque()

    def is_limited(self) -> bool:
        """Check and record whether the incoming rate is exceeded.

        Returns
        -------
        bool
            True if the caller has already recorded
            ``max_per_second`` events within the trailing one-second
            window and the current event should be dropped.
        """
        now = time.monotonic()
        window = self._times
        while window and now - window[0] > 1:
            window.popleft()
        if len(window) >= self._max_per_second:
            logger.warning(
                "Audio message rate limit exceeded, dropping frame"
            )
            return True
        window.append(now)
        return False
