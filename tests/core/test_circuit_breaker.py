import time
import unittest

from core.base_provider import BaseAgent
from core.circuit_breaker import CircuitBreaker, circuit_breaker


class TestCircuitBreaker(unittest.TestCase):

    def setUp(self):
        circuit_breaker._failures.clear()
        circuit_breaker._state.clear()
        circuit_breaker._opened_at.clear()

    def tearDown(self):
        circuit_breaker._failures.clear()
        circuit_breaker._state.clear()
        circuit_breaker._opened_at.clear()

    def test_state_transitions(self):
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=0.01)
        provider = "test_prov"

        self.assertEqual(cb.get_state(provider), "CLOSED")
        self.assertTrue(cb.allow_request(provider))

        cb.record_failure(provider)
        cb.record_failure(provider)
        self.assertEqual(cb.get_state(provider), "CLOSED")

        # 3rd failure trips the circuit breaker to OPEN
        cb.record_failure(provider)
        self.assertEqual(cb.get_state(provider), "OPEN")
        self.assertFalse(cb.allow_request(provider))
        self.assertGreater(cb.remaining_cooldown(provider), 0.0)

        # Wait for cooldown to expire
        time.sleep(0.015)
        self.assertEqual(cb.get_state(provider), "HALF_OPEN")
        self.assertTrue(cb.allow_request(provider))

        # Success in HALF_OPEN resets to CLOSED
        cb.record_success(provider)
        self.assertEqual(cb.get_state(provider), "CLOSED")
        self.assertEqual(cb.remaining_cooldown(provider), 0.0)

    def test_half_open_failure_reopens_immediately(self):
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=0.01)
        provider = "test_prov"

        for _ in range(3):
            cb.record_failure(provider)
        self.assertEqual(cb.get_state(provider), "OPEN")

        time.sleep(0.015)
        self.assertEqual(cb.get_state(provider), "HALF_OPEN")

        cb.record_failure(provider)
        self.assertEqual(cb.get_state(provider), "OPEN")

    def test_failures_tracked_per_provider(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure("prov1")
        cb.record_failure("prov2")

        self.assertEqual(cb.get_state("prov1"), "OPEN")
        self.assertEqual(cb.get_state("prov2"), "OPEN")


class TestAgentCircuitBreakerIntegration(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        circuit_breaker._failures.clear()
        circuit_breaker._state.clear()
        circuit_breaker._opened_at.clear()

    async def asyncTearDown(self):
        circuit_breaker._failures.clear()
        circuit_breaker._state.clear()
        circuit_breaker._opened_at.clear()

    async def test_agent_yields_circuit_breaker_open_error(self):
        cb = circuit_breaker
        cb.failure_threshold = 2
        cb.cooldown_seconds = 10.0
        cb.record_failure("test_prov")
        cb.record_failure("test_prov")

        agent = BaseAgent(api_key="t", model="t", provider_key="test_prov")
        agent.system_prompt = "system"

        events = []
        async for event in agent.stream_steps("hello"):
            events.append(event)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "event_divider")
        self.assertIn("Circuit breaker for provider 'test_prov' is OPEN", events[0][1])
