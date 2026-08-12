"""Edge-case tests for core.provider_manager.ProviderManager.

Focused on malformed configs, env-edge handling, secret hygiene, cache
staleness, and fallback behavior. No real API keys / no network (httpx mocked).
"""
import asyncio
import json
import os
import time

import pytest

from core.provider_manager import ProviderManager


@pytest.fixture
def pm(tmp_path, monkeypatch):
    monkeypatch.setattr("core.provider_manager.CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr("core.provider_manager.CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr("core.provider_manager.PROVIDERS_JSON_FILE", str(tmp_path / "providers.json"))
    return ProviderManager()


def _write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


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
    # get_disabled_providers must not blow up on list config
    assert pm.get_disabled_providers() == []


def test_config_missing(pm):
    assert pm._read_config() == {}
    assert pm.get_api_key("openai") == ""


def test_provider_absent_from_config(pm):
    assert pm.get_api_key("does_not_exist") == ""
    assert pm.get_provider_model("does_not_exist") == ""


def test_unicode_and_quoted_key_values(pm, tmp_path):
    key = 'sk-привет"quote\\back\\slash'
    pm.set_provider_api_key("openai", key)
    assert pm.get_api_key("openai") == key
    with open(tmp_path / "config.json", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["api_keys"]["openai"] == key
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


def test_connected_env_key(pm, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-secret-key")
    _write(
        tmp_path / "config.json",
        {"api_keys": {"openai": "file-secret-key"}},
    )
    # env should NOT leak into config-backed get_api_key
    assert pm.get_api_key("openai") == "file-secret-key"


def test_connected_with_file_key(pm, tmp_path):
    _write(tmp_path / "config.json", {"api_keys": {"openai": "sk-abc"}})
    assert pm.is_provider_connected("openai") is True


def test_connected_whitespace_key(pm, tmp_path):
    _write(tmp_path / "config.json", {"api_keys": {"openai": "   "}})
    assert pm.is_provider_connected("openai") is False


def test_connected_case_sensitive_name(pm, tmp_path):
    _write(tmp_path / "config.json", {"api_keys": {"openai": "sk-abc"}})
    # actual provider key is lowercase; uppercase name must not match
    assert pm.is_provider_connected("OpenAI") is False


def test_connected_disabled_provider(pm, tmp_path):
    _write(tmp_path / "config.json", {"api_keys": {"openai": "sk-abc"}, "disabled_providers": ["openai"]})
    assert pm.is_provider_connected("openai") is False


def test_connected_multiple_providers(pm, tmp_path):
    _write(
        tmp_path / "config.json",
        {"api_keys": {"openai": "sk-abc", "groq": "sk-xyz"}},
    )
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


def test_active_provider_json_null(pm, tmp_path):
    _write(tmp_path / "config.json", {"active_provider": None})
    # get_active_provider_key returns None for json null (not "")
    assert pm.get_active_provider_key() is None


def test_active_provider_nonexistent(pm):
    pm.set_active_provider_key("ghost-provider")
    agent = pm.create_active_agent()
    assert agent.provider_key == "ghost-provider"
    assert agent.model == ""


# ---------------------------------------------------------------------------
# create_agent_for_provider
# ---------------------------------------------------------------------------

def test_create_agent_none_provider(pm):
    agent = pm.create_agent_for_provider(None)
    assert agent is not None
    assert agent.provider_key in (None, "")


def test_create_agent_unknown_provider(pm):
    agent = pm.create_agent_for_provider("unknown")
    assert agent is not None
    assert agent.model == ""


def test_create_agent_missing_api_key(pm):
    agent = pm.create_agent_for_provider("openai")
    assert agent.model == ""
    # api_key defaults to placeholder, should not be a real secret
    assert agent.api_key in ("", "sk-placeholder")


def test_create_agent_invalid_model(pm, tmp_path):
    _write(tmp_path / "config.json", {"provider_models": {"openai": "not-a-real-model"}})
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
    _write(
        tmp_path / "providers.json",
        {"custom": {"key": "custom", "name": "C", "base_url": "http://127.0.0.1:1/v1", "model": "m1"}},
    )
    _write(tmp_path / "config.json", {"api_keys": {"custom": "sk-abc"}})

    async def _run():
        # httpx fails to connect; ProviderManager catches Exception and
        # falls back to the configured model list.
        return await pm.fetch_models_for_provider("custom", force_refresh=True)

    models = asyncio.run(_run())
    assert models == ["m1"]


def test_fetch_models_no_base_url(pm, tmp_path):
    _write(
        tmp_path / "providers.json",
        {"nobaseurl": {"key": "nobaseurl", "name": "N", "model": "m1"}},
    )
    _write(tmp_path / "config.json", {"api_keys": {"nobaseurl": "sk-abc"}})

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
    assert pm.get_active_provider_key() is None


def test_save_secret_not_in_caplog(pm, caplog):
    import logging
    with caplog.at_level(logging.DEBUG):
        pm.set_provider_api_key("openai", "SUPER-SECRET-KEY-123")
        # force a fresh read through cache path
        pm.get_api_key("openai")
    assert "SUPER-SECRET-KEY-123" not in caplog.text


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
    _write(config, {"api_keys": {"openai": "one"}})
    assert pm.get_api_key("openai") == "one"
    # external modification with a later mtime
    time.sleep(0.01)
    _write(config, {"api_keys": {"openai": "two"}})
    assert pm.get_api_key("openai") == "two"


def test_cache_reload_after_providers_change(pm, tmp_path):
    pfile = tmp_path / "providers.json"
    _write(pfile, {"custom": {"key": "custom", "name": "One", "model": "m1"}})
    assert pm.load_providers()["custom"]["name"] == "One"
    time.sleep(0.01)
    _write(pfile, {"custom": {"key": "custom", "name": "Two", "model": "m2"}})
    assert pm.load_providers()["custom"]["name"] == "Two"
