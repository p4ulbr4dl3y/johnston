import json
from collections import OrderedDict
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx

from core.adapters.base import check_httpx_response_status
from core.infrastructure.adapters.base import (
    BaseApiAdapter,
    build_adapter_usage_event,
    extract_image_details,
    new_tool_call_id,
    parse_sse_line,
    parse_tool_call_args,
    resolve_stream_timeout,
    sort_keys_recursive,
)
from core.infrastructure.runtime.thinking_effort import build_anthropic_thinking_payload

# Bounded LRU cache for deterministic tool-schema sorting. `sort_keys_recursive`
# deep-copies + sorts the whole structure on every stream request; tool schemas
# are stable across requests, so cache the sorted result keyed by a cheap repr
# fingerprint of the freshly converted tools (re-computed only when schemas change).
_SORT_CACHE_MAX = 64
_sort_cache: "OrderedDict" = OrderedDict()


def _get_sorted_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return the deep-sorted copy of a tool list, caching by content fingerprint."""
    key = repr(tools)
    cached = _sort_cache.pop(key, None)
    if cached is not None:
        _sort_cache[key] = cached  # LRU promote
        return cached
    sorted_tools = sort_keys_recursive(tools)
    _sort_cache[key] = sorted_tools
    if len(_sort_cache) > _SORT_CACHE_MAX:
        _sort_cache.popitem(last=False)
    return sorted_tools


def _set_ephemeral(msg: Dict[str, Any]) -> None:
    """Attach a cache_control breakpoint to the last content block of a message."""
    content = msg.get("content")
    if isinstance(content, str):
        if content:
            msg["content"] = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
    elif isinstance(content, list) and content:
        last_block = content[-1]
        if isinstance(last_block, dict) and "cache_control" not in last_block:
            cloned_block = dict(last_block)
            cloned_block["cache_control"] = {"type": "ephemeral"}
            msg["content"] = content[:-1] + [cloned_block]


def apply_anthropic_rolling_cache(anthropic_msgs: List[Dict[str, Any]]) -> None:
    """Place up to two rolling cache_control breakpoints on the conversation tail.

    Anthropic allows max 4 breakpoints per request; the adapter uses the other
    two on the system prompt and the last tool. Here:

    - breakpoint 1: 2nd-to-last user message — the classic rolling anchor. Its
      prefix is stable across turns, so it always lands a cache hit.
    - breakpoint 2: last user message — covers the fresh tail (big tool_result
      blocks from the previous exchange). Without it that tail is written as
      uncached (1x) this turn and only becomes cacheable next turn, when its
      position has shifted. With it, the tail is written to cache now (1.25x)
      and read back at 0.1x on the next turn.
    """
    user_indices = [i for i, m in enumerate(anthropic_msgs) if m.get("role") == "user"]
    if len(user_indices) < 2:
        return

    _set_ephemeral(anthropic_msgs[user_indices[-2]])
    _set_ephemeral(anthropic_msgs[user_indices[-1]])


class AnthropicAdapter(BaseApiAdapter):
    """Adapter for the Anthropic Native Messages API (/v1/messages).

    Full tool-calling support: converts OpenAI-format messages (including
    assistant tool_calls and tool-result messages) into Anthropic content
    blocks, parses streaming tool_use blocks, and reports token usage.
    """

    def _create_client(self, base_url: str, api_key: str) -> httpx.AsyncClient:
        return httpx.AsyncClient()

    @staticmethod
    def _to_anthropic_messages(messages: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
        system_prompt = ""
        final: List[Dict[str, Any]] = []
        pending_tools: List[Dict[str, Any]] = []

        def _flush_tools():
            if pending_tools:
                final.append({"role": "user", "content": pending_tools[:]})
                pending_tools.clear()

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "system":
                system_prompt = content if isinstance(content, str) else json.dumps(content)
                continue
            if role == "tool":
                tc_id = msg.get("tool_call_id") or ""
                img_info = extract_image_details(msg.get("content", ""))

                if img_info:
                    pending_tools.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tc_id,
                            "content": [
                                {"type": "text", "text": img_info.summary},
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": img_info.media_type,
                                        "data": img_info.base64,
                                    },
                                },
                            ],
                        }
                    )
                    continue

                tcontent = msg.get("content", "")
                if not isinstance(tcontent, str):
                    tcontent = json.dumps(tcontent, ensure_ascii=False)
                pending_tools.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc_id,
                        "content": tcontent,
                    }
                )
                continue

            _flush_tools()

            if role == "user":
                if isinstance(content, str):
                    final.append({"role": "user", "content": content})
                elif isinstance(content, list):
                    converted_parts = []
                    for p in content:
                        if isinstance(p, dict) and p.get("type") == "image_url":
                            img_url = p.get("image_url", {})
                            url = img_url.get("url", "") if isinstance(img_url, dict) else str(img_url)
                            if url.startswith("data:"):
                                header, b64_data = url.split(",", 1) if "," in url else ("", url)
                                mime_type = header.split(";")[0].replace("data:", "") or "image/jpeg"
                                converted_parts.append(
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": mime_type,
                                            "data": b64_data,
                                        },
                                    }
                                )
                        else:
                            converted_parts.append(p)
                    final.append({"role": "user", "content": converted_parts})
                else:
                    final.append({"role": "user", "content": json.dumps(content)})
            elif role == "assistant":
                blocks: List[Dict[str, Any]] = []
                if isinstance(content, str) and content:
                    blocks.append({"type": "text", "text": content})
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            blocks.append({"type": "text", "text": part.get("text", "")})
                for tc in msg.get("tool_calls") or []:
                    fn_name, args_obj = parse_tool_call_args(tc)
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.get("id") or new_tool_call_id(),
                            "name": fn_name,
                            "input": args_obj,
                        }
                    )
                final.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})

        _flush_tools()
        apply_anthropic_rolling_cache(final)
        return system_prompt, final

    async def stream_chat(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 4096,
        thinking_effort: Optional[str] = None,
        stream_timeout: Optional[float] = None,
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        system_prompt, anthropic_msgs = self._to_anthropic_messages(messages)
        endpoint_url = f"{(base_url or 'https://api.anthropic.com').rstrip('/')}/v1/messages"
        headers = {
            "x-api-key": api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "anthropic-beta": "prompt-caching-2024-07-31",
        }
        payload: Dict[str, Any] = {
            "model": model,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens or 4096,
            "stream": True,
        }
        payload.update(build_anthropic_thinking_payload(thinking_effort))

        if system_prompt:
            payload["system"] = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
        else:
            payload["system"] = ""

        if tools:
            converted_tools = []
            for t in tools:
                fn = t.get("function", {})
                fn_name = fn.get("name", "")
                if not fn_name:
                    continue
                converted_tools.append(
                    {
                        "name": fn_name,
                        "description": fn.get("description", ""),
                        "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                    }
                )
            if converted_tools:
                sorted_tools = _get_sorted_tools(converted_tools)
                # Shallow-copy list + dict-copy last element so the cache_control
                # mutation below never touches the shared cached structure.
                sorted_tools = list(sorted_tools)
                sorted_tools[-1] = dict(sorted_tools[-1])
                sorted_tools[-1]["cache_control"] = {"type": "ephemeral"}
                payload["tools"] = sorted_tools

        tool_blocks: Dict[int, Dict[str, str]] = {}
        pending_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }

        client = self._get_client(base_url, api_key)
        async with client.stream(
            "POST", endpoint_url, headers=headers, json=payload, timeout=resolve_stream_timeout(stream_timeout)
        ) as resp:
            await check_httpx_response_status(resp)
            async for line in resp.aiter_lines():
                evt = parse_sse_line(line)
                if evt is None:
                    continue

                etype = evt.get("type")
                if etype == "message_start":
                    u = (evt.get("message") or {}).get("usage") or {}
                    uncached_in = u.get("input_tokens", 0) or 0
                    cache_read = u.get("cache_read_input_tokens", 0) or 0
                    cache_write = u.get("cache_creation_input_tokens", 0) or 0
                    pending_usage["prompt_tokens"] = uncached_in + cache_read + cache_write
                    pending_usage["cache_read_tokens"] = cache_read
                    pending_usage["cache_write_tokens"] = cache_write
                elif etype == "content_block_start":
                    idx = evt.get("index")
                    cb = evt.get("content_block") or {}
                    if cb.get("type") == "tool_use":
                        tool_blocks[idx] = {"id": cb.get("id", ""), "name": cb.get("name", ""), "args_parts": []}
                elif etype == "content_block_delta":
                    idx = evt.get("index")
                    delta = evt.get("delta") or {}
                    dtype = delta.get("type")
                    if dtype == "text_delta":
                        txt = delta.get("text", "")
                        if txt:
                            yield ("adapter_text", txt)
                    elif dtype == "thinking_delta":
                        thought = delta.get("thinking", "")
                        if thought:
                            yield ("adapter_thought", thought)
                    elif dtype == "input_json_delta":
                        if idx in tool_blocks:
                            part = delta.get("partial_json", "")
                            if part:
                                tool_blocks[idx]["args_parts"].append(part)
                elif etype == "content_block_stop":
                    idx = evt.get("index")
                    if idx in tool_blocks:
                        tb = tool_blocks.pop(idx)
                        yield (
                            "adapter_tool_call",
                            {
                                "id": tb["id"] or new_tool_call_id(),
                                "name": tb["name"],
                                "arguments": "".join(tb["args_parts"]) or "{}",
                            },
                        )
                elif etype == "message_delta":
                    u = evt.get("usage") or {}
                    if u.get("output_tokens") is not None:
                        pending_usage["completion_tokens"] = u.get("output_tokens", 0) or 0
                elif etype == "message_stop":
                    yield build_adapter_usage_event(
                        pending_usage["prompt_tokens"],
                        pending_usage["completion_tokens"],
                        cache_read_tokens=pending_usage["cache_read_tokens"],
                        cache_write_tokens=pending_usage["cache_write_tokens"],
                    )
                    pending_usage = {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "cache_read_tokens": 0,
                        "cache_write_tokens": 0,
                    }
