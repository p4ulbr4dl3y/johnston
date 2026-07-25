import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from core.base_provider import BaseAgent
from core.provider_manager import ProviderManager


class TestProviderAdvancedFeatures(unittest.IsolatedAsyncioTestCase):
    def test_custom_headers_extra_body_and_reasoning_effort(self):
        agent = BaseAgent(
            provider_key="test_prov",
            headers={"X-Custom-Header": "TestValue"},
            extra_body={"temperature": 0.2},
            reasoning_effort="high",
            chunk_timeout=15.0,
            fallback_provider="fallback_prov"
        )
        self.assertEqual(agent.headers, {"X-Custom-Header": "TestValue"})
        self.assertEqual(agent.extra_body, {"temperature": 0.2})
        self.assertEqual(agent.reasoning_effort, "high")
        self.assertEqual(agent.chunk_timeout, 15.0)
        self.assertEqual(agent.fallback_provider, "fallback_prov")

    def test_provider_manager_loads_advanced_options(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_file = os.path.join(tmpdir, "providers.json")
            with open(json_file, "w", encoding="utf-8") as f:
                f.write("""{
  "test_custom": {
    "key": "test_custom",
    "name": "Test Custom Provider",
    "base_url": "https://api.test.com/v1",
    "model": "test-model-v1",
    "api_type": "openai",
    "headers": {"X-Test": "123"},
    "extra_body": {"top_p": 0.9},
    "reasoning_effort": "medium",
    "chunk_timeout": 20.0,
    "fallback_provider": "opencode"
  }
}""")
            with patch("core.provider_manager.PROVIDERS_JSON_FILE", json_file):
                with patch("core.provider_manager.CONFIG_DIR", tmpdir):
                    with patch("core.provider_manager.PROVIDERS_DIR", os.path.join(tmpdir, "providers")):
                        pm = ProviderManager()
                        agent = pm.create_agent_for_provider("test_custom")
                        self.assertIsNotNone(agent)
                        self.assertEqual(agent.headers, {"X-Test": "123"})
                        self.assertEqual(agent.extra_body, {"top_p": 0.9})
                        self.assertEqual(agent.reasoning_effort, "medium")
                        self.assertEqual(agent.chunk_timeout, 20.0)
                        self.assertEqual(agent.fallback_provider, "opencode")

    def test_provider_disabling(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = os.path.join(tmpdir, "config.json")
            with patch("core.provider_manager.CONFIG_FILE", config_file):
                with patch("core.provider_manager.CONFIG_DIR", tmpdir):
                    pm = ProviderManager()
                    self.assertEqual(pm.get_disabled_providers(), [])
                    pm.set_provider_disabled("xai", True)
                    self.assertIn("xai", pm.get_disabled_providers())

                    providers_all = pm.load_providers(include_disabled=True)
                    self.assertTrue(providers_all["xai"]["disabled"])

                    providers_enabled = pm.load_providers(include_disabled=False)
                    self.assertNotIn("xai", providers_enabled)

                    pm.set_provider_disabled("xai", False)
                    self.assertNotIn("xai", pm.get_disabled_providers())

    async def test_fetch_models_grouped_excludes_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = os.path.join(tmpdir, "config.json")
            with patch("core.provider_manager.CONFIG_FILE", config_file):
                with patch("core.provider_manager.CONFIG_DIR", tmpdir):
                    pm = ProviderManager()
                    pm.set_provider_disabled("opencode", True)
                    with patch.object(pm, "fetch_models_for_provider", new_callable=AsyncMock) as mock_fetch:
                        mock_fetch.return_value = ["dummy-model"]
                        grouped = await pm.fetch_models_grouped()
                        self.assertNotIn("opencode", grouped)

    def test_provider_default_max_tokens_when_unspecified(self):
        # When a provider config omits max_tokens, the agent must fall back to
        # the raised production default (8192), not the old 4096.
        with tempfile.TemporaryDirectory() as tmpdir:
            json_file = os.path.join(tmpdir, "providers.json")
            with open(json_file, "w", encoding="utf-8") as f:
                f.write("""{
  "test_no_max": {
    "key": "test_no_max",
    "name": "Test No Max",
    "base_url": "https://api.test.com/v1",
    "model": "m1",
    "api_type": "openai"
  }
}""")
            with patch("core.provider_manager.PROVIDERS_JSON_FILE", json_file):
                with patch("core.provider_manager.CONFIG_DIR", tmpdir):
                    with patch("core.provider_manager.PROVIDERS_DIR", os.path.join(tmpdir, "providers")):
                        pm = ProviderManager()
                        agent = pm.create_agent_for_provider("test_no_max")
                        self.assertIsNotNone(agent)
                        self.assertEqual(agent.max_tokens, 8192)


if __name__ == "__main__":
    unittest.main()
