import asyncio
import os
import tempfile
from typing import Any, Dict

import httpx

from tools.base import BaseTool, format_tool_error, truncate_output

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 Johnston/0.1"
)

MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MB limit


def _convert_content_to_md_sync(content_bytes: bytes, suffix: str = ".html") -> str:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content_bytes)
        tmp_path = tmp.name

    try:
        from tools.read import convert_doc_to_markdown_sync
        return convert_doc_to_markdown_sync(tmp_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = "Fetch a URL. Converts HTML/PDF/DOCX to Markdown. raw returns raw text."

    schema = {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch"},
                    "raw": {"type": "boolean", "description": "Skip Markdown conversion, return raw response"}
                },
                "required": ["url"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> str:
        url = args.get("url", "").strip()
        if not url:
            return format_tool_error("params", name="url", detail="required")

        if not (url.startswith("http://") or url.startswith("https://")):
            return format_tool_error("scheme", name=url, detail="must be http(s)")

        raw_mode = bool(args.get("raw", False))

        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
                async with client.stream("GET", url, headers=headers) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    # Pre-check Content-Length to fail fast on oversized responses.
                    cl = response.headers.get("content-length")
                    if cl:
                        try:
                            if int(cl) > MAX_RESPONSE_SIZE:
                                return format_tool_error("file", detail=f"exceeds {MAX_RESPONSE_SIZE // (1024*1024)}MB", name=url)
                        except ValueError:
                            pass
                    # Stream the body with a hard cap so an oversized or chunked
                    # response cannot exhaust memory before the size check can trigger.
                    total = 0
                    chunks = []
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_RESPONSE_SIZE:
                            return format_tool_error("file", detail=f"exceeds {MAX_RESPONSE_SIZE // (1024*1024)}MB", name=url)
                        chunks.append(chunk)
                    content_bytes = b"".join(chunks)
        except httpx.HTTPStatusError as e:
            return format_tool_error("http", detail=f"{e.response.status_code} {e.response.reason_phrase}", name=url)
        except httpx.TimeoutException:
            return format_tool_error("timeout", name=url)
        except Exception as e:
            return format_tool_error("fetch", detail=str(e), name=url)

        if raw_mode:
            text_content = content_bytes.decode("utf-8", errors="replace")
        else:
            if "application/pdf" in content_type or url.lower().endswith(".pdf"):
                suffix = ".pdf"
            elif "application/vnd.openxmlformats-officedocument.wordprocessingml" in content_type or url.lower().endswith(".docx"):
                suffix = ".docx"
            elif "application/vnd.openxmlformats-officedocument.spreadsheetml" in content_type or url.lower().endswith(".xlsx"):
                suffix = ".xlsx"
            else:
                suffix = ".html"

            if "json" in content_type or "text/plain" in content_type:
                text_content = content_bytes.decode("utf-8", errors="replace")
            else:
                try:
                    text_content = await asyncio.to_thread(_convert_content_to_md_sync, content_bytes, suffix)
                except Exception:
                    text_content = content_bytes.decode("utf-8", errors="replace")

        return truncate_output(
            text_content,
            max_chars=8000,
            tool_name="web_fetch",
        )

