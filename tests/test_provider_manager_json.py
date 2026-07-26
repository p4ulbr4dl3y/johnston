import json
import os
import tempfile
import unittest
from unittest.mock import patch

from core.provider_manager import ProviderManager


class TestProviderManagerJson(unittest.TestCase):
    def test_json_providers_loading(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_file = os.path.join(tmpdir, "providers.json")
            config_file = os.path.join(tmpdir, "config.json")

            sample_data = {
                "custom_json": {
                    "key": "custom_json",
                    "name": "Custom JSON LLM",
                    "base_url": "http://localhost:8080/v1",
                    "model": "my-custom-model"
                }
            }
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(sample_data, f)

            with patch("core.provider_manager.PROVIDERS_JSON_FILE", json_file), \
                 patch("core.provider_manager.CONFIG_FILE", config_file), \
                  patch("core.provider_manager.CONFIG_DIR", tmpdir):
                pm = ProviderManager()
                providers = pm.load_providers()

                self.assertIn("custom_json", providers)
                self.assertEqual(providers["custom_json"]["name"], "Custom JSON LLM")
                self.assertEqual(providers["custom_json"]["model"], "my-custom-model")

                pm.set_active_provider_key("custom_json")
                agent = pm.create_active_agent()
                self.assertEqual(agent.model, "my-custom-model")
                self.assertEqual(agent.base_url, "http://localhost:8080/v1")

    def test_fetch_models_universal_static_list(self):
        import asyncio
        async def _test():
            with tempfile.TemporaryDirectory() as tmpdir:
                json_file = os.path.join(tmpdir, "providers.json")
                config_file = os.path.join(tmpdir, "config.json")

                sample_data = {
                    "no_models_endpoint": {
                        "key": "no_models_endpoint",
                        "name": "No Models Endpoint API",
                        "base_url": "http://invalid-host-no-models-endpoint:9999/v1",
                        "model": "model-1",
                        "fetch_models": False,
                        "models": ["model-1", "model-2", "model-3"]
                    }
                }
                with open(json_file, "w", encoding="utf-8") as f:
                    json.dump(sample_data, f)

                with patch("core.provider_manager.PROVIDERS_JSON_FILE", json_file), \
                     patch("core.provider_manager.CONFIG_FILE", config_file), \
                          patch("core.provider_manager.CONFIG_DIR", tmpdir):
                    pm = ProviderManager()
                    models = await pm.fetch_models_for_provider("no_models_endpoint", force_refresh=True)
                    self.assertEqual(models, ["model-1", "model-2", "model-3"])

        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()
