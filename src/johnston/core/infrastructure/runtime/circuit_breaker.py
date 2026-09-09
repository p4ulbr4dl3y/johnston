import threading
import time
from enum import Enum
from typing import Dict, List, Optional


class CircuitState(str, Enum):
    """Circuit breaker lifecycle state for a provider."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


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

    def __init__(
        self,
        failure_threshold: Optional[int] = None,
        cooldown_seconds: Optional[float] = None,
        failure_ttl_seconds: Optional[float] = None,
    ):
        if failure_threshold is None or cooldown_seconds is None or failure_ttl_seconds is None:
            from johnston.core.infrastructure.config.settings import get_settings

            st = get_settings().llm
            failure_threshold = failure_threshold if failure_threshold is not None else st.cb_failure_threshold
            cooldown_seconds = cooldown_seconds if cooldown_seconds is not None else st.cb_cooldown_seconds
            failure_ttl_seconds = (
                failure_ttl_seconds
                if failure_ttl_seconds is not None
                else getattr(st, "cb_failure_ttl_seconds", 60.0)
            )
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.failure_ttl_seconds = failure_ttl_seconds
        self._lock = threading.Lock()
        self._failures: Dict[str, int] = {}
        self._failure_timestamps: Dict[str, List[float]] = {}
        self._state: Dict[str, CircuitState] = {}
        self._opened_at: Dict[str, float] = {}
        self._half_open_in_flight: Dict[str, bool] = {}

    def _prune_failures_locked(self, provider_key: str, now: float) -> List[float]:
        if provider_key not in self._failures:
            self._failure_timestamps.pop(provider_key, None)
            return []
        cutoff = now - self.failure_ttl_seconds
        timestamps = [t for t in self._failure_timestamps.get(provider_key, []) if t >= cutoff]
        self._failure_timestamps[provider_key] = timestamps
        self._failures[provider_key] = len(timestamps)
        return timestamps

    def _get_state_locked(self, provider_key: str) -> CircuitState:
        now = time.time()
        state = self._state.get(provider_key, CircuitState.CLOSED)
        if state == CircuitState.OPEN:
            opened_time = self._opened_at.get(provider_key, 0.0)
            if now - opened_time >= self.cooldown_seconds:
                self._state[provider_key] = CircuitState.HALF_OPEN
                self._half_open_in_flight[provider_key] = False
                return CircuitState.HALF_OPEN
        elif state == CircuitState.CLOSED:
            self._prune_failures_locked(provider_key, now)
        return state

    def get_state(self, provider_key: str) -> CircuitState:
        with self._lock:
            return self._get_state_locked(provider_key)

    def allow_request(self, provider_key: str) -> bool:
        with self._lock:
            state = self._get_state_locked(provider_key)
            if state == CircuitState.CLOSED:
                return True
            if state == CircuitState.HALF_OPEN:
                if not self._half_open_in_flight.get(provider_key, False):
                    self._half_open_in_flight[provider_key] = True
                    return True
                return False
            return False

    def remaining_cooldown(self, provider_key: str) -> float:
        with self._lock:
            if self._get_state_locked(provider_key) != CircuitState.OPEN:
                return 0.0
            opened_time = self._opened_at.get(provider_key, time.time())
            elapsed = time.time() - opened_time
            return max(0.0, self.cooldown_seconds - elapsed)

    def record_success(self, provider_key: str) -> None:
        with self._lock:
            self._failures[provider_key] = 0
            self._failure_timestamps[provider_key] = []
            self._state[provider_key] = CircuitState.CLOSED
            self._opened_at.pop(provider_key, None)
            self._half_open_in_flight.pop(provider_key, None)

    def record_failure(self, provider_key: str) -> None:
        with self._lock:
            current_state = self._get_state_locked(provider_key)
            now = time.time()
            if current_state == CircuitState.HALF_OPEN:
                self._state[provider_key] = CircuitState.OPEN
                self._opened_at[provider_key] = now
                self._half_open_in_flight[provider_key] = False
                return

            timestamps = self._prune_failures_locked(provider_key, now)
            timestamps.append(now)
            self._failure_timestamps[provider_key] = timestamps
            failures = len(timestamps)
            self._failures[provider_key] = failures

            if failures >= self.failure_threshold:
                self._state[provider_key] = CircuitState.OPEN
                self._opened_at[provider_key] = now
                self._half_open_in_flight[provider_key] = False

    def reset(self, provider_key: Optional[str] = None) -> None:
        """Reset circuit breaker state for a provider or all providers."""
        with self._lock:
            if provider_key is None:
                self._failures.clear()
                self._failure_timestamps.clear()
                self._state.clear()
                self._opened_at.clear()
                self._half_open_in_flight.clear()
            else:
                self._failures.pop(provider_key, None)
                self._failure_timestamps.pop(provider_key, None)
                self._state.pop(provider_key, None)
                self._opened_at.pop(provider_key, None)
                self._half_open_in_flight.pop(provider_key, None)


# Shared singleton instance
circuit_breaker = CircuitBreaker()
