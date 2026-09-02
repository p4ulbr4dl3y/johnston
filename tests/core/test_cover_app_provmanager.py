"""Coverage-focused unit tests for core/provider_manager.py.

Covers error/edge paths in ensure_config_dir, _load_json_providers, the
load_providers memo overflow guard, set_provider_model failures,
recreate_active_agent and the fetch_models cache/refresh branches.
HTTP is fully mocked; no real network calls.
"""

import asyncio
import json
import os
import time
import unittest.mock
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import core.provider_manager as pm_mod
from core.infrastructure.secrets import save_secret
from core.provider_manager import ProviderManager


@pytest.fixture
def pm(tmp_path, monkeypatch):
    monkeypatch.setattr(pm_mod, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(pm_mod, "CONFIG_FILE", os.path.join(str(tmp_path), "config.json"))
    monkeypatch.setattr(pm_mod, "PROVIDERS_JSON_FILE", os.path.join(str(tmp_path), "providers.json"))
    monkeypatch.setattr(pm_mod, "CACHE_DIR", os.path.join(str(tmp_path), "cache"))
    from core.models_catalog import catalog

    catalog._client = None
    manager = ProviderManager()
    return manager, tmp_path


def _write_providers(tmp_path, data):
    path = os.path.join(str(tmp_path), "providers.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def _set_api_key(pm, key, value="sekret"):
    save_secret(key, value)


def test_ensure_config_dir_save_failure_is_swallowed(pm):
    manager, tmp_path = pm
    os.remove(os.path.join(str(tmp_path), "providers.json"))
    with patch.object(manager, "_save_providers_json", side_effect=OSError("disk full")):
        manager.ensure_config_dir()  # must not raise


def test_load_json_providers_merge_error_swallowed(pm, monkeypatch):
    manager, _ = pm

    class _Noisy(dict):
        def get(self, key, default=None):
            raise RuntimeError("boom")

    monkeypatch.setattr(pm_mod, "DEFAULT_JSON_PROVIDERS", _Noisy({"openai": {}}))
    monkeypatch.setattr(manager, "_cached_json", lambda path, default: {"openai": {"name": "x"}})
    providers = manager._load_json_providers()
    assert isinstance(providers, dict)


def test_load_providers_memo_overflow_guard(pm):
    manager, _ = pm
    manager._providers_memo = {f"key{i}": {} for i in range(16)}
    # FIFO eviction: with the memo at/over 16 keys the oldest entry is dropped
    # before caching the new one, so the that cache never exceeds 16 entries.
    prev_first = next(iter(manager._providers_memo))
    result = manager.load_providers()
    assert prev_first not in manager._providers_memo
    assert result is not None
    fresh_cached = [k for k in manager._providers_memo][-1]
    assert prev_first != fresh_cached


def test_set_provider_model_save_failure_logged(pm):
    manager, tmp_path = pm
    _write_providers(tmp_path, {"pv": {"key": "pv", "name": "PV", "base_url": "", "models": []}})
    with patch.object(manager, "_save_providers_json", side_effect=OSError("nope")):
        manager.set_provider_model("pv", "m1")  # must not raise


def test_recreate_active_agent_preserves_state(pm):
    from widgets.app.role_service import reconcile_active_agent

    manager, tmp_path = pm
    manager.set_active_provider_key("openai")
    # Test core manager recreate (pure domain)
    agent = manager.recreate_active_agent(provider_key="openai", history=[{"role": "user", "content": "x"}], role="custom")
    assert agent is not None
    assert agent.history == [{"role": "user", "content": "x"}]
    assert agent.role == "custom"

    # Test UI state reconciliation
    app = MagicMock()
    app.pm = manager
    app.agent = MagicMock()
    app.agent.history = [{"role": "user", "content": "old"}]
    app.agent.role = "custom"
    del app.role
    reconciled = reconcile_active_agent(app, provider_key="openai", history=[{"role": "user", "content": "x"}])
    assert reconciled is not None
    assert reconciled.history == [{"role": "user", "content": "x"}]
    assert reconciled.role == "custom"
    assert app.agent is reconciled
    assert app.role == "custom"
    app.refresh_status_footer.assert_called_once()


def test_recreate_active_agent_no_provider_key(pm):
    manager, tmp_path = pm
    manager.set_active_provider_key("openai")
    agent = manager.recreate_active_agent(role="worker")
    assert agent is not None
    assert agent.role == "worker"


@pytest.mark.asyncio
async def test_fetch_models_unknown_provider_returns_empty(pm):
    manager, _ = pm
    assert await manager.fetch_models_for_provider("doesnotexist") == []


@pytest.mark.asyncio
async def test_fetch_models_no_key_removes_stale_cache(pm):
    manager, tmp_path = pm
    _write_providers(tmp_path, {"nokey": {"key": "nokey", "name": "NoKey", "base_url": "http://x", "models": []}})
    cache_dir = os.path.join(str(tmp_path), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, "models_nokey.json")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"models": ["old"]}, f)
    result = await manager.fetch_models_for_provider("nokey")
    assert result == []
    assert not os.path.exists(cache_path)


@pytest.mark.asyncio
async def test_fetch_models_no_key_remove_failure_swallowed(pm):
    manager, tmp_path = pm
    _write_providers(tmp_path, {"nokey": {"key": "nokey", "name": "NoKey", "base_url": "http://x", "models": []}})
    cache_dir = os.path.join(str(tmp_path), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, "models_nokey.json")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"models": ["old"]}, f)
    with patch.object(os, "remove", side_effect=OSError("busy")):
        result = await manager.fetch_models_for_provider("nokey")
    assert result == []


@pytest.mark.asyncio
async def test_fetch_models_returns_fresh_cache(pm):
    manager, tmp_path = pm
    _write_providers(tmp_path, {"apik": {"key": "apik", "name": "APIK", "base_url": "http://x", "models": []}})
    _set_api_key(manager, "apik")
    cache_dir = os.path.join(str(tmp_path), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, "models_apik.json")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"updated_at": time.time(), "models": ["m1", "m2"]}, f)
    result = await manager.fetch_models_for_provider("apik")
    assert result == ["m1", "m2"]


@pytest.mark.asyncio
async def test_fetch_models_schedules_background_refresh_with_fallback(pm):
    manager, tmp_path = pm
    _write_providers(
        tmp_path,
        {"apikf": {"key": "apikf", "name": "APIKF", "base_url": "http://x", "model": "fallback-model", "models": []}},
    )
    _set_api_key(manager, "apikf")
    # Background task hits forced path: mock httpx so no real network.
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": []}
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__.return_value = mock_client
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await manager.fetch_models_for_provider("apikf")
    await asyncio.sleep(0.1)  # let the background task settle
    assert result == ["fallback-model"]


@pytest.mark.asyncio
async def test_fetch_models_no_running_loop_for_background(pm):
    manager, tmp_path = pm
    _write_providers(tmp_path, {"apikg": {"key": "apikg", "name": "APIKG", "base_url": "http://x", "model": "fb", "models": []}})
    _set_api_key(manager, "apikg")
    with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
        result = await manager.fetch_models_for_provider("apikg")
    assert result == ["fb"]


@pytest.mark.asyncio
async def test_fetch_models_forced_refresh_http_flow(pm):
    manager, tmp_path = pm
    _write_providers(tmp_path, {"apik": {"key": "apik", "name": "APIK", "base_url": "http://x", "models": []}})
    _set_api_key(manager, "apik")
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [{"id": "model-a", "name": "Model A", "context_length": 100000}, {"id": "model-b"}]
    }
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__.return_value = mock_client
    with patch("core.provider_manager.catalog.save_cache", unittest.mock.MagicMock(side_effect=OSError("save fail"))):
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await manager.fetch_models_for_provider("apik", force_refresh=True)
    assert result == ["model-a", "model-b"]


@pytest.mark.asyncio
async def test_fetch_models_forced_no_models_falls_back_and_keeps_fallback(pm):
    manager, tmp_path = pm
    _write_providers(tmp_path, {"apik2": {"key": "apik2", "name": "APIK2", "base_url": "http://x", "models": []}})
    _set_api_key(manager, "apik2")
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": []}
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__.return_value = mock_client
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await manager.fetch_models_for_provider("apik2", force_refresh=True)
    assert result == []
    # cache still written (empty list persisted)
    cache_path = os.path.join(str(tmp_path), "cache", "models_apik2.json")
    assert os.path.exists(cache_path)


@pytest.mark.asyncio
async def test_fetch_models_recursion_when_no_cache_no_fallback(pm):
    manager, tmp_path = pm
    _write_providers(tmp_path, {"apik3": {"key": "apik3", "name": "APIK3", "base_url": "http://x", "models": []}})
    _set_api_key(manager, "apik3")
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"id": "rec-model"}]}
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__.return_value = mock_client
    with patch("httpx.AsyncClient", return_value=mock_client):
        # Non-forced returns empty list with zero network requests
        res_fast = await manager.fetch_models_for_provider("apik3", force_refresh=False)
        assert res_fast == []
        mock_client.get.assert_not_called()

        # Forced refresh makes HTTP request
        result = await manager.fetch_models_for_provider("apik3", force_refresh=True)
    assert result == ["rec-model"]


@pytest.mark.asyncio
async def test_fetch_models_forced_direct_http_failure_last_err(pm):
    manager, tmp_path = pm
    _write_providers(tmp_path, {"apik4": {"key": "apik4", "name": "APIK4", "base_url": "http://x", "models": []}})
    _set_api_key(manager, "apik4")
    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=RuntimeError("conn refused"))
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__ = AsyncMock(return_value=False)
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await manager.fetch_models_for_provider("apik4")
    assert result == []


@pytest.mark.asyncio
async def test_fetch_models_cache_write_error_swallowed(pm):
    manager, tmp_path = pm
    _write_providers(tmp_path, {"apik5": {"key": "apik5", "name": "APIK5", "base_url": "http://x", "models": []}})
    _set_api_key(manager, "apik5")
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"id": "m1"}]}
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__.return_value = mock_client
    with patch("core.provider_manager.atomic_write_json", side_effect=OSError("write io")):
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await manager.fetch_models_for_provider("apik5", force_refresh=True)
    assert result == ["m1"]


@pytest.mark.asyncio
async def test_fetch_models_grouped_connected_only(pm):
    manager, _ = pm
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"id": "m1"}]}
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__.return_value = mock_client
    with patch.object(manager, "is_provider_connected", return_value=True):
        with patch("httpx.AsyncClient", return_value=mock_client):
            grouped = await manager.fetch_models_grouped(force_refresh=True, connected_only=True)
    assert "openai" in grouped


@pytest.mark.asyncio
async def test_fetch_models_grouped_connected_only_empty(pm):
    manager, _ = pm
    with patch.object(manager, "is_provider_connected", return_value=False):
        grouped = await manager.fetch_models_grouped(force_refresh=True, connected_only=True)
    assert grouped == {}  # no connected provider -> early return


@pytest.mark.asyncio
async def test_fetch_models_requires_key_false_with_custom_headers(pm):
    manager, tmp_path = pm
    _write_providers(
        tmp_path,
        {
            "opencode": {
                "key": "opencode",
                "name": "OpenCode Zen",
                "base_url": "https://opencode.ai/zen/v1",
                "requires_key": False,
                "headers": {"User-Agent": "opencode-cli"},
                "model": "hy3-free",
            }
        },
    )
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"id": "claude-sonnet-4"}, {"id": "hy3-free"}]}
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__.return_value = mock_client

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await manager.fetch_models_for_provider("opencode", force_refresh=True)

    assert result == ["claude-sonnet-4", "hy3-free"]
    mock_client.get.assert_called_once()
    called_url, called_kwargs = mock_client.get.call_args
    assert called_url[0] == "https://opencode.ai/zen/v1/models"
    assert called_kwargs["headers"].get("User-Agent") == "opencode-cli"


@pytest.mark.asyncio
async def test_fetch_models_preserves_stale_cache_on_network_error(pm):
    manager, tmp_path = pm
    _write_providers(
        tmp_path,
        {
            "opencode": {
                "key": "opencode",
                "name": "OpenCode Zen",
                "base_url": "https://opencode.ai/zen/v1",
                "requires_key": False,
                "model": "fallback-model",
            }
        },
    )
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "models_opencode.json"
    cache_file.write_text(json.dumps({"updated_at": 1000.0, "models": ["cached-model-1", "cached-model-2"]}))

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=Exception("network timeout"))
    mock_client.__aenter__.return_value = mock_client

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await manager.fetch_models_for_provider("opencode", force_refresh=True)

    # Stale cache must be preserved and returned instead of falling back to 1 model
    assert result == ["cached-model-1", "cached-model-2"]
    saved_data = json.loads(cache_file.read_text())
    assert saved_data["models"] == ["cached-model-1", "cached-model-2"]


