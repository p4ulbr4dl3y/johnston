import time
from typing import Dict, Optional


class CircuitBreakerOpenError(Exception):
    """Raised when a request is attempted while the provider circuit breaker is OPEN."""

    def __init__(self, provider_key: str, cooldown_remaining: float):
        super().__init__(
            f"Circuit breaker for provider '{provider_key}' is OPEN. Cooldown remaining: {cooldown_remaining:.1f}s."
        )
        self.provider_key = provider_key
        self.cooldown_remaining = cooldown_remaining


class CircuitBreaker:
    """Production-grade circuit breaker to prevent cascading failures to unresponsive AI providers."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 30.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures: Dict[str, int] = {}
        self._state: Dict[str, str] = {}  # "CLOSED", "OPEN", "HALF_OPEN"
        self._opened_at: Dict[str, float] = {}

    def get_state(self, provider_key: str) -> str:
        state = self._state.get(provider_key, "CLOSED")
        if state == "OPEN":
            opened_time = self._opened_at.get(provider_key, 0.0)
            if time.time() - opened_time >= self.cooldown_seconds:
                self._state[provider_key] = "HALF_OPEN"
                return "HALF_OPEN"
        return state

    def allow_request(self, provider_key: str) -> bool:
        state = self.get_state(provider_key)
        if state in ("CLOSED", "HALF_OPEN"):
            return True
        return False

    def remaining_cooldown(self, provider_key: str) -> float:
        if self.get_state(provider_key) != "OPEN":
            return 0.0
        opened_time = self._opened_at.get(provider_key, time.time())
        elapsed = time.time() - opened_time
        return max(0.0, self.cooldown_seconds - elapsed)

    def record_success(self, provider_key: str):
        self._failures[provider_key] = 0
        self._state[provider_key] = "CLOSED"
        self._opened_at.pop(provider_key, None)

    def record_failure(self, provider_key: str):
        current_state = self.get_state(provider_key)
        if current_state == "HALF_OPEN":
            self._state[provider_key] = "OPEN"
            self._opened_at[provider_key] = time.time()
            return

        failures = self._failures.get(provider_key, 0) + 1
        self._failures[provider_key] = failures
        if failures >= self.failure_threshold:
            self._state[provider_key] = "OPEN"
            self._opened_at[provider_key] = time.time()

    def reset(self, provider_key: Optional[str] = None):
        if provider_key:
            self._failures.pop(provider_key, None)
            self._state.pop(provider_key, None)
            self._opened_at.pop(provider_key, None)
        else:
            self._failures.clear()
            self._state.clear()
            self._opened_at.clear()


# Shared singleton instance
circuit_breaker = CircuitBreaker()
