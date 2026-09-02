import asyncio
import json
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx

from core.adapters.base import check_httpx_response_status
from core.infrastructure.adapters.base import (
    BaseApiAdapter,
    build_adapter_usage_event,
    extract_image_details,
    image_url_block,
    new_tool_call_id,
    normalize_tool_arguments_str,
    parse_sse_line,
    resolve_stream_timeout,
)
from core.infrastructure.runtime.thinking_effort import build_openai_thinking_kwargs
from core.infrastructure.runtime.token_util import parse_usage


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
                            fn_copy["arguments"] = normalize_tool_arguments_str(fn.get("arguments", "{}"))
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
    """Adapter for OpenAI and OpenAI-compatible Chat Completions APIs using httpx."""

    def _create_client(
        self, base_url: str, api_key: str, headers: Optional[Dict[str, str]] = None
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient()

    def _client_is_closed(self, client: Any) -> bool:
        return bool(getattr(client, "is_closed", False))

    async def _consume_chunks(
        self,
        stream_iter: Any,
        chunk_timeout: Optional[float] = 30.0,
        provider_key: Optional[str] = "openai",
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        chunk_to = chunk_timeout or 30.0
        _chunk_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)
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
        tool_calls: Dict[int, Dict[str, Any]] = {}
        tool_call_arg_parts: Dict[int, List[str]] = {}
        last_finish_reason = None
        last_native_finish_reason = None
        had_content = False

        try:
            while True:
                try:
                    item = await asyncio.wait_for(_chunk_queue.get(), timeout=chunk_to)
                except asyncio.TimeoutError:
                    producer_task.cancel()
                    pkey = provider_key or "openai"
                    raise RuntimeError(
                        f"Stream chunk timeout: No response received from provider '{pkey}' for {chunk_to}s."
                    )
                if item is _DONE:
                    break
                if isinstance(item, Exception):
                    raise item
                chunk = item

                usage = chunk.get("usage") if isinstance(chunk, dict) else getattr(chunk, "usage", None)
                if usage:
                    if isinstance(usage, dict):
                        p_tok = usage.get("prompt_tokens", 0)
                        c_tok = usage.get("completion_tokens", 0)
                        t_tok = usage.get("total_tokens") or (p_tok + c_tok)
                        ptd = usage.get("prompt_tokens_details") or {}
                        cr_tok = ptd.get("cached_tokens", 0) if isinstance(ptd, dict) else getattr(ptd, "cached_tokens", 0)
                        cw_tok = ptd.get("cache_write_tokens", 0) if isinstance(ptd, dict) else getattr(ptd, "cache_write_tokens", 0)
                        yield build_adapter_usage_event(
                            prompt_tokens=p_tok,
                            completion_tokens=c_tok,
                            total_tokens=t_tok,
                            cache_read_tokens=cr_tok,
                            cache_write_tokens=cw_tok,
                            cost=usage.get("cost") or usage.get("cost_usd"),
                        )
                    else:
                        pu = parse_usage(usage)
                        yield build_adapter_usage_event(
                            prompt_tokens=pu["prompt_tokens"],
                            completion_tokens=pu["completion_tokens"],
                            total_tokens=pu["total_tokens"],
                            cache_read_tokens=pu["cache_read_tokens"],
                            cache_write_tokens=pu["cache_write_tokens"],
                            cost=pu.get("cost"),
                        )

                chunk_is_dict = isinstance(chunk, dict)
                chunk_error = chunk.get("error") if chunk_is_dict else getattr(chunk, "error", None)
                if (
                    chunk_error is not None
                    and not callable(chunk_error)
                    and not hasattr(chunk_error, "_mock_name")
                    and (isinstance(chunk_error, (dict, str)) or getattr(chunk_error, "message", None))
                ):
                    err_msg = (
                        chunk_error.get("message")
                        if isinstance(chunk_error, dict)
                        else getattr(chunk_error, "message", str(chunk_error))
                    )
                    raise RuntimeError(f"Provider stream error: {err_msg}")

                choices = getattr(chunk, "choices", None) if not chunk_is_dict else chunk.get("choices")
                if not choices and (hasattr(chunk, "data") or (chunk_is_dict and "data" in chunk)):
                    d = getattr(chunk, "data", None) if not chunk_is_dict else chunk.get("data")
                    choices = d.get("choices") if isinstance(d, dict) else getattr(d, "choices", None)
                if not choices:
                    continue

                choice = choices[0]
                choice_is_dict = isinstance(choice, dict)
                f_reason = choice.get("finish_reason") if choice_is_dict else getattr(choice, "finish_reason", None)
                native_reason = choice.get("native_finish_reason") if choice_is_dict else getattr(choice, "native_finish_reason", None)
                if isinstance(f_reason, str):
                    last_finish_reason = f_reason
                    yield ("adapter_finish_reason", f_reason)
                if isinstance(native_reason, str):
                    last_native_finish_reason = native_reason

                delta = choice.get("delta") if choice_is_dict else getattr(choice, "delta", None)
                if not delta:
                    continue

                delta_is_dict = isinstance(delta, dict)
                reasoning = (
                    (delta.get("reasoning_content") or delta.get("reasoning"))
                    if delta_is_dict
                    else (
                        getattr(delta, "reasoning_content", None)
                        or getattr(delta, "reasoning", None)
                        or (getattr(delta, "model_extra", {}) or {}).get("reasoning_content")
                        or (getattr(delta, "model_extra", {}) or {}).get("reasoning")
                    )
                )
                if reasoning:
                    had_content = True
                    yield ("adapter_thought", str(reasoning))

                content = delta.get("content") if delta_is_dict else getattr(delta, "content", None)
                if content:
                    had_content = True
                    yield ("adapter_text", content)

                tool_calls_raw = delta.get("tool_calls") if delta_is_dict else getattr(delta, "tool_calls", None)
                if tool_calls_raw:
                    for tc in tool_calls_raw:
                        tc_is_dict = isinstance(tc, dict)
                        idx = tc.get("index", 0) if tc_is_dict else getattr(tc, "index", 0)
                        if idx not in tool_calls:
                            tool_calls[idx] = {"id": "", "name": ""}
                        tc_id = tc.get("id", "") if tc_is_dict else getattr(tc, "id", "")
                        if tc_id:
                            tool_calls[idx]["id"] = tc_id
                        tc_fn = tc.get("function") if tc_is_dict else getattr(tc, "function", None)
                        if tc_fn:
                            fn_is_dict = isinstance(tc_fn, dict)
                            fn_name = tc_fn.get("name", "") if fn_is_dict else getattr(tc_fn, "name", "")
                            if fn_name:
                                tool_calls[idx]["name"] = fn_name
                            fn_args = tc_fn.get("arguments", "") if fn_is_dict else getattr(tc_fn, "arguments", "")
                            if fn_args:
                                tool_call_arg_parts.setdefault(idx, []).append(fn_args)
        finally:
            if not producer_task.done():
                producer_task.cancel()

        if (
            (last_native_finish_reason in ("network_error", "error") or last_finish_reason == "error")
            and not had_content
            and not tool_calls
        ):
            err_name = last_native_finish_reason or last_finish_reason
            raise RuntimeError(f"Provider stream interrupted: {err_name}")

        for idx in sorted(tool_calls):
            tc = tool_calls[idx]
            tc_name = tc.get("name", "")
            if tc_name:
                args_str = "".join(tool_call_arg_parts.get(idx, [])) or "{}"
                yield (
                    "adapter_tool_call",
                    {
                        "id": tc.get("id") or new_tool_call_id(idx),
                        "name": tc_name,
                        "arguments": args_str,
                    },
                )

    async def stream_chat(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 32768,
        thinking_effort: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        extra_body: Optional[Dict[str, Any]] = None,
        chunk_timeout: Optional[float] = 30.0,
        provider_key: Optional[str] = "openai",
        client: Optional[Any] = None,
        stream_timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        target_client = client or self._get_client(base_url, api_key, headers=headers)
        formatted_msgs = format_messages_for_openai(messages)
        create_kwargs: Dict[str, Any] = {"model": model, "messages": formatted_msgs, "stream": True}
        if tools:
            create_kwargs["tools"] = tools
        if max_tokens and max_tokens > 0:
            create_kwargs["max_tokens"] = max_tokens
        if extra_body:
            create_kwargs["extra_body"] = dict(extra_body)
        create_kwargs.update(build_openai_thinking_kwargs(thinking_effort))

        if hasattr(target_client, "chat") and hasattr(target_client.chat, "completions"):
            timeout = resolve_stream_timeout(stream_timeout)
            create_kwargs["timeout"] = timeout
            try:
                response = await target_client.chat.completions.create(
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
                    create_kwargs.pop("timeout", None)
                    response = await target_client.chat.completions.create(**create_kwargs)
                else:
                    raise create_err

            choices_attr = (
                getattr(response, "choices", None) if not isinstance(response, dict) else response.get("choices")
            )
            if choices_attr and len(choices_attr) > 0:
                first_c = choices_attr[0]
                if hasattr(first_c, "message") or (isinstance(first_c, dict) and "message" in first_c):
                    msg_obj = first_c.get("message") if isinstance(first_c, dict) else getattr(first_c, "message", None)
                    content = msg_obj.get("content") if isinstance(msg_obj, dict) else getattr(msg_obj, "content", "")
                    if content:
                        yield ("adapter_text", content)
                    return

            async for item in self._consume_chunks(response.__aiter__(), chunk_timeout, provider_key):
                yield item
            return

        base = (base_url or "https://api.openai.com/v1").rstrip("/")
        endpoint = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        req_headers = {"Content-Type": "application/json"}
        if api_key:
            req_headers["Authorization"] = f"Bearer {api_key}"
        if headers:
            req_headers.update(headers)

        timeout = resolve_stream_timeout(stream_timeout)
        payload = dict(create_kwargs)
        if "extra_body" in payload:
            eb = payload.pop("extra_body")
            if isinstance(eb, dict):
                payload.update(eb)
        payload["stream_options"] = {"include_usage": True}

        async def _lines_to_chunks(resp_obj):
            async for line in resp_obj.aiter_lines():
                if not line or not line.strip():
                    continue
                chunk = parse_sse_line(line)
                if chunk is None and line.strip().startswith("{") and line.strip().endswith("}"):
                    try:
                        chunk = json.loads(line.strip())
                    except Exception:
                        chunk = None
                if chunk is not None:
                    yield chunk

        async with target_client.stream(
            "POST", endpoint, headers=req_headers, json=payload, timeout=timeout
        ) as resp:
            if getattr(resp, "status_code", 200) >= 400:
                err_bytes = await resp.aread()
                err_text = err_bytes.decode("utf-8", errors="replace").lower()
                if resp.status_code == 400 and (
                    "stream_options" in err_text
                    or "reasoning_effort" in err_text
                    or "extra" in err_text
                ):
                    payload.pop("stream_options", None)
                    payload.pop("reasoning_effort", None)
                    async with target_client.stream(
                        "POST", endpoint, headers=req_headers, json=payload, timeout=timeout
                    ) as retry_resp:
                        if getattr(retry_resp, "status_code", 200) >= 400:
                            await check_httpx_response_status(retry_resp)
                        async for item in self._consume_chunks(_lines_to_chunks(retry_resp), chunk_timeout, provider_key):
                            yield item
                    return
                await check_httpx_response_status(resp)

            async for item in self._consume_chunks(_lines_to_chunks(resp), chunk_timeout, provider_key):
                yield item
