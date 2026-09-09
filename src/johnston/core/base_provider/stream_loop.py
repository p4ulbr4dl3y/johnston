import asyncio
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from johnston.core.base_provider.errors import format_api_error
from johnston.core.base_provider.history_cache import (
    _extract_streaming_target,
    sanitize_history_cached,
)
from johnston.core.domain.defaults.config import DEFAULT_MAX_TOKENS, ESCALATED_MAX_TOKENS
from johnston.core.infrastructure.adapters.base import (
    build_stream_kwargs,
    new_tool_call_id,
)
from johnston.core.infrastructure.runtime.token_util import (
    estimate_message_tokens as _default_estimate_message_tokens,
)
from johnston.core.infrastructure.runtime.token_util import (
    estimate_tokens as _default_estimate_tokens,
)

logger = logging.getLogger("johnston.core.base_provider.agent")

__all__ = [
    "StreamLoopMixin",
]


def _resolve_estimate_tokens(val: Any) -> int:
    import johnston.core.base_provider.agent as agent_mod

    fn = getattr(agent_mod, "estimate_tokens", _default_estimate_tokens)
    return fn(val)


def _resolve_estimate_message_tokens(val: Any) -> int:
    import johnston.core.base_provider.agent as agent_mod

    fn = getattr(agent_mod, "estimate_message_tokens", _default_estimate_message_tokens)
    return fn(val)


class StreamLoopMixin:
    """Mixin handling stream attempt retries, usage finalization, and stream_steps orchestration."""

    async def _stream_attempts(
        self,
        messages: List[Dict[str, Any]],
        all_tools: List[Dict[str, Any]],
        prompt_tokens_est: int,
        max_retries: int,
        retry_delay: float,
        retry_backoff: float,
        max_retry_delay: float,
        pkey: str,
        result: Dict[str, Any],
    ) -> AsyncGenerator[Tuple[Any, ...], None]:
        """Run the per-step attempt loop (stream consumption + retry/escalation).

        Yields every streaming event exactly as the inline loop did. On a
        successful attempt it writes ``(messages, thinking_started, thinking_t0,
        step_usage, full_assistant_parts, active_thought_parts,
        last_thought_parts, tool_calls_dict)`` into ``result`` before returning
        (an async generator cannot carry a return value); ``messages`` may have
        been replaced by vision-error sanitization, so callers must keep the
        written list.
        """
        from johnston.core.infrastructure.runtime.circuit_breaker import circuit_breaker

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
                from johnston.core.adapters import get_adapter

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
                    _resolve_estimate_tokens("".join(full_assistant_parts))
                    + _resolve_estimate_tokens("".join(active_thought_parts) or "".join(last_thought_parts))
                    + _resolve_estimate_tokens(tool_calls_dict)
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

        result["messages"] = messages
        result["thinking_started"] = thinking_started
        result["thinking_t0"] = thinking_t0
        result["step_usage"] = step_usage
        result["full_assistant_parts"] = full_assistant_parts
        result["active_thought_parts"] = active_thought_parts
        result["last_thought_parts"] = last_thought_parts
        result["tool_calls_dict"] = tool_calls_dict

    async def _finalize_step_usage(
        self,
        *,
        full_assistant_parts: List[str],
        active_thought_parts: List[str],
        last_thought_parts: List[str],
        tool_calls_dict: Dict[int, Dict[str, Any]],
        step_usage: Optional[Dict[str, Any]],
        prompt_tokens_est: int,
        thinking_started: bool,
        thinking_t0: float,
    ) -> AsyncGenerator[Tuple[str, str, str], None]:
        """Accumulate usage/metrics for a completed step and close open thinking."""
        output_tokens_est = (
            _resolve_estimate_tokens("".join(full_assistant_parts))
            + _resolve_estimate_tokens("".join(active_thought_parts) or "".join(last_thought_parts))
            + _resolve_estimate_tokens(tool_calls_dict)
        )
        self._accumulate_usage(
            step_usage=step_usage, prompt_tokens_est=prompt_tokens_est, output_tokens_est=output_tokens_est
        )

        if thinking_started:
            dt = time.time() - thinking_t0
            thoughts_str = "".join(active_thought_parts) or "".join(last_thought_parts)
            yield ("thinking_end", f"{dt}", thoughts_str)

    async def stream_steps(
        self, user_text: str, attachments: Optional[List[Any]] = None
    ) -> AsyncGenerator[Tuple[str, str, str], None]:
        prep_result: Dict[str, Any] = {}
        prep_gen = self._prepare_turn_context(user_text, attachments, prep_result)
        while True:
            try:
                evt = await prep_gen.__anext__()
            except StopAsyncIteration:
                break
            yield evt
        messages, all_tools, threshold = (
            prep_result["messages"],
            prep_result["all_tools"],
            prep_result["threshold"],
        )

        try:
            while True:
                # Drain queued user messages between agent steps.
                for msg_text, atts, show_ui, disp_text in self._drain_queued_messages():
                    messages.append({"role": "user", "content": msg_text})
                    self._append_history(messages[-1])
                    yield ("queued_user_message", msg_text, atts, show_ui, disp_text)

                # messages = [system] + self.history (invariant maintained below), so
                # estimate_tokens(messages) == estimate_message_tokens(messages[0]) +
                # self._history_tokens. Only the single system message is walked here;
                # the full-history O(n) walk is avoided on every step. Guard for an
                # empty messages list (defensive; e.g. a mocked no-op compaction).
                prompt_tokens_est = (
                    _resolve_estimate_message_tokens(messages[0]) + self._current_history_tokens() if messages else 0
                )
                max_retries = getattr(self, "max_retries", 3)
                retry_delay = getattr(self, "retry_delay", 1.0)
                retry_backoff = getattr(self, "retry_backoff", 2.0)
                max_retry_delay = getattr(self, "max_retry_delay", 10.0)
                pkey = getattr(self, "provider_key", "default")

                from johnston.core.infrastructure.runtime.circuit_breaker import (
                    CircuitBreakerOpenError,
                    circuit_breaker,
                )

                if not circuit_breaker.allow_request(pkey):
                    cb_rem = circuit_breaker.remaining_cooldown(pkey)
                    raise CircuitBreakerOpenError(pkey, cb_rem)

                # The attempt loop's streaming events are re-yielded directly,
                # exactly as if the loop body lived in this frame. A consumer
                # that throws (e.g. athrow(CancelledError)) at a re-yield point
                # must have the exception delivered INTO the attempt generator
                # so its cancel-time usage accounting and retry handling run
                # identically to the inline `except asyncio.CancelledError`.
                attempt_result: Dict[str, Any] = {}
                attempt_gen = self._stream_attempts(
                    messages=messages,
                    all_tools=all_tools,
                    prompt_tokens_est=prompt_tokens_est,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                    retry_backoff=retry_backoff,
                    max_retry_delay=max_retry_delay,
                    pkey=pkey,
                    result=attempt_result,
                )
                while True:
                    try:
                        evt = await attempt_gen.__anext__()
                    except StopAsyncIteration:
                        break
                    try:
                        yield evt
                    except BaseException as exc:
                        # The consumer threw at the re-yield point (task
                        # cancellation or an explicit gen.athrow). The attempt
                        # generator is suspended at the yield that produced
                        # ``evt``, so deliver the exception into it: its
                        # handlers (cancel-time usage accounting, retry
                        # scheduling, vision recovery) then run exactly as they
                        # did when the attempt-loop body lived in this frame.
                        evt = await attempt_gen.athrow(exc)
                        yield evt

                messages = attempt_result["messages"]
                thinking_started = attempt_result["thinking_started"]
                thinking_t0 = attempt_result["thinking_t0"]
                step_usage = attempt_result["step_usage"]
                full_assistant_parts = attempt_result["full_assistant_parts"]
                active_thought_parts = attempt_result["active_thought_parts"]
                last_thought_parts = attempt_result["last_thought_parts"]
                tool_calls_dict = attempt_result["tool_calls_dict"]

                fin_gen = self._finalize_step_usage(
                    full_assistant_parts=full_assistant_parts,
                    active_thought_parts=active_thought_parts,
                    last_thought_parts=last_thought_parts,
                    tool_calls_dict=tool_calls_dict,
                    step_usage=step_usage,
                    prompt_tokens_est=prompt_tokens_est,
                    thinking_started=thinking_started,
                    thinking_t0=thinking_t0,
                )
                while True:
                    try:
                        evt = await fin_gen.__anext__()
                    except StopAsyncIteration:
                        break
                    yield evt

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

                tool_result = {}
                tool_gen = self._execute_tool_calls(
                    messages=messages,
                    tool_calls_dict=tool_calls_dict,
                    full_assistant_parts=full_assistant_parts,
                    active_thought_parts=active_thought_parts,
                    threshold=threshold,
                    result=tool_result,
                )
                while True:
                    try:
                        evt = await tool_gen.__anext__()
                    except StopAsyncIteration:
                        break
                    yield evt
                messages = tool_result["messages"]
        except Exception as err:
            import johnston.core.base_provider.agent as agent_mod

            agent_mod.logger.exception("API request failed: %s", err)
            error_msg = format_api_error(err)
            clean_msg = error_msg.replace("**API Error:**", "API Error:").replace("**", "").replace("`", "").strip()
            clean_msg = " ".join(clean_msg.split())
            yield ("error", clean_msg, "")
        finally:
            if len(messages) > 1:
                sanitized = await sanitize_history_cached(self, messages[1:])
                self._set_history(sanitized)
