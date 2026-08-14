import json
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple


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


def sort_keys_recursive(obj: Any) -> Any:
    """Recursively sorts dictionary keys to guarantee deterministic JSON serialization (stableStringify)."""
    if isinstance(obj, dict):
        # JSON object keys are strings, but real inputs may carry mixed types.
        # Sort by (type, value) so non-comparable keys don't raise TypeError.
        return {
            k: sort_keys_recursive(v)
            for k, v in sorted(obj.items(), key=lambda item: (type(item[0]).__name__, str(item[0])))
        }
    elif isinstance(obj, list):
        return [sort_keys_recursive(elem) for elem in obj]
    return obj


def parse_tool_call_args(tc: dict) -> Tuple[str, Dict[str, Any]]:
    """Helper to extract function name and normalized argument dict from tool call payloads."""
    if not isinstance(tc, dict):
        return "", {}
    fn = tc.get("function", {})
    if not isinstance(fn, dict):
        fn = {}
    fn_name = fn.get("name", "")
    raw_args = fn.get("arguments", "{}")
    if isinstance(raw_args, str):
        try:
            args_obj = json.loads(raw_args) if raw_args.strip() else {}
        except Exception:
            args_obj = {}
    else:
        args_obj = raw_args or {}
    return fn_name, args_obj


def extract_image_payload(tcontent: Any) -> Optional[Dict[str, Any]]:
    """Extracts image payload dictionary from raw message content."""
    if isinstance(tcontent, dict) and tcontent.get("type") == "image":
        return tcontent
    if isinstance(tcontent, str) and (tcontent.startswith('{"type": "image"') or '"type": "image"' in tcontent[:40]):
        try:
            data = json.loads(tcontent)
            if isinstance(data, dict) and data.get("type") == "image":
                return data
        except Exception:
            pass
    return None


def extract_image_details(tcontent: Any) -> Optional[Tuple[str, str, str, str]]:
    """Extracts (summary_text, media_type, base64_data, detail) from image tool content if present."""
    parsed_img = extract_image_payload(tcontent)
    if parsed_img and parsed_img.get("base64"):
        summary_text = parsed_img.get("summary", "[Image content]")
        media_type = parsed_img.get("media_type", "image/jpeg")
        b64_data = parsed_img.get("base64")
        detail_val = parsed_img.get("detail", "high")
        return summary_text, media_type, b64_data, detail_val
    return None


def image_url_block(media_type: str, b64_data: str, detail: str = "high") -> Dict[str, Any]:
    """Builds an OpenAI-style image_url content block with base64 data URI."""
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{media_type};base64,{b64_data}", "detail": detail},
    }


def _safe_int(val: Any) -> int:
    """Coerce a token count to int, tolerating NaN/Inf/None/non-numeric input."""
    if val is None or isinstance(val, bool):
        return 0
    try:
        f = float(val)
    except (ValueError, TypeError):
        return 0
    if f != f or f in (float("inf"), float("-inf")):  # NaN / ±Inf
        return 0
    return int(f)


def build_adapter_usage_event(
    prompt_tokens: Any = 0,
    completion_tokens: Any = 0,
    total_tokens: Optional[Any] = None,
    cache_read_tokens: Any = 0,
) -> Tuple[str, Dict[str, Any]]:
    """Formats standard ('adapter_usage', dict) tuple for provider adapters."""
    p_tok = _safe_int(prompt_tokens)
    c_tok = _safe_int(completion_tokens)
    t_tok = _safe_int(total_tokens) if total_tokens is not None else (p_tok + c_tok)
    return (
        "adapter_usage",
        {
            "prompt_tokens": p_tok,
            "completion_tokens": c_tok,
            "total_tokens": t_tok,
            "cache_read_tokens": int(cache_read_tokens or 0),
        },
    )


async def check_httpx_response_status(resp: Any) -> None:
    """Checks httpx response status and raises HTTPStatusError with body on failure."""
    if getattr(resp, "status_code", 200) >= 400:
        err_bytes = await resp.aread()
        err_body = err_bytes.decode("utf-8", errors="replace")
        import httpx

        raise httpx.HTTPStatusError(
            f"HTTP {resp.status_code}: {err_body}",
            request=resp.request,
            response=resp,
        )


def normalize_tool_arguments_str(raw: Any) -> str:
    """Converts dict or string arguments into clean JSON string format."""
    if isinstance(raw, str):
        return raw or "{}"
    if raw is None:
        return "{}"
    return json.dumps(raw, ensure_ascii=False)


def parse_sse_line(line: str) -> Optional[Any]:
    """Parses a Server-Sent Events line into its JSON payload.

    Expects a line with a ``data:`` prefix (SSE wire format). Returns the parsed
    JSON object, or None if the line is not a data frame / contains invalid JSON.
    Handles the ``data: [DONE]`` sentinel transparently (returns None).
    """
    if not line or not line.startswith("data:"):
        return None
    line_data = line[5:].strip()
    if not line_data or line_data == "[DONE]":
        return None
    try:
        return json.loads(line_data)
    except Exception:
        return None
