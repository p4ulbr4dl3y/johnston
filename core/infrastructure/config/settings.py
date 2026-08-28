"""Central application settings with environment variable and JSON config support."""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from core.domain.defaults.config import (
    CONTEXT_COMPACTION_THRESHOLD_RATIO,
    DEFAULT_CB_COOLDOWN_SECONDS,
    DEFAULT_CB_FAILURE_THRESHOLD,
    DEFAULT_CHAT_PAGE_SIZE,
    DEFAULT_CHUNK_TIMEOUT,
    DEFAULT_COMPACTION_USER_BUDGET,
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


def _env_int(key: str, default: int) -> int:
    val = os.getenv(key)
    if val:
        try:
            parsed = int(val.strip())
            if parsed > 0:
                return parsed
        except ValueError:
            pass
    return default


def _env_float(key: str, default: float) -> float:
    val = os.getenv(key)
    if val:
        try:
            parsed = float(val.strip())
            if parsed > 0:
                return parsed
        except ValueError:
            pass
    return default


def _env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val:
        norm = val.strip().lower()
        if norm in ("1", "true", "yes", "on"):
            return True
        if norm in ("0", "false", "no", "off"):
            return False
    return default


@dataclass
class LLMSettings:
    compaction_threshold_ratio: float = CONTEXT_COMPACTION_THRESHOLD_RATIO
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
            compaction_threshold_ratio=_env_float(
                "JOHNSTON_COMPACTION_RATIO",
                float(sec.get("compaction_threshold_ratio", CONTEXT_COMPACTION_THRESHOLD_RATIO)),
            ),
            compaction_user_budget=_env_int(
                "JOHNSTON_COMPACTION_USER_BUDGET",
                int(sec.get("compaction_user_budget", DEFAULT_COMPACTION_USER_BUDGET)),
            ),
            stream_timeout=_env_float(
                "JOHNSTON_STREAM_TIMEOUT",
                float(sec.get("stream_timeout", DEFAULT_STREAM_TIMEOUT)),
            ),
            chunk_timeout=_env_float(
                "JOHNSTON_CHUNK_TIMEOUT",
                float(sec.get("chunk_timeout", DEFAULT_CHUNK_TIMEOUT)),
            ),
            default_max_tokens=_env_int(
                "JOHNSTON_MAX_TOKENS",
                int(sec.get("default_max_tokens", DEFAULT_MAX_TOKENS)),
            ),
            max_retries=_env_int(
                "JOHNSTON_MAX_RETRIES",
                int(sec.get("max_retries", DEFAULT_MAX_RETRIES)),
            ),
            retry_delay=_env_float(
                "JOHNSTON_RETRY_DELAY",
                float(sec.get("retry_delay", DEFAULT_RETRY_DELAY)),
            ),
            retry_backoff=_env_float(
                "JOHNSTON_RETRY_BACKOFF",
                float(sec.get("retry_backoff", DEFAULT_RETRY_BACKOFF)),
            ),
            max_retry_delay=_env_float(
                "JOHNSTON_MAX_RETRY_DELAY",
                float(sec.get("max_retry_delay", DEFAULT_MAX_RETRY_DELAY)),
            ),
            cb_failure_threshold=_env_int(
                "JOHNSTON_CB_THRESHOLD",
                int(sec.get("cb_failure_threshold", DEFAULT_CB_FAILURE_THRESHOLD)),
            ),
            cb_cooldown_seconds=_env_float(
                "JOHNSTON_CB_COOLDOWN",
                float(sec.get("cb_cooldown_seconds", DEFAULT_CB_COOLDOWN_SECONDS)),
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
                float(sec.get("shell_default_timeout", DEFAULT_SHELL_TIMEOUT)),
            ),
            shell_max_cap=_env_float(
                "JOHNSTON_SHELL_MAX_CAP",
                float(sec.get("shell_max_cap", DEFAULT_SHELL_MAX_CAP)),
            ),
            shell_output_chars=_env_int(
                "JOHNSTON_SHELL_OUTPUT_CHARS",
                int(sec.get("shell_output_chars", DEFAULT_SHELL_OUTPUT_CHARS)),
            ),
            max_tool_output_chars=_env_int(
                "JOHNSTON_MAX_TOOL_OUTPUT_CHARS",
                int(sec.get("max_tool_output_chars", DEFAULT_TOOL_OUTPUT_CHARS)),
            ),
            max_tool_payload_bytes=_env_int(
                "JOHNSTON_MAX_TOOL_PAYLOAD_BYTES",
                int(sec.get("max_tool_payload_bytes", DEFAULT_TOOL_PAYLOAD_BYTES)),
            ),
            max_snapshot_log_bytes=_env_int(
                "JOHNSTON_MAX_SNAPSHOT_LOG_BYTES",
                int(sec.get("max_snapshot_log_bytes", DEFAULT_SNAPSHOT_LOG_BYTES)),
            ),
            mcp_call_timeout=_env_float(
                "JOHNSTON_MCP_CALL_TIMEOUT",
                float(sec.get("mcp_call_timeout", DEFAULT_MCP_CALL_TIMEOUT)),
            ),
            mcp_init_timeout=_env_float(
                "JOHNSTON_MCP_INIT_TIMEOUT",
                float(sec.get("mcp_init_timeout", DEFAULT_MCP_INIT_TIMEOUT)),
            ),
            web_fetch_timeout=_env_float(
                "JOHNSTON_WEB_FETCH_TIMEOUT",
                float(sec.get("web_fetch_timeout", DEFAULT_WEB_FETCH_TIMEOUT)),
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
        max_sub = (
            sec.get("max_concurrent")
            or data.get("max_concurrent_subagents")
            or MAX_CONCURRENT_SUBAGENTS
        )
        return cls(
            max_concurrent=_env_int("JOHNSTON_MAX_CONCURRENT_SUBAGENTS", int(max_sub)),
            result_max_chars=_env_int(
                "JOHNSTON_SUBAGENT_RESULT_MAX_CHARS",
                int(sec.get("result_max_chars", DEFAULT_SUBAGENT_RESULT_MAX_CHARS)),
            ),
            worktree_timeout=_env_float(
                "JOHNSTON_SUBAGENT_WORKTREE_TIMEOUT",
                float(sec.get("worktree_timeout", DEFAULT_SUBAGENT_WORKTREE_TIMEOUT)),
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
                int(sec.get("max_prompt_history", DEFAULT_PROMPT_HISTORY)),
            ),
            stream_flush_interval=_env_float(
                "JOHNSTON_STREAM_FLUSH_INTERVAL",
                float(sec.get("stream_flush_interval", DEFAULT_STREAM_FLUSH_INTERVAL)),
            ),
            chat_page_size=_env_int(
                "JOHNSTON_CHAT_PAGE_SIZE",
                int(sec.get("chat_page_size", DEFAULT_CHAT_PAGE_SIZE)),
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
                int(sec.get("log_max_bytes", DEFAULT_LOG_MAX_BYTES)),
            ),
            log_max_age_days=_env_int(
                "JOHNSTON_LOG_MAX_AGE_DAYS",
                int(sec.get("log_max_age_days", DEFAULT_LOG_MAX_AGE_DAYS)),
            ),
            disk_cache_ttl=_env_float(
                "JOHNSTON_DISK_CACHE_TTL",
                float(sec.get("disk_cache_ttl", DEFAULT_DISK_CACHE_TTL)),
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


_cached_settings: Optional[JohnstonSettings] = None
_cached_mtime: Optional[float] = None


def load_settings(config_file: Optional[str] = None) -> JohnstonSettings:
    """Load settings from JSON config file with environment variable overlays."""
    config_file = config_file or paths.CONFIG_FILE
    data = {}
    try:
        raw = read_json(config_file, default={})
        if isinstance(raw, dict):
            data = raw
    except Exception:
        data = {}
    return JohnstonSettings.from_dict(data)


def get_settings(config_file: Optional[str] = None, force_reload: bool = False) -> JohnstonSettings:
    """Returns singleton cached JohnstonSettings, refreshing on file mtime change."""
    global _cached_settings, _cached_mtime
    target_file = config_file or paths.CONFIG_FILE

    try:
        mtime = os.path.getmtime(target_file) if os.path.exists(target_file) else 0.0
    except Exception:
        mtime = 0.0

    if force_reload or _cached_settings is None or _cached_mtime != mtime:
        _cached_settings = load_settings(target_file)
        _cached_mtime = mtime
    return _cached_settings


def reload_settings() -> JohnstonSettings:
    """Force reloads and returns active settings."""
    return get_settings(force_reload=True)


def save_settings(settings: JohnstonSettings, config_file: Optional[str] = None) -> None:
    """Saves structured settings back to config_file."""
    config_file = config_file or paths.CONFIG_FILE
    try:
        data = read_json(config_file, default={})
        if not isinstance(data, dict):
            data = {}
        if settings.theme is not None:
            data["theme"] = settings.theme
        data["sandbox_enabled"] = settings.sandbox_enabled
        data["subagents"] = asdict(settings.subagents)
        data["llm"] = asdict(settings.llm)
        data["tools"] = asdict(settings.tools)
        data["ui"] = asdict(settings.ui)
        data["storage"] = asdict(settings.storage)
        atomic_write_json(config_file, data, indent=2)
        reload_settings()
    except Exception:
        pass
