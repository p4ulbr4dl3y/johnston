import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

with patch("core.config.CONFIG_DIR", "/dummy"), patch("core.config.PROVIDERS_DIR", "/dummy"), patch("core.config.CONFIG_FILE", "/dummy"):
    from core.provider_manager import ProviderManager

class TestProviderManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

        # Patch config values inside provider_manager
        self.config_dir_patcher = patch("core.provider_manager.CONFIG_DIR", self.test_dir)
        self.providers_dir_patcher = patch("core.provider_manager.PROVIDERS_DIR", os.path.join(self.test_dir, "providers"))
        self.config_file_patcher = patch("core.provider_manager.CONFIG_FILE", os.path.join(self.test_dir, "config.json"))
        self.providers_json_patcher = patch("core.provider_manager.PROVIDERS_JSON_FILE", os.path.join(self.test_dir, "providers.json"))

        self.config_dir_patcher.start()
        self.providers_dir_patcher.start()
        self.config_file_patcher.start()
        self.providers_json_patcher.start()

        self.pm = ProviderManager()

    def tearDown(self):
        self.config_dir_patcher.stop()
        self.providers_dir_patcher.stop()
        self.config_file_patcher.stop()
        self.providers_json_patcher.stop()
        shutil.rmtree(self.test_dir)

    def test_ensure_config_dir(self):
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, "providers")))
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, "providers.json")))
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, "config.json")))

    def test_load_providers(self):
        providers = self.pm.load_providers()
        self.assertIn("opencode", providers)
        self.assertEqual(providers["opencode"]["name"], "OpenCode")

    def test_get_set_active_provider_key(self):
        self.assertEqual(self.pm.get_active_provider_key(), "opencode")
        self.pm.set_active_provider_key("custom_prov")
        self.assertEqual(self.pm.get_active_provider_key(), "custom_prov")

    def test_create_active_agent(self):
        agent = self.pm.create_active_agent()
        self.assertIsNotNone(agent)
        self.assertEqual(agent.model, "")

    def test_api_keys(self):
        self.assertEqual(self.pm.get_api_key("opencode"), "")
        self.pm.set_provider_api_key("opencode", "test-key-123")
        self.assertEqual(self.pm.get_api_key("opencode"), "test-key-123")

    @patch("httpx.AsyncClient")
    async def _async_test_fetch_models(self, mock_client_cls):
        # Setup mock responses for httpx
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"id": "model-a"},
                {"id": "model-b"}
            ]
        }
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        # Test fetching models
        models = await self.pm.fetch_models_for_provider("opencode", force_refresh=True)
        self.assertEqual(models, ["model-a", "model-b"])

        # Verify cache was written
        cache_file = os.path.join(self.test_dir, "cache", "models_opencode.json")
        self.assertTrue(os.path.exists(cache_file))
        with open(cache_file, "r") as f:
            cdata = json.load(f)
            self.assertEqual(cdata["models"], ["model-a", "model-b"])

    def test_custom_provider_without_model(self):
        # Create a custom provider entry in providers.json without a "model" property
        providers_file = os.path.join(self.test_dir, "providers.json")
        with open(providers_file, "w", encoding="utf-8") as f:
            json.dump({
                "custom_no_model": {
                    "key": "custom_no_model",
                    "name": "Custom No Model",
                    "base_url": "https://api.example.com/v1",
                    "models": ["model-1", "model-2"]
                }
            }, f)

        pm = ProviderManager()
        pm.set_active_provider_key("custom_no_model")
        agent = pm.create_active_agent()
        self.assertEqual(agent.provider_key, "custom_no_model")
        self.assertEqual(agent.model, "")  # No model selected automatically

        pm.set_provider_model("custom_no_model", "model-2")
        agent2 = pm.create_active_agent()
        self.assertEqual(agent2.model, "model-2")


if __name__ == "__main__":
    unittest.main()
