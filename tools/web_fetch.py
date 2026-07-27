import asyncio
import os
import tempfile
import time
from typing import Any, Dict, List, Tuple

import httpx

from tools.base import BaseTool

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 Johnston/0.1"
)

MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MB limit
DEFAULT_CACHE_TTL = 300.0  # 5 minutes in seconds
MAX_CACHE_ENTRIES = 100


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
    description = "Fetch content from a web URL. Automatically converts HTML/PDF/DOCX to Markdown cleanly. Specify url, and optionally raw, start_line, end_line, no_cache."
    _cache: Dict[str, Tuple[float, bytes, str]] = {}

    schema = {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch"},
                    "raw": {"type": "boolean", "description": "If true, skip Markdown conversion and return raw response text"},
                    "start_line": {"type": "integer", "description": "Start line number (1-indexed)"},
                    "end_line": {"type": "integer", "description": "End line number (inclusive)"},
                    "no_cache": {"type": "boolean", "description": "If true, bypass cache and perform fresh fetch"}
                },
                "required": ["url"]
            }
        }
    }

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache.clear()

    @classmethod
    def _get_from_cache(cls, url: str, ttl: float = DEFAULT_CACHE_TTL) -> Tuple[bytes, str] | None:
        if url in cls._cache:
            ts, content_bytes, content_type = cls._cache[url]
            if time.monotonic() - ts < ttl:
                return content_bytes, content_type
            del cls._cache[url]
        return None

    @classmethod
    def _put_in_cache(cls, url: str, content_bytes: bytes, content_type: str) -> None:
        if len(cls._cache) >= MAX_CACHE_ENTRIES:
            oldest_key = min(cls._cache.keys(), key=lambda k: cls._cache[k][0])
            del cls._cache[oldest_key]
        cls._cache[url] = (time.monotonic(), content_bytes, content_type)

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        self._ensure_context(app)
        url = args.get("url", "").strip()
        if not url:
            return "Error: parameter 'url' is required."

        if not (url.startswith("http://") or url.startswith("https://")):
            return f"Error: invalid URL scheme for '{url}'. Must start with http:// or https://."

        raw_mode = bool(args.get("raw", False))
        no_cache = bool(args.get("no_cache", False))

        cached = None if no_cache else self._get_from_cache(url)
        if cached is not None:
            content_bytes, content_type = cached
        else:
            headers = {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }

            content_bytes = b""
            content_type = ""
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
                                    return f"Error: response body for '{url}' exceeds max allowed size of {MAX_RESPONSE_SIZE // (1024*1024)}MB."
                            except ValueError:
                                pass
                        # Stream the body with a hard cap so an oversized or chunked
                        # response cannot exhaust memory before the size check can trigger.
                        total = 0
                        chunks = []
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > MAX_RESPONSE_SIZE:
                                return f"Error: response body for '{url}' exceeds max allowed size of {MAX_RESPONSE_SIZE // (1024*1024)}MB."
                            chunks.append(chunk)
                        content_bytes = b"".join(chunks)
                        self._put_in_cache(url, content_bytes, content_type)
            except httpx.HTTPStatusError as e:
                return f"Error fetching '{url}': HTTP {e.response.status_code} {e.response.reason_phrase}"
            except httpx.TimeoutException:
                return f"Error fetching '{url}': Request timed out after 20 seconds."
            except Exception as e:
                return f"Error fetching '{url}': {e}"

        lines: List[str] = []

        if raw_mode:
            text_content = content_bytes.decode("utf-8", errors="replace")
            lines = text_content.splitlines(keepends=True)
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
                lines = text_content.splitlines(keepends=True)
            else:
                try:
                    md_text = await asyncio.to_thread(_convert_content_to_md_sync, content_bytes, suffix)
                    lines = md_text.splitlines(keepends=True)
                except Exception:
                    text_content = content_bytes.decode("utf-8", errors="replace")
                    lines = text_content.splitlines(keepends=True)

        from tools.utils import format_line_pagination

        start_line = args.get("start_line")
        end_line = args.get("end_line")

        raw_lines = [line.rstrip("\r\n") for line in lines]
        formatted = format_line_pagination(
            raw_lines,
            start_line=start_line,
            end_line=end_line,
            max_chars=8000,
            hint=f"URL output has {len(lines)} lines. Use start_line/end_line to read specific ranges.",
        )

        if start_line is not None or end_line is not None:
            s_val = start_line or 1
            e_val = end_line or len(lines)
            return f"=== Lines {s_val}-{min(e_val, len(lines))} of {len(lines)} in {url} ===\n{formatted}"
        return formatted
