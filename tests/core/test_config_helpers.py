import json
import os
import tempfile

import pytest

from core.domain.defaults.config import MAX_CONCURRENT_SUBAGENTS
from core.infrastructure.config.config_helpers import (
    ensure_json_config,
    load_max_concurrent_subagents,
    load_sandbox_config,
    load_theme_config,
    save_max_concurrent_subagents,
    save_sandbox_config,
    save_theme_config,
)
from core.infrastructure.config.settings import (
    JohnstonSettings,
    LLMSettings,
    StorageSettings,
    SubagentsSettings,
    ToolsSettings,
    UISettings,
    load_settings,
    save_settings,
)


def test_ensure_json_config_creates_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "subdir", "config.json")
        ensure_json_config(path, {"default_key": "val"})
        assert os.path.exists(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data == {"default_key": "val"}


def test_sandbox_config_load_and_save():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        assert load_sandbox_config(path) is False
        save_sandbox_config(True, path)
        assert load_sandbox_config(path) is True
        save_sandbox_config(False, path)
        assert load_sandbox_config(path) is False


def test_theme_config_load_and_save():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        assert load_theme_config(path) is None
        save_theme_config("dracula", path)
        assert load_theme_config(path) == "dracula"


def test_max_concurrent_subagents_defaults():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        assert load_max_concurrent_subagents(path) == MAX_CONCURRENT_SUBAGENTS


def test_max_concurrent_subagents_config_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        save_max_concurrent_subagents(12, path)
        assert load_max_concurrent_subagents(path) == 12


def test_max_concurrent_subagents_env_override(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        save_max_concurrent_subagents(10, path)

        monkeypatch.setenv("JOHNSTON_MAX_CONCURRENT_SUBAGENTS", "20")
        assert load_max_concurrent_subagents(path) == 20

        monkeypatch.setenv("JOHNSTON_MAX_CONCURRENT_SUBAGENTS", "invalid")
        assert load_max_concurrent_subagents(path) == 10


def test_save_max_concurrent_subagents_invalid_value():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        with pytest.raises(ValueError):
            save_max_concurrent_subagents(0, path)
        with pytest.raises(ValueError):
            save_max_concurrent_subagents(-5, path)


def test_load_settings_full_sections():
    raw_data = {
        "active_provider": "openai",
        "theme": "nord",
        "sandbox_enabled": True,
        "llm": {
            "compaction_threshold_ratio": 0.8,
            "stream_timeout": 90.0,
            "chunk_timeout": 45.0,
            "max_retries": 5,
        },
        "tools": {
            "shell_default_timeout": 180,
            "shell_max_cap": 900,
            "max_tool_output_chars": 12000,
            "mcp_call_timeout": 150.0,
        },
        "subagents": {
            "max_concurrent": 8,
            "result_max_chars": 20000,
            "worktree_timeout": 25.0,
        },
        "ui": {
            "max_prompt_history": 1000,
            "stream_flush_interval": 0.02,
            "chat_page_size": 100,
        },
        "storage": {
            "log_max_bytes": 10485760,
            "log_max_age_days": 14,
            "disk_cache_ttl": 5.0,
        },
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(raw_data, f)

        settings = load_settings(path)
        assert settings.active_provider == "openai"
        assert settings.theme == "nord"
        assert settings.sandbox_enabled is True
        assert settings.llm.compaction_threshold_ratio == 0.8
        assert settings.llm.stream_timeout == 90.0
        assert settings.llm.chunk_timeout == 45.0
        assert settings.llm.max_retries == 5
        assert settings.tools.shell_default_timeout == 180
        assert settings.tools.shell_max_cap == 900
        assert settings.tools.max_tool_output_chars == 12000
        assert settings.tools.mcp_call_timeout == 150.0
        assert settings.subagents.max_concurrent == 8
        assert settings.subagents.result_max_chars == 20000
        assert settings.subagents.worktree_timeout == 25.0
        assert settings.ui.max_prompt_history == 1000
        assert settings.ui.stream_flush_interval == 0.02
        assert settings.ui.chat_page_size == 100
        assert settings.storage.log_max_bytes == 10485760
        assert settings.storage.log_max_age_days == 14
        assert settings.storage.disk_cache_ttl == 5.0


def test_save_and_reload_settings():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        settings = JohnstonSettings(
            theme="monokai",
            sandbox_enabled=True,
            llm=LLMSettings(stream_timeout=120.0),
            tools=ToolsSettings(shell_default_timeout=300),
            subagents=SubagentsSettings(max_concurrent=7),
            ui=UISettings(chat_page_size=75),
            storage=StorageSettings(log_max_age_days=30),
        )
        save_settings(settings, path)

        loaded = load_settings(path)
        assert loaded.theme == "monokai"
        assert loaded.sandbox_enabled is True
        assert loaded.llm.stream_timeout == 120.0
        assert loaded.tools.shell_default_timeout == 300
        assert loaded.subagents.max_concurrent == 7
        assert loaded.ui.chat_page_size == 75
        assert loaded.storage.log_max_age_days == 30


def test_settings_env_var_overrides(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        monkeypatch.setenv("JOHNSTON_STREAM_TIMEOUT", "75.5")
        monkeypatch.setenv("JOHNSTON_SHELL_TIMEOUT", "240")
        monkeypatch.setenv("JOHNSTON_MAX_TOOL_OUTPUT_CHARS", "16000")
        monkeypatch.setenv("JOHNSTON_SANDBOX_ENABLED", "true")

        settings = load_settings(path)
        assert settings.llm.stream_timeout == 75.5
        assert settings.tools.shell_default_timeout == 240
        assert settings.tools.max_tool_output_chars == 16000
        assert settings.sandbox_enabled is True
