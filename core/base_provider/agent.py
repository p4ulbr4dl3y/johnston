import asyncio
import json
import logging
import os
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from openai import AsyncOpenAI

from core.adapters.base import parse_tool_call_args
from core.base_provider.compaction import CompactionMixin
from core.base_provider.errors import ErrorHandlingMixin, format_api_error
from core.base_provider.tools import ToolMixin
from core.models_catalog import catalog
from core.prompt_builder import DEFAULT_SYSTEM_PROMPT, PromptBuilder
from core.thinking_effort import build_openai_thinking_kwargs, normalize_thinking_effort
from core.token_util import estimate_tokens, parse_usage
from core.tool_display import extract_tool_display
from tools.base import format_tool_error
from tools.registry import execute_tool

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
        max_tokens: int = 8192,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        max_retry_delay: float = 10.0,
    ):
        if tools is None:
            from tools.registry import get_default_tools

            tools = get_default_tools()
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
        self.mode = "act"

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

    @staticmethod
    async def _process_attachment_image(
        att_path: str, error_prefix: str = "Error processing attachment image"
    ) -> Optional[Dict[str, Any]]:
        try:
            from tools.read import process_image_file_sync

            img_data_str = await asyncio.to_thread(process_image_file_sync, att_path)
            img_dict = json.loads(img_data_str) if isinstance(img_data_str, str) else img_data_str
            if isinstance(img_dict, dict) and img_dict.get("base64"):
                media_type = img_dict.get("media_type", "image/jpeg")
                b64_data = img_dict.get("base64")
                detail_val = img_dict.get("detail", "high")
                return {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{b64_data}", "detail": detail_val},
                }
        except Exception as e:
            logger.warning("%s: %s", error_prefix, e)
        return None

    def _has_queued_messages(self) -> bool:
        """True if the main app's queue has a message for the current session."""
        app = getattr(self, "app", None)
        if app is None or getattr(self, "is_subagent", False):
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
        agent_mode = getattr(self, "mode", "act")
        allow_task = getattr(self, "allow_task", True)
        m_name = catalog.get_model_display_name(
            getattr(self, "provider_key", ""), getattr(self, "model", "")
        ) or getattr(self, "model", "")
        # Kick off MCP tool warmup in the background WITHOUT blocking the first
        # user turn and WITHOUT cancelling it when that turn wins the race.
        # `ensure_tools_ready_async` coalesces concurrent callers and returns
        # already-cached tools when the warmup task is still running; the prompt
        # builder snapshots whatever MCP tools are ready at build time and the
        # still-running warmup fills the cache so a later turn picks the rest up.
        # A slow server (npx/uvx cold start) never stalls the send path.
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            from core.mcp_manager import get_mcp_manager

            try:
                await get_mcp_manager().ensure_tools_ready_async(max_age=60.0)
            except Exception:
                pass
        is_subagent = getattr(self, "is_subagent", False)
        builder = PromptBuilder(
            self.system_prompt,
            self.tools,
            mode=agent_mode,
            allow_task=allow_task,
            model_name=m_name,
            cwd=getattr(self, "cwd", None),
            is_subagent=is_subagent,
        )
        sys_prompt = builder.build_system_prompt()
        all_tools = builder.build_tools(
            provider_key=getattr(self, "provider_key", ""), model_id=getattr(self, "model", "")
        )
        self._last_sys_tokens = estimate_tokens(sys_prompt) + estimate_tokens(all_tools)

        # Automatic context compaction when total context (system prompt + tools + history)
        # exceeds 75% of the context window. Counting history alone ignores the system
        # prompt / tool schema overhead (often 2-4k tokens), which would let the real
        # context silently overflow before this threshold ever triggers.
        from core.defaults.config import CONTEXT_COMPACTION_THRESHOLD_RATIO, DEFAULT_CONTEXT_LIMIT

        threshold = int(getattr(self, "context_limit", DEFAULT_CONTEXT_LIMIT) * CONTEXT_COMPACTION_THRESHOLD_RATIO)
        sys_overhead = getattr(self, "_last_sys_tokens", 0) or 0
        compacted_this_turn = False
        if len(self.history) > 4 and (estimate_tokens(self.history) + sys_overhead) > threshold:
            yield ("thinking", "Auto-compacting conversation history (context reached threshold)...", "")
            try:
                success, _ = await self.compact_history()
                if success:
                    compacted_this_turn = True
                    yield ("event_divider", "Session Compacted", "")
            except Exception as compact_err:
                yield ("thinking", f"Auto-compaction warning: {compact_err}", "")

        sanitized_history = self.sanitize_history_for_model(self.history)
        if attachments:
            user_content: List[Dict[str, Any]] = [{"type": "text", "text": user_text}]
            for idx, att in enumerate(attachments):
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
                # Drain queued user messages between agent steps (main app only).
                app = getattr(self, "app", None)
                if app is not None and not getattr(self, "is_subagent", False):
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
                            yield ("queued_user_message", item[0], item[2] if len(item) > 2 else None, item[1])
                        mq[:] = kept

                full_assistant_text = ""
                step_usage = None
                prompt_tokens_est = estimate_tokens(messages)
                max_retries = getattr(self, "max_retries", 3)
                retry_delay = getattr(self, "retry_delay", 1.0)
                retry_backoff = getattr(self, "retry_backoff", 2.0)
                max_retry_delay = getattr(self, "max_retry_delay", 10.0)
                pkey = getattr(self, "provider_key", "default")

                from core.circuit_breaker import CircuitBreakerOpenError, circuit_breaker

                if not circuit_breaker.allow_request(pkey):
                    cb_rem = circuit_breaker.remaining_cooldown(pkey)
                    raise CircuitBreakerOpenError(pkey, cb_rem)

                attempt = 0
                while True:
                    attempt += 1
                    full_assistant_parts = []
                    active_thought_parts = []
                    full_assistant_text = ""
                    step_usage = None
                    tool_calls_dict = {}
                    tool_call_arg_parts: Dict[int, List[str]] = {}
                    active_thought = ""
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
                                        yield ("thinking_end", f"{dt}", active_thought)
                                        thinking_started = False
                                    full_assistant_parts.append(payload)
                                    full_assistant_text = "".join(full_assistant_parts)
                                    yield ("bot_delta", payload, "")
                                elif tag == "adapter_thought":
                                    if not thinking_started:
                                        yield ("thinking_start", "Thinking...", "")
                                        thinking_started = True
                                        thinking_t0 = time.time()
                                    active_thought_parts.append(payload)
                                    active_thought = "".join(active_thought_parts)
                                    yield ("thinking_delta", payload, "")
                                elif tag == "adapter_tool_call":
                                    if thinking_started:
                                        dt = time.time() - thinking_t0
                                        yield ("thinking_end", f"{dt}", active_thought)
                                        thinking_started = False
                                    idx = len(tool_calls_dict)
                                    tc_id = payload.get("id") or f"call_{idx}"
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
                            from asyncio import Queue

                            _chunk_queue: "Queue[Any]" = Queue(maxsize=8)
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
                                        active_thought = "".join(active_thought_parts)
                                        yield ("thinking_delta", str(reasoning), "")

                                    if delta.content:
                                        if thinking_started:
                                            dt = time.time() - thinking_t0
                                            yield ("thinking_end", f"{dt}", active_thought)
                                            thinking_started = False
                                        full_assistant_parts.append(delta.content)
                                        full_assistant_text = "".join(full_assistant_parts)
                                        yield ("bot_delta", delta.content, "")

                                    if delta.tool_calls:
                                        if thinking_started:
                                            dt = time.time() - thinking_t0
                                            yield ("thinking_end", f"{dt}", active_thought)
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
                            estimate_tokens(full_assistant_text)
                            + estimate_tokens(active_thought)
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
                            import random

                            delay = min(max_retry_delay, retry_delay * (retry_backoff ** (attempt - 1)))
                            jitter = random.uniform(0, 0.5 * delay)
                            actual_delay = delay + jitter
                            if full_assistant_text:
                                # Signal the UI to drop the partially-streamed text so the
                                # retried attempt starts from a blank reply (no duplication).
                                yield ("bot_reset", "", "")
                            yield (
                                "thinking",
                                f"[Retry {attempt}/{max_retries}] Provider '{pkey}' error ({api_err}). Retrying in {actual_delay:.1f}s...",
                                "",
                            )
                            await asyncio.sleep(actual_delay)
                            continue

                        circuit_breaker.record_failure(pkey)
                        raise api_err

                output_tokens_est = (
                    estimate_tokens(full_assistant_text)
                    + estimate_tokens(active_thought)
                    + estimate_tokens(tool_calls_dict)
                )
                self._accumulate_usage(
                    step_usage=step_usage, prompt_tokens_est=prompt_tokens_est, output_tokens_est=output_tokens_est
                )

                if thinking_started:
                    dt = time.time() - thinking_t0
                    yield ("thinking_end", f"{dt}", active_thought)
                    thinking_started = False

                if not tool_calls_dict:
                    messages.append({"role": "assistant", "content": full_assistant_text})
                    yield ("bot_text", full_assistant_text, "")
                    # If user messages were queued during this turn, keep going
                    # so the next while-iteration drains them as new steps.
                    if self._has_queued_messages():
                        continue
                    break

                # Execute tool calls in the order the model emitted them. Dict insertion
                # order usually matches, but delta tool_calls can arrive out of order on
                # some providers, so sort explicitly by the tool-call index key.
                ordered_calls = [tool_calls_dict[k] for k in sorted(tool_calls_dict.keys())]

                assistant_tool_msg = {
                    "role": "assistant",
                    "content": full_assistant_text or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": tc["arguments"]},
                        }
                        for tc in ordered_calls
                    ],
                }
                messages.append(assistant_tool_msg)

                for tc in ordered_calls:
                    t_id = tc["id"]
                    t_name = tc["name"]
                    raw_args = tc["arguments"]

                    try:
                        # parse_tool_call_args (shared with adapters) normalizes the
                        # tool-call payload but silently swallows malformed JSON into {}.
                        # Validate first so the invalid-arguments error is surfaced.
                        if raw_args.strip():
                            json.loads(raw_args)
                        _, args = parse_tool_call_args({"function": {"name": t_name, "arguments": raw_args}})
                    except Exception as json_err:
                        tool_result = format_tool_error(
                            "invalid", detail=f"JSON arguments: {json_err}. Raw: {raw_args}", name=t_name
                        )
                        yield ("tool", t_name, t_name, {})
                        yield ("tool_result", tool_result, "")
                        messages.append({"role": "tool", "tool_call_id": t_id, "content": tool_result})
                        continue

                    target = extract_tool_display(t_name, args)
                    yield ("tool", t_name, target, args)

                    from core.role_registry import RoleRegistry

                    current_mode = getattr(self, "mode", "act").lower()
                    role_def = RoleRegistry.get_instance().get_role(current_mode)

                    policy_err = self._tool_policy_error(t_name, args, role_def)
                    if policy_err:
                        tool_result = policy_err
                    else:
                        tool_result = None

                    if tool_result is None:
                        tool_app = self
                        try:
                            tool_result = await execute_tool(t_name, args, app=tool_app)
                        except Exception as e:
                            tool_result = format_tool_error("execute", detail=str(e), name=t_name)

                    display_result = tool_result
                    if isinstance(tool_result, str) and (
                        tool_result.startswith('{"type": "image"') or '"type": "image"' in tool_result[:40]
                    ):
                        try:
                            parsed_img = json.loads(tool_result)
                            if isinstance(parsed_img, dict) and parsed_img.get("type") == "image":
                                display_result = parsed_img.get("summary", f"[Image file: {parsed_img.get('path')}]")
                        except Exception:
                            pass
                    elif isinstance(tool_result, dict) and tool_result.get("type") == "image":
                        display_result = tool_result.get("summary", f"[Image file: {tool_result.get('path')}]")

                    yield ("tool_result", display_result, "")

                    content_str = tool_result
                    if isinstance(tool_result, (dict, list)):
                        content_str = json.dumps(tool_result, ensure_ascii=False)
                    elif tool_result is None:
                        content_str = ""

                    messages.append({"role": "tool", "tool_call_id": t_id, "content": content_str})

                self.history = messages[1:]
                messages, compacted_in_loop = (
                    (messages, False)
                    if compacted_this_turn
                    else await self._compact_messages_if_needed(messages, self._last_sys_tokens, threshold)
                )
                if compacted_in_loop:
                    compacted_this_turn = True
                    yield ("event_divider", "Session Compacted", "")
                    yield ("thinking", "Context budget reached; compacted earlier tool history before continuing.", "")

        except Exception as err:
            error_msg = format_api_error(err)
            clean_msg = error_msg.replace("**API Error:**", "API Error:").replace("**", "").replace("`", "").strip()
            yield ("event_divider", clean_msg, "")
        finally:
            if len(messages) > 1:
                self.history = self.sanitize_history_for_model(messages[1:])
