"""Central application settings with environment variable and JSON config support."""
from __future__ import annotations

import logging
import math
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple

from core.domain.defaults.config import (
    DEFAULT_AGENT_MD_MAX_CHARS,
    DEFAULT_AUTO_TITLE,
    DEFAULT_AUTO_TITLE_MAX_LEN,
    DEFAULT_AUTO_TITLE_MODEL,
    DEFAULT_AUTO_TITLE_TIMEOUT,
    DEFAULT_AUTOCOMPLETE_MAX_FILES,
    DEFAULT_CATALOG_CACHE_TTL,
    DEFAULT_CB_COOLDOWN_SECONDS,
    DEFAULT_CB_FAILURE_THRESHOLD,
    DEFAULT_CHAT_INPUT_MAX_LINES,
    DEFAULT_CHAT_PAGE_SIZE,
    DEFAULT_CHUNK_TIMEOUT,
    DEFAULT_COMPACTION_SUMMARIZE_RATIO,
    DEFAULT_COMPACTION_THRESHOLD_RATIO,
    DEFAULT_COMPACTION_USER_BUDGET,
    DEFAULT_CONTEXT_LIMIT,
    DEFAULT_DISK_CACHE_TTL,
    DEFAULT_DOC_CONVERSION_TIMEOUT,
    DEFAULT_IMAGE_MAX_DIMENSION,
    DEFAULT_LOG_MAX_AGE_DAYS,
    DEFAULT_LOG_MAX_BYTES,
    DEFAULT_MAX_CONCURRENT_SUBAGENTS,
    DEFAULT_MAX_DIR_ENTRIES,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_RETRY_DELAY,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MCP_CALL_TIMEOUT,
    DEFAULT_MCP_INIT_TIMEOUT,
    DEFAULT_PASTE_LINE_THRESHOLD,
    DEFAULT_PERMISSIONS,
    DEFAULT_PROMPT_HISTORY,
    DEFAULT_READ_LINE_WINDOW,
    DEFAULT_RETRY_BACKOFF,
    DEFAULT_RETRY_DELAY,
    DEFAULT_SHELL_MAX_CAP,
    DEFAULT_SHELL_OUTPUT_CHARS,
    DEFAULT_SHELL_STREAM_BUFFER_BYTES,
    DEFAULT_SHELL_TIMEOUT,
    DEFAULT_SNAPSHOT_LOG_BYTES,
    DEFAULT_STREAM_FLUSH_INTERVAL,
    DEFAULT_STREAM_TIMEOUT,
    DEFAULT_SUBAGENT_RESULT_MAX_CHARS,
    DEFAULT_SUBAGENT_WORKTREE_TIMEOUT,
    DEFAULT_TOOL_OUTPUT_CHARS,
    DEFAULT_TOOL_PAYLOAD_BYTES,
    DEFAULT_WEB_FETCH_TIMEOUT,
    DEFAULT_WEB_USER_AGENT,
)
from core.infrastructure.platform import paths
from core.infrastructure.platform.platform_utils import atomic_write_json, read_json

logger = logging.getLogger(__name__)


def _safe_int(val: Any, default: int, min_val: Optional[int] = None) -> int:
    if val is None or isinstance(val, bool):
        return default
    try:
        parsed = int(val)
        if min_val is not None and parsed < min_val:
            return default
        return parsed
    except (ValueError, TypeError):
        return default


def _safe_float(val: Any, default: float, min_val: Optional[float] = None) -> float:
    if val is None or isinstance(val, bool):
        return default
    try:
        parsed = float(val)
        if math.isnan(parsed) or math.isinf(parsed):
            return default
        if min_val is not None and parsed < min_val:
            return default
        return parsed
    except (ValueError, TypeError):
        return default


def _env_int(key: str, default: int, min_val: Optional[int] = None) -> int:
    val = os.getenv(key)
    if val is not None and val.strip():
        return _safe_int(val.strip(), default, min_val=min_val)
    return default


def _env_float(key: str, default: float, min_val: Optional[float] = None) -> float:
    val = os.getenv(key)
    if val is not None and val.strip():
        return _safe_float(val.strip(), default, min_val=min_val)
    return default


def _env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is not None and val.strip():
        norm = val.strip().lower()
        if norm in ("1", "true", "yes", "on"):
            return True
        if norm in ("0", "false", "no", "off"):
            return False
    return default


def _env_str(key: str, default: str) -> str:
    val = os.getenv(key)
    if val is not None and val.strip():
        return val.strip()
    return default


@dataclass
class LLMSettings:
    context_limit: int = DEFAULT_CONTEXT_LIMIT
    compaction_threshold_ratio: float = DEFAULT_COMPACTION_THRESHOLD_RATIO
    compaction_summarize_ratio: float = DEFAULT_COMPACTION_SUMMARIZE_RATIO
    compaction_user_budget: int = DEFAULT_COMPACTION_USER_BUDGET
    stream_timeout: float = DEFAULT_STREAM_TIMEOUT
    chunk_timeout: float = DEFAULT_CHUNK_TIMEOUT
    default_max_tokens: int = DEFAULT_MAX_TOKENS
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_delay: float = DEFAULT_RETRY_DELAY
    retry_backoff: float = DEFAULT_RETRY_BACKOFF
    max_retry_delay: float = DEFAULT_MAX_RETRY_DELAY
    cb_failure_threshold: int = DEFAULT_CB_FAILURE_THRESHOLD
    cb_cooldown_seconds: float = DEFAULT_CB_COOLDOWN_SECONDS
    auto_title: bool = DEFAULT_AUTO_TITLE
    auto_title_timeout: float = DEFAULT_AUTO_TITLE_TIMEOUT
    auto_title_max_len: int = DEFAULT_AUTO_TITLE_MAX_LEN
    auto_title_model: Optional[str] = DEFAULT_AUTO_TITLE_MODEL
    catalog_cache_ttl: float = DEFAULT_CATALOG_CACHE_TTL
    agent_md_max_chars: int = DEFAULT_AGENT_MD_MAX_CHARS
    thinking_efforts: Dict[str, Dict[str, str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> LLMSettings:
        sec = data.get("llm") if isinstance(data.get("llm"), dict) else {}
        efforts = sec.get("thinking_efforts") if isinstance(sec.get("thinking_efforts"), dict) else {}
        return cls(
            context_limit=_env_int(
                "JOHNSTON_CONTEXT_LIMIT",
                _safe_int(sec.get("context_limit"), DEFAULT_CONTEXT_LIMIT, min_val=1024),
                min_val=1024,
            ),
            compaction_threshold_ratio=_env_float(
                "JOHNSTON_COMPACTION_RATIO",
                _safe_float(sec.get("compaction_threshold_ratio"), DEFAULT_COMPACTION_THRESHOLD_RATIO, min_val=0.1),
                min_val=0.1,
            ),
            compaction_summarize_ratio=_env_float(
                "JOHNSTON_COMPACTION_SUMMARIZE_RATIO",
                _safe_float(sec.get("compaction_summarize_ratio"), DEFAULT_COMPACTION_SUMMARIZE_RATIO, min_val=0.1),
                min_val=0.1,
            ),
            compaction_user_budget=_env_int(
                "JOHNSTON_COMPACTION_USER_BUDGET",
                _safe_int(sec.get("compaction_user_budget"), DEFAULT_COMPACTION_USER_BUDGET, min_val=100),
                min_val=100,
            ),
            stream_timeout=_env_float(
                "JOHNSTON_STREAM_TIMEOUT",
                _safe_float(sec.get("stream_timeout"), DEFAULT_STREAM_TIMEOUT, min_val=0.1),
                min_val=0.1,
            ),
            chunk_timeout=_env_float(
                "JOHNSTON_CHUNK_TIMEOUT",
                _safe_float(sec.get("chunk_timeout"), DEFAULT_CHUNK_TIMEOUT, min_val=0.1),
                min_val=0.1,
            ),
            default_max_tokens=_env_int(
                "JOHNSTON_MAX_TOKENS",
                _safe_int(sec.get("default_max_tokens"), DEFAULT_MAX_TOKENS, min_val=1),
                min_val=1,
            ),
            max_retries=_env_int(
                "JOHNSTON_MAX_RETRIES",
                _safe_int(sec.get("max_retries"), DEFAULT_MAX_RETRIES, min_val=0),
                min_val=0,
            ),
            retry_delay=_env_float(
                "JOHNSTON_RETRY_DELAY",
                _safe_float(sec.get("retry_delay"), DEFAULT_RETRY_DELAY, min_val=0.0),
                min_val=0.0,
            ),
            retry_backoff=_env_float(
                "JOHNSTON_RETRY_BACKOFF",
                _safe_float(sec.get("retry_backoff"), DEFAULT_RETRY_BACKOFF, min_val=1.0),
                min_val=1.0,
            ),
            max_retry_delay=_env_float(
                "JOHNSTON_MAX_RETRY_DELAY",
                _safe_float(sec.get("max_retry_delay"), DEFAULT_MAX_RETRY_DELAY, min_val=0.0),
                min_val=0.0,
            ),
            cb_failure_threshold=_env_int(
                "JOHNSTON_CB_THRESHOLD",
                _safe_int(sec.get("cb_failure_threshold"), DEFAULT_CB_FAILURE_THRESHOLD, min_val=1),
                min_val=1,
            ),
            cb_cooldown_seconds=_env_float(
                "JOHNSTON_CB_COOLDOWN",
                _safe_float(sec.get("cb_cooldown_seconds"), DEFAULT_CB_COOLDOWN_SECONDS, min_val=0.0),
                min_val=0.0,
            ),
            auto_title=_env_bool(
                "JOHNSTON_AUTO_TITLE",
                sec.get("auto_title", DEFAULT_AUTO_TITLE) if isinstance(sec.get("auto_title"), bool) else DEFAULT_AUTO_TITLE,
            ),
            auto_title_timeout=_env_float(
                "JOHNSTON_AUTO_TITLE_TIMEOUT",
                _safe_float(sec.get("auto_title_timeout"), DEFAULT_AUTO_TITLE_TIMEOUT, min_val=0.1),
                min_val=0.1,
            ),
            auto_title_max_len=_env_int(
                "JOHNSTON_AUTO_TITLE_MAX_LEN",
                _safe_int(sec.get("auto_title_max_len"), DEFAULT_AUTO_TITLE_MAX_LEN, min_val=10),
                min_val=10,
            ),
            auto_title_model=_env_str(
                "JOHNSTON_AUTO_TITLE_MODEL",
                sec.get("auto_title_model") if isinstance(sec.get("auto_title_model"), str) else DEFAULT_AUTO_TITLE_MODEL,
            ),
            catalog_cache_ttl=_env_float(
                "JOHNSTON_CATALOG_CACHE_TTL",
                _safe_float(sec.get("catalog_cache_ttl"), DEFAULT_CATALOG_CACHE_TTL, min_val=0.0),
                min_val=0.0,
            ),
            agent_md_max_chars=_env_int(
                "JOHNSTON_AGENT_MD_MAX_CHARS",
                _safe_int(sec.get("agent_md_max_chars"), DEFAULT_AGENT_MD_MAX_CHARS, min_val=1000),
                min_val=1000,
            ),
            thinking_efforts=efforts,
        )


@dataclass
class ToolsSettings:
    shell_default_timeout: float = DEFAULT_SHELL_TIMEOUT
    shell_max_cap: float = DEFAULT_SHELL_MAX_CAP
    max_shell_output_chars: int = DEFAULT_SHELL_OUTPUT_CHARS
    max_tool_output_chars: int = DEFAULT_TOOL_OUTPUT_CHARS
    max_tool_payload_bytes: int = DEFAULT_TOOL_PAYLOAD_BYTES
    max_snapshot_log_bytes: int = DEFAULT_SNAPSHOT_LOG_BYTES
    mcp_call_timeout: float = DEFAULT_MCP_CALL_TIMEOUT
    mcp_init_timeout: float = DEFAULT_MCP_INIT_TIMEOUT
    web_fetch_timeout: float = DEFAULT_WEB_FETCH_TIMEOUT
    read_line_window: int = DEFAULT_READ_LINE_WINDOW
    max_dir_entries: int = DEFAULT_MAX_DIR_ENTRIES
    doc_conversion_timeout: float = DEFAULT_DOC_CONVERSION_TIMEOUT
    max_image_dimension: int = DEFAULT_IMAGE_MAX_DIMENSION
    shell_stream_buffer_bytes: int = DEFAULT_SHELL_STREAM_BUFFER_BYTES
    web_user_agent: str = DEFAULT_WEB_USER_AGENT

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolsSettings:
        sec = data.get("tools") if isinstance(data.get("tools"), dict) else {}
        ua_val = sec.get("web_user_agent") if isinstance(sec.get("web_user_agent"), str) and sec.get("web_user_agent").strip() else DEFAULT_WEB_USER_AGENT
        raw_shell_chars = sec.get("max_shell_output_chars")
        raw_img_dim = sec.get("max_image_dimension")
        return cls(
            shell_default_timeout=_env_float(
                "JOHNSTON_SHELL_TIMEOUT",
                _safe_float(sec.get("shell_default_timeout"), DEFAULT_SHELL_TIMEOUT, min_val=0.1),
                min_val=0.1,
            ),
            shell_max_cap=_env_float(
                "JOHNSTON_SHELL_MAX_CAP",
                _safe_float(sec.get("shell_max_cap"), DEFAULT_SHELL_MAX_CAP, min_val=0.1),
                min_val=0.1,
            ),
            max_shell_output_chars=_env_int(
                "JOHNSTON_SHELL_OUTPUT_CHARS",
                _safe_int(raw_shell_chars, DEFAULT_SHELL_OUTPUT_CHARS, min_val=100),
                min_val=100,
            ),
            max_tool_output_chars=_env_int(
                "JOHNSTON_MAX_TOOL_OUTPUT_CHARS",
                _safe_int(sec.get("max_tool_output_chars"), DEFAULT_TOOL_OUTPUT_CHARS, min_val=100),
                min_val=100,
            ),
            max_tool_payload_bytes=_env_int(
                "JOHNSTON_MAX_TOOL_PAYLOAD_BYTES",
                _safe_int(sec.get("max_tool_payload_bytes"), DEFAULT_TOOL_PAYLOAD_BYTES, min_val=1024),
                min_val=1024,
            ),
            max_snapshot_log_bytes=_env_int(
                "JOHNSTON_MAX_SNAPSHOT_LOG_BYTES",
                _safe_int(sec.get("max_snapshot_log_bytes"), DEFAULT_SNAPSHOT_LOG_BYTES, min_val=1024),
                min_val=1024,
            ),
            mcp_call_timeout=_env_float(
                "JOHNSTON_MCP_CALL_TIMEOUT",
                _safe_float(sec.get("mcp_call_timeout"), DEFAULT_MCP_CALL_TIMEOUT, min_val=0.1),
                min_val=0.1,
            ),
            mcp_init_timeout=_env_float(
                "JOHNSTON_MCP_INIT_TIMEOUT",
                _safe_float(sec.get("mcp_init_timeout"), DEFAULT_MCP_INIT_TIMEOUT, min_val=0.1),
                min_val=0.1,
            ),
            web_fetch_timeout=_env_float(
                "JOHNSTON_WEB_FETCH_TIMEOUT",
                _safe_float(sec.get("web_fetch_timeout"), DEFAULT_WEB_FETCH_TIMEOUT, min_val=0.1),
                min_val=0.1,
            ),
            read_line_window=_env_int(
                "JOHNSTON_READ_LINE_WINDOW",
                _safe_int(sec.get("read_line_window"), DEFAULT_READ_LINE_WINDOW, min_val=10),
                min_val=10,
            ),
            max_dir_entries=_env_int(
                "JOHNSTON_MAX_DIR_ENTRIES",
                _safe_int(sec.get("max_dir_entries"), DEFAULT_MAX_DIR_ENTRIES, min_val=5),
                min_val=5,
            ),
            doc_conversion_timeout=_env_float(
                "JOHNSTON_DOC_CONVERSION_TIMEOUT",
                _safe_float(sec.get("doc_conversion_timeout"), DEFAULT_DOC_CONVERSION_TIMEOUT, min_val=0.5),
                min_val=0.5,
            ),
            max_image_dimension=_env_int(
                "JOHNSTON_IMAGE_MAX_DIMENSION",
                _safe_int(raw_img_dim, DEFAULT_IMAGE_MAX_DIMENSION, min_val=128),
                min_val=128,
            ),
            shell_stream_buffer_bytes=_env_int(
                "JOHNSTON_SHELL_STREAM_BUFFER_BYTES",
                _safe_int(sec.get("shell_stream_buffer_bytes"), DEFAULT_SHELL_STREAM_BUFFER_BYTES, min_val=1024),
                min_val=1024,
            ),
            web_user_agent=_env_str("JOHNSTON_WEB_USER_AGENT", ua_val),
        )


@dataclass
class SubagentsSettings:
    max_concurrent: int = DEFAULT_MAX_CONCURRENT_SUBAGENTS
    max_result_chars: int = DEFAULT_SUBAGENT_RESULT_MAX_CHARS
    worktree_timeout: float = DEFAULT_SUBAGENT_WORKTREE_TIMEOUT

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SubagentsSettings:
        sec = data.get("subagents") if isinstance(data.get("subagents"), dict) else {}
        max_sub = _safe_int(sec.get("max_concurrent"), DEFAULT_MAX_CONCURRENT_SUBAGENTS, min_val=1)
        raw_chars = sec.get("max_result_chars")
        return cls(
            max_concurrent=_env_int("JOHNSTON_MAX_CONCURRENT_SUBAGENTS", max_sub, min_val=1),
            max_result_chars=_env_int(
                "JOHNSTON_SUBAGENT_RESULT_MAX_CHARS",
                _safe_int(raw_chars, DEFAULT_SUBAGENT_RESULT_MAX_CHARS, min_val=100),
                min_val=100,
            ),
            worktree_timeout=_env_float(
                "JOHNSTON_SUBAGENT_WORKTREE_TIMEOUT",
                _safe_float(sec.get("worktree_timeout"), DEFAULT_SUBAGENT_WORKTREE_TIMEOUT, min_val=0.1),
                min_val=0.1,
            ),
        )


@dataclass
class UISettings:
    max_prompt_history: int = DEFAULT_PROMPT_HISTORY
    max_chat_input_lines: int = DEFAULT_CHAT_INPUT_MAX_LINES
    stream_flush_interval: float = DEFAULT_STREAM_FLUSH_INTERVAL
    chat_page_size: int = DEFAULT_CHAT_PAGE_SIZE
    paste_line_threshold: int = DEFAULT_PASTE_LINE_THRESHOLD
    autocomplete_max_files: int = DEFAULT_AUTOCOMPLETE_MAX_FILES

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> UISettings:
        sec = data.get("ui") if isinstance(data.get("ui"), dict) else {}
        raw_input_lines = sec.get("max_chat_input_lines")
        return cls(
            max_prompt_history=_env_int(
                "JOHNSTON_MAX_PROMPT_HISTORY",
                _safe_int(sec.get("max_prompt_history"), DEFAULT_PROMPT_HISTORY, min_val=1),
                min_val=1,
            ),
            max_chat_input_lines=_env_int(
                "JOHNSTON_CHAT_INPUT_MAX_LINES",
                _safe_int(raw_input_lines, DEFAULT_CHAT_INPUT_MAX_LINES, min_val=2),
                min_val=2,
            ),
            stream_flush_interval=_env_float(
                "JOHNSTON_STREAM_FLUSH_INTERVAL",
                _safe_float(sec.get("stream_flush_interval"), DEFAULT_STREAM_FLUSH_INTERVAL, min_val=0.0),
                min_val=0.0,
            ),
            chat_page_size=_env_int(
                "JOHNSTON_CHAT_PAGE_SIZE",
                _safe_int(sec.get("chat_page_size"), DEFAULT_CHAT_PAGE_SIZE, min_val=1),
                min_val=1,
            ),
            paste_line_threshold=_env_int(
                "JOHNSTON_PASTE_LINE_THRESHOLD",
                _safe_int(sec.get("paste_line_threshold"), DEFAULT_PASTE_LINE_THRESHOLD, min_val=1),
                min_val=1,
            ),
            autocomplete_max_files=_env_int(
                "JOHNSTON_AUTOCOMPLETE_MAX_FILES",
                _safe_int(sec.get("autocomplete_max_files"), DEFAULT_AUTOCOMPLETE_MAX_FILES, min_val=10),
                min_val=10,
            ),
        )


@dataclass
class StorageSettings:
    max_log_bytes: int = DEFAULT_LOG_MAX_BYTES
    max_log_age_days: int = DEFAULT_LOG_MAX_AGE_DAYS
    disk_cache_ttl: float = DEFAULT_DISK_CACHE_TTL

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StorageSettings:
        sec = data.get("storage") if isinstance(data.get("storage"), dict) else {}
        raw_bytes = sec.get("max_log_bytes")
        raw_age = sec.get("max_log_age_days")
        return cls(
            max_log_bytes=_env_int(
                "JOHNSTON_LOG_MAX_BYTES",
                _safe_int(raw_bytes, DEFAULT_LOG_MAX_BYTES, min_val=1024),
                min_val=1024,
            ),
            max_log_age_days=_env_int(
                "JOHNSTON_LOG_MAX_AGE_DAYS",
                _safe_int(raw_age, DEFAULT_LOG_MAX_AGE_DAYS, min_val=0),
                min_val=0,
            ),
            disk_cache_ttl=_env_float(
                "JOHNSTON_DISK_CACHE_TTL",
                _safe_float(sec.get("disk_cache_ttl"), DEFAULT_DISK_CACHE_TTL, min_val=0.0),
                min_val=0.0,
            ),
        )


@dataclass
class SandboxSettings:
    enabled: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SandboxSettings:
        sec = data.get("sandbox") if isinstance(data.get("sandbox"), dict) else {}
        val = sec.get("enabled", False)
        return cls(
            enabled=_env_bool("JOHNSTON_SANDBOX_ENABLED", bool(val)),
        )


@dataclass
class JohnstonSettings:
    model: Optional[str] = None
    theme: Optional[str] = None
    sandbox: SandboxSettings = field(default_factory=SandboxSettings)
    permissions: Dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_PERMISSIONS))
    llm: LLMSettings = field(default_factory=LLMSettings)
    tools: ToolsSettings = field(default_factory=ToolsSettings)
    subagents: SubagentsSettings = field(default_factory=SubagentsSettings)
    ui: UISettings = field(default_factory=UISettings)
    storage: StorageSettings = field(default_factory=StorageSettings)

    @property
    def sandbox_enabled(self) -> bool:
        return self.sandbox.enabled

    @sandbox_enabled.setter
    def sandbox_enabled(self, val: bool) -> None:
        self.sandbox.enabled = bool(val)

    @property
    def active_provider(self) -> Optional[str]:
        """Provider derived solely from ``model``.

        ``model`` is the single source of truth (``provider/model`` or a bare
        ``provider`` key); the provider is extracted from its ``/``-prefix.
        Returns ``None`` when no model is set or the model is a bare name that
        cannot be decoded to a provider here (no catalog context).
        """
        if not self.model:
            return None
        if "/" in self.model:
            return self.model.split("/", 1)[0].strip().lower()
        return None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> JohnstonSettings:
        if not isinstance(data, dict):
            return cls()

        model = data.get("model")
        if not (isinstance(model, str) and model.strip()):
            model = None
        theme = data.get("theme")
        if not (isinstance(theme, str) and theme.strip()):
            theme = None

        perms = data.get("permissions")
        if not isinstance(perms, dict):
            perms = dict(DEFAULT_PERMISSIONS)

        return cls(
            model=model.strip() if model else None,
            theme=theme.strip() if theme else None,
            sandbox=SandboxSettings.from_dict(data),
            permissions=perms,
            llm=LLMSettings.from_dict(data),
            tools=ToolsSettings.from_dict(data),
            subagents=SubagentsSettings.from_dict(data),
            ui=UISettings.from_dict(data),
            storage=StorageSettings.from_dict(data),
        )


_cached_settings_map: Dict[str, Tuple[float, JohnstonSettings]] = {}


def load_settings(config_file: Optional[str] = None) -> JohnstonSettings:
    """Load settings from JSON config file with environment variable overlays.

    A missing file yields defaults. A file that exists but is unreadable or
    contains invalid JSON is surfaced via a warning instead of silently
    discarding the user's configuration.
    """
    target_file = os.path.abspath(config_file or paths.CONFIG_FILE)
    if not os.path.exists(target_file):
        return JohnstonSettings.from_dict({})
    raw = read_json(target_file, default=None)
    if isinstance(raw, dict):
        return JohnstonSettings.from_dict(raw)
    logger.warning("Config file %s is unreadable or contains invalid JSON; using defaults.", target_file)
    return JohnstonSettings.from_dict({})


def get_settings(config_file: Optional[str] = None, force_reload: bool = False) -> JohnstonSettings:
    """Returns per-file cached JohnstonSettings, refreshing on file mtime change."""
    global _cached_settings_map
    target_file = os.path.abspath(config_file or paths.CONFIG_FILE)

    try:
        mtime = os.path.getmtime(target_file) if os.path.exists(target_file) else 0.0
    except Exception:
        mtime = 0.0

    cached = _cached_settings_map.get(target_file)
    if force_reload or cached is None or cached[0] != mtime:
        loaded = load_settings(target_file)
        _cached_settings_map[target_file] = (mtime, loaded)
        return loaded
    return cached[1]


def reload_settings(config_file: Optional[str] = None) -> JohnstonSettings:
    """Force reloads and returns active settings for specified or default config file."""
    return get_settings(config_file=config_file, force_reload=True)


def save_settings(settings: JohnstonSettings, config_file: Optional[str] = None) -> None:
    """Saves structured settings back to config_file.

    Write failures propagate to the caller so a lost update is never silent.
    """
    target_file = os.path.abspath(config_file or paths.CONFIG_FILE)
    data = read_json(target_file, default={})
    if not isinstance(data, dict):
        data = {}
    data.pop("provider_models", None)
    if settings.model is not None:
        data["model"] = settings.model
    else:
        data.pop("model", None)
    if settings.theme is not None:
        data["theme"] = settings.theme
    elif "theme" in data:
        data.pop("theme", None)
    data["sandbox"] = asdict(settings.sandbox)
    data.pop("sandbox_enabled", None)
    data.pop("provider_thinking_efforts", None)
    data["permissions"] = settings.permissions
    data["subagents"] = asdict(settings.subagents)
    data["llm"] = asdict(settings.llm)
    data["tools"] = asdict(settings.tools)
    data["ui"] = asdict(settings.ui)
    data["storage"] = asdict(settings.storage)
    atomic_write_json(target_file, data, indent=2)
    reload_settings(target_file)


def patch_settings(config_file: Optional[str] = None, **kwargs: Any) -> JohnstonSettings:
    """Partially updates current settings, saves them to disk and returns reloaded instance."""
    target_file = os.path.abspath(config_file or paths.CONFIG_FILE)
    current = load_settings(target_file)
    for key, value in kwargs.items():
        if key == "sandbox_enabled":
            current.sandbox.enabled = bool(value)
        elif hasattr(current, key):
            setattr(current, key, value)
    save_settings(current, target_file)
    return get_settings(target_file, force_reload=True)

