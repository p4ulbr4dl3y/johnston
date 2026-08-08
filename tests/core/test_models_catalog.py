import json
import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from core.models_catalog import ModelsCatalog, format_context_tokens, get_context_window


class TestModelsCatalog(unittest.TestCase):
    def setUp(self):
        # Isolate the cache file so tests never touch the real user cache.
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        cache_file = os.path.join(self._tmpdir.name, "cache", "models_catalog_cache.json")
        cache_patch = patch("core.models_catalog.CACHE_FILE", cache_file)
        cache_patch.start()
        self.addCleanup(cache_patch.stop)

    def test_format_context_tokens(self):
        self.assertEqual(format_context_tokens(1_000_000), "1M")
        self.assertEqual(format_context_tokens(2_000_000), "2M")
        self.assertEqual(format_context_tokens(128_000), "128k")
        self.assertEqual(format_context_tokens(64_000), "64k")
        self.assertEqual(format_context_tokens(500), "500")

    def test_format_context_tokens_decimals(self):
        self.assertEqual(format_context_tokens(1_500_000), "1.5M")
        self.assertEqual(format_context_tokens(1_040_000), "1M")
        self.assertEqual(format_context_tokens(1_500), "1.5k")
        self.assertEqual(format_context_tokens(100_000), "100k")

    def test_get_context_limit_default_and_cache(self):
        catalog = ModelsCatalog()
        # Default fallback
        limit = catalog.get_context_limit("unknown_provider", "non_existent_model")
        self.assertEqual(limit, 128000)

    def test_get_context_limit_reloads_when_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            catalog = ModelsCatalog()
            catalog._limits = {}
            catalog._names = {}
            with patch("core.models_catalog.CONFIG_DIR", tmpdir):
                with patch.object(ModelsCatalog, "load_cache", return_value=True) as mock_load:
                    limit = catalog.get_context_limit("prov", "m1")
        self.assertEqual(limit, 128000)
        mock_load.assert_called_once()

    def test_get_context_limit_provider_specific_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, "cache")
            os.makedirs(cache_dir)
            with open(os.path.join(cache_dir, "models_acme.json"), "w", encoding="utf-8") as f:
                json.dump({"model_limits": {"acme/warp-1": 64000}}, f)
            with patch("core.models_catalog.CONFIG_DIR", tmpdir):
                catalog = ModelsCatalog()
                self.assertEqual(catalog.get_context_limit("acme", "warp-1"), 64000)
                self.assertEqual(catalog.get_context_limit("acme", "missing"), 128000)

    def test_get_context_limit_provider_cache_corrupt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, "cache")
            os.makedirs(cache_dir)
            with open(os.path.join(cache_dir, "models_acme.json"), "w", encoding="utf-8") as f:
                f.write("{broken json")
            with patch("core.models_catalog.CONFIG_DIR", tmpdir):
                catalog = ModelsCatalog()
                self.assertEqual(catalog.get_context_limit("acme", "warp-1"), 128000)

    def test_get_model_display_name(self):
        catalog = ModelsCatalog()
        self.assertEqual(catalog.get_model_display_name("opencode", ""), "")
        name = catalog.get_model_display_name("opencode", "deepseek-v4-flash")
        self.assertIn("deepseek", name.lower())

    def test_get_model_display_name_resolved_with_suffix(self):
        catalog = ModelsCatalog()
        catalog._names = {"openai/gpt-4o": "OpenAI: GPT-4o"}
        self.assertEqual(catalog.get_model_display_name("openai", "openai/gpt-4o:vision"), "GPT-4o (Vision)")
        catalog._names["openai/gpt-4o"] = "GPT-4o (Vision)"
        self.assertEqual(catalog.get_model_display_name("openai", "openai/gpt-4o:vision"), "GPT-4o (Vision)")
        catalog._names["openai/gpt-4o"] = "GPT-4o"
        self.assertEqual(catalog.get_model_display_name("openai", "openai/gpt-4o"), "GPT-4o")

    def test_get_model_display_name_fallback_formatting(self):
        catalog = ModelsCatalog()
        self.assertEqual(catalog.get_model_display_name("", "gpt-db-4-o:vision"), "GPT DB 4 o (Vision)")
        self.assertEqual(catalog.get_model_display_name("", "gpt-4o:"), "GPT 4o")
        self.assertEqual(catalog.get_model_display_name("", "gpt-4o://weird"), "Weird")

    def test_get_context_window_helper(self):
        window = get_context_window("opencode", "deepseek-v4-flash")
        self.assertIsInstance(window, str)

    def test_get_model_pricing(self):
        catalog = ModelsCatalog()
        catalog._pricing = {
            "openai/gpt-4o": {"prompt": 0.0000025, "completion": 0.00001}
        }
        pricing = catalog.get_model_pricing("openrouter", "openai/gpt-4o")
        self.assertEqual(pricing["prompt"], 0.0000025)
        self.assertEqual(pricing["completion"], 0.00001)

        pricing_unknown = catalog.get_model_pricing("openrouter", "unknown")
        self.assertEqual(pricing_unknown["prompt"], 0.0)
        self.assertEqual(pricing_unknown["completion"], 0.0)

    def test_get_model_pricing_reloads_when_empty(self):
        catalog = ModelsCatalog()
        catalog._pricing = {}
        catalog._limits = {}
        with patch.object(ModelsCatalog, "load_cache", return_value=True) as mock_load:
            pricing = catalog.get_model_pricing("prov", "m1")
        self.assertEqual(pricing, {"prompt": 0.0, "completion": 0.0})
        mock_load.assert_called_once()

    def test_fuzzy_matching_local_models(self):
        cat = ModelsCatalog()
        cat._limits = {"google/gemma-4-31b": 262144, "gemma-4": 262144}
        cat._reasoning = ["google/gemma-4-31b", "gemma-4"]

        # Test exact match
        self.assertEqual(cat.get_context_limit("google", "gemma-4"), 262144)
        # Test fuzzy match with MLX/4bit suffix
        self.assertEqual(cat.get_context_limit("omlx", "gemma-4-E4B-it-MLX-4bit"), 262144)

    def test_reasoning_and_open_weights_parsed_from_cache(self):
        cat = ModelsCatalog()
        cat._limits = {"deepseek/deepseek-v4-pro": 1000000}
        cat._reasoning = ["deepseek/deepseek-v4-pro"]
        cat._open_weights = ["deepseek/deepseek-v4-pro"]

        self.assertIn("deepseek/deepseek-v4-pro", cat._reasoning)
        self.assertIn("deepseek/deepseek-v4-pro", cat._open_weights)

    def test_save_and_load_cache(self):
        cat = ModelsCatalog()
        cat._limits = {"test/m1": 100000}
        cat._names = {"test/m1": "Test Model 1"}
        cat._pricing = {"test/m1": {"prompt": 0.001, "completion": 0.002}}

        with tempfile.NamedTemporaryFile("w+", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            with patch("core.models_catalog.CACHE_FILE", tmp_path):
                cat.save_cache()
                cat2 = ModelsCatalog()
                self.assertTrue(cat2.load_cache())
                self.assertEqual(cat2.get_context_limit("test", "m1"), 100000)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_load_cache_corrupt_file(self):
        with tempfile.NamedTemporaryFile("w+", delete=False) as tmp:
            tmp.write("{invalid json")
            tmp.close()
            tmp_path = tmp.name
        try:
            cat = ModelsCatalog()
            with patch("core.models_catalog.CACHE_FILE", tmp_path):
                self.assertFalse(cat.load_cache())
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_save_cache_replace_failure(self):
        with tempfile.NamedTemporaryFile("w+", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            cat = ModelsCatalog()
            with patch("core.models_catalog.CACHE_FILE", tmp_path):
                with patch("core.models_catalog.os.replace", side_effect=OSError("replace failed")):
                    cat.save_cache()
            self.assertFalse(os.path.exists(tmp_path + ".tmp"))
        finally:
            for path in (tmp_path, tmp_path + ".tmp"):
                if os.path.exists(path):
                    os.remove(path)

    def test_save_cache_cleanup_failure(self):
        with tempfile.NamedTemporaryFile("w+", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            cat = ModelsCatalog()
            with patch("core.models_catalog.CACHE_FILE", tmp_path):
                with patch("core.models_catalog.os.replace", side_effect=OSError("replace failed")):
                    with patch("core.models_catalog.os.remove", side_effect=OSError("remove failed")):
                        cat.save_cache()
        finally:
            for path in (tmp_path, tmp_path + ".tmp"):
                if os.path.exists(path):
                    os.remove(path)

    def test_get_all_catalog_keys(self):
        cat = ModelsCatalog()
        cat._limits = {"a/1": 1}
        cat._names = {"a/2": "x"}
        cat._descriptions = {"a/3": "d"}
        cat._pricing = {"a/4": {}}
        cat._reasoning = ["a/5"]
        cat._open_weights = ["a/6"]
        self.assertEqual(cat._get_all_catalog_keys(), {"a/1", "a/2", "a/3", "a/4", "a/5", "a/6"})

    def test_resolve_catalog_key_empty_model_id(self):
        cat = ModelsCatalog()
        self.assertEqual(cat._resolve_catalog_key("prov", ""), "")

    def test_resolve_catalog_key_empty_search_space(self):
        cat = ModelsCatalog()
        self.assertEqual(cat._resolve_catalog_key("prov", "m1", set()), "")

    def test_resolve_catalog_key_tag_branches_and_cache(self):
        cat = ModelsCatalog()
        cat._limits = {"google/gemma-4": 262144}
        cat._output_limits = {"google/gemma-4": 8192}
        cat._names = {"google/gemma-4": "Gemma 4"}
        cat._descriptions = {"google/gemma-4": "desc"}
        cat._pricing = {"google/gemma-4": {"prompt": 0.0, "completion": 0.0}}
        cat._reasoning = ["google/gemma-4"]
        cat._open_weights = ["google/gemma-4"]

        # Direct identity branches
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._reasoning), "google/gemma-4")
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._open_weights), "google/gemma-4")
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._limits), "google/gemma-4")
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._names), "google/gemma-4")
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._descriptions), "google/gemma-4")
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._pricing), "google/gemma-4")
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._output_limits), "google/gemma-4")
        # Bound-view branches (search_space.__self__)
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._limits.keys()), "google/gemma-4")
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._names.keys()), "google/gemma-4")
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._descriptions.keys()), "google/gemma-4")
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._pricing.keys()), "google/gemma-4")
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._output_limits.keys()), "google/gemma-4")
        # Unknown search space falls through to the id() branch
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", {"gemma-4": "custom"}), "gemma-4")
        # Default search space (union of all catalog keys)
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4"), "google/gemma-4")
        # Repeated call hits the match cache
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._limits), "google/gemma-4")

    def test_resolve_catalog_key_slug_match(self):
        cat = ModelsCatalog()
        cat._limits = {"google/gemma-4-31b": 262144}
        self.assertEqual(cat._resolve_catalog_key("", "gemma-4-31b", cat._limits), "google/gemma-4-31b")

    def test_resolve_catalog_key_digit_conflict(self):
        cat = ModelsCatalog()
        cat._limits = {"google/gemma-2-27b": 131072, "google/gemma-3-31b": 262144}
        self.assertEqual(cat._resolve_catalog_key("", "gemma-3-31b-instruct", cat._limits), "google/gemma-3-31b")


class TestModelsCatalogAsync(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Isolate the cache file so tests never touch the real user cache.
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        cache_file = os.path.join(self._tmpdir.name, "cache", "models_catalog_cache.json")
        cache_patch = patch("core.models_catalog.CACHE_FILE", cache_file)
        cache_patch.start()
        self.addCleanup(cache_patch.stop)

    async def test_refresh_returns_cached_limits_when_fresh(self):
        cat = ModelsCatalog()
        cat._limits = {"a/b": 1000}
        cat._updated_at = time.time()
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            limits = await cat.refresh()
        mock_get.assert_not_called()
        self.assertEqual(limits, {"a/b": 1000})

    async def test_refresh_catalog_mocked(self):
        cat = ModelsCatalog()
        cat._limits = {}
        cat._updated_at = 0.0

        mdev_json = {
            "openai": {
                "models": {
                    "gpt-4o": {
                        "name": "GPT-4o",
                        "description": "Flagship model",
                        "limit": {"context": 128000, "output": 4096},
                        "modalities": {"input": ["text"]},
                        "reasoning": True,
                        "open_weights": False,
                        "cost": {"input": 2.5, "output": 10.0}
                    }
                }
            }
        }
        openrouter_json = {
            "data": [
                {
                    "id": "anthropic/claude-3.5-sonnet",
                    "name": "Anthropic: Claude 3.5 Sonnet",
                    "context_length": 200000,
                    "pricing": {"prompt": "0.000003", "completion": "0.000015"}
                }
            ]
        }

        mock_mdev_res = httpx.Response(200, json=mdev_json)
        mock_or_res = httpx.Response(200, json=openrouter_json)

        def get_mock_res(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "models.dev" in url:
                return mock_mdev_res
            return mock_or_res

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_async_get:
            mock_async_get.side_effect = get_mock_res

            limits = await cat.refresh()
            self.assertIn("openai/gpt-4o", limits)
            self.assertEqual(limits["openai/gpt-4o"], 128000)

            self.assertIn("anthropic/claude-3.5-sonnet", limits)
            self.assertEqual(limits["anthropic/claude-3.5-sonnet"], 200000)

    async def test_refresh_parses_models_dev_and_openrouter_branches(self):
        cat = ModelsCatalog()
        cat._limits = {}
        cat._updated_at = 0.0

        mdev_json = {
            "openai": {
                "models": {
                    "gpt-4o": {
                        "name": "GPT-4o",
                        "description": "Flagship model",
                        "limit": {"context": 128000, "output": 4096},
                        "reasoning": True,
                        "open_weights": True,
                        "cost": {"input": 2.5, "output": 10.0},
                    },
                    "cheap-model": {
                        "name": "",
                        "limit": "not-a-dict",
                        "cost": {"input": 0, "output": 0},
                    },
                    "free-model": {
                        "limit": {"context": None, "output": "bad"},
                        "cost": "not-a-dict",
                    },
                    "ctx-only": {"limit": {"context": 1000}},
                }
            },
            "bad_provider": "not-a-dict",
            "empty_provider": {"models": "not-a-dict"},
            "weird_provider": {"models": {"not-a-model": "string"}},
        }
        openrouter_json = {
            "data": [
                {
                    "id": "anthropic/claude-3.5-sonnet",
                    "name": "Anthropic: Claude 3.5 Sonnet",
                    "context_length": 200000,
                    "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                },
                {
                    "id": "meta/llama-4",
                    "name": "Meta Llama 4",
                    "context_window": 131072,
                    "pricing": "free",
                },
                {
                    "id": "misc/other",
                    "top_provider": {"context_length": 32000},
                    "pricing": {"prompt": 0, "completion": 0},
                },
                "not-a-dict",
                {"id": "only-id", "pricing": {"prompt": "0.5", "completion": "1"}},
            ]
        }

        mock_mdev_res = httpx.Response(200, json=mdev_json)
        mock_or_res = httpx.Response(200, json=openrouter_json)

        def get_mock_res(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "models.dev" in url:
                return mock_mdev_res
            return mock_or_res

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = get_mock_res
            limits = await cat.refresh()

        self.assertEqual(limits["openai/gpt-4o"], 128000)
        self.assertEqual(limits["gpt-4o"], 128000)
        self.assertEqual(limits["ctx-only"], 1000)
        self.assertEqual(cat._output_limits["openai/gpt-4o"], 4096)
        self.assertIn("openai/gpt-4o", cat._reasoning)
        self.assertIn("openai/gpt-4o", cat._open_weights)
        self.assertEqual(cat._names["openai/gpt-4o"], "GPT-4o")
        self.assertEqual(cat._names["anthropic/claude-3.5-sonnet"], "Claude 3.5 Sonnet")
        self.assertEqual(cat._names["llama-4"], "Meta Llama 4")
        self.assertEqual(cat._descriptions["gpt-4o"], "Flagship model")
        self.assertAlmostEqual(cat._pricing["openai/gpt-4o"]["prompt"], 2.5e-6)
        self.assertAlmostEqual(cat._pricing["openai/gpt-4o"]["completion"], 1e-5)
        self.assertEqual(cat._pricing["anthropic/claude-3.5-sonnet"]["prompt"], 0.000003)
        self.assertEqual(limits["anthropic/claude-3.5-sonnet"], 200000)
        self.assertEqual(limits["meta/llama-4"], 131072)
        self.assertEqual(limits["misc/other"], 32000)
        self.assertEqual(cat._pricing["only-id"]["completion"], 1.0)
        self.assertNotIn("misc/other", cat._pricing)

    async def test_refresh_mdev_parse_error(self):
        cat = ModelsCatalog()
        cat._limits = {}
        cat._updated_at = 0.0
        mock_mdev_res = httpx.Response(200, text="{invalid")
        mock_or_res = httpx.Response(200, json={"data": []})

        def get_mock_res(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "models.dev" in url:
                return mock_mdev_res
            return mock_or_res

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = get_mock_res
            limits = await cat.refresh()
        self.assertEqual(limits, {})

    async def test_refresh_openrouter_parse_error(self):
        cat = ModelsCatalog()
        cat._limits = {}
        cat._updated_at = 0.0
        mock_mdev_res = httpx.Response(200, json={"openai": {"models": {}}})
        mock_or_res = httpx.Response(200, text="{invalid")

        def get_mock_res(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "models.dev" in url:
                return mock_mdev_res
            return mock_or_res

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = get_mock_res
            limits = await cat.refresh()
        self.assertEqual(limits, {})

    async def test_refresh_non_200_responses(self):
        cat = ModelsCatalog()
        cat._limits = {}
        cat._updated_at = 0.0
        mock_mdev_res = httpx.Response(500)
        mock_or_res = httpx.Response(503)

        def get_mock_res(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "models.dev" in url:
                return mock_mdev_res
            return mock_or_res

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = get_mock_res
            limits = await cat.refresh()
        self.assertEqual(limits, {})

    async def test_refresh_handles_request_exception(self):
        cat = ModelsCatalog()
        cat._limits = {}
        cat._updated_at = 0.0
        mock_or_res = httpx.Response(200, json={"data": [{"id": "x/m1", "context_length": 1000}]})

        def get_mock_res(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "models.dev" in url:
                raise RuntimeError("network error")
            return mock_or_res

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = get_mock_res
            limits = await cat.refresh()
        self.assertEqual(limits["x/m1"], 1000)
        self.assertNotIn("openai/gpt-4o", limits)

    async def test_refresh_outer_exception(self):
        cat = ModelsCatalog()
        cat._limits = {}
        with patch("core.models_catalog.asyncio.gather", side_effect=RuntimeError("boom")):
            limits = await cat.refresh()
        self.assertEqual(limits, {})


if __name__ == "__main__":
    unittest.main()
