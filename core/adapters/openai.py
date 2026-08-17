import asyncio
import atexit
import json
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from openai import AsyncOpenAI

from core.infrastructure.adapters.base import (
    BaseApiAdapter,
    build_adapter_usage_event,
    extract_image_details,
    image_url_block,
    new_tool_call_id,
)
from core.infrastructure.runtime.thinking_effort import build_openai_thinking_kwargs


def format_messages_for_openai(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Formates OpenAI tool messages containing image JSON by extracting clean string content for tool role and appending image_url user messages after tool response blocks."""
    formatted: List[Dict[str, Any]] = []
    i = 0
    n = len(messages)
    while i < n:
        msg = messages[i]
        if not isinstance(msg, dict):
            formatted.append(msg)
            i += 1
            continue

        role = msg.get("role")
        if role == "tool":
            tool_batch: List[Dict[str, Any]] = []
            pending_user_images: List[Dict[str, Any]] = []

            while i < n and isinstance(messages[i], dict) and messages[i].get("role") == "tool":
                curr_msg = messages[i]
                img_info = extract_image_details(curr_msg.get("content", ""))

                if img_info:
                    tool_msg = dict(curr_msg)
                    tool_msg["content"] = img_info.summary
                    tool_batch.append(tool_msg)

                    pending_user_images.append(
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": f"Image preview ({img_info.summary}):"},
                                image_url_block(img_info.media_type, img_info.base64, img_info.detail),
                            ],
                        }
                    )
                else:
                    tool_batch.append(curr_msg)
                i += 1

            formatted.extend(tool_batch)
            formatted.extend(pending_user_images)
            continue

        if role == "assistant":
            cleaned_msg = dict(msg)
            if "reasoning_content" not in cleaned_msg or cleaned_msg.get("reasoning_content") is None:
                cleaned_msg["reasoning_content"] = ""
            if msg.get("tool_calls"):
                cleaned_calls = []
                for tc in msg["tool_calls"]:
                    if isinstance(tc, dict):
                        tc_copy = dict(tc)
                        fn = tc.get("function")
                        if isinstance(fn, dict):
                            fn_copy = dict(fn)
                            raw_args = fn.get("arguments", "{}")
                            if not isinstance(raw_args, str):
                                raw_args = json.dumps(raw_args)
                            else:
                                try:
                                    json.loads(raw_args)
                                except Exception:
                                    raw_args = "{}"
                            fn_copy["arguments"] = raw_args
                            tc_copy["function"] = fn_copy
                        cleaned_calls.append(tc_copy)
                    else:
                        cleaned_calls.append(tc)
                cleaned_msg["tool_calls"] = cleaned_calls
            formatted.append(cleaned_msg)
            i += 1
            continue

        formatted.append(msg)
        i += 1

    return formatted


class OpenAIAdapter(BaseApiAdapter):
    """Adapter for OpenAI-compatible Chat Completions API.

    The main agent loop talks to AsyncOpenAI directly on the canonical OpenAI
    path (to access reasoning_content and per-chunk usage). This adapter is used
    as a uniform fallback for OpenAI-compatible providers reached via the
    adapter branch, and yields the same normalized event protocol as the other
    adapters.
    """

    def __init__(self) -> None:
        # Reuse AsyncOpenAI clients across calls instead of creating one per
        # stream_chat invocation (which previously leaked HTTP connection pools).
        # Clients are cached per (base_url, api_key) pair so different providers
        # reached through the adapter branch each get their own client.
        self._clients: Dict[Tuple[str, str], AsyncOpenAI] = {}
        atexit.register(self.close)

    def _get_client(self, base_url: str, api_key: str) -> AsyncOpenAI:
        key = (base_url or "", api_key or "")
        client = self._clients.get(key)
        if client is None:
            client = AsyncOpenAI(api_key=api_key or "sk-placeholder", base_url=base_url or "https://api.openai.com/v1")
            self._clients[key] = client
        return client

    def close(self) -> None:
        """Closes all cached AsyncOpenAI clients to release HTTP connection pools.

        Sync best-effort hook (e.g. registered via ``atexit``). Real cleanup
        happens through :meth:`_close_all`; this runs the async close in a fresh
        event loop when no loop is currently running.
        """
        clients, self._clients = self._clients, {}
        if not clients:
            return
        try:
            asyncio.run(self._close_all(clients))
        except Exception:
            pass

    @staticmethod
    async def _close_all(clients: Dict[Tuple[str, str], AsyncOpenAI]) -> None:
        for client in clients.values():
            try:
                await client.close()
            except Exception:
                pass

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
        client = self._get_client(base_url, api_key)
        formatted_msgs = format_messages_for_openai(messages)
        kwargs: Dict[str, Any] = {"model": model, "messages": formatted_msgs, "stream": True}
        if tools:
            kwargs["tools"] = tools
        if max_tokens and max_tokens > 0:
            kwargs["max_tokens"] = max_tokens
        kwargs.update(build_openai_thinking_kwargs(thinking_effort))
        response = await client.chat.completions.create(**kwargs)
        tool_calls: Dict[int, Dict[str, str]] = {}
        async for chunk in response:
            if getattr(chunk, "usage", None):
                u = chunk.usage
                cache_read = 0
                prompt_details = getattr(u, "prompt_tokens_details", None)
                if prompt_details:
                    cache_read = getattr(prompt_details, "cached_tokens", 0) or 0
                yield build_adapter_usage_event(
                    getattr(u, "prompt_tokens", 0),
                    getattr(u, "completion_tokens", 0),
                    getattr(u, "total_tokens", 0),
                    cache_read,
                )
            choices = getattr(chunk, "choices", None)
            if not choices and hasattr(chunk, "data"):
                d = getattr(chunk, "data")
                choices = d.get("choices") if isinstance(d, dict) else getattr(d, "choices", None)
            if not choices:
                continue
            choice_0 = choices[0]
            delta = getattr(choice_0, "delta", None) if not isinstance(choice_0, dict) else choice_0.get("delta")
            if not delta:
                continue
            if getattr(delta, "content", None):
                yield ("adapter_text", delta.content)
            if getattr(delta, "tool_calls", None):
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls:
                        tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc.id:
                        tool_calls[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls[idx]["arguments"] += tc.function.arguments
        for idx in sorted(tool_calls):
            tc = tool_calls[idx]
            if tc["name"]:
                yield (
                    "adapter_tool_call",
                    {
                        "id": tc["id"] or new_tool_call_id(idx),
                        "name": tc["name"],
                        "arguments": tc["arguments"] or "{}",
                    },
                )
