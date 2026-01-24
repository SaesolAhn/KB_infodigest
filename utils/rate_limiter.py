"""
Rate limiting utilities for InfoDigest Bot.
Provides per-user request throttling to prevent abuse.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""
    allowed: bool
    remaining: int
    reset_in_seconds: float
    message: Optional[str] = None


class RateLimiter:
    """
    Token bucket rate limiter for per-user request throttling.

    Attributes:
        max_requests: Maximum requests allowed in the time window
        window_seconds: Time window in seconds
    """

    def __init__(
        self,
        max_requests: int = 5,
        window_seconds: int = 60
    ):
        """
        Initialize the rate limiter.

        Args:
            max_requests: Maximum requests allowed per window (default: 5)
            window_seconds: Time window in seconds (default: 60)
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[int, List[float]] = defaultdict(list)

    def _cleanup_old_requests(self, user_id: int, current_time: float) -> None:
        """Remove requests older than the time window."""
        cutoff = current_time - self.window_seconds
        self._requests[user_id] = [
            ts for ts in self._requests[user_id] if ts > cutoff
        ]

    def check(self, user_id: int) -> RateLimitResult:
        """
        Check if a user is rate limited without consuming a request.

        Args:
            user_id: The user/chat ID to check

        Returns:
            RateLimitResult with allowed status and metadata
        """
        current_time = time.time()
        self._cleanup_old_requests(user_id, current_time)

        request_count = len(self._requests[user_id])
        remaining = max(0, self.max_requests - request_count)

        if request_count >= self.max_requests:
            oldest_request = min(self._requests[user_id])
            reset_in = (oldest_request + self.window_seconds) - current_time
            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_in_seconds=max(0, reset_in),
                message=f"Rate limit exceeded. Please wait {int(reset_in)} seconds."
            )

        return RateLimitResult(
            allowed=True,
            remaining=remaining,
            reset_in_seconds=0
        )

    def acquire(self, user_id: int) -> RateLimitResult:
        """
        Attempt to acquire a request slot for a user.

        Args:
            user_id: The user/chat ID

        Returns:
            RateLimitResult with allowed status and metadata
        """
        result = self.check(user_id)
        if result.allowed:
            self._requests[user_id].append(time.time())
            result.remaining -= 1
        return result

    def reset(self, user_id: int) -> None:
        """
        Reset rate limit for a specific user.

        Args:
            user_id: The user/chat ID to reset
        """
        if user_id in self._requests:
            del self._requests[user_id]

    def reset_all(self) -> None:
        """Reset rate limits for all users."""
        self._requests.clear()

    def get_status(self, user_id: int) -> Dict:
        """
        Get detailed rate limit status for a user.

        Args:
            user_id: The user/chat ID

        Returns:
            Dictionary with rate limit details
        """
        current_time = time.time()
        self._cleanup_old_requests(user_id, current_time)

        request_count = len(self._requests[user_id])
        remaining = max(0, self.max_requests - request_count)

        return {
            "user_id": user_id,
            "requests_made": request_count,
            "remaining": remaining,
            "max_requests": self.max_requests,
            "window_seconds": self.window_seconds,
        }
