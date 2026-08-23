import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

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
        )
        self.assertEqual(agent.headers, {"X-Custom-Header": "TestValue"})
        self.assertEqual(agent.extra_body, {"temperature": 0.2})
        self.assertEqual(agent.reasoning_effort, "high")
        self.assertEqual(agent.chunk_timeout, 15.0)

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
    "chunk_timeout": 20.0
  }
}""")
            with patch("core.provider_manager.PROVIDERS_JSON_FILE", json_file):
                with patch("core.provider_manager.CONFIG_DIR", tmpdir):
                    pm = ProviderManager()
                    agent = pm.create_agent_for_provider("test_custom")
                    self.assertIsNotNone(agent)
                    self.assertEqual(agent.headers, {"X-Test": "123"})
                    self.assertEqual(agent.extra_body, {"top_p": 0.9})
                    self.assertEqual(agent.reasoning_effort, "medium")
                    self.assertEqual(agent.chunk_timeout, 20.0)

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
                    self.assertFalse(providers_all["xai"]["enabled"])

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
                    pm.set_provider_disabled("openai", True)
                    with patch.object(pm, "fetch_models_for_provider", new_callable=AsyncMock) as mock_fetch:
                        mock_fetch.return_value = ["dummy-model"]
                        grouped = await pm.fetch_models_grouped()
                        self.assertNotIn("openai", grouped)

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
                    pm = ProviderManager()
                    agent = pm.create_agent_for_provider("test_no_max")
                    self.assertIsNotNone(agent)
                    self.assertEqual(agent.max_tokens, 8192)

    def _make_pm(self):
        """Build a ProviderManager with config/providers paths isolated to a tmp dir."""
        tmpdir = tempfile.TemporaryDirectory()
        config_file = os.path.join(tmpdir.name, "config.json")
        providers_file = os.path.join(tmpdir.name, "providers.json")
        self._tmpdir = tmpdir
        self._patch1 = patch("core.provider_manager.CONFIG_FILE", config_file)
        self._patch2 = patch("core.provider_manager.CONFIG_DIR", tmpdir.name)
        self._patch3 = patch("core.provider_manager.PROVIDERS_JSON_FILE", providers_file)
        self._patch1.start()
        self._patch2.start()
        self._patch3.start()
        return ProviderManager()

    def _teardown_pm(self):
        self._patch1.stop()
        self._patch2.stop()
        self._patch3.stop()
        self._tmpdir.cleanup()

    def test_create_agent_for_provider_disabled_returns_none(self):
        pm = self._make_pm()
        try:
            pm.set_provider_disabled("openai", True)
            self.assertIsNone(pm.create_agent_for_provider("openai"))
        finally:
            self._teardown_pm()

    def test_create_active_agent_falls_back_when_active_disabled(self):
        pm = self._make_pm()
        try:
            pm.set_active_provider_key("openai")
            pm.set_provider_disabled("openai", True)
            agent = pm.create_active_agent()
            self.assertIsNotNone(agent)
            self.assertNotEqual(agent.provider_key, "openai")
            self.assertNotEqual(pm.get_active_provider_key(), "openai")
        finally:
            self._teardown_pm()

    def test_create_active_agent_fallback_prefers_connected_only(self):
        # Fallback must pick a *connected* (no-key) provider, not a key-required
        # provider that has no credential and would fail on first call.
        pm = self._make_pm()
        try:
            pm.set_active_provider_key("openai")
            pm.set_provider_disabled("openai", True)
            agent = pm.create_active_agent()
            self.assertIsNotNone(agent)
            self.assertEqual(agent.provider_key, "lmstudio")  # first connected (no-key) provider
        finally:
            self._teardown_pm()

    def test_create_active_agent_returns_none_when_no_connected_provider(self):
        pm = self._make_pm()
        try:
            pm.set_active_provider_key("openai")
            # Disable openai plus every no-key (local) provider; all remaining
            # providers need a key that is not configured -> no connected fallback.
            for key in ("openai", "lmstudio", "litellm"):
                pm.set_provider_disabled(key, True)
            self.assertIsNone(pm.create_active_agent())
        finally:
            self._teardown_pm()

    def test_set_provider_credentials_empty_key_does_not_activate_key_required(self):
        from core.application.provider.actions import set_provider_credentials

        pm = self._make_pm()
        try:
            pm.set_active_provider_key("openai")
            app = MagicMock()
            result = set_provider_credentials(pm, "anthropic", "", app)
            self.assertFalse(result)
            # key-required provider must NOT become active on an empty key
            self.assertEqual(pm.get_active_provider_key(), "openai")
            self.assertNotIn("anthropic", pm.get_disabled_providers())
        finally:
            self._teardown_pm()

    def test_set_provider_credentials_empty_key_activates_no_key_provider(self):
        from core.application.provider.actions import set_provider_credentials

        pm = self._make_pm()
        try:
            pm.set_active_provider_key("openai")
            pm.set_provider_disabled("lmstudio", True)
            app = MagicMock()
            result = set_provider_credentials(pm, "lmstudio", "", app)
            self.assertFalse(result)
            # local provider (requires_key=False) may be activated with no key
            self.assertEqual(pm.get_active_provider_key(), "lmstudio")
            self.assertNotIn("lmstudio", pm.get_disabled_providers())
        finally:
            self._teardown_pm()

    def test_set_provider_credentials_nonempty_key_enables_and_activates(self):
        from core.application.provider.actions import set_provider_credentials

        pm = self._make_pm()
        try:
            pm.set_active_provider_key("openai")
            pm.set_provider_disabled("anthropic", True)
            app = MagicMock()
            with patch("core.application.provider.actions._refresh_models_background"):
                result = set_provider_credentials(pm, "anthropic", "sk-test", app)
            self.assertTrue(result)
            self.assertEqual(pm.get_active_provider_key(), "anthropic")
            self.assertNotIn("anthropic", pm.get_disabled_providers())
            self.assertEqual(pm.get_api_key("anthropic"), "sk-test")
        finally:
            self._teardown_pm()


if __name__ == "__main__":
    unittest.main()
