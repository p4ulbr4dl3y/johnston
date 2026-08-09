import json
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx

from core.adapters.base import (
    BaseApiAdapter,
    extract_image_payload,
    parse_tool_call_args,
    sort_keys_recursive,
)
from core.thinking_effort import build_anthropic_thinking_payload


def apply_anthropic_rolling_cache(anthropic_msgs: List[Dict[str, Any]]) -> None:
    """Places a rolling Anthropic cache_control breakpoint on the 2nd-to-last user message in history."""
    user_indices = [i for i, m in enumerate(anthropic_msgs) if m.get("role") == "user"]
    if len(user_indices) < 2:
        return

    target_idx = user_indices[-2]
    msg = anthropic_msgs[target_idx]
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


class AnthropicAdapter(BaseApiAdapter):
    """Adapter for the Anthropic Native Messages API (/v1/messages).

    Full tool-calling support: converts OpenAI-format messages (including
    assistant tool_calls and tool-result messages) into Anthropic content
    blocks, parses streaming tool_use blocks, and reports token usage.
    """

    @staticmethod
    def _to_anthropic_messages(
        messages: List[Dict[str, Any]]
    ) -> Tuple[str, List[Dict[str, Any]]]:
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
                tcontent = msg.get("content", "")
                parsed_img = extract_image_payload(tcontent)

                if parsed_img and parsed_img.get("base64"):
                    summary_text = parsed_img.get("summary", "[Image content]")
                    media_type = parsed_img.get("media_type", "image/jpeg")
                    b64_data = parsed_img.get("base64")
                    pending_tools.append({
                        "type": "tool_result",
                        "tool_use_id": tc_id,
                        "content": [
                            {"type": "text", "text": summary_text},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": b64_data,
                                },
                            },
                        ],
                    })
                    continue

                if not isinstance(tcontent, str):
                    tcontent = json.dumps(tcontent, ensure_ascii=False)
                pending_tools.append({
                    "type": "tool_result",
                    "tool_use_id": tc_id,
                    "content": tcontent,
                })
                continue

            _flush_tools()

            if role == "user":
                final.append({"role": "user", "content": content if content is not None else ""})
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
                    blocks.append({
                        "type": "tool_use",
                        "id": (tc.get("id") if isinstance(tc, dict) else None) or f"toolu_{uuid.uuid4().hex[:12]}",
                        "name": fn_name,
                        "input": args_obj,
                    })
                final.append({"role": "assistant", "content": blocks or [{"type": "text", "text": content or ""}]})

        _flush_tools()
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
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        system_prompt, anthropic_msgs = self._to_anthropic_messages(messages)
        apply_anthropic_rolling_cache(anthropic_msgs)
        endpoint_url = f"{(base_url or 'https://api.anthropic.com/v1').rstrip('/')}/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": max_tokens if max_tokens and max_tokens > 0 else 8192,
            "messages": anthropic_msgs,
            "stream": True,
        }
        payload.update(build_anthropic_thinking_payload(thinking_effort))
        # Anthropic prompt caching: mark the stable system prompt and the final
        # tool definition as ephemeral cache breakpoints. The system prompt +
        # tool schemas (~2-4k tokens) are identical across the tool-call steps of
        # a turn, so they are read from cache on steps 2..N at ~10% of the price.
        if system_prompt:
            payload["system"] = [
                {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
            ]
        else:
            payload["system"] = ""
        if tools:
            native_tools = [
                {
                    "name": (t.get("function", {}) or {}).get("name"),
                    "description": (t.get("function", {}) or {}).get("description", ""),
                    "input_schema": sort_keys_recursive((t.get("function", {}) or {}).get("parameters", {})),
                }
                for t in tools
            ]
            if native_tools:
                native_tools[-1]["cache_control"] = {"type": "ephemeral"}
            payload["tools"] = native_tools

        tool_blocks: Dict[int, Dict[str, str]] = {}
        pending_usage: Dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cache_read_tokens": 0,
        }

        async with httpx.AsyncClient() as client:
            async with client.stream("POST", endpoint_url, headers=headers, json=payload, timeout=60.0) as resp:
                if getattr(resp, "status_code", 200) >= 400:
                    err_bytes = await resp.aread()
                    err_body = err_bytes.decode("utf-8", errors="replace")
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}: {err_body}",
                        request=resp.request,
                        response=resp,
                    )
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    line_data = line[5:].strip()
                    if not line_data:
                        continue
                    if line_data == "[DONE]":
                        break
                    try:
                        evt = json.loads(line_data)
                    except Exception:
                        continue

                    etype = evt.get("type")
                    if etype == "message_start":
                        u = (evt.get("message") or {}).get("usage") or {}
                        pending_usage["prompt_tokens"] = u.get("input_tokens", 0) or 0
                        pending_usage["cache_read_tokens"] = u.get("cache_read_input_tokens", 0) or 0
                    elif etype == "content_block_start":
                        idx = evt.get("index")
                        cb = evt.get("content_block") or {}
                        if cb.get("type") == "tool_use":
                            tool_blocks[idx] = {"id": cb.get("id", ""), "name": cb.get("name", ""), "args_buf": ""}
                    elif etype == "content_block_delta":
                        idx = evt.get("index")
                        delta = evt.get("delta") or {}
                        dtype = delta.get("type")
                        if dtype == "text_delta":
                            txt = delta.get("text", "")
                            if txt:
                                yield ("adapter_text", txt)
                        elif dtype == "input_json_delta":
                            if idx in tool_blocks:
                                tool_blocks[idx]["args_buf"] += delta.get("partial_json", "")
                    elif etype == "content_block_stop":
                        idx = evt.get("index")
                        if idx in tool_blocks:
                            tb = tool_blocks.pop(idx)
                            yield ("adapter_tool_call", {
                                "id": tb["id"] or f"call_{uuid.uuid4().hex[:8]}",
                                "name": tb["name"],
                                "arguments": tb["args_buf"] or "{}",
                            })
                    elif etype == "message_delta":
                        u = evt.get("usage") or {}
                        if u.get("output_tokens") is not None:
                            pending_usage["completion_tokens"] = u.get("output_tokens", 0) or 0
                    elif etype == "message_stop":
                        pending_usage["total_tokens"] = (
                            pending_usage["prompt_tokens"] + pending_usage["completion_tokens"]
                        )
                        yield ("adapter_usage", dict(pending_usage))
                        pending_usage = {"prompt_tokens": 0, "completion_tokens": 0, "cache_read_tokens": 0}
