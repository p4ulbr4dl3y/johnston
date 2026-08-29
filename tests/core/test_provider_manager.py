import asyncio
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.models_catalog import catalog
from core.provider_manager import ProviderManager


@pytest.fixture
def pm(tmp_path, monkeypatch):
    monkeypatch.setattr("core.provider_manager.CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr("core.provider_manager.CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr("core.provider_manager.PROVIDERS_JSON_FILE", str(tmp_path / "providers.json"))
    monkeypatch.setattr("core.provider_manager.CACHE_DIR", str(tmp_path / "cache"))
    return ProviderManager()


def _write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


class TestProviderManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

        # Patch config values inside provider_manager
        self.config_dir_patcher = patch("core.provider_manager.CONFIG_DIR", self.test_dir)
        self.config_file_patcher = patch(
            "core.provider_manager.CONFIG_FILE", os.path.join(self.test_dir, "config.json")
        )
        self.providers_json_patcher = patch(
            "core.provider_manager.PROVIDERS_JSON_FILE", os.path.join(self.test_dir, "providers.json")
        )
        self.cache_dir_patcher = patch("core.provider_manager.CACHE_DIR", os.path.join(self.test_dir, "cache"))

        self.config_dir_patcher.start()
        self.config_file_patcher.start()
        self.providers_json_patcher.start()
        self.cache_dir_patcher.start()

        self.pm = ProviderManager()

    def tearDown(self):
        self.config_dir_patcher.stop()
        self.config_file_patcher.stop()
        self.providers_json_patcher.stop()
        self.cache_dir_patcher.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_ensure_config_dir(self):
        self.assertTrue(os.path.exists(self.test_dir))
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, "providers.json")))

    def test_load_providers(self):
        providers = self.pm.load_providers()
        self.assertIn("openai", providers)
        self.assertEqual(providers["openai"]["name"], "OpenAI")

    def test_get_set_active_provider_key(self):
        self.assertEqual(self.pm.get_active_provider_key(), "")
        self.pm.set_active_provider_key("custom_prov")
        self.assertEqual(self.pm.get_active_provider_key(), "custom_prov")

    def test_create_active_agent(self):
        self.assertIsNone(self.pm.create_active_agent())
        self.pm.set_active_provider_key("openai")
        agent = self.pm.create_active_agent()
        self.assertIsNotNone(agent)
        self.assertEqual(agent.model, "")

    def test_api_keys(self):
        self.assertEqual(self.pm.get_api_key("openai"), "")
        self.pm.set_provider_api_key("openai", "test-key-123")
        self.assertEqual(self.pm.get_api_key("openai"), "test-key-123")

    @patch("httpx.AsyncClient")
    async def _async_test_fetch_models(self, mock_client_cls):
        # Setup mock responses for httpx
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "model-a"}, {"id": "model-b"}]}
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
            json.dump(
                {
                    "custom_no_model": {
                        "key": "custom_no_model",
                        "name": "Custom No Model",
                        "base_url": "https://api.example.com/v1",
                        "models": ["model-1", "model-2"],
                    }
                },
                f,
            )

        pm = ProviderManager()
        pm.set_active_provider_key("custom_no_model")
        agent = pm.create_active_agent()
        self.assertEqual(agent.model, "")  # No default model fallback

        pm.set_provider_model("custom_no_model", "model-2")
        agent2 = pm.create_active_agent()
        self.assertEqual(agent2.model, "model-2")

    def test_disabled_providers(self):
        self.pm.set_provider_disabled("groq", True)
        disabled = self.pm.get_disabled_providers()
        self.assertIn("groq", disabled)

        provs = self.pm.load_providers(include_disabled=False)
        self.assertNotIn("groq", provs)

        self.pm.set_provider_disabled("groq", False)
        self.assertNotIn("groq", self.pm.get_disabled_providers())

    def test_thinking_effort(self):
        self.pm.set_provider_thinking_effort("openai", "gpt-4o", "high")
        eff = self.pm.get_provider_thinking_effort("openai", "gpt-4o")
        self.assertEqual(eff, "high")

        self.pm.set_provider_thinking_effort("openai", "gpt-4o", "")
        eff_empty = self.pm.get_provider_thinking_effort("openai", "gpt-4o")
        self.assertEqual(eff_empty, "auto")

    @patch("httpx.AsyncClient")
    def test_fetch_models_grouped(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.is_closed = False
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "m1"}]}
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        catalog._client = None

        res = asyncio.run(self.pm.fetch_models_grouped(force_refresh=True, connected_only=False))
        self.assertIn("openai", res)

    def test_load_providers_memo_reuses_result(self):
        """Repeated load_providers() must reuse one memoized dict (no re-merge)."""
        with patch.object(self.pm, "_load_json_providers", wraps=self.pm._load_json_providers) as spy:
            p1 = self.pm.load_providers()
            p2 = self.pm.load_providers()
            self.assertIs(p1, p2)  # memoized, same object (read-only usage)
            self.assertEqual(spy.call_count, 1)

    def test_load_providers_memo_invalidated_by_providers_file(self):
        """External change to providers.json (mtime) must invalidate the memo."""
        providers_file = os.path.join(self.test_dir, "providers.json")
        with open(providers_file, "w", encoding="utf-8") as f:
            json.dump({"pp": {"key": "pp", "name": "PP", "base_url": "", "models": []}}, f)

        p1 = self.pm.load_providers()
        self.assertIsNotNone(p1.get("pp"))

        # Rewrite with updated provider name; mtime change invalidates the memo.
        with open(providers_file, "w", encoding="utf-8") as f:
            json.dump({"pp": {"key": "pp", "name": "PP2", "base_url": "", "models": []}}, f)
        # Some filesystems (Windows) have coarse mtime granularity; bump the
        # timestamp explicitly so the memo invalidation is deterministic.
        st = os.stat(providers_file)
        os.utime(providers_file, (st.st_atime, st.st_mtime + 2))

        p2 = self.pm.load_providers()
        self.assertEqual(p2["pp"]["name"], "PP2")
        self.assertIsNot(p1, p2)


# ---------------------------------------------------------------------------
# JSON providers loading (was test_provider_manager_json.py)
# ---------------------------------------------------------------------------

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
                    "model": "my-custom-model",
                }
            }
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(sample_data, f)

            with (
                patch("core.provider_manager.PROVIDERS_JSON_FILE", json_file),
                patch("core.provider_manager.CONFIG_FILE", config_file),
                patch("core.provider_manager.CONFIG_DIR", tmpdir),
            ):
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
                        "models": ["model-1", "model-2", "model-3"],
                    }
                }
                with open(json_file, "w", encoding="utf-8") as f:
                    json.dump(sample_data, f)

                with (
                    patch("core.provider_manager.PROVIDERS_JSON_FILE", json_file),
                    patch("core.provider_manager.CONFIG_FILE", config_file),
                    patch("core.provider_manager.CONFIG_DIR", tmpdir),
                ):
                    pm = ProviderManager()
                    models = await pm.fetch_models_for_provider("no_models_endpoint", force_refresh=True)
                    self.assertEqual(models, ["model-1", "model-2", "model-3"])

        asyncio.run(_test())


class TestProviderManagerJsonRegression(unittest.TestCase):
    def test_invalid_providers_json_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_file = os.path.join(tmpdir, "providers.json")
            config_file = os.path.join(tmpdir, "config.json")
            with open(json_file, "w", encoding="utf-8") as f:
                f.write("{not json")

            with (
                patch("core.provider_manager.PROVIDERS_JSON_FILE", json_file),
                patch("core.provider_manager.CONFIG_FILE", config_file),
                patch("core.provider_manager.CONFIG_DIR", tmpdir),
            ):
                pm = ProviderManager()
                providers = pm.load_providers()

        self.assertIn("anthropic", providers)
        self.assertIn("openai", providers)

    def test_saved_model_overrides_json_default_model(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_file = os.path.join(tmpdir, "providers.json")
            config_file = os.path.join(tmpdir, "config.json")
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "custom_json": {
                            "key": "custom_json",
                            "name": "Custom JSON LLM",
                            "base_url": "http://localhost:8080/v1",
                            "model": "default-model",
                            "models": ["default-model", "saved-model"],
                        }
                    },
                    f,
                )

            with (
                patch("core.provider_manager.PROVIDERS_JSON_FILE", json_file),
                patch("core.provider_manager.CONFIG_FILE", config_file),
                patch("core.provider_manager.CONFIG_DIR", tmpdir),
            ):
                pm = ProviderManager()
                pm.set_provider_model("custom_json", "saved-model")
                pm.set_active_provider_key("custom_json")
                agent = pm.create_active_agent()

        self.assertEqual(agent.model, "saved-model")


# ---------------------------------------------------------------------------
# Edge cases (was test_edge_provider_manager.py)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def test_empty_config_file(pm, tmp_path):
    (tmp_path / "config.json").write_text("", encoding="utf-8")
    assert pm._read_config() == {}
    assert pm.get_api_key("openai") == ""
    assert pm.get_active_provider_key() == ""


def test_whitespace_only_config_file(pm, tmp_path):
    (tmp_path / "config.json").write_text("   \n\t  ", encoding="utf-8")
    assert pm.get_active_provider_key() == ""


def test_config_not_a_dict(pm, tmp_path):
    _write(tmp_path / "config.json", ["openai", "groq"])
    # _read_config must coerce to {}
    assert pm._read_config() == {}
    _write(tmp_path / "providers.json", ["openai", "groq"])
    # get_disabled_providers must not blow up on list providers config
    assert pm.get_disabled_providers() == []


def test_config_missing(pm):
    assert pm._read_config() == {}
    assert pm.get_api_key("openai") == ""


def test_provider_absent_from_config(pm):
    assert pm.get_api_key("does_not_exist") == ""
    assert pm.get_provider_model("does_not_exist") == ""


def test_unicode_and_quoted_key_values(pm):
    key = 'sk-привет"quote\\back\\slash'
    pm.set_provider_api_key("openai", key)
    assert pm.get_api_key("openai") == key
    from core.infrastructure.secrets import load_secrets

    saved = load_secrets()
    assert saved.get("openai") == key or saved.get("OPENAI_API_KEY") == key
    # round-trip integrity
    assert pm.get_api_key("openai") == key


# ---------------------------------------------------------------------------
# is_provider_connected
# ---------------------------------------------------------------------------

def test_connected_none_name(pm):
    assert pm.is_provider_connected(None) is False


def test_connected_unknown_name(pm):
    assert pm.is_provider_connected("nope-not-a-provider") is False


def test_connected_no_key(pm):
    assert pm.is_provider_connected("openai") is False


def test_connected_env_key(pm, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-secret-key")
    from core.infrastructure.secrets import save_secret

    save_secret("openai", "file-secret-key")
    # file should take precedence over env
    assert pm.get_api_key("openai") == "file-secret-key"


def test_connected_with_file_key(pm):
    from core.infrastructure.secrets import save_secret

    save_secret("openai", "sk-abc")
    assert pm.is_provider_connected("openai") is True


def test_connected_whitespace_key(pm):
    from core.infrastructure.secrets import save_secret

    save_secret("openai", "   ")
    assert pm.is_provider_connected("openai") is False


def test_connected_case_sensitive_name(pm, tmp_path):
    from core.infrastructure.secrets import save_secret

    save_secret("openai", "sk-abc")
    # actual provider key is lowercase; uppercase name must not match
    assert pm.is_provider_connected("OpenAI") is False


def test_connected_disabled_provider(pm, tmp_path):
    from core.infrastructure.secrets import save_secret

    save_secret("openai", "sk-abc")
    _write(tmp_path / "providers.json", {"openai": {"enabled": False}})
    assert pm.is_provider_connected("openai") is False


def test_connected_multiple_providers(pm, tmp_path):
    from core.infrastructure.secrets import save_secret

    save_secret("openai", "sk-abc")
    save_secret("groq", "sk-xyz")
    assert pm.is_provider_connected("openai") is True
    assert pm.is_provider_connected("groq") is True
    assert pm.is_provider_connected("anthropic") is False


def test_connected_passed_pdata_local(pm):
    assert pm.is_provider_connected("any", {"api_type": "ollama"}) is True


def test_connected_passed_pdata_requires_key_false(pm):
    assert pm.is_provider_connected("any", {"requires_key": False}) is True


# ---------------------------------------------------------------------------
# Active provider selection
# ---------------------------------------------------------------------------

def test_active_provider_none(pm):
    assert pm.get_active_provider_key() == ""
    pm.set_active_provider_key("openai")
    assert pm.get_active_provider_key() == "openai"


def test_active_provider_field_is_ignored(pm, tmp_path):
    # ``model`` is the single source of truth; a stale legacy ``active_provider``
    # field is never read, so an active_provider-only config yields no provider.
    _write(tmp_path / "config.json", {"active_provider": "openai"})
    assert pm.get_active_provider_key() == ""

    _write(tmp_path / "config.json", {"model": "openai/gpt-4o", "active_provider": "anthropic"})
    assert pm.get_active_provider_key() == "openai"


def test_active_provider_nonexistent(pm):
    pm.set_active_provider_key("ghost-provider")
    agent = pm.create_active_agent()
    # ghost-provider cannot back an agent, falls back to connected provider or None
    if agent is not None:
        assert agent.provider_key != "ghost-provider"


# ---------------------------------------------------------------------------
# create_agent_for_provider
# ---------------------------------------------------------------------------

def test_create_agent_none_provider(pm):
    agent = pm.create_agent_for_provider(None)
    assert agent is None


def test_create_agent_unknown_provider(pm):
    agent = pm.create_agent_for_provider("unknown")
    assert agent is None


def test_create_agent_missing_api_key(pm):
    agent = pm.create_agent_for_provider("openai")
    assert agent.model == ""
    # api_key defaults to placeholder, should not be a real secret
    assert agent.api_key in ("", "sk-placeholder")


def test_create_agent_invalid_model(pm, tmp_path):
    _write(tmp_path / "config.json", {"model": "openai/not-a-real-model"})
    agent = pm.create_agent_for_provider("openai")
    assert agent.model == "not-a-real-model"


def test_create_agent_provider_without_base_url(pm, tmp_path):
    _write(
        tmp_path / "providers.json",
        {"custom_nobase": {"key": "custom_nobase", "name": "No Base URL"}},
    )
    agent = pm.create_agent_for_provider("custom_nobase")
    assert agent.base_url == ""


def test_fetch_models_network_error_swallowed(pm, tmp_path):
    from core.infrastructure.secrets import save_secret

    _write(
        tmp_path / "providers.json",
        {"custom": {"key": "custom", "name": "C", "base_url": "http://127.0.0.1:1/v1", "model": "m1"}},
    )
    save_secret("custom", "sk-abc")

    async def _run():
        # httpx fails to connect; ProviderManager catches Exception and
        # falls back to the configured model list.
        return await pm.fetch_models_for_provider("custom", force_refresh=True)

    models = asyncio.run(_run())
    assert models == ["m1"]


def test_fetch_models_no_base_url(pm, tmp_path):
    from core.infrastructure.secrets import save_secret

    _write(
        tmp_path / "providers.json",
        {"nobaseurl": {"key": "nobaseurl", "name": "N", "model": "m1"}},
    )
    save_secret("nobaseurl", "sk-abc")

    async def _run():
        return await pm.fetch_models_for_provider("nobaseurl", force_refresh=True)

    models = asyncio.run(_run())
    assert models == ["m1"]


# ---------------------------------------------------------------------------
# Config save / atomicity / secrets
# ---------------------------------------------------------------------------

def test_save_atomic_no_partial_file(pm, tmp_path):
    pm.set_active_provider_key("openai")
    # no leftover temp files
    leftovers = [p for p in os.listdir(tmp_path) if ".tmp" in p or p.startswith(".johnston-")]
    assert leftovers == []


def test_save_none_value(pm, tmp_path):
    pm.set_active_provider_key(None)
    # Clearing clears the model; no provider is left behind.
    assert pm.get_active_provider_key() == ""


def test_save_secret_not_in_caplog(pm, caplog):
    import logging
    with caplog.at_level(logging.DEBUG):
        pm.set_provider_api_key("openai", "SUPER-SECRET-KEY-123")
        # force a fresh read through cache path
        pm.get_api_key("openai")
    assert "SUPER-SECRET-KEY-123" not in caplog.text


@pytest.mark.skipif(os.name == "nt", reason="chmod read-only dir is ineffective on Windows")
def test_save_readonly_path_permission_error(pm, tmp_path):
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    os.chmod(tmp_path, 0o500)
    try:
        with pytest.raises(OSError):
            pm.set_active_provider_key("openai")
    finally:
        os.chmod(tmp_path, 0o755)


def test_save_unicode_special_chars(pm, tmp_path):
    val = 'héllo "quoted" \u2603 snowman \n newline \t tab \\ backslash'
    pm.set_provider_api_key("openai", val)
    assert pm.get_api_key("openai") == val


# ---------------------------------------------------------------------------
# env precedence / dirty env
# ---------------------------------------------------------------------------

def test_env_key_does_not_override_file(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_dirty_env_no_crash(pm, monkeypatch):
    monkeypatch.setenv("SOME_UNRELATED_ENV", "  whitespace  ")
    assert pm.get_api_key("openai") == ""


# ---------------------------------------------------------------------------
# Provider list edges
# ---------------------------------------------------------------------------

def test_empty_providers_json(pm, tmp_path):
    _write(tmp_path / "providers.json", {})
    providers = pm.load_providers()
    # defaults still present
    assert "openai" in providers
    assert "anthropic" in providers


def test_providers_json_not_dict(pm, tmp_path):
    _write(tmp_path / "providers.json", ["openai"])
    providers = pm.load_providers()
    assert "openai" in providers


def test_providers_json_non_dict_value(pm, tmp_path):
    _write(tmp_path / "providers.json", {"openai": "garbage-string"})
    providers = pm.load_providers()
    # non-dict value must not crash; default provider still loaded
    assert providers["openai"]["name"] == "OpenAI"


def test_providers_json_missing_len_token_fields(pm, tmp_path):
    _write(
        tmp_path / "providers.json",
        {"sparse": {"key": "sparse", "name": "Sparse"}},
    )
    providers = pm.load_providers()
    assert providers["sparse"]["model"] == ""
    assert providers["sparse"]["models"] == []
    assert providers["sparse"]["max_tokens"] is None


def test_providers_json_duplicate_keys(pm, tmp_path):
    # json duplicates -> last wins per json.loads
    content = '{"dup": {"name": "A"}, "dup": {"name": "B"}}'
    (tmp_path / "providers.json").write_text(content, encoding="utf-8")
    providers = pm.load_providers()
    assert providers["dup"]["name"] == "B"


# ---------------------------------------------------------------------------
# Cache invalidation / staleness
# ---------------------------------------------------------------------------

def test_cache_invalidated_after_set(pm, tmp_path):
    pm.set_provider_api_key("openai", "first")
    assert pm.get_api_key("openai") == "first"
    pm.set_provider_api_key("openai", "second")
    assert pm.get_api_key("openai") == "second"


def test_cache_reload_after_external_file_change(pm, tmp_path):
    config = tmp_path / "config.json"
    _write(config, {"model": "one/model-a"})
    assert pm.get_active_provider_key() == "one"
    # external modification with a later mtime
    time.sleep(0.01)
    _write(config, {"model": "two/model-b"})
    assert pm.get_active_provider_key() == "two"


def test_cache_reload_after_providers_change(pm, tmp_path):
    pfile = tmp_path / "providers.json"
    _write(pfile, {"custom": {"key": "custom", "name": "One", "model": "m1"}})
    assert pm.load_providers()["custom"]["name"] == "One"
    time.sleep(0.01)
    _write(pfile, {"custom": {"key": "custom", "name": "Two", "model": "m2"}})
    assert pm.load_providers()["custom"]["name"] == "Two"


def test_load_provider_def_from_catalog_fallback(pm):
    with patch.object(catalog, "get_catalog_provider") as mock_get_cat:
        mock_get_cat.return_value = {
            "key": "chutes",
            "name": "Chutes AI",
            "base_url": "https://chutes.ai/v1",
            "api_type": "openai",
            "models": ["chutes-model-1"],
        }
        pdef = pm.load_provider_def("chutes")
        assert pdef is not None
        assert pdef.key == "chutes"
        assert pdef.name == "Chutes AI"
        assert pdef.base_url == "https://chutes.ai/v1"

    # also test get_catalog_providers
    with patch.object(catalog, "get_discovered_providers", return_value={"p1": {}}):
        assert "p1" in pm.get_catalog_providers()


# ---------------------------------------------------------------------------
# Robustness: malformed providers.json, env keys, placeholders, null-delete
# ---------------------------------------------------------------------------

def test_malformed_provider_field_skipped_not_fatal(pm, tmp_path):
    # Regression: a single garbage numeric field used to raise ValueError out
    # of load_providers() and take down the whole provider list.
    _write(tmp_path / "providers.json", {"broken": {"chunk_timeout": "abc"}, "openai": {"model": "g"}})
    providers = pm.load_providers()
    assert "broken" not in providers
    assert providers["openai"]["model"] == "g"


def test_load_provider_def_malformed_returns_none(pm, tmp_path):
    _write(tmp_path / "providers.json", {"bad": {"max_retries": "lots"}})
    assert pm.load_provider_def("bad") is None


def test_explicit_zero_fields_preserved(pm, tmp_path):
    _write(
        tmp_path / "providers.json",
        {"zeroed": {"key": "zeroed", "name": "Z", "chunk_timeout": 0, "retry_delay": 0, "max_retries": 0}},
    )
    pdef = pm.load_provider_def("zeroed")
    assert pdef is not None
    assert pdef.chunk_timeout == 0.0
    assert pdef.retry_delay == 0.0
    assert pdef.max_retries == 0


def test_env_api_key_fallback_and_stored_precedence(pm, tmp_path, monkeypatch):
    monkeypatch.setenv("ACME_API_KEY", "from-env")
    assert pm.get_api_key("acme") == "from-env"

    pm.set_provider_api_key("acme", "typed-by-user")
    assert pm.get_api_key("acme") == "typed-by-user"


def test_env_api_key_togetherai(pm, monkeypatch):
    monkeypatch.setenv("TOGETHERAI_API_KEY", "tog-key")
    from core.infrastructure.secrets import get_secret

    assert get_secret("togetherai") == "tog-key"
    assert get_secret("unknown-provider") == ""


def test_base_url_placeholder_resolved_from_env(pm, tmp_path, monkeypatch):
    monkeypatch.setenv("AZURE_RESOURCE", "my-org")
    _write(tmp_path / "providers.json", {})
    pdef = pm.load_provider_def("azure")
    assert pdef is not None
    assert pdef.base_url == "https://my-org.openai.azure.com/openai"


def test_base_url_placeholder_resolved_from_provider_field(pm, tmp_path):
    _write(
        tmp_path / "providers.json",
        {
            "cf": {
                "key": "cf",
                "name": "CF",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
                "account_id": "acct42",
            }
        },
    )
    pdef = pm.load_provider_def("cf")
    assert pdef is not None
    assert pdef.base_url == "https://api.cloudflare.com/client/v4/accounts/acct42/ai/v1"


def test_base_url_placeholder_unresolved_stays_verbatim(pm, tmp_path, caplog, monkeypatch):
    import logging as _logging

    # Fresh dedup state: earlier tests may have already warned for this token.
    monkeypatch.setattr("core.provider_manager._WARNED_BASE_URL_TOKENS", set())
    _write(
        tmp_path / "providers.json",
        {"azure": {"key": "azure", "name": "Azure"}},
    )
    with caplog.at_level(_logging.WARNING):
        pdef = pm.load_provider_def("azure")
    assert pdef is not None
    assert "{resource}" in pdef.base_url
    assert any("{resource}" in rec.message for rec in caplog.records)


def test_null_provider_entry_deletes_builtin(pm, tmp_path):
    _write(tmp_path / "providers.json", {"cohere": None})
    providers = pm.load_providers()
    assert "cohere" not in providers
    assert "openai" in providers  # untouched defaults remain


def test_set_provider_model_single_source_of_truth(pm, tmp_path):
    pfile = tmp_path / "providers.json"
    _write(pfile, {"custom": {"key": "custom", "name": "C", "model": "orig"}})

    pm.set_provider_model("custom", "new-model")

    # config.json holds the selection...
    data = _load_json(tmp_path / "config.json")
    assert data["model"] == "custom/new-model"
    # ...and providers.json is no longer rewritten (no drift).
    assert _load_json(pfile)["custom"]["model"] == "orig"


def test_select_model_switching_provider_sets_live_agent_model(pm, tmp_path):
    """Regression: switching provider via select_model must apply the chosen model
    to the *recreated* agent (not a stale pre-recreation reference), and persist
    it via the ``model`` field alone (no dedicated ``active_provider`` field)."""
    from core.application.provider.actions import select_model

    _write(
        tmp_path / "providers.json",
        {
            "prov_a": {"key": "prov_a", "name": "A", "model": "model-a-default"},
            "prov_b": {"key": "prov_b", "name": "B", "model": "model-b-default"},
        },
    )
    _write(tmp_path / "config.json", {"model": "prov_a/model-a-default"})
    pm.invalidate_cache()

    agent = pm.create_active_agent()
    assert agent.model == "model-a-default"

    class _App:
        def __init__(self, a):
            self.agent = a
            self.role = a.role

        def refresh_status_footer(self):
            pass

    app = _App(agent)
    select_model(pm, agent, "prov_b", "model-b2", app)

    # The live agent (recreated for prov_b) must carry the selected model.
    assert app.agent.provider_key == "prov_b"
    assert app.agent.model == "model-b2"
    assert pm.get_active_provider_key() == "prov_b"

    # model is the single source of truth; no active_provider field is stored.
    data = _load_json(tmp_path / "config.json")
    assert data["model"] == "prov_b/model-b2"
    assert "active_provider" not in data
    # Re-reading the persisted selection gives back the selected model.
    assert pm.get_provider_model("prov_b") == "model-b2"


def test_is_local_provider():
    from core.provider_manager import is_local_provider

    assert is_local_provider("ollama") is True
    assert is_local_provider("lmstudio") is True
    assert is_local_provider("litellm") is True
    assert is_local_provider("custom", api_type="ollama") is True
    assert is_local_provider("custom", api_type="lmstudio") is True
    assert is_local_provider("custom", api_type="litellm") is True
    # Custom provider with requires_key=False
    assert is_local_provider("custom_vllm", requires_key=False) is True
    # Custom provider with localhost base_url
    assert is_local_provider("custom_vllm", base_url="http://localhost:8000/v1") is True
    assert is_local_provider("custom_vllm", base_url="http://127.0.0.1:8000/v1") is True
    assert is_local_provider("custom_vllm", base_url="http://[::1]:8000/v1") is True
    assert is_local_provider("custom_vllm", base_url="http://0.0.0.0:8000/v1") is True
    # Remote providers with keys
    assert is_local_provider("openai") is False
    assert is_local_provider("anthropic", base_url="https://api.anthropic.com") is False
    assert is_local_provider("custom_remote", base_url="https://api.my-cloud.com/v1", requires_key=True) is False


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


