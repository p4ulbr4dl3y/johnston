import time
import unittest
from unittest.mock import MagicMock, patch

from core.base_provider import BaseAgent
from core.circuit_breaker import CircuitBreaker, circuit_breaker


class TestCircuitBreaker(unittest.TestCase):

    def setUp(self):
        circuit_breaker.reset()

    def tearDown(self):
        circuit_breaker.reset()

    def test_state_transitions(self):
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=0.2)
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
        time.sleep(0.25)
        self.assertEqual(cb.get_state(provider), "HALF_OPEN")
        self.assertTrue(cb.allow_request(provider))

        # Success in HALF_OPEN resets to CLOSED
        cb.record_success(provider)
        self.assertEqual(cb.get_state(provider), "CLOSED")
        self.assertEqual(cb.remaining_cooldown(provider), 0.0)

    def test_half_open_failure_reopens_immediately(self):
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=0.1)
        provider = "test_prov"

        for _ in range(3):
            cb.record_failure(provider)
        self.assertEqual(cb.get_state(provider), "OPEN")

        time.sleep(0.15)
        self.assertEqual(cb.get_state(provider), "HALF_OPEN")

        cb.record_failure(provider)
        self.assertEqual(cb.get_state(provider), "OPEN")

    def test_reset_specific_or_all(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure("prov1")
        cb.record_failure("prov2")

        self.assertEqual(cb.get_state("prov1"), "OPEN")
        self.assertEqual(cb.get_state("prov2"), "OPEN")

        cb.reset("prov1")
        self.assertEqual(cb.get_state("prov1"), "CLOSED")
        self.assertEqual(cb.get_state("prov2"), "OPEN")

        cb.reset()
        self.assertEqual(cb.get_state("prov2"), "CLOSED")


class TestAgentCircuitBreakerIntegration(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        circuit_breaker.reset()

    async def asyncTearDown(self):
        circuit_breaker.reset()

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
        self.assertEqual(events[0][0], "bot_text")
        self.assertIn("Circuit breaker for provider 'test_prov' is OPEN", events[0][1])

    async def test_agent_fast_fails_to_fallback_when_open(self):
        cb = circuit_breaker
        cb.failure_threshold = 1
        cb.cooldown_seconds = 10.0
        cb.record_failure("primary_prov")

        agent = BaseAgent(api_key="t", model="t", provider_key="primary_prov")
        agent.system_prompt = "system"
        agent.fallback_provider = "fallback_prov"

        mock_fallback_agent = MagicMock()
        mock_fallback_agent.history = []
        mock_fallback_agent.mode = "action"
        mock_fallback_agent.tokens_input = 10
        mock_fallback_agent.tokens_output = 20
        mock_fallback_agent.total_tokens = 30
        mock_fallback_agent.cost_usd = 0.001

        async def mock_fallback_stream(user_text):
            yield ("bot_delta", "Response from fallback", "")

        mock_fallback_agent.stream_steps = mock_fallback_stream

        with patch("core.provider_manager.ProviderManager.create_agent_for_provider", return_value=mock_fallback_agent):
            events = []
            async for event in agent.stream_steps("hello"):
                events.append(event)

        self.assertTrue(any("circuit breaker OPEN" in e[1] for e in events if e[0] == "thinking"))
        self.assertTrue(any("Response from fallback" in e[1] for e in events if e[0] == "bot_delta"))
        self.assertEqual(agent.total_tokens, 30)
