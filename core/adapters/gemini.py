import json
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx

from core.adapters.base import check_httpx_response_status
from core.infrastructure.adapters.base import (
    BaseApiAdapter,
    build_adapter_usage_event,
    extract_image_details,
    new_tool_call_id,
    normalize_tool_arguments_str,
    parse_sse_line,
    parse_tool_call_args,
    resolve_stream_timeout,
)
from core.infrastructure.runtime.thinking_effort import build_gemini_thinking_config


class GeminiAdapter(BaseApiAdapter):
    """Adapter for the Google Gemini REST API with tool-calling support.

    Converts OpenAI-format messages (including tool_calls and tool results)
    into Gemini contents (functionCall/functionResponse parts), parses
    streaming functionCall parts, and reports usageMetadata.
    """

    def _create_client(self, base_url: str, api_key: str) -> httpx.AsyncClient:
        return httpx.AsyncClient()

    def _content_to_parts(self, content: Any, msg: Dict[str, Any], role: str) -> List[Dict[str, Any]]:
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
                elif p.get("type") == "image_url":
                    img_url = p.get("image_url", {})
                    url = img_url.get("url", "") if isinstance(img_url, dict) else str(img_url)
                    if url.startswith("data:"):
                        header, b64_data = url.split(",", 1) if "," in url else ("", url)
                        mime_type = header.split(";")[0].replace("data:", "") or "image/jpeg"
                        parts.append({"inlineData": {"mimeType": mime_type, "data": b64_data}})
        if role == "model":
            for tc in msg.get("tool_calls") or []:
                fn_name, args_obj = parse_tool_call_args(tc)
                parts.append({"functionCall": {"name": fn_name, "args": args_obj}})
        return parts or [{"text": ""}]

    def _to_gemini(self, messages: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
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
                img_info = extract_image_details(msg.get("content", ""))

                if img_info:
                    pending_tools.append({"functionResponse": {"name": name, "response": {"result": img_info.summary}}})
                    pending_tools.append({"text": f"Image preview ({img_info.summary}):"})
                    pending_tools.append({"inlineData": {"mimeType": img_info.media_type, "data": img_info.base64}})
                    continue

                tcontent = msg.get("content", "")
                if isinstance(tcontent, str):
                    tcontent_stripped = tcontent.strip()
                    if tcontent_stripped.startswith("{") and tcontent_stripped.endswith("}"):
                        try:
                            resp_obj = json.loads(tcontent_stripped)
                        except Exception:
                            resp_obj = {"result": tcontent}
                    elif not tcontent_stripped:
                        resp_obj = {}
                    else:
                        resp_obj = {"result": tcontent}
                elif isinstance(tcontent, dict):
                    resp_obj = tcontent
                else:
                    resp_obj = {"result": tcontent}
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
        stream_timeout: Optional[float] = None,
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        system_instruction, contents = self._to_gemini(messages)
        base = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
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
                fn_name = fn.get("name", "")
                if not fn_name:
                    continue
                function_declarations.append(
                    {
                        "name": fn_name,
                        "description": fn.get("description", ""),
                        "parameters": fn.get("parameters", {}),
                    }
                )
            payload["tools"] = [{"functionDeclarations": function_declarations}]

        client = self._get_client(base_url, api_key)
        async with client.stream(
            "POST", endpoint, json=payload, timeout=resolve_stream_timeout(stream_timeout)
        ) as resp:
            await check_httpx_response_status(resp)
            async for line in resp.aiter_lines():
                evt = parse_sse_line(line)
                if evt is None:
                    continue

                for cand in evt.get("candidates") or []:
                    parts = ((cand.get("content") or {}).get("parts")) or []
                    for p in parts:
                        if not isinstance(p, dict):
                            continue
                        if p.get("text"):
                            yield ("adapter_text", p["text"])
                        elif p.get("thought"):
                            t = p["thought"]
                            yield ("adapter_thought", t if isinstance(t, str) else json.dumps(t, ensure_ascii=False))
                        elif "functionCall" in p:
                            fc = p.get("functionCall") or {}
                            yield (
                                "adapter_tool_call",
                                {
                                    "id": new_tool_call_id(),
                                    "name": fc.get("name", ""),
                                    "arguments": normalize_tool_arguments_str(fc.get("args")),
                                },
                            )

                um = evt.get("usageMetadata")
                if um:
                    p_tok = um.get("promptTokenCount", 0) or 0
                    c_tok = um.get("candidatesTokenCount", 0) or 0
                    # Implicit caching: cachedContentTokenCount is the portion of
                    # the prompt served from Gemini's automatic cache.
                    cached_tok = um.get("cachedContentTokenCount", 0) or 0
                    yield build_adapter_usage_event(
                        p_tok,
                        c_tok,
                        um.get("totalTokenCount") or (p_tok + c_tok),
                        cache_read_tokens=cached_tok,
                    )
