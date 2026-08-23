import asyncio
import hashlib
import json
import logging
import os
import random
import time
from asyncio import Queue
from collections import OrderedDict
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional, Tuple

from openai import AsyncOpenAI

from core.application.generation.prompt_builder import DEFAULT_SYSTEM_PROMPT
from core.base_provider.compaction import CompactionMixin, should_compact
from core.base_provider.errors import ErrorHandlingMixin, format_api_error
from core.base_provider.tools import ToolMixin
from core.domain.defaults.errors import ToolResult
from core.infrastructure.adapters.base import (
    extract_image_payload,
    image_url_block,
    new_tool_call_id,
    parse_tool_call_args,
)
from core.infrastructure.presentation.tool_display import extract_tool_display
from core.infrastructure.runtime.thinking_effort import build_openai_thinking_kwargs, normalize_thinking_effort
from core.infrastructure.runtime.token_util import estimate_tokens, parse_usage
from core.models_catalog import catalog

logger = logging.getLogger(__name__)


def serialize_messages_key(msgs: List[Dict[str, Any]]) -> bytes:
    """Return a stable memoization key for a message list.

    Built only from the operationally-meaningful fields (role, content,
    tool_call_id, tool_calls), so two distinct histories can't alias a cache
    entry without also having identical payloads.
    """
    out = []
    for m in msgs:
        out.append(str(m.get("role")))
        c = m.get("content")
        if isinstance(c, str):
            out.append(c)
        elif c is None:
            out.append("")
        else:
            out.append(str(c))
        out.append(str(m.get("tool_call_id") or ""))
        tc = m.get("tool_calls")
        if tc and isinstance(tc, list):
            tc_parts = []
            for item in tc:
                if isinstance(item, dict):
                    fn = item.get("function") or {}
                    tc_parts.append(f"{item.get('id')}:{fn.get('name')}:{fn.get('arguments')}")
                else:
                    tc_parts.append(str(item))
            out.append("|".join(tc_parts))
        elif tc:
            out.append(str(tc))
        else:
            out.append("")
    return ("\x1f".join(out)).encode("utf-8")


# LRU memo cache for sanitize_history_for_model. The key is a compact serialized
# snapshot of the history and stores only the sanitized messages (never the deep
# input). Multi-tool turns call sanitize once per step with only a couple of
# messages appended per step, so the cached tail is reused and the O(history)
# pass runs once per turn instead of once per tool_result.
_SANITIZE_CACHE: "OrderedDict[bytes, List[Dict[str, Any]]]" = OrderedDict()
_SANITIZE_CACHE_MAX = 64


def _cache_sanitize_get(encoded_history: bytes) -> Optional[List[Dict[str, Any]]]:
    val = _SANITIZE_CACHE.get(encoded_history)
    if val is not None:
        _SANITIZE_CACHE.move_to_end(encoded_history)
    return val


def _cache_sanitize_put(encoded_history: bytes, sanitized: List[Dict[str, Any]]) -> None:
    _SANITIZE_CACHE[encoded_history] = sanitized
    while len(_SANITIZE_CACHE) > _SANITIZE_CACHE_MAX:
        _SANITIZE_CACHE.popitem(last=False)


async def sanitize_history_cached(agent: Any, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Memoized, event-loop-friendly ``sanitize_history_for_model``.

    Returns the cached result when the history is unchanged since the last call
    (the common case inside a multi-tool turn). On a miss, the O(history)
    sanitize pass is offloaded to a worker thread so it never blocks the UI
    event loop; the result (not the input) is stored in the LRU cache.
    """
    key = serialize_messages_key(history)
    cached = _cache_sanitize_get(key)
    if cached is not None:
        return cached
    sanitized = await asyncio.to_thread(agent.sanitize_history_for_model, history)
    _cache_sanitize_put(key, sanitized)
    return sanitized




class BaseAgent(CompactionMixin, ToolMixin, ErrorHandlingMixin):
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
        max_tokens: int = 8192,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        max_retry_delay: float = 10.0,
        tool_executor: Optional[Callable[[str, dict, Any], Awaitable[str]]] = None,
        default_tools_provider: Optional[Callable[[], List[Dict]]] = None,
        image_processor: Optional[Callable] = None,
        tool_name_normalizer: Optional[Callable[[str], str]] = None,
    ):
        if tools is None:
            tools = default_tools_provider() if default_tools_provider else []
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.system_prompt = system_prompt if system_prompt is not None else DEFAULT_SYSTEM_PROMPT
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

        client_kwargs = {"api_key": self.api_key or "sk-placeholder", "base_url": self.base_url}
        if self.headers:
            client_kwargs["default_headers"] = self.headers
        self.client = AsyncOpenAI(**client_kwargs)
        self.history = []
        self.app = None
        self.tokens_input = 0
        self.tokens_output = 0
        self.tokens_cache_read = 0
        self.last_context_tokens = 0
        self.total_tokens = 0
        self.cost_usd = 0.0
        self.role = "worker"
        self.tool_executor = tool_executor
        self.default_tools_provider = default_tools_provider
        self.image_processor = image_processor
        self.tool_name_normalizer = tool_name_normalizer
        # Per-agent memo for _tool_policy_error keyed by (id(role_def), tool_name).
        # The stream loop calls it once per tool call; without the memo the role
        # resolution + membership checks rerun for every tool_result.
        self._tool_policy_cache: Dict[tuple, Any] = {}

    async def close(self):
        if hasattr(self, "client") and self.client:
            await self.client.close()

    def clear_history(self):
        self.history.clear()
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
            hist_tok = estimate_tokens(self.history) if getattr(self, "history", None) else 0
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
        """Accumulates input/output/cache tokens and estimates USD cost based on model pricing."""
        pricing = catalog.get_model_pricing(self.provider_key, self.model)
        p_prompt = pricing.get("prompt", 0.0)
        p_comp = pricing.get("completion", 0.0)

        if step_usage and step_usage.get("total_tokens", 0) > 0:
            in_tok = step_usage.get("prompt_tokens", 0)
            out_tok = step_usage.get("completion_tokens", 0)
            cache_read_tok = step_usage.get("cache_read_tokens", 0)
            uncached_in = max(0, in_tok - cache_read_tok)

            # Cached input is discounted differently per provider:
            # Anthropic ~90% off (0.1x), OpenAI-compatible ~50% off (0.5x).
            cache_mult = 0.1 if getattr(self, "api_type", "openai") == "anthropic" else 0.5
            cost = uncached_in * p_prompt + cache_read_tok * (p_prompt * cache_mult) + out_tok * p_comp

            self.tokens_input += in_tok
            self.tokens_output += out_tok
            self.tokens_cache_read += cache_read_tok
            self.last_context_tokens = in_tok
            self.total_tokens += step_usage.get("total_tokens", in_tok + out_tok)
            self.cost_usd += cost
        else:
            self.tokens_input += prompt_tokens_est
            self.tokens_output += output_tokens_est
            self.last_context_tokens = prompt_tokens_est
            self.total_tokens += prompt_tokens_est + output_tokens_est
            self.cost_usd += prompt_tokens_est * p_prompt + output_tokens_est * p_comp

    async def _process_attachment_image(
        self, att_path: str, error_prefix: str = "Error processing attachment image"
    ) -> Optional[Dict[str, Any]]:
        if not self.image_processor:
            return None
        try:
            img_data_str = await asyncio.to_thread(self.image_processor, att_path)
            img_dict = json.loads(img_data_str) if isinstance(img_data_str, str) else img_data_str
            if isinstance(img_dict, dict) and img_dict.get("base64"):
                media_type = img_dict.get("media_type", "image/jpeg")
                b64_data = img_dict.get("base64")
                detail_val = img_dict.get("detail", "high")
                return image_url_block(media_type, b64_data, detail_val)
        except Exception as e:
            logger.warning("%s: %s", error_prefix, e)
        return None

    def _has_queued_messages(self) -> bool:
        """True if the queue has a message for the current session."""
        if getattr(self, "is_subagent", False):
            session = getattr(self, "session", None)
            if session is not None and getattr(session, "pending_messages", None):
                return True
            pending = getattr(self, "pending_messages", None)
            return bool(pending)
        app = getattr(self, "app", None)
        if app is None:
            return False
        mq = getattr(app, "message_queue", None)
        if not mq:
            return False
        sid = getattr(app, "current_session_id", None)
        for item in mq:
            item_sid = item[3] if len(item) > 3 else None
            if item_sid is None or sid is None or item_sid == sid:
                return True
        return False

    async def stream_steps(
        self, user_text: str, attachments: Optional[List[Any]] = None
    ) -> AsyncGenerator[Tuple[str, str, str], None]:
        # Kick off MCP tool warmup in the background WITHOUT blocking the first
        # user turn and WITHOUT cancelling it when that turn wins the race.
        # `ensure_tools_ready_async` coalesces concurrent callers and returns
        # already-cached tools when the warmup task is still running; the prompt
        # builder snapshots whatever MCP tools are ready at build time and the
        # still-running warmup fills the cache so a later turn picks the rest up.
        # A slow server (npx/uvx cold start) never stalls the send path.
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            from core.infrastructure.mcp import get_mcp_manager

            try:
                await get_mcp_manager().ensure_tools_ready_async(max_age=60.0)
            except Exception:
                pass
        from core.base_provider.tools import build_prompt_context_async

        sys_prompt, all_tools, sys_tokens = await build_prompt_context_async(self)
        self._last_sys_tokens = sys_tokens

        # Automatic context compaction when total context (system prompt + tools + history)
        # exceeds 75% of the context window, when switching to a smaller model (downshift),
        # or when system prompt/tool schemas changed significantly.
        from core.domain.defaults.config import CONTEXT_COMPACTION_THRESHOLD_RATIO, DEFAULT_CONTEXT_LIMIT

        cur_limit = getattr(self, "context_limit", DEFAULT_CONTEXT_LIMIT)
        threshold = int(cur_limit * CONTEXT_COMPACTION_THRESHOLD_RATIO)
        sys_overhead = getattr(self, "_last_sys_tokens", 0) or 0
        history_tokens = estimate_tokens(self.history) if self.history else 0
        total_tokens = sys_overhead + history_tokens

        # 1. Model Downshift detection
        last_limit = getattr(self, "_last_model_limit", None)
        self._last_model_limit = cur_limit
        model_downshift = last_limit is not None and last_limit > cur_limit and total_tokens > cur_limit

        # 2. Instruction / Tool schema hash change detection
        cur_hash = hashlib.sha256(f"{sys_prompt}:{repr(all_tools)}".encode("utf-8")).hexdigest()
        last_hash = getattr(self, "_last_comp_hash", None)
        self._last_comp_hash = cur_hash
        hash_changed = last_hash is not None and last_hash != cur_hash and len(self.history) > 4 and total_tokens > threshold * 0.8

        need_compact = should_compact(len(self.history), sys_overhead, history_tokens, threshold) or model_downshift or hash_changed
        self._compacted_count_this_turn = 0
        if need_compact:
            yield ("thinking", "Auto-compacting conversation history (context reached threshold)...", "")
            try:
                success, msg = await self.compact_history()
                if success:
                    divider_text = "Session Compacted"
                    if "(" in msg and ")" in msg:
                        divider_text = f"Session Compacted ({msg[msg.find('(') + 1: msg.rfind(')')]})"
                    yield ("event_divider", divider_text, "")
            except Exception as compact_err:
                yield ("thinking", f"Auto-compaction warning: {compact_err}", "")

        sanitized_history = await sanitize_history_cached(self, self.history)
        if attachments:
            user_content: List[Dict[str, Any]] = [{"type": "text", "text": user_text}]
            for att in attachments:
                att_path = getattr(att, "path", str(att))
                img_item = await self._process_attachment_image(att_path)
                if img_item:
                    user_content.append(img_item)
            messages = (
                [{"role": "system", "content": sys_prompt}]
                + sanitized_history
                + [{"role": "user", "content": user_content}]
            )
        else:
            messages = (
                [{"role": "system", "content": sys_prompt}]
                + sanitized_history
                + [{"role": "user", "content": user_text}]
            )

        try:
            while True:
                # Drain queued user messages between agent steps.
                if getattr(self, "is_subagent", False):
                    session = getattr(self, "session", None)
                    pending_list = None
                    if session is not None and hasattr(session, "pending_messages") and session.pending_messages:
                        pending_list = session.pending_messages
                    elif hasattr(self, "pending_messages") and self.pending_messages:
                        pending_list = self.pending_messages

                    if pending_list:
                        while pending_list:
                            item = pending_list.pop(0)
                            msg_text = item if isinstance(item, str) else item[0]
                            messages.append({"role": "user", "content": msg_text})
                            yield ("queued_user_message", msg_text, None, True)
                else:
                    app = getattr(self, "app", None)
                    if app is not None:
                        mq = getattr(app, "message_queue", None)
                        if mq:
                            sid = getattr(app, "current_session_id", None)
                            # Iterate over a snapshot so foreign-session items are left
                            # in place (no infinite loop) while own items are consumed.
                            # Single-pass drain: keep foreign-session items in place,
                            # consume own items. O(n) instead of list()+remove() O(n^2).
                            kept = []
                            for item in mq:
                                item_sid = item[3] if len(item) > 3 else None
                                if item_sid is not None and sid is not None and item_sid != sid:
                                    kept.append(item)
                                    continue
                                messages.append({"role": "user", "content": item[0]})
                                # Carry the queued item's display_text (item[4]) so the UI
                                # can render the short command instead of the full prompt text
                                # (e.g. "/skill-name" vs the expanded <SKILL ...> block).
                                yield (
                                    "queued_user_message",
                                    item[0],
                                    item[2] if len(item) > 2 else None,
                                    item[1],
                                    item[4] if len(item) > 4 else None,
                                )
                            mq[:] = kept

                step_usage = None
                prompt_tokens_est = estimate_tokens(messages)
                max_retries = getattr(self, "max_retries", 3)
                retry_delay = getattr(self, "retry_delay", 1.0)
                retry_backoff = getattr(self, "retry_backoff", 2.0)
                max_retry_delay = getattr(self, "max_retry_delay", 10.0)
                pkey = getattr(self, "provider_key", "default")

                from core.infrastructure.runtime.circuit_breaker import CircuitBreakerOpenError, circuit_breaker

                if not circuit_breaker.allow_request(pkey):
                    cb_rem = circuit_breaker.remaining_cooldown(pkey)
                    raise CircuitBreakerOpenError(pkey, cb_rem)

                attempt = 0
                while True:
                    attempt += 1
                    full_assistant_parts = []
                    active_thought_parts = []
                    step_usage = None
                    tool_calls_dict = {}
                    tool_call_arg_parts: Dict[int, List[str]] = {}
                    thinking_started = False
                    thinking_t0 = time.time()

                    try:
                        if getattr(self, "api_type", "openai") != "openai":
                            from core.adapters import get_adapter

                            adapter = get_adapter(self.api_type)
                            async for tag, payload in adapter.stream_chat(
                                self.base_url,
                                self.api_key,
                                self.model,
                                messages,
                                all_tools if all_tools else None,
                                max_tokens=getattr(self, "max_tokens", 4096),
                                thinking_effort=getattr(self, "thinking_effort", None),
                            ):
                                if tag == "adapter_text":
                                    if thinking_started:
                                        dt = time.time() - thinking_t0
                                        yield ("thinking_end", f"{dt}", "".join(active_thought_parts))
                                        thinking_started = False
                                    full_assistant_parts.append(payload)
                                    yield ("bot_delta", payload, "")
                                elif tag == "adapter_thought":
                                    if not thinking_started:
                                        yield ("thinking_start", "Thinking...", "")
                                        thinking_started = True
                                        thinking_t0 = time.time()
                                    active_thought_parts.append(payload)
                                    yield ("thinking_delta", payload, "")
                                elif tag == "adapter_tool_call":
                                    if thinking_started:
                                        dt = time.time() - thinking_t0
                                        yield ("thinking_end", f"{dt}", "".join(active_thought_parts))
                                        thinking_started = False
                                    idx = len(tool_calls_dict)
                                    tc_id = payload.get("id") or new_tool_call_id(idx)
                                    tool_calls_dict[idx] = {
                                        "id": tc_id,
                                        "name": payload.get("name", ""),
                                        "arguments": payload.get("arguments", "") or "",
                                    }
                                elif tag == "adapter_usage":
                                    step_usage = payload
                        else:
                            from core.adapters import format_messages_for_openai

                            formatted_messages = format_messages_for_openai(messages)
                            create_kwargs = {
                                "model": self.model,
                                "messages": formatted_messages,
                                "tools": all_tools if all_tools else None,
                                "stream": True,
                            }
                            e_body = dict(getattr(self, "extra_body", {}) or {})
                            if e_body:
                                create_kwargs["extra_body"] = e_body
                            create_kwargs.update(build_openai_thinking_kwargs(getattr(self, "thinking_effort", None)))

                            try:
                                response = await self.client.chat.completions.create(
                                    **create_kwargs, stream_options={"include_usage": True}
                                )
                            except Exception as create_err:
                                c_err_str = str(create_err).lower()
                                if (
                                    "stream_options" in c_err_str
                                    or "extra" in c_err_str
                                    or isinstance(create_err, TypeError)
                                ):
                                    if "reasoning_effort" in c_err_str or isinstance(create_err, TypeError):
                                        create_kwargs.pop("reasoning_effort", None)
                                    response = await self.client.chat.completions.create(**create_kwargs)
                                else:
                                    raise create_err

                            stream_iter = response.__aiter__()
                            chunk_to = getattr(self, "chunk_timeout", 30.0) or 30.0
                            # Single producer task pulls chunks off the provider; the
                            # consumer polls the queue with a watchdog deadline so we
                            # keep per-chunk timeouts without creating a task per chunk.
                            _chunk_queue: "Queue[Any]" = Queue(maxsize=64)
                            _DONE = object()

                            async def _produce_chunks():
                                try:
                                    async for chunk in stream_iter:
                                        await _chunk_queue.put(chunk)
                                except asyncio.CancelledError:
                                    raise
                                except Exception as exc:
                                    await _chunk_queue.put(exc)
                                finally:
                                    await _chunk_queue.put(_DONE)

                            producer_task = asyncio.ensure_future(_produce_chunks())
                            try:
                                while True:
                                    try:
                                        item = await asyncio.wait_for(
                                            _chunk_queue.get(), timeout=chunk_to
                                        )
                                    except asyncio.TimeoutError:
                                        producer_task.cancel()
                                        raise RuntimeError(
                                            f"Stream chunk timeout: No response received from provider '{self.provider_key}' for {chunk_to}s."
                                        )
                                    if item is _DONE:
                                        break
                                    if isinstance(item, Exception):
                                        raise item
                                    chunk = item

                                    if getattr(chunk, "usage", None):
                                        step_usage = parse_usage(chunk.usage)

                                    chunk_is_dict = isinstance(chunk, dict)
                                    choices = (
                                        getattr(chunk, "choices", None)
                                        if not chunk_is_dict
                                        else chunk.get("choices")
                                    )
                                    if not choices and (
                                        hasattr(chunk, "data") or (chunk_is_dict and "data" in chunk)
                                    ):
                                        d = (
                                            getattr(chunk, "data", None)
                                            if not chunk_is_dict
                                            else chunk.get("data")
                                        )
                                        choices = (
                                            d.get("choices") if isinstance(d, dict) else getattr(d, "choices", None)
                                        )
                                    if not choices:
                                        continue
                                    choice = choices[0]
                                    delta = choice.delta
                                    reasoning = (
                                        getattr(delta, "reasoning_content", None)
                                        or getattr(delta, "reasoning", None)
                                        or (getattr(delta, "model_extra", {}) or {}).get("reasoning_content")
                                        or (getattr(delta, "model_extra", {}) or {}).get("reasoning")
                                    )
                                    if reasoning:
                                        if not thinking_started:
                                            yield ("thinking_start", "Thinking...", "")
                                            thinking_started = True
                                            thinking_t0 = time.time()
                                        active_thought_parts.append(str(reasoning))
                                        yield ("thinking_delta", str(reasoning), "")

                                    if delta.content:
                                        if thinking_started:
                                            dt = time.time() - thinking_t0
                                            yield ("thinking_end", f"{dt}", "".join(active_thought_parts))
                                            thinking_started = False
                                        full_assistant_parts.append(delta.content)
                                        yield ("bot_delta", delta.content, "")

                                    if delta.tool_calls:
                                        if thinking_started:
                                            dt = time.time() - thinking_t0
                                            yield ("thinking_end", f"{dt}", "".join(active_thought_parts))
                                            thinking_started = False

                                        for tc in delta.tool_calls:
                                            idx = tc.index
                                            if idx not in tool_calls_dict:
                                                tool_calls_dict[idx] = {"id": tc.id, "name": "", "arguments": ""}
                                            if tc.id:
                                                tool_calls_dict[idx]["id"] = tc.id
                                            if tc.function:
                                                if tc.function.name:
                                                    tool_calls_dict[idx]["name"] = tc.function.name
                                                if tc.function.arguments:
                                                    tool_call_arg_parts.setdefault(idx, []).append(
                                                        tc.function.arguments
                                                    )
                            finally:
                                if not producer_task.done():
                                    producer_task.cancel()

                            # Resolve streamed tool-call argument fragments once.
                            for _idx, _parts in tool_call_arg_parts.items():
                                tool_calls_dict[_idx]["arguments"] = "".join(_parts)
                        # Stream completed successfully
                        circuit_breaker.record_success(pkey)
                        break
                    except asyncio.CancelledError:
                        for _idx, _parts in tool_call_arg_parts.items():
                            tool_calls_dict[_idx]["arguments"] = "".join(_parts)
                        output_est = (
                            estimate_tokens("".join(full_assistant_parts))
                            + estimate_tokens("".join(active_thought_parts))
                            + estimate_tokens(tool_calls_dict)
                        )
                        self._accumulate_usage(
                            step_usage=step_usage, prompt_tokens_est=prompt_tokens_est, output_tokens_est=output_est
                        )
                        raise
                    except Exception as api_err:
                        if self._is_vision_error(api_err):
                            sanitized = self._sanitize_vision_error_messages(messages)
                            if len(sanitized) != len(messages) or any(s != m for s, m in zip(sanitized, messages)):
                                messages = sanitized
                                yield (
                                    "thinking",
                                    "Model does not support vision; converted image tool result to hint.",
                                    "",
                                )
                                continue

                        is_retryable = self._is_retryable_error(api_err)
                        if is_retryable and attempt < max_retries:
                            retry_after = self._extract_retry_after(api_err)
                            if retry_after is not None and retry_after > 0:
                                actual_delay = min(max_retry_delay, max(retry_delay, retry_after))
                            else:
                                delay = min(max_retry_delay, retry_delay * (retry_backoff ** (attempt - 1)))
                                jitter = random.uniform(0, 0.5 * delay)
                                actual_delay = delay + jitter
                            if full_assistant_parts:
                                # Signal the UI to drop the partially-streamed text so the
                                # retried attempt starts from a blank reply (no duplication).
                                yield ("bot_reset", "", "")
                            yield ("retry", attempt, max_retries, actual_delay, api_err)
                            await asyncio.sleep(actual_delay)
                            continue

                        circuit_breaker.record_failure(pkey)
                        raise api_err

                output_tokens_est = (
                    estimate_tokens("".join(full_assistant_parts))
                    + estimate_tokens("".join(active_thought_parts))
                    + estimate_tokens(tool_calls_dict)
                )
                self._accumulate_usage(
                    step_usage=step_usage, prompt_tokens_est=prompt_tokens_est, output_tokens_est=output_tokens_est
                )

                if thinking_started:
                    dt = time.time() - thinking_t0
                    yield ("thinking_end", f"{dt}", "".join(active_thought_parts))
                    thinking_started = False

                if not tool_calls_dict:
                    full_assistant_text_final = "".join(full_assistant_parts)
                    final_msg: Dict[str, Any] = {
                        "role": "assistant",
                        "content": full_assistant_text_final,
                        "reasoning_content": "".join(active_thought_parts),
                    }
                    messages.append(final_msg)
                    yield ("bot_text", full_assistant_text_final, "")
                    # If user messages were queued during this turn, keep going
                    # so the next while-iteration drains them as new steps.
                    if self._has_queued_messages():
                        continue
                    break

                # Execute tool calls in the order the model emitted them. Dict insertion
                # order usually matches, but delta tool_calls can arrive out of order on
                # some providers, so sort explicitly by the tool-call index key.
                ordered_calls = [tool_calls_dict[k] for k in sorted(tool_calls_dict.keys())]

                cleaned_tool_calls = []
                for tc in ordered_calls:
                    raw_args = tc.get("arguments", "{}")
                    if not isinstance(raw_args, str):
                        raw_args = json.dumps(raw_args)
                    cleaned_tool_calls.append(
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": raw_args},
                        }
                    )

                assistant_tool_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": "".join(full_assistant_parts) or None,
                    "tool_calls": cleaned_tool_calls,
                    "reasoning_content": "".join(active_thought_parts),
                }
                messages.append(assistant_tool_msg)

                for tc in ordered_calls:
                    t_id = tc["id"]
                    t_name = tc["name"]
                    raw_args = tc["arguments"]

                    # parse_tool_call_args (shared with adapters) parses the
                    # arguments; malformed JSON is normalized to {} by design.
                    _, args = parse_tool_call_args({"function": {"name": t_name, "arguments": raw_args}})

                    target = extract_tool_display(t_name, args)
                    yield ("tool", t_name, target, args)

                    from core.role_registry import RoleRegistry

                    current_role = getattr(self, "role", "worker").lower()
                    role_def = RoleRegistry.get_instance().get_role(current_role)

                    policy_err = self._tool_policy_error(t_name, role_def)
                    if policy_err:
                        tool_result: Any = policy_err
                    else:
                        tool_result = None

                    if tool_result is None:
                        if self.tool_executor:
                            try:
                                tool_result = await self.tool_executor(t_name, args, self)
                            except Exception as e:
                                tool_result = ToolResult.error("execute", detail=str(e), name=t_name)
                        else:
                            tool_result = ToolResult.error("error", "tool_executor not provided", t_name)

                    resolved = self._normalize_tool_result(tool_result)

                    source_for_image = resolved.content if isinstance(tool_result, ToolResult) else tool_result
                    display_result = tool_result
                    parsed_img = extract_image_payload(source_for_image)
                    if parsed_img is not None and parsed_img.get("type") == "image":
                        display_result = parsed_img.get("summary", f"[Image file: {parsed_img.get('path')}]")
                    elif isinstance(tool_result, ToolResult):
                        display_result = resolved.content or ""

                    yield (
                        "tool_result",
                        display_result,
                        "",
                        resolved.is_error,
                        resolved.status,
                        resolved.returncode,
                    )

                    messages.append({"role": "tool", "tool_call_id": t_id, "content": resolved.content or ""})

                # Per-step copy of the transcript for the next provider request.
                # Recomputing the full ``messages[1:]`` slice on every tool_result
                # was a repeated O(history) allocation on the UI thread; build it
                # once here and reuse the latest slice on the next iteration.
                history_snapshot = await asyncio.to_thread(list, messages[1:])
                self.history = history_snapshot
                compacted_count = getattr(self, "_compacted_count_this_turn", 0)
                if compacted_count < 10:
                    messages, compacted_in_loop, compact_msg = await self._compact_messages_if_needed(
                        messages, self._last_sys_tokens, threshold
                    )
                else:
                    compacted_in_loop, compact_msg = False, ""

                if compacted_in_loop:
                    self._compacted_count_this_turn = compacted_count + 1
                    divider_text = "Session Compacted"
                    if "(" in compact_msg and ")" in compact_msg:
                        divider_text = f"Session Compacted ({compact_msg[compact_msg.find('(') + 1: compact_msg.rfind(')')]})"
                    yield ("event_divider", divider_text, "")
                    yield ("thinking", "Context budget reached; compacted earlier tool history before continuing.", "")

        except Exception as err:
            error_msg = format_api_error(err)
            clean_msg = error_msg.replace("**API Error:**", "API Error:").replace("**", "").replace("`", "").strip()
            clean_msg = " ".join(clean_msg.split())
            yield ("event_divider", clean_msg, "")
        finally:
            if len(messages) > 1:
                self.history = await sanitize_history_cached(self, messages[1:])
