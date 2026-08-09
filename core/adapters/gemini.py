import json
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx

from core.adapters.base import BaseApiAdapter, extract_image_payload, parse_tool_call_args
from core.thinking_effort import build_gemini_thinking_config


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
                parsed_img = extract_image_payload(tcontent)

                if parsed_img and parsed_img.get("base64"):
                    summary_text = parsed_img.get("summary", "[Image content]")
                    media_type = parsed_img.get("media_type", "image/jpeg")
                    b64_data = parsed_img.get("base64")
                    pending_tools.append({"functionResponse": {"name": name, "response": {"result": summary_text}}})
                    pending_tools.append({"text": f"Image preview ({summary_text}):"})
                    pending_tools.append({"inlineData": {"mimeType": media_type, "data": b64_data}})
                    continue

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
