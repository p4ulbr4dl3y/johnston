import json
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx

from core.adapters.base import (
    BaseApiAdapter,
    build_adapter_usage_event,
    check_httpx_response_status,
    normalize_tool_arguments_str,
    parse_tool_call_args,
)
from core.base_provider.tools import new_tool_call_id
from core.infrastructure.runtime.thinking_effort import build_ollama_thinking_payload


class OllamaAdapter(BaseApiAdapter):
    """Adapter for the Ollama Native Chat API (/api/chat) with tool-calling support.

    Ollama accepts OpenAI-ish messages (role "tool" and assistant tool_calls);
    arguments are normalized to objects on the way in. Streaming tool_calls and
    eval token counts are parsed from each JSON line.
    """

    @staticmethod
    def _to_ollama_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role")
            item: Dict[str, Any] = {"role": role, "content": msg.get("content") or ""}
            if role == "assistant":
                tcs = msg.get("tool_calls")
                if tcs:
                    norm = []
                    for tc in tcs:
                        fn_name, args_obj = parse_tool_call_args(tc)
                        norm.append({"function": {"name": fn_name, "arguments": args_obj}})
                    if norm:
                        item["tool_calls"] = norm
            out.append(item)
        return out

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
        endpoint = f"{(base_url or 'http://localhost:11434').rstrip('/')}/api/chat"
        payload: Dict[str, Any] = {
            "model": model,
            "messages": self._to_ollama_messages(messages),
            "stream": True,
        }
        payload.update(build_ollama_thinking_payload(thinking_effort))
        if tools:
            payload["tools"] = tools
        if max_tokens and max_tokens > 0:
            payload["options"] = {"num_predict": max_tokens}

        async with httpx.AsyncClient() as client:
            async with client.stream("POST", endpoint, json=payload, timeout=60.0) as resp:
                await check_httpx_response_status(resp)
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except Exception:
                        continue
                    msg_obj = evt.get("message") or {}
                    content = msg_obj.get("content", "")
                    if content:
                        if msg_obj.get("thinking"):
                            yield ("adapter_thought", content)
                        else:
                            yield ("adapter_text", content)
                    for tc in msg_obj.get("tool_calls") or []:
                        if not isinstance(tc, dict):
                            continue
                        fn = tc.get("function", {})
                        if not isinstance(fn, dict):
                            fn = {}
                        yield (
                            "adapter_tool_call",
                            {
                                "id": new_tool_call_id(),
                                "name": fn.get("name", ""),
                                "arguments": normalize_tool_arguments_str(fn.get("arguments")),
                            },
                        )
                    if evt.get("done"):
                        in_tok = evt.get("prompt_eval_count", 0) or 0
                        out_tok = evt.get("eval_count", 0) or 0
                        if in_tok or out_tok:
                            yield build_adapter_usage_event(in_tok, out_tok)
