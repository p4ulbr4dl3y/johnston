import json
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx
from openai import AsyncOpenAI

from core.thinking_effort import (
    build_anthropic_thinking_payload,
    build_gemini_thinking_config,
    build_ollama_thinking_payload,
    build_openai_thinking_kwargs,
)


class BaseApiAdapter:
    """Base API Adapter interface for LLM formats.

    Adapters yield normalized events so the agent loop can consume them
    uniformly regardless of provider wire protocol:
      - ("adapter_text", str)        : a text delta to append to the reply
      - ("adapter_tool_call", dict)  : {"id", "name", "arguments"(JSON str)}
      - ("adapter_usage", dict)      : {"prompt_tokens", "completion_tokens",
                                        "total_tokens", "cache_read_tokens"}
    """
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
        raise NotImplementedError


class OpenAIAdapter(BaseApiAdapter):
    """Adapter for OpenAI-compatible Chat Completions API.

    The main agent loop talks to AsyncOpenAI directly on the canonical OpenAI
    path (to access reasoning_content and per-chunk usage). This adapter is used
    as a uniform fallback for OpenAI-compatible providers reached via the
    adapter branch, and yields the same normalized event protocol as the other
    adapters.
    """

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
        client = AsyncOpenAI(api_key=api_key or "sk-placeholder", base_url=base_url or "https://api.openai.com/v1")
        kwargs: Dict[str, Any] = {"model": model, "messages": messages, "stream": True}
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
                yield ("adapter_usage", {
                    "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(u, "total_tokens", 0) or 0,
                    "cache_read_tokens": cache_read,
                })
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
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
                yield ("adapter_tool_call", {
                    "id": tc["id"] or f"call_{idx}",
                    "name": tc["name"],
                    "arguments": tc["arguments"] or "{}",
                })


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
                    if not isinstance(tc, dict):
                        continue
                    fn = tc.get("function", {})
                    if not isinstance(fn, dict):
                        fn = {}
                    raw_args = fn.get("arguments", "{}")
                    if isinstance(raw_args, str):
                        try:
                            args_obj = json.loads(raw_args) if raw_args.strip() else {}
                        except Exception:
                            args_obj = {}
                    else:
                        args_obj = raw_args or {}
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id") or f"toolu_{uuid.uuid4().hex[:12]}",
                        "name": fn.get("name", ""),
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
                    "input_schema": (t.get("function", {}) or {}).get("parameters", {}),
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
                        pending_usage["cache_read_tokens"] = (
                            u.get("cache_read_input_tokens", 0) or u.get("cache_creation_input_tokens", 0) or 0
                        )
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


class GeminiAdapter(BaseApiAdapter):
    """Adapter for the Google Gemini REST API with tool-calling support.

    Converts OpenAI-format messages (including tool_calls and tool results)
    into Gemini contents (functionCall/functionResponse parts), parses
    streaming functionCall parts, and reports usageMetadata.
    """

    def _content_to_parts(
        self, content: Any, msg: Dict[str, Any], role: str
    ) -> List[Dict[str, Any]]:
        parts: List[Dict[str, Any]] = []
        if isinstance(content, str):
            if content:
                parts.append({"text": content})
        elif isinstance(content, list):
            for p in content:
                if not isinstance(p, dict):
                    continue
                if p.get("type") == "text":
                    parts.append({"text": p.get("text", "")})
        if role == "model":
            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function", {})
                if not isinstance(fn, dict):
                    fn = {}
                raw_args = fn.get("arguments", "{}")
                if isinstance(raw_args, str):
                    try:
                        args_obj = json.loads(raw_args) if raw_args.strip() else {}
                    except Exception:
                        args_obj = {}
                else:
                    args_obj = raw_args or {}
                parts.append({"functionCall": {"name": fn.get("name", ""), "args": args_obj}})
        return parts or [{"text": ""}]

    def _to_gemini(
        self, messages: List[Dict[str, Any]]
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        system_instruction: Optional[Dict[str, Any]] = None
        contents: List[Dict[str, Any]] = []
        pending_tools: List[Dict[str, Any]] = []

        def _flush_tools():
            if pending_tools:
                contents.append({"role": "user", "parts": pending_tools[:]})
                pending_tools.clear()

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "system":
                text = content if isinstance(content, str) else json.dumps(content)
                system_instruction = {"parts": [{"text": text}]}
                continue
            if role == "tool":
                name = msg.get("name", "tool")
                tcontent = msg.get("content", "")
                if isinstance(tcontent, str):
                    try:
                        resp_obj = json.loads(tcontent) if tcontent.strip() else {}
                    except Exception:
                        resp_obj = {"result": tcontent}
                else:
                    resp_obj = tcontent
                if not isinstance(resp_obj, dict):
                    resp_obj = {"result": resp_obj}
                pending_tools.append({"functionResponse": {"name": name, "response": resp_obj}})
                continue

            _flush_tools()

            if role == "user":
                contents.append({"role": "user", "parts": self._content_to_parts(content, msg, "user")})
            elif role == "assistant":
                contents.append({"role": "model", "parts": self._content_to_parts(content, msg, "model")})

        _flush_tools()
        return system_instruction, contents

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
        system_instruction, contents = self._to_gemini(messages)
        base = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        # alt=sse gives clean Server-Sent Events (data: lines) instead of a
        # comma-separated JSON array, which is far simpler to parse incrementally.
        endpoint = f"{base}/models/{model}:streamGenerateContent?alt=sse&key={api_key}"
        payload: Dict[str, Any] = {"contents": contents}
        if system_instruction:
            payload["systemInstruction"] = system_instruction
        generation_config: Dict[str, Any] = {}
        if max_tokens and max_tokens > 0:
            generation_config["maxOutputTokens"] = max_tokens
        thinking_config = build_gemini_thinking_config(model, thinking_effort)
        if thinking_config:
            generation_config["thinkingConfig"] = thinking_config
        if generation_config:
            payload["generationConfig"] = generation_config
        if tools:
            function_declarations = []
            for t in tools:
                fn = t.get("function", {}) if isinstance(t.get("function"), dict) else {}
                function_declarations.append({
                    "name": fn.get("name"),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {}),
                })
            payload["tools"] = [{"functionDeclarations": function_declarations}]

        async with httpx.AsyncClient() as client:
            async with client.stream("POST", endpoint, json=payload, timeout=60.0) as resp:
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
                    try:
                        evt = json.loads(line_data)
                    except Exception:
                        continue

                    for cand in evt.get("candidates") or []:
                        parts = ((cand.get("content") or {}).get("parts")) or []
                        for p in parts:
                            if not isinstance(p, dict):
                                continue
                            if p.get("text"):
                                yield ("adapter_text", p["text"])
                            elif "functionCall" in p:
                                fc = p.get("functionCall") or {}
                                args = fc.get("args") or {}
                                if not isinstance(args, str):
                                    args = json.dumps(args, ensure_ascii=False)
                                yield ("adapter_tool_call", {
                                    "id": f"call_{uuid.uuid4().hex[:8]}",
                                    "name": fc.get("name", ""),
                                    "arguments": args or "{}",
                                })

                    um = evt.get("usageMetadata")
                    if um:
                        p_tok = um.get("promptTokenCount", 0) or 0
                        c_tok = um.get("candidatesTokenCount", 0) or 0
                        yield ("adapter_usage", {
                            "prompt_tokens": p_tok,
                            "completion_tokens": c_tok,
                            "total_tokens": um.get("totalTokenCount") or (p_tok + c_tok),
                            "cache_read_tokens": 0,
                        })


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
                        if not isinstance(tc, dict):
                            continue
                        fn = tc.get("function", {})
                        if not isinstance(fn, dict):
                            fn = {}
                        raw_args = fn.get("arguments", "{}")
                        if isinstance(raw_args, str):
                            try:
                                args_obj = json.loads(raw_args) if raw_args.strip() else {}
                            except Exception:
                                args_obj = {}
                        else:
                            args_obj = raw_args or {}
                        norm.append({"function": {"name": fn.get("name", ""), "arguments": args_obj}})
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
                if getattr(resp, "status_code", 200) >= 400:
                    err_bytes = await resp.aread()
                    err_body = err_bytes.decode("utf-8", errors="replace")
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}: {err_body}",
                        request=resp.request,
                        response=resp,
                    )
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
                        yield ("adapter_text", content)
                    for tc in msg_obj.get("tool_calls") or []:
                        if not isinstance(tc, dict):
                            continue
                        fn = tc.get("function", {})
                        if not isinstance(fn, dict):
                            fn = {}
                        args = fn.get("arguments", {})
                        if not isinstance(args, str):
                            args = json.dumps(args, ensure_ascii=False)
                        yield ("adapter_tool_call", {
                            "id": f"call_{uuid.uuid4().hex[:8]}",
                            "name": fn.get("name", ""),
                            "arguments": args or "{}",
                        })
                    if evt.get("done"):
                        in_tok = evt.get("prompt_eval_count", 0) or 0
                        out_tok = evt.get("eval_count", 0) or 0
                        if in_tok or out_tok:
                            yield ("adapter_usage", {
                                "prompt_tokens": in_tok,
                                "completion_tokens": out_tok,
                                "total_tokens": in_tok + out_tok,
                                "cache_read_tokens": 0,
                            })


ADAPTERS: Dict[str, BaseApiAdapter] = {
    "openai": OpenAIAdapter(),
    "anthropic": AnthropicAdapter(),
    "gemini": GeminiAdapter(),
    "ollama": OllamaAdapter(),
}


def get_adapter(api_type: str = "openai") -> BaseApiAdapter:
    key = (api_type or "openai").lower().strip()
    return ADAPTERS.get(key, ADAPTERS["openai"])
