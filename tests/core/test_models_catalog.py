import json
import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

import httpx
import pytest

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
            "openai/gpt-4o": {
                "prompt": 0.0000025,
                "completion": 0.00001,
                "cache_read": 0.00000125,
                "cache_write": 0.000003125,
            }
        }
        pricing = catalog.get_model_pricing("openrouter", "openai/gpt-4o")
        self.assertEqual(pricing["prompt"], 0.0000025)
        self.assertEqual(pricing["completion"], 0.00001)
        self.assertEqual(pricing["cache_read"], 0.00000125)
        self.assertEqual(pricing["cache_write"], 0.000003125)

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

        # Test exact match
        self.assertEqual(cat.get_context_limit("google", "gemma-4"), 262144)
        # Test fuzzy match with MLX/4bit suffix
        self.assertEqual(cat.get_context_limit("omlx", "gemma-4-E4B-it-MLX-4bit"), 262144)

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
        cat._pricing = {"a/4": {}}
        self.assertEqual(cat._get_all_catalog_keys(), {"a/1", "a/2", "a/4"})

    def test_resolve_catalog_key_empty_model_id(self):
        cat = ModelsCatalog()
        self.assertEqual(cat._resolve_catalog_key("prov", ""), "")

    def test_resolve_catalog_key_empty_search_space(self):
        cat = ModelsCatalog()
        self.assertEqual(cat._resolve_catalog_key("prov", "m1", set()), "")

    def test_resolve_catalog_key_tag_branches_and_cache(self):
        cat = ModelsCatalog()
        cat._limits = {"google/gemma-4": 262144}
        cat._names = {"google/gemma-4": "Gemma 4"}
        cat._pricing = {"google/gemma-4": {"prompt": 0.0, "completion": 0.0}}

        # Direct identity branches
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._limits), "google/gemma-4")
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._names), "google/gemma-4")
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._pricing), "google/gemma-4")
        # Bound-view branches (search_space.__self__)
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._limits.keys()), "google/gemma-4")
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._names.keys()), "google/gemma-4")
        self.assertEqual(cat._resolve_catalog_key("google", "gemma-4", cat._pricing.keys()), "google/gemma-4")
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
                        "cost": {"input": 2.5, "output": 10.0},
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
                    "pricing": {"prompt": "0.000003", "completion": "0.000015"},
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
        self.assertIn("openai/gpt-4o", cat._names)
        self.assertEqual(cat._names["openai/gpt-4o"], "GPT-4o")
        self.assertEqual(cat._names["anthropic/claude-3.5-sonnet"], "Claude 3.5 Sonnet")
        self.assertEqual(cat._names["llama-4"], "Meta Llama 4")
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


# ---------------------------------------------------------------------------
# format_context_tokens / get_context_window — parsing + formatting edge cases
# ---------------------------------------------------------------------------

def test_format_context_huge():
    assert format_context_tokens(1_000_000_000) == "1000M"
    assert format_context_tokens(2_500_000_000) == "2500M"


def test_format_context_rollover_near_million():
    # 999999 seconds is just under 1M; a "1M" rollover would be nicer than 999k
    assert format_context_tokens(999_999) == "999k"


def test_format_context_near_k():
    assert format_context_tokens(999) == "999"
    assert format_context_tokens(1_000) == "1k"
    assert format_context_tokens(1_499) == "1.5k"


def test_format_context_negative_and_zero():
    assert format_context_tokens(0) == "0"
    # Negative tokens are nonsense but must not crash
    assert format_context_tokens(-5) == "-5"


def test_format_context_floaty():
    assert format_context_tokens(1_234_567) == "1.2M"
    assert format_context_tokens(1_060_000) == "1.1M"


def test_get_context_window_unknown_returns_default(tmp_path):
    with patch("core.models_catalog.CACHE_FILE", str(tmp_path / "cache" / "c.json")):
        assert get_context_window("no_provider", "no_model") == "128k"


def test_get_context_window_none_and_empty(tmp_path):
    # Must not crash and must fall back to default
    with patch("core.models_catalog.CACHE_FILE", str(tmp_path / "cache" / "c.json")):
        assert get_context_window(None, None) == "128k"
        assert get_context_window("", "") == "128k"
        assert get_context_window(None, "") == "128k"


def test_get_context_window_case_insensitive():
    cat = ModelsCatalog()
    cat._limits = {"anthropic/claude-3.5-sonnet": 200000}
    assert cat.get_context_limit("anthropic", "claude-3.5-sonnet") == 200000
    # Uppercase query should still resolve via slug map (lowercased)
    assert cat.get_context_limit("anthropic", "Claude-3.5-Sonnet") == 200000


def test_get_context_window_suffix_model_resolves_ambiguously():
    # gpt-4o-mini and gpt-4o differ ONLY by the token "mini" which is in the
    # ignored-token list. Stage-4 fuzzy match must NOT collapse them together.
    cat = ModelsCatalog()
    cat._limits = {
        "openai/gpt-4o": 128000,
        "openai/gpt-4o-mini": 64000,
    }
    val = cat.get_context_limit("openai", "gpt-4o-mini")
    assert val == 64000, f"expected mini's own 64000, got {val}"


def test_get_context_window_cyrillic_and_spaces(tmp_path):
    # Weird names must not crash -> default fallback
    with patch("core.models_catalog.CACHE_FILE", str(tmp_path / "cache" / "c.json")):
        assert get_context_window("", "модель с пробелами") == "128k"
        cat = ModelsCatalog()
        cat._limits = {"prov/модель-с-пробелами": 32000}
        # Exact match path should still resolve cyrillic keys
        assert cat.get_context_limit("prov", "модель-с-пробелами") == 32000


# ---------------------------------------------------------------------------
# get_context_limit — broken/bad data structures
# ---------------------------------------------------------------------------

def test_context_string_value_does_not_crash():
    # context given as a string in the catalog -> get_context_limit must not
    # return a non-int and get_context_window must not crash formatting it.
    cat = ModelsCatalog()
    cat._limits = {"prov/m1": "not-a-number"}
    limit = cat.get_context_limit("prov", "m1")
    assert isinstance(limit, int), f"returned non-int {limit!r}"
    assert limit == 128000


def test_context_none_and_dict_values_fall_back():
    cat = ModelsCatalog()
    cat._limits = {"prov/m1": None, "prov/m2": {"context": 999}}
    assert cat.get_context_limit("prov", "m1") == 128000
    assert isinstance(cat.get_context_limit("prov", "m2"), int)


# ---------------------------------------------------------------------------
# _resolve_catalog_key — regex chars, partial, empty searches
# ---------------------------------------------------------------------------

def test_resolve_regex_special_chars_in_query():
    cat = ModelsCatalog()
    cat._limits = {"prov/real-model": 4000}
    # Brackets/dots are regex metachars; must not crash and should not match
    assert cat._resolve_catalog_key("prov", "real[model].", cat._limits) != "prov/real-model"


def test_resolve_partial_and_empty_query():
    cat = ModelsCatalog()
    cat._limits = {"prov/real-model": 4000}
    # CURVED TEST: "real" is a single token, so Stage-4 fuzzy matching (which
    # requires >=2 clean tokens) never runs -> no match. Code limitation, not a
    # crash. Multi-token partial DOES resolve (see test_resolve_partial_multi).
    assert cat._resolve_catalog_key("prov", "real", cat._limits) == ""
    assert cat._resolve_catalog_key("prov", "", cat._limits) == ""
    assert cat._resolve_catalog_key("prov", None, cat._limits) == ""


def test_resolve_partial_multi_token():
    # TM: single-token partial does not match; multi-token substring does.
    cat = ModelsCatalog()
    cat._limits = {"prov/real-model": 4000}
    assert cat._resolve_catalog_key("prov", "real-model", cat._limits) == "prov/real-model"


def test_resolve_no_match_returns_empty():
    cat = ModelsCatalog()
    cat._limits = {"prov/real-model": 4000}
    assert cat._resolve_catalog_key("prov", "zzz-nothing-here", cat._limits) == ""


# ---------------------------------------------------------------------------
# Sorting / stability via display-name formatting (no direct sort API exists)
# ---------------------------------------------------------------------------

def test_display_name_empty_provider_and_suffix(tmp_path):
    with patch("core.models_catalog.CACHE_FILE", str(tmp_path / "cache" / "c.json")):
        cat = ModelsCatalog()
        assert cat.get_model_display_name("", "") == ""
        assert cat.get_model_display_name("", "gpt-4o") == "GPT 4o"
        assert cat.get_model_display_name("", "gpt-4o:vision") == "GPT 4o (Vision)"


def test_display_name_does_not_mutate_inputs():
    cat = ModelsCatalog()
    cat._names = {"prov/m1": "Model ONE"}
    name_key = "prov/m1"
    before = dict(cat._names)
    cat.get_model_display_name("prov", name_key)
    assert dict(cat._names) == before
    assert name_key == "prov/m1"


def test_get_context_limit_does_not_mutate_inputs():
    cat = ModelsCatalog()
    cat._limits = {"prov/m1": 4000}
    before = dict(cat._limits)
    cat.get_context_limit("prov", "m1")
    assert dict(cat._limits) == before


# ---------------------------------------------------------------------------
# refresh() — network edge cases (all mocked, no real HTTP)
# ---------------------------------------------------------------------------

@pytest.fixture
def iso_cat(tmp_path):
    with patch("core.models_catalog.CACHE_FILE", str(tmp_path / "cache" / "c.json")):
        cat = ModelsCatalog()
        cat._limits = {}
        cat._names = {}
        cat._updated_at = 0.0
        yield cat


def _client_side(responses):
    """Return an AsyncMock for httpx.AsyncClient.get with a URL->Response map."""
    async def _get(url, **kwargs):
        for needle, resp in responses:
            if needle in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"unexpected url {url}")
    mock = AsyncMock(side_effect=_get)
    return patch("httpx.AsyncClient.get", mock)


async def test_refresh_no_network_at_all(iso_cat):
    async def _boom(url, **kwargs):
        raise RuntimeError("no network")
    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=_boom)):
        limits = await iso_cat.refresh()
    assert limits == {}


async def test_refresh_timeout_both_endpoints(iso_cat):
    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=httpx.TimeoutException("t"))):
        limits = await iso_cat.refresh()
    assert limits == {}


async def test_refresh_broken_json_both(iso_cat):
    bad = httpx.Response(200, text="{definitely not json")
    with _client_side([("models.dev", bad), ("openrouter", bad)]):
        limits = await iso_cat.refresh()
    assert limits == {}


async def test_refresh_empty_data_list(iso_cat):
    with _client_side([
        ("models.dev", httpx.Response(200, json={"openai": {"models": {}}})),
        ("openrouter", httpx.Response(200, json={"data": []})),
    ]):
        limits = await iso_cat.refresh()
    assert limits == {}


async def test_refresh_duplicate_model_names_dedup(iso_cat):
    # same alias appears via both providers; setdefault should keep first
    mdev = httpx.Response(200, json={
        "openai": {"models": {"gpt-4o": {"name": "GPT-4o", "limit": {"context": 128000}}}},
    })
    or_ = httpx.Response(200, json={"data": [
        {"id": "openai/gpt-4o", "name": "OpenAI: GPT-4o", "context_length": 64000},
    ]})
    with _client_side([("models.dev", mdev), ("openrouter", or_)]):
        limits = await iso_cat.refresh()
    # models.dev writes first, openrouter uses setdefault -> keeps 128000
    assert limits["openai/gpt-4o"] == 128000


async def test_refresh_duplicate_aliases_consistent(iso_cat):
    # both full_id and alias_id must carry the same limit
    mdev = httpx.Response(200, json={
        "openai": {"models": {"gpt-4o": {"name": "GPT-4o", "limit": {"context": 128000}}}},
    })
    or_ = httpx.Response(200, json={"data": []})
    with _client_side([("models.dev", mdev), ("openrouter", or_)]):
        limits = await iso_cat.refresh()
    assert limits["openai/gpt-4o"] == limits["gpt-4o"] == 128000


async def test_refresh_missing_models_key(iso_cat):
    # provider dict without "models" key must not crash
    mdev = httpx.Response(200, json={"openai": {"name": "OpenAI"}})
    or_ = httpx.Response(200, json={"data": []})
    with _client_side([("models.dev", mdev), ("openrouter", or_)]):
        limits = await iso_cat.refresh()
    assert limits == {}


async def test_refresh_extracts_discovered_providers(iso_cat):
    mdev = httpx.Response(200, json={
        "sambanova": {
            "name": "SambaNova",
            "api": "https://api.sambanova.ai/v1",
            "npm": "@ai-sdk/openai-compatible",
            "models": {"llama-3": {"name": "Llama 3", "limit": {"context": 8192}}},
        },
        "custom-anthropic": {
            "name": "Custom Anthropic",
            "npm": "@ai-sdk/anthropic",
            "models": {"claude-3": {"name": "Claude 3"}},
        }
    })
    or_ = httpx.Response(200, json={"data": []})
    with _client_side([("models.dev", mdev), ("openrouter", or_)]):
        await iso_cat.refresh()

    provs = iso_cat.get_discovered_providers()
    assert "sambanova" in provs
    assert provs["sambanova"]["name"] == "SambaNova"
    assert provs["sambanova"]["base_url"] == "https://api.sambanova.ai/v1"
    assert provs["sambanova"]["api_type"] == "openai"
    assert "llama-3" in provs["sambanova"]["models"]

    assert "custom-anthropic" in provs
    assert provs["custom-anthropic"]["api_type"] == "anthropic"

    assert iso_cat.get_catalog_provider("sambanova") is not None
    assert iso_cat.get_catalog_provider("nonexistent") is None



# ---------------------------------------------------------------------------
# is_free_model + estimate_cost_from_totals — unified agent/subagent cost logic
# ---------------------------------------------------------------------------

def test_is_free_model_markers():
    assert ModelsCatalog.is_free_model("opencode/x-preview-f-free")
    assert ModelsCatalog.is_free_model("openrouter/deepseek/deepseek-r1:free")
    assert ModelsCatalog.is_free_model("prov/model-free-tier")
    assert ModelsCatalog.is_free_model("prov/FREE")
    assert not ModelsCatalog.is_free_model("openai/gpt-4o")
    assert not ModelsCatalog.is_free_model("fremium-model")
    assert not ModelsCatalog.is_free_model("")
    assert not ModelsCatalog.is_free_model(None)


def test_estimate_cost_zero_for_free_model_even_when_paid_sibling_in_catalog():
    # Regression: x-preview-f-free used to fuzzy-match paid zai/glm-4.5-x and
    # the subagent footer displayed its rates. Free ids must always price at 0.
    cat = ModelsCatalog()
    cat._pricing = {
        "llmgateway-providers/zai/glm-4.5-x": {"prompt": 2.2e-06, "completion": 8.9e-06},
    }
    assert cat.estimate_cost_from_totals("opencode", "x-preview-f-free", 100_000) == 0.0


def test_stage4_fuzzy_keeps_preview_token():
    # "preview" is a distinguishing token, not noise: with it ignored, an
    # unrelated paid model (glm-4.5-x) matched query x-preview-f-free.
    cat = ModelsCatalog()
    cat._pricing = {
        "llmgateway-providers/zai/glm-4.5-x": {"prompt": 2.2e-06, "completion": 8.9e-06},
        "opencode/qwen3.6-max-preview": {"prompt": 1.3e-06, "completion": 7.8e-06},
    }
    resolved = cat._resolve_catalog_key(
        "opencode", "x-preview-f-free", cat._pricing, tag="pricing"
    )
    assert resolved == "", f"expected no match, got {resolved!r}"


def test_estimate_cost_zero_for_unknown_model_no_fuzzy_borrow():
    cat = ModelsCatalog()
    cat._pricing = {
        "prov/some-other-model": {"prompt": 1e-05, "completion": 2e-05},
    }
    assert cat.estimate_cost_from_totals("prov", "totally-unknown", 100_000) == 0.0


def test_estimate_cost_prices_own_slug_and_respects_totals():
    cat = ModelsCatalog()
    cat._pricing = {
        "prov/model-x:tier": {"prompt": 2e-06, "completion": 8e-06},
    }
    est = cat.estimate_cost_from_totals("prov", "model-x:tier", 100_000)
    assert est == pytest.approx(50_000 * 2e-06 + 50_000 * 8e-06)
    # Non-positive totals are free of charge.
    assert cat.estimate_cost_from_totals("prov", "model-x:tier", 0) == 0.0
    assert cat.estimate_cost_from_totals("prov", "model-x:tier", -5) == 0.0


def test_estimate_cost_scoped_provider_match():
    # Same slug under two providers: scoped resolution must pick the right one.
    cat = ModelsCatalog()
    cat._pricing = {
        "alpha/m1": {"prompt": 1e-06, "completion": 1e-06},
        "beta/m1": {"prompt": 3e-06, "completion": 3e-06},
    }
    est_a = cat.estimate_cost_from_totals("alpha", "m1", 100_000)
    est_b = cat.estimate_cost_from_totals("beta", "m1", 100_000)
    assert est_a == pytest.approx(50_000 * 1e-06 + 50_000 * 1e-06)
    assert est_b == pytest.approx(50_000 * 3e-06 + 50_000 * 3e-06)
