import json
import os
import tempfile
import unittest
from unittest.mock import patch

from core.commands import ModelsCommand
from core.models_catalog import ModelsCatalog


class TestVisionModelPersistence(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.config_file = os.path.join(self.test_dir.name, "config.json")
        self.cache_file = os.path.join(self.test_dir.name, "cache", "models_catalog_cache.json")

    def tearDown(self):
        self.test_dir.cleanup()

    async def test_fallback_vision_persisted_in_config_file(self):
        with patch("core.models_catalog.CONFIG_FILE", self.config_file), \
             patch("core.models_catalog.CACHE_FILE", self.cache_file):
            catalog = ModelsCatalog()
            catalog.set_fallback_vision_model("test_provider", "custom-vision-v1", explicit=True)

            self.assertTrue(os.path.exists(self.config_file))
            with open(self.config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.assertEqual(cfg.get("fallback_vision_provider"), "test_provider")
            self.assertEqual(cfg.get("fallback_vision_model"), "custom-vision-v1")
            self.assertTrue(cfg.get("fallback_vision_explicit"))

            # Reset in-memory state and reload from config_file
            catalog._fallback_vision_provider = ""
            catalog._fallback_vision_model = ""
            catalog._fallback_vision_explicit = False
            catalog.load_cache()

            prov, mod = catalog.get_fallback_vision_model()
            self.assertEqual(prov, "test_provider")
            self.assertEqual(mod, "custom-vision-v1")
            self.assertTrue(catalog.is_fallback_vision_explicit())

    async def test_auto_updates_vision_model_when_not_explicit(self):
        with patch("core.models_catalog.CONFIG_FILE", self.config_file), \
             patch("core.models_catalog.CACHE_FILE", self.cache_file):
            catalog = ModelsCatalog()
            catalog.set_fallback_vision_model("old_provider", "old-vision-model", explicit=False)

            with patch("core.commands.catalog", catalog):
                catalog.is_native_vision = lambda prov, mod: True

                class MockApp:
                    def push_screen(self, screen, callback=None):
                        if callback:
                            callback(("openai", "gpt-4o"))
                    def query_one(self, *args, **kwargs):
                        return type("MockInput", (), {"focus": lambda self: None})()
                    def refresh_status_footer(self):
                        pass
                    def notify(self, msg):
                        pass
                    async def mock_fetch(self):
                        return {"openai": {"name": "OpenAI", "models": ["gpt-4o"]}}
                    pm = type("MockPM", (), {
                        "fetch_models_grouped": mock_fetch,
                        "get_active_provider_key": lambda self: "openai",
                        "set_provider_model": lambda self, p, m: None,
                        "load_providers": lambda self: {}
                    })()
                    agent = type("MockAgent", (), {"model": "gpt-4o"})()

                app = MockApp()
                cmd = ModelsCommand()
                await cmd.execute(app)

                # Since vision choice was not explicit, selecting gpt-4o updates fallback vision model!
                prov, mod = catalog.get_fallback_vision_model()
                self.assertEqual(prov, "openai")
                self.assertEqual(mod, "gpt-4o")
                self.assertFalse(catalog.is_fallback_vision_explicit())

    async def test_native_vision_updates_fallback(self):
        with patch("core.models_catalog.CONFIG_FILE", self.config_file), \
             patch("core.models_catalog.CACHE_FILE", self.cache_file):
            catalog = ModelsCatalog()
            catalog.set_fallback_vision_model("explicit_provider", "my-preferred-vision-model", explicit=True)

            with patch("core.commands.catalog", catalog):
                catalog.is_native_vision = lambda prov, mod: True

                class MockApp:
                    def push_screen(self, screen, callback=None):
                        if callback:
                            callback(("openai", "gpt-4o"))
                    def query_one(self, *args, **kwargs):
                        return type("MockInput", (), {"focus": lambda self: None})()
                    def refresh_status_footer(self):
                        pass
                    def notify(self, msg):
                        pass
                    async def mock_fetch(self):
                        return {"openai": {"name": "OpenAI", "models": ["gpt-4o"]}}
                    pm = type("MockPM", (), {
                        "fetch_models_grouped": mock_fetch,
                        "get_active_provider_key": lambda self: "openai",
                        "set_provider_model": lambda self, p, m: None,
                        "load_providers": lambda self: {}
                    })()
                    agent = type("MockAgent", (), {"model": "gpt-4o"})()

                app = MockApp()
                cmd = ModelsCommand()
                await cmd.execute(app)

                # Selecting a main model with native vision updates fallback vision model to match primary model!
                prov, mod = catalog.get_fallback_vision_model()
                self.assertEqual(prov, "openai")
                self.assertEqual(mod, "gpt-4o")


if __name__ == "__main__":
    unittest.main()
