import json
import os
import tempfile
import time

from core.domain.defaults.config import (
    DEFAULT_COMPACTION_THRESHOLD_RATIO,
    DEFAULT_MAX_CONCURRENT_SUBAGENTS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_STREAM_TIMEOUT,
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
    patch_settings,
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
        "model": "openai/gpt-4o",
        "theme": "nord",
        "sandbox_enabled": True,
        "llm": {
            "context_limit": 100000,
            "compaction_threshold_ratio": 0.8,
            "compaction_summarize_ratio": 0.85,
            "stream_timeout": 90.0,
            "chunk_timeout": 45.0,
            "max_retries": 5,
            "auto_title_max_len": 60,
            "auto_title_model": "anthropic/claude-3-5-haiku",
            "catalog_cache_ttl": 3600.0,
            "agent_md_max_chars": 15000,
        },
        "tools": {
            "shell_default_timeout": 180.0,
            "shell_max_cap": 900.0,
            "max_tool_output_chars": 12000,
            "max_tool_payload_bytes": 2097152,
            "max_snapshot_log_bytes": 3145728,
            "web_fetch_timeout": 33.0,
            "mcp_call_timeout": 150.0,
            "read_line_window": 500,
            "max_dir_entries": 40,
            "doc_conversion_timeout": 45.0,
            "image_max_dimension": 1024,
            "web_user_agent": "CustomAgent/1.0",
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
            "paste_line_threshold": 15,
            "chat_input_max_lines": 8,
            "autocomplete_max_files": 500,
            "shell_stream_buffer_bytes": 102400,
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
        assert settings.llm.context_limit == 100000
        assert settings.llm.compaction_threshold_ratio == 0.8
        assert settings.llm.compaction_summarize_ratio == 0.85
        assert settings.llm.stream_timeout == 90.0
        assert settings.llm.chunk_timeout == 45.0
        assert settings.llm.max_retries == 5
        assert settings.llm.auto_title_max_len == 60
        assert settings.llm.auto_title_model == "anthropic/claude-3-5-haiku"
        assert settings.llm.catalog_cache_ttl == 3600.0
        assert settings.llm.agent_md_max_chars == 15000
        assert settings.tools.shell_default_timeout == 180.0
        assert settings.tools.shell_max_cap == 900.0
        assert settings.tools.max_tool_output_chars == 12000
        assert settings.tools.max_tool_payload_bytes == 2097152
        assert settings.tools.max_snapshot_log_bytes == 3145728
        assert settings.tools.web_fetch_timeout == 33.0
        assert settings.tools.mcp_call_timeout == 150.0
        assert settings.tools.read_line_window == 500
        assert settings.tools.max_dir_entries == 40
        assert settings.tools.doc_conversion_timeout == 45.0
        assert settings.tools.image_max_dimension == 1024
        assert settings.tools.web_user_agent == "CustomAgent/1.0"
        assert settings.subagents.max_concurrent == 8
        assert settings.subagents.result_max_chars == 20000
        assert settings.subagents.worktree_timeout == 25.0
        assert settings.ui.max_prompt_history == 1000
        assert settings.ui.stream_flush_interval == 0.02
        assert settings.ui.chat_page_size == 100
        assert settings.ui.paste_line_threshold == 15
        assert settings.ui.chat_input_max_lines == 8
        assert settings.ui.autocomplete_max_files == 500
        assert settings.ui.shell_stream_buffer_bytes == 102400
        assert settings.storage.log_max_bytes == 10485760
        assert settings.storage.log_max_age_days == 14
        assert settings.storage.disk_cache_ttl == 5.0


def test_load_settings_handles_corrupt_or_null_values():
    raw_data = {
        "llm": {
            "compaction_threshold_ratio": None,
            "compaction_summarize_ratio": "bad",
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
        assert settings.llm.compaction_threshold_ratio == DEFAULT_COMPACTION_THRESHOLD_RATIO
        assert settings.llm.compaction_summarize_ratio == 0.90
        assert settings.llm.stream_timeout == DEFAULT_STREAM_TIMEOUT
        assert settings.llm.max_retries == DEFAULT_MAX_RETRIES
        assert settings.llm.retry_delay == 1.0
        assert settings.llm.chunk_timeout == 30.0
        assert settings.subagents.max_concurrent == DEFAULT_MAX_CONCURRENT_SUBAGENTS
        assert settings.tools.shell_default_timeout == 120.0
        assert settings.storage.log_max_age_days == 7


def test_save_and_reload_settings():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        settings = JohnstonSettings(
            model="anthropic/claude-3-7-sonnet",
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
        assert loaded.model == "anthropic/claude-3-7-sonnet"
        assert loaded.active_provider == "anthropic"
        assert loaded.theme == "monokai"
        assert loaded.sandbox_enabled is True
        assert loaded.llm.stream_timeout == 120.0
        assert loaded.tools.shell_default_timeout == 300.0
        assert loaded.subagents.max_concurrent == 7
        assert loaded.ui.chat_page_size == 75
        assert loaded.storage.log_max_age_days == 30

        # Clearing model and theme removes them from JSON
        settings.model = None
        settings.theme = None
        save_settings(settings, path)
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        assert "model" not in raw
        assert "active_provider" not in raw
        assert "theme" not in raw


def test_settings_env_var_overrides(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        monkeypatch.setenv("JOHNSTON_STREAM_TIMEOUT", "75.5")
        monkeypatch.setenv("JOHNSTON_CONTEXT_LIMIT", "90000")
        monkeypatch.setenv("JOHNSTON_COMPACTION_SUMMARIZE_RATIO", "0.65")
        monkeypatch.setenv("JOHNSTON_SHELL_TIMEOUT", "240")
        monkeypatch.setenv("JOHNSTON_MAX_TOOL_OUTPUT_CHARS", "16000")
        monkeypatch.setenv("JOHNSTON_MAX_TOOL_PAYLOAD_BYTES", "2097152")
        monkeypatch.setenv("JOHNSTON_MAX_SNAPSHOT_LOG_BYTES", "3145728")
        monkeypatch.setenv("JOHNSTON_WEB_FETCH_TIMEOUT", "33.0")
        monkeypatch.setenv("JOHNSTON_SANDBOX_ENABLED", "true")
        monkeypatch.setenv("JOHNSTON_MAX_RETRIES", "0")
        monkeypatch.setenv("JOHNSTON_MAX_CONCURRENT_SUBAGENTS", "15")
        monkeypatch.setenv("JOHNSTON_READ_LINE_WINDOW", "650")
        monkeypatch.setenv("JOHNSTON_MAX_DIR_ENTRIES", "35")
        monkeypatch.setenv("JOHNSTON_WEB_USER_AGENT", "CustomBot/2.0")
        monkeypatch.setenv("JOHNSTON_PASTE_LINE_THRESHOLD", "20")

        settings = load_settings(path)
        assert settings.llm.stream_timeout == 75.5
        assert settings.llm.context_limit == 90000
        assert settings.llm.compaction_summarize_ratio == 0.65
        assert settings.tools.shell_default_timeout == 240.0
        assert settings.tools.max_tool_output_chars == 16000
        assert settings.tools.max_tool_payload_bytes == 2097152
        assert settings.tools.max_snapshot_log_bytes == 3145728
        assert settings.tools.web_fetch_timeout == 33.0
        assert settings.tools.read_line_window == 650
        assert settings.tools.max_dir_entries == 35
        assert settings.tools.web_user_agent == "CustomBot/2.0"
        assert settings.ui.paste_line_threshold == 20
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


def test_session_store_disk_cache_ttl_respects_settings(monkeypatch):
    from core.infrastructure.storage.session_store import SessionStore

    settings = JohnstonSettings(storage=StorageSettings(disk_cache_ttl=9.0))
    monkeypatch.setattr("core.infrastructure.storage.session_store.get_settings", lambda: settings)
    store = SessionStore.__new__(SessionStore)
    assert store.DISK_CACHE_TTL == 9.0
    # per-instance override (existing tests assign this value) still wins
    store.DISK_CACHE_TTL = 1.5
    assert store.DISK_CACHE_TTL == 1.5


def test_patch_settings():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        save_settings(JohnstonSettings(theme="monokai", sandbox_enabled=False), path)

        patched = patch_settings(path, theme="dracula", sandbox_enabled=True)
        assert patched.theme == "dracula"
        assert patched.sandbox_enabled is True

        reloaded = get_settings(path)
        assert reloaded.theme == "dracula"
        assert reloaded.sandbox_enabled is True


def test_permissions_settings_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        custom_perms = {"mode": "auto", "default": "deny", "tools": {"shell": "ask"}, "patterns": {}}
        settings = JohnstonSettings(permissions=custom_perms)
        save_settings(settings, path)

        loaded = load_settings(path)
        assert loaded.permissions == custom_perms
