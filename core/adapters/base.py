from typing import Any

from core.infrastructure.adapters.base import (
    BaseApiAdapter,
    _safe_int,
    build_adapter_usage_event,
    extract_image_details,
    extract_image_payload,
    image_url_block,
    new_tool_call_id,
    normalize_tool_arguments_str,
    parse_sse_line,
    parse_tool_call_args,
    sort_keys_recursive,
)

__all__ = [
    "BaseApiAdapter",
    "_safe_int",
    "build_adapter_usage_event",
    "extract_image_details",
    "extract_image_payload",
    "image_url_block",
    "new_tool_call_id",
    "normalize_tool_arguments_str",
    "parse_sse_line",
    "parse_tool_call_args",
    "sort_keys_recursive",
]


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
