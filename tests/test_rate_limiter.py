"""
Tests for rate limiting functionality.
"""

import time
import pytest
from utils.rate_limiter import RateLimiter, RateLimitResult


class TestRateLimiter:
    """Tests for RateLimiter class."""

    def test_initial_request_allowed(self):
        """Test that initial request is allowed."""
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        result = limiter.acquire(user_id=123)

        assert result.allowed is True
        assert result.remaining == 4  # 5 - 1 = 4

    def test_multiple_requests_within_limit(self):
        """Test multiple requests within limit are allowed."""
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        user_id = 123

        for i in range(5):
            result = limiter.acquire(user_id)
            assert result.allowed is True
            assert result.remaining == 4 - i

    def test_requests_exceed_limit(self):
        """Test that requests exceeding limit are blocked."""
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        user_id = 123

        # Make 3 allowed requests
        for _ in range(3):
            result = limiter.acquire(user_id)
            assert result.allowed is True

        # 4th request should be blocked
        result = limiter.acquire(user_id)
        assert result.allowed is False
        assert result.remaining == 0
        assert result.message is not None

    def test_check_does_not_consume_request(self):
        """Test that check() doesn't consume a request slot."""
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        user_id = 123

        # Check multiple times
        for _ in range(5):
            result = limiter.check(user_id)
            assert result.allowed is True
            assert result.remaining == 2  # Still 2 remaining

    def test_different_users_have_separate_limits(self):
        """Test that different users have independent limits."""
        limiter = RateLimiter(max_requests=2, window_seconds=60)

        # User 1 makes 2 requests
        limiter.acquire(user_id=1)
        limiter.acquire(user_id=1)

        # User 1 is now limited
        result = limiter.acquire(user_id=1)
        assert result.allowed is False

        # User 2 can still make requests
        result = limiter.acquire(user_id=2)
        assert result.allowed is True

    def test_reset_clears_user_limit(self):
        """Test that reset() clears limit for specific user."""
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        user_id = 123

        # Exhaust limit
        limiter.acquire(user_id)
        limiter.acquire(user_id)
        assert limiter.acquire(user_id).allowed is False

        # Reset user
        limiter.reset(user_id)

        # User can make requests again
        result = limiter.acquire(user_id)
        assert result.allowed is True

    def test_reset_all_clears_all_limits(self):
        """Test that reset_all() clears all user limits."""
        limiter = RateLimiter(max_requests=1, window_seconds=60)

        # Exhaust limit for multiple users
        limiter.acquire(user_id=1)
        limiter.acquire(user_id=2)

        assert limiter.acquire(user_id=1).allowed is False
        assert limiter.acquire(user_id=2).allowed is False

        # Reset all
        limiter.reset_all()

        # All users can make requests again
        assert limiter.acquire(user_id=1).allowed is True
        assert limiter.acquire(user_id=2).allowed is True

    def test_get_status_returns_correct_info(self):
        """Test that get_status() returns accurate information."""
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        user_id = 123

        # Make 2 requests
        limiter.acquire(user_id)
        limiter.acquire(user_id)

        status = limiter.get_status(user_id)

        assert status["user_id"] == user_id
        assert status["requests_made"] == 2
        assert status["remaining"] == 3
        assert status["max_requests"] == 5
        assert status["window_seconds"] == 60

    def test_window_expiration(self):
        """Test that old requests expire after window passes."""
        # Use very short window for testing
        limiter = RateLimiter(max_requests=1, window_seconds=1)
        user_id = 123

        # Make request
        limiter.acquire(user_id)
        assert limiter.acquire(user_id).allowed is False

        # Wait for window to expire
        time.sleep(1.1)

        # Should be allowed again
        result = limiter.acquire(user_id)
        assert result.allowed is True


class TestRateLimitResult:
    """Tests for RateLimitResult dataclass."""

    def test_result_fields(self):
        """Test RateLimitResult fields."""
        result = RateLimitResult(
            allowed=True,
            remaining=4,
            reset_in_seconds=0,
            message=None
        )

        assert result.allowed is True
        assert result.remaining == 4
        assert result.reset_in_seconds == 0
        assert result.message is None

    def test_result_with_message(self):
        """Test RateLimitResult with error message."""
        result = RateLimitResult(
            allowed=False,
            remaining=0,
            reset_in_seconds=30.5,
            message="Rate limit exceeded. Please wait 30 seconds."
        )

        assert result.allowed is False
        assert result.remaining == 0
        assert result.reset_in_seconds == 30.5
        assert "Rate limit exceeded" in result.message
