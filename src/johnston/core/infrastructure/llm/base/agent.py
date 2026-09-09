import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from johnston.core.domain.defaults.config import DEFAULT_MAX_TOKENS
from johnston.core.domain.defaults.prompts import DEFAULT_SYSTEM_PROMPT
from johnston.core.infrastructure.llm.base.compaction import CompactionMixin
from johnston.core.infrastructure.llm.base.errors import ErrorHandlingMixin, format_api_error
from johnston.core.infrastructure.llm.base.history_cache import (
    _SANITIZE_CACHE,
    _SANITIZE_CACHE_MAX,
    _STREAMING_TARGET_RE,
    _TARGET_SCAN_BACKOFF,
    _cache_sanitize_get,
    _cache_sanitize_put,
    _extract_streaming_target,
    _get_tools_digest,
    sanitize_history_cached,
    serialize_messages_key,
)
from johnston.core.infrastructure.llm.base.message_queue import drain_queued_messages, has_queued_messages
from johnston.core.infrastructure.llm.base.stream_loop import StreamLoopMixin
from johnston.core.infrastructure.llm.base.tools import ToolMixin
from johnston.core.infrastructure.llm.base.turn_context import (
    TurnContextMixin,
    _warmup_mcp_tools,  # noqa: F401
)
from johnston.core.infrastructure.llm.base.turn_execution import TurnExecutionMixin
from johnston.core.infrastructure.llm.base.usage import accumulate_usage
from johnston.core.infrastructure.runtime.thinking_effort import normalize_thinking_effort
from johnston.core.infrastructure.runtime.token_util import estimate_message_tokens, estimate_tokens

__all__ = [
    "BaseAgent",
    "_extract_streaming_target",
    "_TARGET_SCAN_BACKOFF",
    "serialize_messages_key",
    "_get_tools_digest",
    "sanitize_history_cached",
    "_SANITIZE_CACHE",
    "_SANITIZE_CACHE_MAX",
    "_STREAMING_TARGET_RE",
    "_cache_sanitize_get",
    "_cache_sanitize_put",
    "estimate_tokens",
    "estimate_message_tokens",
    "format_api_error",
]

logger = logging.getLogger(__name__)


class BaseAgent(
    CompactionMixin,
    ToolMixin,
    ErrorHandlingMixin,
    TurnContextMixin,
    TurnExecutionMixin,
    StreamLoopMixin,
):
    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        base_url: str = "",
        system_prompt: Optional[str] = None,
        tools: List[Dict[str, Any]] = None,
        provider_key: str = "openai",
        api_type: str = "openai",
        headers: Dict[str, str] = None,
        extra_body: Dict[str, Any] = None,
        reasoning_effort: str = None,
        thinking_effort: str = None,
        chunk_timeout: float = 30.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        max_retry_delay: float = 10.0,
        tool_executor: Optional[Callable[[str, dict, Any], Awaitable[str]]] = None,
        default_tools_provider: Optional[Callable[[], List[Dict]]] = None,
        image_processor: Optional[Callable] = None,
        tool_name_normalizer: Optional[Callable[[str], str]] = None,
        auto_compact_token_limit: Optional[int] = None,
    ):
        if tools is None:
            tools = default_tools_provider() if default_tools_provider else []
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.system_prompt = system_prompt if system_prompt is not None else DEFAULT_SYSTEM_PROMPT
        self.auto_compact_token_limit = auto_compact_token_limit
        self.tools = tools
        self.provider_key = provider_key
        self.api_type = api_type
        self.headers = headers or {}
        self.extra_body = extra_body or {}
        self.reasoning_effort = reasoning_effort
        self.thinking_effort = normalize_thinking_effort(thinking_effort or reasoning_effort)
        self.chunk_timeout = chunk_timeout
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.retry_backoff = retry_backoff
        self.max_retry_delay = max_retry_delay

        self._client: Optional[Any] = None
        self.history = []
        # Running token accumulator for self.history. Always equals
        # estimate_tokens(self.history); kept fresh via _set_history /
        # _append_history and self-healing against direct external mutation
        # through the identity+length guard in _current_history_tokens().
        self._history_tokens = 0
        self._history_ident = id(self.history)
        self.host: Optional[Any] = None
        self.tokens_input = 0
        self.tokens_output = 0
        self.tokens_cache_read = 0
        self.last_context_tokens = 0
        self.total_tokens = 0
        self.cost_usd = 0.0
        self.role = "worker"
        self._role_name: Optional[str] = None
        self.tool_executor = tool_executor
        self.default_tools_provider = default_tools_provider
        self.image_processor = image_processor
        self.tool_name_normalizer = tool_name_normalizer
        # Per-agent memo for _tool_policy_error keyed by (id(role_def), tool_name).
        # The stream loop calls it once per tool call; without the memo the role
        # resolution + membership checks rerun for every tool_result.
        self._tool_policy_cache: Dict[tuple, Any] = {}

    @property
    def app(self) -> Optional[Any]:
        """Backward compatibility alias for host."""
        return self.host

    @app.setter
    def app(self, val: Optional[Any]) -> None:
        self.host = val

    @property
    def role_name(self) -> str:
        if getattr(self, "_role_name", None):
            return self._role_name
        from johnston.core.application.roles.role_registry import resolve_role_display_name

        pdir = getattr(getattr(self, "host", None), "project_dir", None)
        return resolve_role_display_name(self.role, project_dir=pdir)

    @role_name.setter
    def role_name(self, value: str) -> None:
        self._role_name = value

    @property
    def client(self) -> Any:
        if self._client is None:
            import unittest.mock

            self._client = unittest.mock.MagicMock()
        return self._client

    @client.setter
    def client(self, val: Any) -> None:
        self._client = val

    async def close(self):
        if getattr(self, "_client", None) is not None:
            closer = getattr(self._client, "aclose", None) or getattr(self._client, "close", None)
            if closer:
                res = closer()
                if asyncio.iscoroutine(res):
                    await res

    def clear_history(self):
        self.history.clear()
        self._history_tokens = 0
        self._history_ident = id(self.history)
        self._history_len = 0
        self.tokens_input = 0
        self.tokens_output = 0
        self.tokens_cache_read = 0
        self.last_context_tokens = 0
        self.total_tokens = 0
        self.cost_usd = 0.0
        self.role = "worker"
        # Drop the cached system prompt + tool schema token count from the last
        # stream. get_metrics() falls back to this when last_context_tokens is
        # zero, so keeping a stale value here makes a fresh session (after /new)
        # show the previous session's sys+tools overhead (e.g. ~3k tokens).
        self._last_sys_tokens = 0

    def get_metrics(self) -> Dict[str, Any]:
        ctx_used = getattr(self, "last_context_tokens", 0)
        if ctx_used <= 0:
            # Avoid expensive prompt/tool rebuilds (and MCP connections) on every
            # status-footer refresh: reuse the cached system+tools token count from
            # the last stream and add the current history estimate.
            sys_tok = getattr(self, "_last_sys_tokens", 0)
            hist_tok = self._current_history_tokens() if getattr(self, "history", None) else 0
            ctx_used = sys_tok + hist_tok
        return {
            "total_tokens": self.total_tokens,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "tokens_cache_read": getattr(self, "tokens_cache_read", 0),
            "context_used": ctx_used,
            "context": self.context_window,
            "context_limit": self.context_limit,
            "cost_usd": getattr(self, "cost_usd", 0.0),
        }

    def _accumulate_usage(
        self,
        step_usage: Optional[Dict[str, Any]] = None,
        prompt_tokens_est: int = 0,
        output_tokens_est: int = 0,
    ) -> None:
        accumulate_usage(self, step_usage, prompt_tokens_est, output_tokens_est)

    def _has_queued_messages(self) -> bool:
        return has_queued_messages(self)

    def _drain_queued_messages(self) -> List[Tuple[str, Any, bool, Any]]:
        return drain_queued_messages(self)
