import asyncio
import hashlib
import json
import logging
import os
import time
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional, Tuple

from core.base_provider.compaction import (
    CompactionMixin,
    format_compaction_title,
    resolve_auto_compact_limit,
    should_compact,
)
from core.base_provider.errors import ErrorHandlingMixin, format_api_error
from core.base_provider.history_cache import (
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
from core.base_provider.message_queue import drain_queued_messages, has_queued_messages
from core.base_provider.tools import ToolMixin
from core.base_provider.usage import accumulate_usage
from core.domain.defaults.config import DEFAULT_MAX_TOKENS, ESCALATED_MAX_TOKENS
from core.domain.defaults.errors import ToolResult
from core.domain.defaults.prompts import DEFAULT_SYSTEM_PROMPT
from core.infrastructure.adapters.base import (
    build_stream_kwargs,
    extract_image_payload,
    image_url_block,
    new_tool_call_id,
    normalize_tool_arguments_str,
    parse_tool_call_args,
)
from core.infrastructure.runtime.thinking_effort import normalize_thinking_effort
from core.infrastructure.runtime.token_util import estimate_message_tokens, estimate_tokens

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
        self._history_len = 0
        self.app = None
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
    def role_name(self) -> str:
        if getattr(self, "_role_name", None):
            return self._role_name
        from core.role_registry import resolve_role_display_name

        pdir = getattr(getattr(self, "app", None), "project_dir", None)
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

    async def _execute_single_tool(self, tc: dict, role_def: Any) -> tuple[str, Any, Any]:
        """Execute a single tool call and return (tool_call_id, display_result, resolved_tool_result)."""
        t_id = tc["id"]
        t_name = tc["name"]
        raw_args = tc.get("arguments", "{}")
        _, args = parse_tool_call_args({"function": {"name": t_name, "arguments": raw_args}})

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

        resolved = await self._normalize_tool_result(tool_result)

        source_for_image = resolved.content if isinstance(tool_result, ToolResult) else tool_result
        display_result = tool_result
        parsed_img = extract_image_payload(source_for_image)
        if parsed_img is not None and parsed_img.get("type") == "image":
            display_result = parsed_img.get("summary", f"[Image file: {parsed_img.get('path')}]")
        elif isinstance(tool_result, ToolResult):
            display_result = resolved.display if resolved.display is not None else (resolved.content or "")

        return t_id, display_result, resolved

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
        return has_queued_messages(self)

    def _drain_queued_messages(self) -> List[Tuple[str, Any, bool, Any]]:
        return drain_queued_messages(self)

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
        from core.domain.defaults.config import DEFAULT_CONTEXT_LIMIT
        from core.infrastructure.config.settings import get_settings

        cur_limit = getattr(self, "context_limit", DEFAULT_CONTEXT_LIMIT)
        settings = get_settings()
        compaction_ratio = settings.llm.compaction_threshold_ratio
        threshold = int(cur_limit * compaction_ratio)
        compact_limit = resolve_auto_compact_limit(self)
        if compact_limit is not None and compact_limit > 0:
            threshold = min(threshold, compact_limit)
        sys_overhead = getattr(self, "_last_sys_tokens", 0) or 0
        history_tokens = self._current_history_tokens() if self.history else 0
        total_tokens = sys_overhead + history_tokens

        # 1. Model Downshift detection
        last_limit = getattr(self, "_last_model_limit", None)
        self._last_model_limit = cur_limit
        model_downshift = last_limit is not None and last_limit > cur_limit and total_tokens > cur_limit

        # 2. Instruction / Tool schema hash change detection
        tools_digest = _get_tools_digest(all_tools)
        cur_hash = hashlib.sha256(f"{sys_prompt}:{tools_digest}".encode("utf-8")).hexdigest()
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
                    yield ("event_divider", format_compaction_title(msg), "")
                else:
                    yield ("event_divider", "Compaction Failed", "")
            except Exception as compact_err:
                yield ("thinking", f"Auto-compaction warning: {compact_err}", "")

        sanitized_history = await sanitize_history_cached(self, self.history)
        if attachments:
            att_paths = [getattr(att, "path", str(att)) for att in attachments if getattr(att, "path", str(att))]
            header_parts = []
            if len(att_paths) == 1:
                header_parts.append(f"[Attached: {att_paths[0]}]")
            elif len(att_paths) > 1:
                items_str = "\n".join(f"- {p}" for p in att_paths)
                header_parts.append(f"[Attached:\n{items_str}]")

            if user_text and user_text.strip():
                header_parts.append(user_text.strip())

            text_content = "\n\n".join(header_parts) if header_parts else "What is in this image?"
            user_content: List[Dict[str, Any]] = [{"type": "text", "text": text_content}]
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

        # Sync self.history to messages[1:] (history sans the system prefix) once
        # per turn so the incremental token accumulator and in-place appends below
        # keep self.history == messages[1:] through the multi-step loop.
        self._set_history(messages[1:])

        try:
            while True:
                # Drain queued user messages between agent steps.
                for msg_text, atts, show_ui, disp_text in self._drain_queued_messages():
                    messages.append({"role": "user", "content": msg_text})
                    self._append_history(messages[-1])
                    yield ("queued_user_message", msg_text, atts, show_ui, disp_text)

                step_usage = None
                # messages = [system] + self.history (invariant maintained below), so
                # estimate_tokens(messages) == estimate_message_tokens(messages[0]) +
                # self._history_tokens. Only the single system message is walked here;
                # the full-history O(n) walk is avoided on every step. Guard for an
                # empty messages list (defensive; e.g. a mocked no-op compaction).
                prompt_tokens_est = (
                    estimate_message_tokens(messages[0]) + self._current_history_tokens() if messages else 0
                )
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
                current_max_tokens = getattr(self, "max_tokens", DEFAULT_MAX_TOKENS)
                thinking_started = False
                thinking_t0 = time.time()
                last_thought_parts = []
                while True:
                    attempt += 1
                    full_assistant_parts = []
                    active_thought_parts = []
                    step_usage = None
                    tool_calls_dict = {}
                    generating_tools = {}
                    last_finish_reason = None

                    try:
                        from core.adapters import get_adapter

                        adapter = get_adapter(self.api_type)
                        stream_kwargs = build_stream_kwargs(
                            self,
                            messages=messages,
                            tools=all_tools if all_tools else None,
                            max_tokens=current_max_tokens,
                            thinking_effort=getattr(self, "thinking_effort", None),
                        )
                        if self.api_type == "openai":
                            stream_kwargs["chunk_timeout"] = getattr(self, "chunk_timeout", 30.0)
                            stream_kwargs["provider_key"] = getattr(self, "provider_key", "openai")

                        async for tag, payload in adapter.stream_chat(**stream_kwargs):
                            if tag == "adapter_text":
                                if thinking_started:
                                    dt = time.time() - thinking_t0
                                    thoughts_str = "".join(active_thought_parts) or "".join(last_thought_parts)
                                    yield ("thinking_end", f"{dt}", thoughts_str)
                                    thinking_started = False
                                full_assistant_parts.append(payload)
                                yield ("bot_delta", payload, "")
                            elif tag == "adapter_thought":
                                if not payload or (isinstance(payload, str) and not payload.strip()):
                                    continue
                                if not thinking_started:
                                    yield ("thinking_start", "Thinking...", "")
                                    thinking_started = True
                                    thinking_t0 = time.time()
                                active_thought_parts.append(payload)
                                yield ("thinking_delta", payload, "")
                            elif tag == "adapter_tool_delta":
                                if thinking_started:
                                    dt = time.time() - thinking_t0
                                    thoughts_str = "".join(active_thought_parts) or "".join(last_thought_parts)
                                    yield ("thinking_end", f"{dt}", thoughts_str)
                                    thinking_started = False
                                idx = payload.get("index", 0)
                                if idx not in generating_tools:
                                    generating_tools[idx] = {
                                        "id": payload.get("id") or new_tool_call_id(idx),
                                        "name": payload.get("name", ""),
                                        "args_buffer": "",
                                        "target": "",
                                        "announced": False,
                                        "target_announced": False,
                                    }
                                g = generating_tools[idx]
                                if payload.get("id"):
                                    g["id"] = payload["id"]
                                if payload.get("name"):
                                    g["name"] = payload["name"]
                                delta_args = payload.get("arguments_delta", "")
                                if delta_args:
                                    g["args_buffer"] += delta_args

                                if g["args_buffer"]:
                                    new_target = _extract_streaming_target(
                                        g["args_buffer"], scan_from=g.get("args_scan_pos", 0), tool_name=g.get("name", "")
                                    )
                                    if new_target and new_target != g["target"]:
                                        g["target"] = new_target
                                        if g["announced"]:
                                            yield ("tool_generating_update", g["name"], g["target"], {"id": g["id"], "index": idx})
                                g["args_scan_pos"] = len(g["args_buffer"])

                                if g["name"] and not g["announced"]:
                                    g["announced"] = True
                                    yield ("tool_generating", g["name"], g["target"], {"id": g["id"], "index": idx})
                            elif tag == "adapter_tool_call":
                                if thinking_started:
                                    dt = time.time() - thinking_t0
                                    thoughts_str = "".join(active_thought_parts) or "".join(last_thought_parts)
                                    yield ("thinking_end", f"{dt}", thoughts_str)
                                    thinking_started = False
                                # Key by the provider's delta index (now carried in
                                # the payload) so the final call maps onto the same
                                # generating_tools slot its deltas announced — even
                                # when parallel calls finish out of order. Without an
                                # index (legacy adapter mocks), fall back to arrival
                                # order, which is what older adapters guaranteed.
                                idx = payload.get("index")
                                if idx is None:
                                    idx = len(tool_calls_dict)
                                tc_id = payload.get("id") or (
                                    generating_tools.get(idx, {}).get("id") if idx in generating_tools else None
                                ) or new_tool_call_id(idx)
                                tool_calls_dict[idx] = {
                                    "id": tc_id,
                                    "name": payload.get("name", ""),
                                    "arguments": payload.get("arguments", "") or "",
                                }
                            elif tag == "adapter_finish_reason":
                                last_finish_reason = payload
                            elif tag == "adapter_usage":
                                step_usage = payload

                        if active_thought_parts:
                            last_thought_parts = active_thought_parts

                        # Check for empty response caused by max tokens cutoff
                        is_token_limit = (
                            last_finish_reason is not None
                            and str(last_finish_reason).upper() in ("MAX_TOKENS", "LENGTH", "MAX_OUTPUT_TOKENS")
                        )
                        if not tool_calls_dict and not full_assistant_parts:
                            if is_token_limit or active_thought_parts:
                                if attempt < max_retries and current_max_tokens < ESCALATED_MAX_TOKENS:
                                    current_max_tokens = min(ESCALATED_MAX_TOKENS, max(current_max_tokens * 2, 65536))
                                    logger.info(
                                        "Token limit reached during reasoning on attempt %d; escalating max_tokens to %d and retrying...",
                                        attempt,
                                        current_max_tokens,
                                    )
                                    continue
                                raise RuntimeError(
                                    "Token limit reached during reasoning without generating response text. Try increasing max_tokens or lowering thinking effort."
                                )

                        # Stream completed successfully
                        circuit_breaker.record_success(pkey)
                        break
                    except asyncio.CancelledError:
                        output_est = (
                            estimate_tokens("".join(full_assistant_parts))
                            + estimate_tokens("".join(active_thought_parts) or "".join(last_thought_parts))
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
                                # Sanitize re-allocates message dicts; resync the
                                # accumulator to the new messages[1:] prefix.
                                self._set_history(messages[1:])
                                yield (
                                    "thinking",
                                    "Model does not support vision; converted image tool result to hint.",
                                    "",
                                )
                                continue

                        is_retryable = self._is_retryable_error(api_err)
                        if is_retryable and attempt < max_retries:
                            actual_delay = self._calculate_retry_delay(
                                attempt,
                                api_err,
                                retry_delay=retry_delay,
                                retry_backoff=retry_backoff,
                                max_retry_delay=max_retry_delay,
                            )
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
                    + estimate_tokens("".join(active_thought_parts) or "".join(last_thought_parts))
                    + estimate_tokens(tool_calls_dict)
                )
                self._accumulate_usage(
                    step_usage=step_usage, prompt_tokens_est=prompt_tokens_est, output_tokens_est=output_tokens_est
                )

                if thinking_started:
                    dt = time.time() - thinking_t0
                    thoughts_str = "".join(active_thought_parts) or "".join(last_thought_parts)
                    yield ("thinking_end", f"{dt}", thoughts_str)
                    thinking_started = False

                if not tool_calls_dict:
                    full_assistant_text_final = "".join(full_assistant_parts)
                    final_msg: Dict[str, Any] = {
                        "role": "assistant",
                        "content": full_assistant_text_final,
                        "reasoning_content": "".join(active_thought_parts),
                    }
                    messages.append(final_msg)
                    self._append_history(final_msg)
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
                    raw_args = normalize_tool_arguments_str(tc.get("arguments", "{}"))
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
                self._append_history(assistant_tool_msg)

                from core.role_registry import RoleRegistry

                current_role = getattr(self, "role", "worker").lower()
                role_def = RoleRegistry.get_instance().get_role(current_role)

                # Partition tool calls into batches: consecutive concurrency-safe
                # tools run in parallel via asyncio.gather; mutating/barrier tools
                # execute sequentially.
                batches: list[tuple[bool, list[tuple[dict, Any]]]] = []
                for tc in ordered_calls:
                    raw_args = tc.get("arguments", "{}")
                    _, parsed_args = parse_tool_call_args({"function": {"name": tc["name"], "arguments": raw_args}})
                    is_safe = self._is_tool_concurrency_safe(tc["name"], parsed_args if isinstance(parsed_args, dict) else None)
                    if batches and batches[-1][0] and is_safe:
                        batches[-1][1].append((tc, parsed_args))
                    else:
                        batches.append((is_safe, [(tc, parsed_args)]))

                for is_safe, batch in batches:
                    if is_safe and len(batch) > 1:
                        # Concurrent batch: announce all tool cards first
                        for tc, args in batch:
                            t_name = tc["name"]
                            target = (
                                (args.get("path") or args.get("command") or args.get("url") or "")
                                if isinstance(args, dict)
                                else ""
                            )
                            yield ("tool", t_name, str(target), args, tc.get("id"))

                        # Execute concurrently and preserve original order
                        batch_results = await asyncio.gather(*(self._execute_single_tool(tc, role_def) for tc, _ in batch))
                        for t_id, display_result, resolved in batch_results:
                            yield (
                                "tool_result",
                                display_result,
                                "",
                                resolved.is_error,
                                resolved.status,
                                resolved.returncode,
                                t_id,
                            )
                            messages.append(
                                {"role": "tool", "name": t_name, "tool_call_id": t_id, "content": resolved.content or ""}
                            )
                            self._append_history(messages[-1])
                    else:
                        # Sequential execution (single tool or mutating barrier)
                        for tc, args in batch:
                            t_name = tc["name"]
                            target = (
                                (args.get("path") or args.get("command") or args.get("url") or "")
                                if isinstance(args, dict)
                                else ""
                            )
                            yield ("tool", t_name, str(target), args, tc.get("id"))

                            t_id, display_result, resolved = await self._execute_single_tool(tc, role_def)
                            yield (
                                "tool_result",
                                display_result,
                                "",
                                resolved.is_error,
                                resolved.status,
                                resolved.returncode,
                                t_id,
                            )
                            messages.append(
                                {"role": "tool", "name": t_name, "tool_call_id": t_id, "content": resolved.content or ""}
                            )
                            self._append_history(messages[-1])


                # self.history was maintained incrementally via _append_history
                # throughout this iteration (queued users, assistant msg, tool
                # results), so no full messages[1:] copy is needed here. Only a
                # mid-loop compaction (below) replaces the prefix and forces a
                # wholesale resync.
                compacted_count = getattr(self, "_compacted_count_this_turn", 0)
                if compacted_count < 10:
                    messages, compacted_in_loop, compact_msg = await self._compact_messages_if_needed(
                        messages, self._last_sys_tokens, threshold
                    )
                else:
                    compacted_in_loop, compact_msg = False, ""

                if compacted_in_loop:
                    self._compacted_count_this_turn = compacted_count + 1
                    # Compaction replaced the messages prefix (self.history is now
                    # the compacted history but messages[1:] is a re-sanitization of
                    # it); resync the accumulator so self.history == messages[1:]
                    # holds for the next step's estimate.
                    self._set_history(messages[1:])
                    yield ("event_divider", format_compaction_title(compact_msg), "")

        except Exception as err:
            logger.exception("API request failed: %s", err)
            error_msg = format_api_error(err)
            clean_msg = error_msg.replace("**API Error:**", "API Error:").replace("**", "").replace("`", "").strip()
            clean_msg = " ".join(clean_msg.split())
            yield ("error", clean_msg, "")
        finally:
            if len(messages) > 1:
                sanitized = await sanitize_history_cached(self, messages[1:])
                self._set_history(sanitized)
