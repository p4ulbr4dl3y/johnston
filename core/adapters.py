import json
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx
from openai import AsyncOpenAI


class BaseApiAdapter:
    """Base API Adapter interface for LLM formats"""
    async def stream_chat(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        raise NotImplementedError


class OpenAIAdapter(BaseApiAdapter):
    """Adapter for OpenAI-compatible Chat Completions API"""
    async def stream_chat(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        client = AsyncOpenAI(api_key=api_key or "sk-placeholder", base_url=base_url or "https://api.openai.com/v1")
        kwargs = {"model": model, "messages": messages, "stream": True}
        if tools:
            kwargs["tools"] = tools
        response = await client.chat.completions.create(**kwargs)
        async for chunk in response:
            yield ("openai_chunk", chunk)


class AnthropicAdapter(BaseApiAdapter):
    """Adapter for Anthropic Native Messages API (/v1/messages)"""
    async def stream_chat(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        system_prompt = ""
        anthropic_msgs = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "system":
                system_prompt = content
            elif role in ("user", "assistant"):
                anthropic_msgs.append({"role": role, "content": content})

        endpoint_url = f"{(base_url or 'https://api.anthropic.com/v1').rstrip('/')}/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": anthropic_msgs,
            "stream": True,
        }
        if tools:
            anthropic_tools = []
            for t in tools:
                fn = t.get("function", {})
                anthropic_tools.append({
                    "name": fn.get("name"),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {}),
                })
            payload["tools"] = anthropic_tools

        async with httpx.AsyncClient() as client:
            async with client.stream("POST", endpoint_url, headers=headers, json=payload, timeout=60.0) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        line_data = line[5:].strip()
                        if line_data == "[DONE]":
                            break
                        try:
                            evt = json.loads(line_data)
                            yield ("anthropic_evt", evt)
                        except Exception:
                            pass


class GeminiAdapter(BaseApiAdapter):
    """Adapter for Google Gemini REST API (/v1beta/models/{model}:streamGenerateContent)"""
    async def stream_chat(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        system_instruction = None
        contents = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "system":
                system_instruction = {"parts": [{"text": content}]}
            elif role in ("user", "assistant"):
                g_role = "user" if role == "user" else "model"
                contents.append({"role": g_role, "parts": [{"text": content}]})

        endpoint = f"{(base_url or 'https://generativelanguage.googleapis.com/v1beta').rstrip('/')}/models/{model}:streamGenerateContent?key={api_key}"
        payload = {"contents": contents}
        if system_instruction:
            payload["systemInstruction"] = system_instruction

        async with httpx.AsyncClient() as client:
            async with client.stream("POST", endpoint, json=payload, timeout=60.0) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        line_data = line[5:].strip()
                        try:
                            evt = json.loads(line_data)
                            yield ("gemini_evt", evt)
                        except Exception:
                            pass


class OllamaAdapter(BaseApiAdapter):
    """Adapter for Ollama Native Chat API (/api/chat)"""
    async def stream_chat(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        endpoint = f"{(base_url or 'http://localhost:11434').rstrip('/')}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient() as client:
            async with client.stream("POST", endpoint, json=payload, timeout=60.0) as resp:
                async for line in resp.aiter_lines():
                    if line:
                        try:
                            evt = json.loads(line)
                            yield ("ollama_evt", evt)
                        except Exception:
                            pass


ADAPTERS: Dict[str, BaseApiAdapter] = {
    "openai": OpenAIAdapter(),
    "anthropic": AnthropicAdapter(),
    "gemini": GeminiAdapter(),
    "ollama": OllamaAdapter(),
}


def get_adapter(api_type: str = "openai") -> BaseApiAdapter:
    key = (api_type or "openai").lower().strip()
    return ADAPTERS.get(key, ADAPTERS["openai"])
