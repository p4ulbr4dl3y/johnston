import json
import os
import tempfile
import time

from core.domain.defaults.config import (
    CONTEXT_COMPACTION_THRESHOLD_RATIO,
    DEFAULT_MAX_RETRIES,
    DEFAULT_STREAM_TIMEOUT,
    MAX_CONCURRENT_SUBAGENTS,
)
from core.infrastructure.config.config_helpers import (
    ensure_json_config,
    load_sandbox_config,
    load_theme_config,
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
    get_settings,
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
            "shell_default_timeout": 180.0,
            "shell_max_cap": 900.0,
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
        assert settings.tools.shell_default_timeout == 180.0
        assert settings.tools.shell_max_cap == 900.0
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


def test_load_settings_handles_corrupt_or_null_values():
    raw_data = {
        "llm": {
            "compaction_threshold_ratio": None,
            "stream_timeout": "not_a_number",
            "max_retries": True,  # boolean rejected as numeric
            "retry_delay": "nan",
            "chunk_timeout": "inf",
        },
        "tools": "not_a_dict",
        "subagents": {
            "max_concurrent": -10,
        },
        "storage": {
            "log_max_age_days": False,  # boolean rejected as numeric
        },
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(raw_data, f)

        settings = load_settings(path)
        assert settings.llm.compaction_threshold_ratio == CONTEXT_COMPACTION_THRESHOLD_RATIO
        assert settings.llm.stream_timeout == DEFAULT_STREAM_TIMEOUT
        assert settings.llm.max_retries == DEFAULT_MAX_RETRIES
        assert settings.llm.retry_delay == 1.0
        assert settings.llm.chunk_timeout == 30.0
        assert settings.subagents.max_concurrent == MAX_CONCURRENT_SUBAGENTS
        assert settings.tools.shell_default_timeout == 120.0
        assert settings.storage.log_max_age_days == 7


def test_save_and_reload_settings():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        settings = JohnstonSettings(
            active_provider="anthropic",
            theme="monokai",
            sandbox_enabled=True,
            llm=LLMSettings(stream_timeout=120.0),
            tools=ToolsSettings(shell_default_timeout=300.0),
            subagents=SubagentsSettings(max_concurrent=7),
            ui=UISettings(chat_page_size=75),
            storage=StorageSettings(log_max_age_days=30),
        )
        save_settings(settings, path)

        loaded = load_settings(path)
        assert loaded.active_provider == "anthropic"
        assert loaded.theme == "monokai"
        assert loaded.sandbox_enabled is True
        assert loaded.llm.stream_timeout == 120.0
        assert loaded.tools.shell_default_timeout == 300.0
        assert loaded.subagents.max_concurrent == 7
        assert loaded.ui.chat_page_size == 75
        assert loaded.storage.log_max_age_days == 30

        # Clearing active_provider removes it from JSON
        settings.active_provider = None
        settings.theme = None
        save_settings(settings, path)
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        assert "active_provider" not in raw
        assert "theme" not in raw


def test_settings_env_var_overrides(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        monkeypatch.setenv("JOHNSTON_STREAM_TIMEOUT", "75.5")
        monkeypatch.setenv("JOHNSTON_SHELL_TIMEOUT", "240")
        monkeypatch.setenv("JOHNSTON_MAX_TOOL_OUTPUT_CHARS", "16000")
        monkeypatch.setenv("JOHNSTON_SANDBOX_ENABLED", "true")
        monkeypatch.setenv("JOHNSTON_MAX_RETRIES", "0")
        monkeypatch.setenv("JOHNSTON_MAX_CONCURRENT_SUBAGENTS", "15")

        settings = load_settings(path)
        assert settings.llm.stream_timeout == 75.5
        assert settings.tools.shell_default_timeout == 240.0
        assert settings.tools.max_tool_output_chars == 16000
        assert settings.sandbox_enabled is True
        assert settings.llm.max_retries == 0
        assert settings.subagents.max_concurrent == 15


def test_get_settings_caching_and_invalidation():
    with tempfile.TemporaryDirectory() as tmpdir:
        path1 = os.path.join(tmpdir, "config1.json")
        path2 = os.path.join(tmpdir, "config2.json")

        save_settings(JohnstonSettings(theme="theme1"), path1)
        save_settings(JohnstonSettings(theme="theme2"), path2)

        s1 = get_settings(path1)
        s2 = get_settings(path2)
        assert s1.theme == "theme1"
        assert s2.theme == "theme2"

        # Cache returns same instance
        assert get_settings(path1) is s1

        # File modification invalidates cache
        time.sleep(0.01)
        save_settings(JohnstonSettings(theme="theme1_updated"), path1)
        s1_updated = get_settings(path1)
        assert s1_updated.theme == "theme1_updated"


def test_config_helpers_custom_path_cache_reload():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config_custom.json")
        save_sandbox_config(True, config_file=path)
        assert get_settings(path).sandbox_enabled is True

        save_theme_config("nord", config_file=path)
        assert get_settings(path).theme == "nord"
