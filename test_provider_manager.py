import os
import tempfile
import unittest
import shutil
import json
from unittest.mock import patch, MagicMock, AsyncMock

with patch("config.CONFIG_DIR", "/dummy"), patch("config.PROVIDERS_DIR", "/dummy"), patch("config.CONFIG_FILE", "/dummy"):
    from provider_manager import ProviderManager

class TestProviderManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        
        # Patch config values inside provider_manager
        self.config_dir_patcher = patch("provider_manager.CONFIG_DIR", self.test_dir)
        self.providers_dir_patcher = patch("provider_manager.PROVIDERS_DIR", os.path.join(self.test_dir, "providers"))
        self.config_file_patcher = patch("provider_manager.CONFIG_FILE", os.path.join(self.test_dir, "config.json"))
        
        self.config_dir_patcher.start()
        self.providers_dir_patcher.start()
        self.config_file_patcher.start()
        
        self.pm = ProviderManager()

    def tearDown(self):
        self.config_dir_patcher.stop()
        self.providers_dir_patcher.stop()
        self.config_file_patcher.stop()
        shutil.rmtree(self.test_dir)

    def test_ensure_config_dir(self):
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, "providers")))
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, "providers", "opencode.py")))
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, "config.json")))

    def test_load_providers(self):
        # We should have opencode provider because it gets created by ensure_config_dir
        providers = self.pm.load_providers()
        self.assertIn("opencode", providers)
        self.assertEqual(providers["opencode"]["name"], "OpenCode Go (DeepSeek v4 Flash)")

    def test_get_set_active_provider_key(self):
        self.assertEqual(self.pm.get_active_provider_key(), "opencode")
        self.pm.set_active_provider_key("custom_prov")
        self.assertEqual(self.pm.get_active_provider_key(), "custom_prov")

    def test_create_active_agent(self):
        agent = self.pm.create_active_agent()
        self.assertIsNotNone(agent)
        self.assertEqual(agent.model, "deepseek-v4-flash")

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

    def test_fetch_models_for_provider(self):
        import asyncio
        asyncio.run(self._async_test_fetch_models())

if __name__ == "__main__":
    unittest.main()
