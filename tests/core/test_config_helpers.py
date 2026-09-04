import json
import logging
import os
import tempfile
import time

from core.domain.defaults.config import (
    DEFAULT_CHAT_INPUT_MAX_LINES,
    DEFAULT_COMPACTION_THRESHOLD_RATIO,
    DEFAULT_DNS_CACHE_MAX,
    DEFAULT_DNS_CACHE_TTL,
    DEFAULT_DOC_CACHE_TTL,
    DEFAULT_IMAGE_DIMENSION_HIGH,
    DEFAULT_IMAGE_DIMENSION_LOW,
    DEFAULT_IMAGE_MAX_DIMENSION,
    DEFAULT_IMAGE_PNG_KEEP_BYTES,
    DEFAULT_LINE_COUNT_CACHE_MAX,
    DEFAULT_LOG_MAX_AGE_DAYS,
    DEFAULT_LOG_MAX_BYTES,
    DEFAULT_MAX_CONCURRENT_SUBAGENTS,
    DEFAULT_MAX_DOC_CACHE,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MCP_MISS_MAX,
    DEFAULT_MCP_MISS_TTL,
    DEFAULT_SHELL_OUTPUT_CHARS,
    DEFAULT_SHELL_STREAM_BUFFER_BYTES,
    DEFAULT_STREAM_TIMEOUT,
    DEFAULT_SUBAGENT_RESULT_MAX_CHARS,
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
    SandboxSettings,
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
        "sandbox": {"enabled": True},
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
            "thinking_efforts": {"openai": {"gpt-4o": "high"}},
        },
        "tools": {
            "shell_default_timeout": 180.0,
            "shell_max_cap": 900.0,
            "max_shell_output_chars": 5000,
            "max_tool_output_chars": 12000,
            "max_tool_payload_bytes": 2097152,
            "max_snapshot_log_bytes": 3145728,
            "web_fetch_timeout": 33.0,
            "mcp_call_timeout": 150.0,
            "read_line_window": 500,
            "max_dir_entries": 40,
            "doc_conversion_timeout": 45.0,
            "max_image_dimension": 1024,
            "shell_stream_buffer_bytes": 102400,
            "web_user_agent": "CustomAgent/1.0",
        },
        "subagents": {
            "max_concurrent": 8,
            "max_result_chars": 20000,
            "worktree_timeout": 25.0,
        },
        "ui": {
            "max_prompt_history": 1000,
            "stream_flush_interval": 0.02,
            "chat_page_size": 100,
            "paste_line_threshold": 15,
            "max_chat_input_lines": 8,
            "autocomplete_max_files": 500,
        },
        "storage": {
            "max_log_bytes": 10485760,
            "max_log_age_days": 14,
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
        assert settings.sandbox.enabled is True
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
        assert settings.llm.thinking_efforts == {"openai": {"gpt-4o": "high"}}
        assert settings.tools.shell_default_timeout == 180.0
        assert settings.tools.shell_max_cap == 900.0
        assert settings.tools.max_shell_output_chars == 5000
        assert settings.tools.max_tool_output_chars == 12000
        assert settings.tools.max_tool_payload_bytes == 2097152
        assert settings.tools.max_snapshot_log_bytes == 3145728
        assert settings.tools.web_fetch_timeout == 33.0
        assert settings.tools.mcp_call_timeout == 150.0
        assert settings.tools.read_line_window == 500
        assert settings.tools.max_dir_entries == 40
        assert settings.tools.doc_conversion_timeout == 45.0
        assert settings.tools.max_image_dimension == 1024
        assert settings.tools.shell_stream_buffer_bytes == 102400
        assert settings.tools.web_user_agent == "CustomAgent/1.0"
        assert settings.subagents.max_concurrent == 8
        assert settings.subagents.max_result_chars == 20000
        assert settings.subagents.worktree_timeout == 25.0
        assert settings.ui.max_prompt_history == 1000
        assert settings.ui.stream_flush_interval == 0.02
        assert settings.ui.chat_page_size == 100
        assert settings.ui.paste_line_threshold == 15
        assert settings.ui.max_chat_input_lines == 8
        assert settings.ui.autocomplete_max_files == 500
        assert settings.storage.max_log_bytes == 10485760
        assert settings.storage.max_log_age_days == 14
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
            "max_log_age_days": False,  # boolean rejected as numeric
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
        assert settings.storage.max_log_age_days == 7


def test_legacy_key_aliases_are_ignored():
    """Backward-compat shims were removed; old keys must not override canonical ones."""
    raw_data = {
        "model": "openai/gpt-4o",
        "provider_thinking_efforts": {"openai": {"gpt-4o": "high"}},  # legacy top-level
        "max_concurrent_subagents": 9,                                  # legacy top-level
        "sandbox_enabled": True,                                        # legacy top-level
        "tools": {
            "shell_output_chars": 999,            # legacy alias
            "image_max_dimension": 999,           # legacy alias
            "shell_stream_buffer_bytes": 999,     # valid canonical key is honored below
            "max_shell_output_chars": 4000,
            "max_image_dimension": 1024,
        },
        "ui": {
            "chat_input_max_lines": 99,           # legacy alias
            "max_chat_input_lines": 8,
        },
        "subagents": {"result_max_chars": 999},   # legacy alias
        "storage": {"log_max_bytes": 999, "log_max_age_days": 99},  # legacy aliases
    }
    settings = JohnstonSettings.from_dict(raw_data)
    # Legacy top-level keys do not override canonical sections.
    assert settings.llm.thinking_efforts == {}
    assert settings.subagents.max_concurrent == DEFAULT_MAX_CONCURRENT_SUBAGENTS
    assert settings.sandbox.enabled is False
    # Legacy aliases do not override canonical keys (canonical present) nor defaults.
    assert settings.tools.max_shell_output_chars == 4000
    assert settings.tools.max_image_dimension == 1024
    assert settings.ui.max_chat_input_lines == 8
    assert settings.subagents.max_result_chars == DEFAULT_SUBAGENT_RESULT_MAX_CHARS
    assert settings.storage.max_log_bytes == DEFAULT_LOG_MAX_BYTES
    assert settings.storage.max_log_age_days == DEFAULT_LOG_MAX_AGE_DAYS


def test_tools_new_fields_parsed():
    """New tool/cache/image knobs are read from the config section."""
    raw_data = {
        "tools": {
            "image_dimension_low": 256,
            "image_dimension_high": 1024,
            "image_png_keep_bytes": 2097152,
            "max_doc_cache": 5,
            "doc_cache_ttl": 60.0,
            "line_count_cache_max": 20,
            "dns_cache_ttl": 30.0,
            "dns_cache_max": 64,
            "mcp_miss_ttl": 10.0,
            "mcp_miss_max": 32,
        },
    }
    settings = JohnstonSettings.from_dict(raw_data)
    tools = settings.tools
    assert tools.image_dimension_low == 256
    assert tools.image_dimension_high == 1024
    assert tools.image_png_keep_bytes == 2097152
    assert tools.max_doc_cache == 5
    assert tools.doc_cache_ttl == 60.0
    assert tools.line_count_cache_max == 20
    assert tools.dns_cache_ttl == 30.0
    assert tools.dns_cache_max == 64
    assert tools.mcp_miss_ttl == 10.0
    assert tools.mcp_miss_max == 32


def test_tools_new_fields_defaults():
    """New tool/cache/image knobs default to their documented constants."""
    tools = ToolsSettings()
    assert tools.image_dimension_low == DEFAULT_IMAGE_DIMENSION_LOW
    assert tools.image_dimension_high == DEFAULT_IMAGE_DIMENSION_HIGH
    assert tools.image_png_keep_bytes == DEFAULT_IMAGE_PNG_KEEP_BYTES
    assert tools.max_doc_cache == DEFAULT_MAX_DOC_CACHE
    assert tools.doc_cache_ttl == DEFAULT_DOC_CACHE_TTL
    assert tools.line_count_cache_max == DEFAULT_LINE_COUNT_CACHE_MAX
    assert tools.dns_cache_ttl == DEFAULT_DNS_CACHE_TTL
    assert tools.dns_cache_max == DEFAULT_DNS_CACHE_MAX
    assert tools.mcp_miss_ttl == DEFAULT_MCP_MISS_TTL
    assert tools.mcp_miss_max == DEFAULT_MCP_MISS_MAX


def test_tools_new_fields_env_overrides(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        monkeypatch.setenv("JOHNSTON_IMAGE_DIMENSION_LOW", "300")
        monkeypatch.setenv("JOHNSTON_DOC_CACHE_TTL", "45.0")
        monkeypatch.setenv("JOHNSTON_MCP_MISS_MAX", "16")
        settings = load_settings(path)
        assert settings.tools.image_dimension_low == 300
        assert settings.tools.doc_cache_ttl == 45.0
        assert settings.tools.mcp_miss_max == 16


def test_catalog_cache_ttl_wired_in_refresh(monkeypatch):
    """models_catalog.refresh() resolves catalog_cache_ttl from settings."""
    from core.models_catalog import ModelsCatalog

    catalog = ModelsCatalog.__new__(ModelsCatalog)
    # _updated_at ~ now so the freshness window (catalog_cache_ttl=999) is fresh
    # and refresh() returns the cached limits without hitting the network.
    catalog._limits = {"a": 1}
    catalog._updated_at = time.time()
    # make the freshness window large so the epoch delta is still < max_age
    mock_settings = JohnstonSettings(llm=LLMSettings(catalog_cache_ttl=1_000_000_000_000.0))
    monkeypatch.setattr("core.infrastructure.config.settings.get_settings", lambda: mock_settings)
    import asyncio

    result = asyncio.run(catalog.refresh(force=False))
    assert result == {"a": 1}


def test_load_settings_legacy_aliases_fall_back_to_defaults():
    """When only a legacy alias is present, the canonical default is used."""
    raw_data = {
        "tools": {
            "shell_output_chars": 999,
            "image_max_dimension": 999,
        },
        "ui": {"shell_stream_buffer_bytes": 999},  # legacy cross-section
        "subagents": {"result_max_chars": 999},
        "storage": {"log_max_bytes": 999, "log_max_age_days": 99},
    }
    settings = JohnstonSettings.from_dict(raw_data)
    assert settings.tools.max_shell_output_chars == DEFAULT_SHELL_OUTPUT_CHARS
    assert settings.tools.max_image_dimension == DEFAULT_IMAGE_MAX_DIMENSION
    assert settings.tools.shell_stream_buffer_bytes == DEFAULT_SHELL_STREAM_BUFFER_BYTES
    assert settings.subagents.max_result_chars == DEFAULT_SUBAGENT_RESULT_MAX_CHARS
    assert settings.storage.max_log_bytes == DEFAULT_LOG_MAX_BYTES
    assert settings.storage.max_log_age_days == DEFAULT_LOG_MAX_AGE_DAYS
    assert settings.ui.max_chat_input_lines == DEFAULT_CHAT_INPUT_MAX_LINES


def test_load_settings_missing_file_defaults_silent():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        settings = load_settings(path)
        assert settings.llm.stream_timeout == DEFAULT_STREAM_TIMEOUT
        assert settings.model is None


def test_load_settings_invalid_json_warns_and_defaults(caplog):
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        with caplog.at_level(logging.WARNING, logger="core.infrastructure.config.settings"):
            settings = load_settings(path)
        assert settings.model is None
        assert any("unreadable" in r.message for r in caplog.records)


def test_save_and_reload_settings():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        settings = JohnstonSettings(
            model="anthropic/claude-3-7-sonnet",
            theme="monokai",
            sandbox=SandboxSettings(enabled=True),
            llm=LLMSettings(stream_timeout=120.0),
            tools=ToolsSettings(shell_default_timeout=300.0),
            subagents=SubagentsSettings(max_concurrent=7),
            ui=UISettings(chat_page_size=75),
            storage=StorageSettings(max_log_age_days=30),
        )
        save_settings(settings, path)

        loaded = load_settings(path)
        assert loaded.model == "anthropic/claude-3-7-sonnet"
        assert loaded.active_provider == "anthropic"
        assert loaded.theme == "monokai"
        assert loaded.sandbox.enabled is True
        assert loaded.llm.stream_timeout == 120.0
        assert loaded.tools.shell_default_timeout == 300.0
        assert loaded.subagents.max_concurrent == 7
        assert loaded.ui.chat_page_size == 75
        assert loaded.storage.max_log_age_days == 30

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
        assert settings.sandbox.enabled is True
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
        assert get_settings(path).sandbox.enabled is True

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
        save_settings(JohnstonSettings(theme="monokai", sandbox=SandboxSettings(enabled=False)), path)

        patched = patch_settings(path, theme="dracula", sandbox=SandboxSettings(enabled=True))
        assert patched.theme == "dracula"
        assert patched.sandbox.enabled is True

        reloaded = get_settings(path)
        assert reloaded.theme == "dracula"
        assert reloaded.sandbox.enabled is True


def test_permissions_settings_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        custom_perms = {"mode": "auto", "default": "deny", "tools": {"shell": "ask"}, "patterns": {}}
        settings = JohnstonSettings(permissions=custom_perms)
        save_settings(settings, path)

        loaded = load_settings(path)
        assert loaded.permissions == custom_perms


def test_auto_compact_token_limit_settings(monkeypatch):
    from core.infrastructure.config.settings import LLMSettings, SubagentsSettings

    # 1. Defaults
    llm = LLMSettings()
    assert llm.auto_compact_token_limit is None
    sub = SubagentsSettings()
    assert sub.auto_compact_token_limit == 200_000

    # 2. Dict parsing
    llm_dict = LLMSettings.from_dict({"llm": {"auto_compact_token_limit": 80_000}})
    assert llm_dict.auto_compact_token_limit == 80_000

    sub_dict = SubagentsSettings.from_dict({"subagents": {"auto_compact_token_limit": 50_000}})
    assert sub_dict.auto_compact_token_limit == 50_000

    # Explicit None for subagents disables it
    sub_none = SubagentsSettings.from_dict({"subagents": {"auto_compact_token_limit": None}})
    assert sub_none.auto_compact_token_limit is None

    # Min limit clamping (< 1000 ignored / clamped)
    llm_invalid = LLMSettings.from_dict({"llm": {"auto_compact_token_limit": 500}})
    assert llm_invalid.auto_compact_token_limit is None

    sub_invalid = SubagentsSettings.from_dict({"subagents": {"auto_compact_token_limit": 500}})
    assert sub_invalid.auto_compact_token_limit == 200_000

    # 3. Env var overrides
    monkeypatch.setenv("JOHNSTON_AUTO_COMPACT_TOKEN_LIMIT", "75000")
    monkeypatch.setenv("JOHNSTON_SUBAGENT_AUTO_COMPACT_TOKEN_LIMIT", "60000")
    llm_env = LLMSettings.from_dict({})
    assert llm_env.auto_compact_token_limit == 75_000
    sub_env = SubagentsSettings.from_dict({})
    assert sub_env.auto_compact_token_limit == 60_000
