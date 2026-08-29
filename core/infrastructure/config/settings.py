"""Central application settings with environment variable and JSON config support."""
from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple

from core.domain.defaults.config import (
    COMPACTION_SUMMARIZE_RATIO,
    CONTEXT_COMPACTION_THRESHOLD_RATIO,
    DEFAULT_CB_COOLDOWN_SECONDS,
    DEFAULT_CB_FAILURE_THRESHOLD,
    DEFAULT_CHAT_PAGE_SIZE,
    DEFAULT_CHUNK_TIMEOUT,
    DEFAULT_COMPACTION_USER_BUDGET,
    DEFAULT_CONTEXT_LIMIT,
    DEFAULT_DISK_CACHE_TTL,
    DEFAULT_LOG_MAX_AGE_DAYS,
    DEFAULT_LOG_MAX_BYTES,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_RETRY_DELAY,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MCP_CALL_TIMEOUT,
    DEFAULT_MCP_INIT_TIMEOUT,
    DEFAULT_PROMPT_HISTORY,
    DEFAULT_RETRY_BACKOFF,
    DEFAULT_RETRY_DELAY,
    DEFAULT_SHELL_MAX_CAP,
    DEFAULT_SHELL_OUTPUT_CHARS,
    DEFAULT_SHELL_TIMEOUT,
    DEFAULT_SNAPSHOT_LOG_BYTES,
    DEFAULT_STREAM_FLUSH_INTERVAL,
    DEFAULT_STREAM_TIMEOUT,
    DEFAULT_SUBAGENT_RESULT_MAX_CHARS,
    DEFAULT_SUBAGENT_WORKTREE_TIMEOUT,
    DEFAULT_TOOL_OUTPUT_CHARS,
    DEFAULT_TOOL_PAYLOAD_BYTES,
    DEFAULT_WEB_FETCH_TIMEOUT,
    MAX_CONCURRENT_SUBAGENTS,
)
from core.infrastructure.platform import paths
from core.infrastructure.platform.platform_utils import atomic_write_json, read_json


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


@dataclass
class LLMSettings:
    context_limit: int = DEFAULT_CONTEXT_LIMIT
    compaction_threshold_ratio: float = CONTEXT_COMPACTION_THRESHOLD_RATIO
    compaction_summarize_ratio: float = COMPACTION_SUMMARIZE_RATIO
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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> LLMSettings:
        sec = data.get("llm") if isinstance(data.get("llm"), dict) else {}
        return cls(
            context_limit=_env_int(
                "JOHNSTON_CONTEXT_LIMIT",
                _safe_int(sec.get("context_limit"), DEFAULT_CONTEXT_LIMIT, min_val=1024),
                min_val=1024,
            ),
            compaction_threshold_ratio=_env_float(
                "JOHNSTON_COMPACTION_RATIO",
                _safe_float(sec.get("compaction_threshold_ratio"), CONTEXT_COMPACTION_THRESHOLD_RATIO, min_val=0.1),
                min_val=0.1,
            ),
            compaction_summarize_ratio=_env_float(
                "JOHNSTON_COMPACTION_SUMMARIZE_RATIO",
                _safe_float(sec.get("compaction_summarize_ratio"), COMPACTION_SUMMARIZE_RATIO, min_val=0.1),
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
        )


@dataclass
class ToolsSettings:
    shell_default_timeout: float = DEFAULT_SHELL_TIMEOUT
    shell_max_cap: float = DEFAULT_SHELL_MAX_CAP
    shell_output_chars: int = DEFAULT_SHELL_OUTPUT_CHARS
    max_tool_output_chars: int = DEFAULT_TOOL_OUTPUT_CHARS
    max_tool_payload_bytes: int = DEFAULT_TOOL_PAYLOAD_BYTES
    max_snapshot_log_bytes: int = DEFAULT_SNAPSHOT_LOG_BYTES
    mcp_call_timeout: float = DEFAULT_MCP_CALL_TIMEOUT
    mcp_init_timeout: float = DEFAULT_MCP_INIT_TIMEOUT
    web_fetch_timeout: float = DEFAULT_WEB_FETCH_TIMEOUT

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolsSettings:
        sec = data.get("tools") if isinstance(data.get("tools"), dict) else {}
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
            shell_output_chars=_env_int(
                "JOHNSTON_SHELL_OUTPUT_CHARS",
                _safe_int(sec.get("shell_output_chars"), DEFAULT_SHELL_OUTPUT_CHARS, min_val=100),
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
        )


@dataclass
class SubagentsSettings:
    max_concurrent: int = MAX_CONCURRENT_SUBAGENTS
    result_max_chars: int = DEFAULT_SUBAGENT_RESULT_MAX_CHARS
    worktree_timeout: float = DEFAULT_SUBAGENT_WORKTREE_TIMEOUT

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SubagentsSettings:
        sec = data.get("subagents") if isinstance(data.get("subagents"), dict) else {}
        raw_max = sec.get("max_concurrent") if sec.get("max_concurrent") is not None else data.get("max_concurrent_subagents")
        max_sub = _safe_int(raw_max, MAX_CONCURRENT_SUBAGENTS, min_val=1)
        return cls(
            max_concurrent=_env_int("JOHNSTON_MAX_CONCURRENT_SUBAGENTS", max_sub, min_val=1),
            result_max_chars=_env_int(
                "JOHNSTON_SUBAGENT_RESULT_MAX_CHARS",
                _safe_int(sec.get("result_max_chars"), DEFAULT_SUBAGENT_RESULT_MAX_CHARS, min_val=100),
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
    stream_flush_interval: float = DEFAULT_STREAM_FLUSH_INTERVAL
    chat_page_size: int = DEFAULT_CHAT_PAGE_SIZE

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> UISettings:
        sec = data.get("ui") if isinstance(data.get("ui"), dict) else {}
        return cls(
            max_prompt_history=_env_int(
                "JOHNSTON_MAX_PROMPT_HISTORY",
                _safe_int(sec.get("max_prompt_history"), DEFAULT_PROMPT_HISTORY, min_val=1),
                min_val=1,
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
        )


@dataclass
class StorageSettings:
    log_max_bytes: int = DEFAULT_LOG_MAX_BYTES
    log_max_age_days: int = DEFAULT_LOG_MAX_AGE_DAYS
    disk_cache_ttl: float = DEFAULT_DISK_CACHE_TTL

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StorageSettings:
        sec = data.get("storage") if isinstance(data.get("storage"), dict) else {}
        return cls(
            log_max_bytes=_env_int(
                "JOHNSTON_LOG_MAX_BYTES",
                _safe_int(sec.get("log_max_bytes"), DEFAULT_LOG_MAX_BYTES, min_val=1024),
                min_val=1024,
            ),
            log_max_age_days=_env_int(
                "JOHNSTON_LOG_MAX_AGE_DAYS",
                _safe_int(sec.get("log_max_age_days"), DEFAULT_LOG_MAX_AGE_DAYS, min_val=0),
                min_val=0,
            ),
            disk_cache_ttl=_env_float(
                "JOHNSTON_DISK_CACHE_TTL",
                _safe_float(sec.get("disk_cache_ttl"), DEFAULT_DISK_CACHE_TTL, min_val=0.0),
                min_val=0.0,
            ),
        )


@dataclass
class JohnstonSettings:
    active_provider: Optional[str] = None
    theme: Optional[str] = None
    sandbox_enabled: bool = False
    llm: LLMSettings = field(default_factory=LLMSettings)
    tools: ToolsSettings = field(default_factory=ToolsSettings)
    subagents: SubagentsSettings = field(default_factory=SubagentsSettings)
    ui: UISettings = field(default_factory=UISettings)
    storage: StorageSettings = field(default_factory=StorageSettings)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> JohnstonSettings:
        if not isinstance(data, dict):
            return cls()

        theme = data.get("theme")
        if not (isinstance(theme, str) and theme.strip()):
            theme = None
        sandbox_val = data.get("sandbox_enabled")
        if not isinstance(sandbox_val, bool):
            sandbox_sec = data.get("sandbox")
            if isinstance(sandbox_sec, dict):
                sandbox_val = bool(sandbox_sec.get("enabled", False))
            else:
                sandbox_val = False

        return cls(
            active_provider=data.get("active_provider") if isinstance(data.get("active_provider"), str) else None,
            theme=theme.strip() if theme else None,
            sandbox_enabled=_env_bool("JOHNSTON_SANDBOX_ENABLED", sandbox_val),
            llm=LLMSettings.from_dict(data),
            tools=ToolsSettings.from_dict(data),
            subagents=SubagentsSettings.from_dict(data),
            ui=UISettings.from_dict(data),
            storage=StorageSettings.from_dict(data),
        )


_cached_settings_map: Dict[str, Tuple[float, JohnstonSettings]] = {}


def load_settings(config_file: Optional[str] = None) -> JohnstonSettings:
    """Load settings from JSON config file with environment variable overlays."""
    target_file = os.path.abspath(config_file or paths.CONFIG_FILE)
    try:
        raw = read_json(target_file, default={})
        if isinstance(raw, dict):
            return JohnstonSettings.from_dict(raw)
    except Exception:
        pass
    return JohnstonSettings()


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
    """Saves structured settings back to config_file."""
    target_file = os.path.abspath(config_file or paths.CONFIG_FILE)
    try:
        data = read_json(target_file, default={})
        if not isinstance(data, dict):
            data = {}
        if settings.active_provider is not None:
            data["active_provider"] = settings.active_provider
        elif "active_provider" in data:
            data.pop("active_provider", None)
        if settings.theme is not None:
            data["theme"] = settings.theme
        elif "theme" in data:
            data.pop("theme", None)
        data["sandbox_enabled"] = settings.sandbox_enabled
        data["subagents"] = asdict(settings.subagents)
        data["llm"] = asdict(settings.llm)
        data["tools"] = asdict(settings.tools)
        data["ui"] = asdict(settings.ui)
        data["storage"] = asdict(settings.storage)
        atomic_write_json(target_file, data, indent=2)
        reload_settings(target_file)
    except Exception:
        pass
